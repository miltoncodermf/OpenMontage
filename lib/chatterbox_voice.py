"""Narration with a locked Chatterbox voice (owner's voice blended with donor voices).

The locked ``voice_profile.json`` (engine "chatterbox") carries the blend recipe, the owner reference clip, the donor
reference clips and the speed factor, all relative to the profile root. Synthesis is per sentence; every sentence is
ASR-checked (coverage + the ending was actually spoken) and only a failing sentence is re-rolled with a new seed, then the
sentences are joined, time-stretched (pitch-preserving) and run through the polish chain. Captions and scene timing are
measured on the final, slowed file.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from lib import chatterbox_runner
from lib import voice_lab as vl

MAX_TAKES = 4


def split_for_synthesis(text: str, max_words: int = 30) -> list[tuple[str, float]]:
    """[(chunk, pause_after_seconds)]: sentences, long ones split at clause boundaries; blank line = paragraph pause."""
    out: list[tuple[str, float]] = []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    for pi, para in enumerate(paras):
        sents = vl.split_sentences(" ".join(para.split()))
        for si, sent in enumerate(sents):
            parts = _split_long(sent, max_words)
            for ci, part in enumerate(parts):
                last_in_para = si == len(sents) - 1 and ci == len(parts) - 1
                gap = 0.45 if last_in_para else (0.16 if ci == len(parts) - 1 else 0.08)
                out.append((part, gap))
    return out


def _split_long(sentence: str, max_words: int) -> list[str]:
    words = sentence.split()
    if len(words) <= max_words:
        return [sentence]
    pieces = re.split(r"(?<=[,;:])\s+", sentence)
    chunks: list[str] = []
    cur = ""
    for piece in pieces:
        if cur and len((cur + " " + piece).split()) > max_words:
            chunks.append(cur)
            cur = piece
        else:
            cur = (cur + " " + piece).strip()
    if cur:
        chunks.append(cur)
    # still too long (no commas): hard split on word count
    final: list[str] = []
    for c in chunks:
        w = c.split()
        for i in range(0, len(w), max_words):
            final.append(" ".join(w[i:i + max_words]))
    return final


def resolve_profile(prof_path: Path) -> dict[str, Any]:
    """Absolute paths for a locked chatterbox voice profile; raises FileNotFoundError naming what is missing."""
    import json

    prof = json.loads(Path(prof_path).read_text(encoding="utf-8"))
    if prof.get("engine") != "chatterbox":
        raise ValueError(f"voice profile engine is {prof.get('engine')!r}, not 'chatterbox'")
    root = Path(prof_path).resolve().parent.parent
    owner = root / prof["owner_ref"]
    donors = {v: root / rel for v, rel in prof["donor_refs"].items()}
    missing = [str(p) for p in [owner, *donors.values()] if not p.is_file()]
    if missing:
        raise FileNotFoundError("locked voice references missing: " + ", ".join(missing))
    recipe = prof["recipe"]
    cand = {"candidate_id": prof["candidate_id"], "owner_weight": recipe["owner_weight"], "donors": recipe["donors"],
            "exaggeration": recipe["exaggeration"], "cfg": recipe["cfg"], "pitch_semitones": recipe.get("pitch_semitones", 0.0)}
    return {"profile": prof, "owner_ref": owner, "donor_refs": donors, "candidate": cand,
            "speed": float(prof.get("speed", 1.0)), "seed": int(prof.get("seed", 1234))}


def synthesize_narration(prof_path: Path, text: str, out_path: Path, *, workdir: Path | None = None) -> dict[str, Any]:
    """Locked-voice narration → ``out_path`` (48 kHz wav, polished, at the profile's speed). Returns a report."""
    import subprocess

    ok, why = chatterbox_runner.available()
    if not ok:
        raise RuntimeError(f"chatterbox unavailable: {why}")  # never a silent substitute voice
    r = resolve_profile(prof_path)
    cand, seed, tempo = r["candidate"], r["seed"], r["speed"]
    chunks = split_for_synthesis(text, int(r["profile"].get("synthesis", {}).get("max_words_per_chunk", 30)))
    if not chunks:
        raise ValueError("no text to synthesize")
    sentences = [c for c, _ in chunks]
    ctx = tempfile.TemporaryDirectory() if workdir is None else None
    work = Path(workdir) if workdir else Path(ctx.name)  # type: ignore[union-attr]
    try:
        work.mkdir(parents=True, exist_ok=True)
        rep = chatterbox_runner.synthesize(r["owner_ref"], r["donor_refs"], [cand], sentences, work / "take1", seed=seed)
        sr = rep["candidates"][0]["sr"]
        best: dict[int, dict[str, Any]] = {}
        for ch in rep["candidates"][0]["chunks"]:
            cov = vl.asr_coverage(Path(ch["raw"]), ch["text"])
            best[ch["idx"]] = {**ch, "asr": cov, "takes": 1, "ok": vl.chunk_ok(ch["text"], cov["heard"], cov["coverage"])}
        for take in range(2, MAX_TAKES + 1):
            bad = [i for i, b in best.items() if not b["ok"]]
            if not bad:
                break
            keys = [f"{cand['candidate_id']}:{i}" for i in bad]
            seeds = {f"{cand['candidate_id']}:{i}": seed + 101 * take + i for i in bad}
            retry = chatterbox_runner.synthesize(r["owner_ref"], r["donor_refs"], [cand], sentences, work / f"take{take}",
                                                 seed=seed, only=keys, seeds=seeds)
            for ch in retry["candidates"][0]["chunks"]:
                cov = vl.asr_coverage(Path(ch["raw"]), ch["text"])
                ok = vl.chunk_ok(ch["text"], cov["heard"], cov["coverage"])
                best[ch["idx"]]["takes"] = take
                if ok or cov["coverage"] > best[ch["idx"]]["asr"]["coverage"]:
                    best[ch["idx"]] = {**ch, "asr": cov, "takes": take, "ok": ok}
        joined = work / "joined.wav"
        vl.assemble_chunks([Path(best[i]["raw"]) for i in range(len(sentences))], joined, [g for _, g in chunks])
        src = joined
        pitch = float(cand.get("pitch_semitones", 0.0))
        if abs(pitch) > 1e-6:
            src = work / "pitched.wav"
            f = 2 ** (pitch / 12)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(joined), "-af",
                            f"asetrate={int(sr * f)},aresample={sr},atempo={1 / f:.6f}", str(src)], check=True, timeout=600)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        vl.polish(src, out_path, tempo=tempo)
    finally:
        if ctx is not None:
            ctx.cleanup()
    incomplete = [i + 1 for i in range(len(sentences)) if not best[i]["ok"]]
    return {"sentences": len(sentences), "speed": tempo, "time_stretch": vl.time_stretch_filter(tempo) or "none",
            "takes": [best[i]["takes"] for i in range(len(sentences))], "rerolled": sum(1 for i in best if best[i]["takes"] > 1),
            "incomplete_sentences": incomplete,
            "warning": (f"sentence(s) {incomplete} may still be cut short after {MAX_TAKES} takes" if incomplete else None)}
