"""Voice design helpers (spec D9, §5.6): recipes, Kokoro blends, polish chain, candidate page.

A *voice profile* is a locked, deterministic recipe: engine + model version + recipe +
polish chain + seed. Kokoro blends are weighted averages of preset style vectors. Chatterbox
cloning/blending is an adapter with an honest availability check (the speaker-embedding
interpolation API must be verified before it is relied on — spec §5.6/§9).
"""

from __future__ import annotations

import hashlib
import html
import json
import subprocess
from pathlib import Path
from typing import Any

POLISH_CHAIN = {
    "name": "om-voice-polish-v1",
    "ffmpeg_filter": (
        "highpass=f=80,"
        "equalizer=f=3200:t=q:w=1.0:g=2.0,"
        "deesser=i=0.4:m=0.5:f=0.5:s=o,"
        "acompressor=threshold=-18dB:ratio=3:attack=10:release=120:makeup=2,"
        "loudnorm=I=-16:TP=-1.5:LRA=11"
    ),
    "steps": ["high-pass 80 Hz", "presence EQ +2 dB @ 3.2 kHz", "de-ess", "light compression 3:1", "loudness normalize -16 LUFS"],
}

# The same tutorial-style paragraph (~20 s) for every candidate so comparison is fair.
SAMPLE_PARAGRAPH = (
    "Today we're going to build something real, step by step. First, I'll show you how the pieces fit together, "
    "then we'll run the code and watch it work. By the end, you'll understand not just what to type, "
    "but why it works, and you'll be able to adapt it to your own project."
)

# Candidate plan: ~8 candidates. Chatterbox ones need the owner's voice recording + the chatterbox backend.
KOKORO_BLENDS = [
    {"candidate_id": "k1_warm_narrator", "voices": [["af_heart", 0.6], ["af_bella", 0.4]], "speed": 1.0},
    {"candidate_id": "k2_clear_guide", "voices": [["af_nicole", 0.5], ["af_heart", 0.5]], "speed": 1.0},
    {"candidate_id": "k3_steady_presenter", "voices": [["am_michael", 0.6], ["am_adam", 0.4]], "speed": 0.98},
    {"candidate_id": "k4_bright_mentor", "voices": [["am_michael", 0.5], ["af_heart", 0.2], ["am_fenrir", 0.3]], "speed": 1.0},
]
CHATTERBOX_BLENDS = [
    {"candidate_id": "c1_owner70", "owner_weight": 0.7, "donors": [{"voice": "am_michael", "weight": 0.3}], "exaggeration": 0.5, "cfg": 0.5, "pitch_semitones": 0.0},
    {"candidate_id": "c2_owner50", "owner_weight": 0.5, "donors": [{"voice": "am_adam", "weight": 0.5}], "exaggeration": 0.5, "cfg": 0.5, "pitch_semitones": 0.0},
    {"candidate_id": "c3_owner30", "owner_weight": 0.3, "donors": [{"voice": "am_michael", "weight": 0.35}, {"voice": "af_heart", "weight": 0.35}], "exaggeration": 0.55, "cfg": 0.45, "pitch_semitones": 0.0},
    {"candidate_id": "c4_owner60_lively", "owner_weight": 0.6, "donors": [{"voice": "am_fenrir", "weight": 0.4}], "exaggeration": 0.7, "cfg": 0.4, "pitch_semitones": 0.5},
]


def validate_kokoro_recipe(rec: dict[str, Any]) -> None:
    voices = rec.get("voices") or []
    if not 1 <= len(voices) <= 3:
        raise ValueError("kokoro recipe needs 1-3 voices")
    total = sum(float(w) for _, w in voices)
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"kokoro blend weights must sum to 1.0 (got {total})")
    if any(float(w) <= 0 for _, w in voices):
        raise ValueError("blend weights must be positive")
    if not 0.7 <= float(rec.get("speed", 1.0)) <= 1.3:
        raise ValueError("speed must be within 0.7-1.3")


def validate_chatterbox_recipe(rec: dict[str, Any]) -> None:
    donors = rec.get("donors") or []
    total = float(rec["owner_weight"]) + sum(float(d["weight"]) for d in donors)
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"chatterbox blend weights must sum to 1.0 (got {total})")
    if not 0.0 <= float(rec.get("exaggeration", 0.5)) <= 1.5:
        raise ValueError("exaggeration out of range")


def blend_arrays(arrays: list[Any], weights: list[float]) -> Any:
    """Weighted average of equally-shaped arrays (numpy or mlx)."""
    if len(arrays) != len(weights) or not arrays:
        raise ValueError("arrays/weights mismatch")
    out = arrays[0] * float(weights[0])
    for a, w in zip(arrays[1:], weights[1:]):
        out = out + a * float(w)
    return out


def blend_name(recipe: dict[str, Any]) -> str:
    """Deterministic Kokoro voice name; keeps the first voice's prefix so G2P language inference works."""
    first = recipe["voices"][0][0]
    digest = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()[:8]
    return f"{first.split('_')[0]}_blend_{digest}"


def kokoro_synthesize(tts: Any, text: str, recipe: dict[str, Any], sample_rate: int = 24000, seed: int | None = 1234) -> Any:
    """Synthesize with a blended voice by registering the averaged style vector in the voice cache.

    Seeds the MLX RNG so repeated synthesis of the same text is identical up to float32 GPU jitter
    (measured max abs diff ~1e-7); Kokoro is otherwise audibly non-deterministic (vocoder noise).
    """
    validate_kokoro_recipe(recipe)
    if seed is not None:
        import mlx.core as mx

        mx.random.seed(int(seed))
    names = [v for v, _ in recipe["voices"]]
    weights = [float(w) for _, w in recipe["voices"]]
    if len(names) == 1:
        voice = names[0]
    else:
        vm = tts._voices
        voice = blend_name(recipe)
        vm._cache[voice] = blend_arrays([vm.load_voice(n) for n in names], weights)
    return tts.generate(text, voice=voice, speed=float(recipe.get("speed", 1.0)), sample_rate=sample_rate)


def time_stretch_filter(tempo: float) -> str:
    """Pitch-preserving tempo filter (rubberband when this ffmpeg has it, else atempo). Chatterbox has no native speed control."""
    if abs(tempo - 1.0) < 1e-9:
        return ""
    if not 0.5 <= tempo <= 2.0:
        raise ValueError("tempo must be within 0.5-2.0")
    return f"rubberband=tempo={tempo:.4f}:pitchq=quality" if _has_filter("rubberband") else f"atempo={tempo:.4f}"


_FILTERS: dict[str, bool] = {}


def _has_filter(name: str) -> bool:
    if name not in _FILTERS:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30).stdout
        _FILTERS[name] = any(len(ln.split()) > 1 and ln.split()[1] == name for ln in out.splitlines())
    return _FILTERS[name]


def polish(src: Path, dst: Path, tempo: float = 1.0) -> None:
    """Apply the fixed polish chain (same for every candidate, so comparison is fair).

    ``tempo`` (< 1 = slower) is applied BEFORE the chain so loudness normalisation sees the final audio; everything
    downstream (captions, scene timing) measures the stretched file.
    """
    stretch = time_stretch_filter(tempo)
    chain = (stretch + "," if stretch else "") + POLISH_CHAIN["ffmpeg_filter"]
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", chain, "-ar", "48000", str(dst)],
        check=True, timeout=600,
    )


def write_candidates_page(out_dir: Path, candidates: list[dict[str, Any]], title: str = "Pick your presenter voice") -> Path:
    """Local HTML page: one audio player + recipe per candidate. `candidates` items: id, audio (relative), recipe, status."""
    rows = []
    for c in candidates:
        if c.get("status", "ok") == "ok":
            player = f'<audio controls preload="none" src="{html.escape(c["audio"])}"></audio>'
        else:
            player = f'<em>unavailable — {html.escape(str(c.get("reason", "")))}</em>'
        rows.append(
            f'<section><h2>{("Voice %s — " % c["n"]) if c.get("n") else ""}{html.escape(c["id"])}</h2>{player}'
            f'<pre>{html.escape(json.dumps(c["recipe"], indent=2))}</pre></section>'
        )
    page = (
        "<!doctype html><meta charset=utf-8><title>" + html.escape(title) + "</title>"
        "<style>body{font:16px system-ui;max-width:760px;margin:2rem auto;padding:0 1rem}"
        "section{border:1px solid #8884;border-radius:8px;padding:1rem;margin:1rem 0}"
        "pre{background:#8881;padding:.5rem;overflow:auto;font-size:12px}audio{width:100%}</style>"
        f"<h1>{html.escape(title)}</h1><p>All candidates read the same paragraph through the same polish chain "
        f"(<code>{html.escape(POLISH_CHAIN['name'])}</code>). Tell the agent the candidate id you like.</p>"
        "<blockquote>" + html.escape(SAMPLE_PARAGRAPH) + "</blockquote>" + "".join(rows)
    )
    out = out_dir / "index.html"
    out.write_text(page, encoding="utf-8")
    return out


def build_voice_profile(candidate: dict[str, Any], *, model_version: str, seed: int = 1234, tempo: float = 1.0) -> dict[str, Any]:
    """voice_profile.json content for a picked candidate (locked recipe)."""
    engine = candidate["engine"]
    prof: dict[str, Any] = {
        "version": "1.0", "engine": engine, "model_version": model_version, "candidate_id": candidate["candidate_id"],
        "recipe": candidate["recipe"], "polish_chain": POLISH_CHAIN, "seed": seed,
        "sample": candidate.get("sample"),
        "notes": "Synthesis is seeded: identical for a given text up to float32 GPU jitter (max abs diff ~1e-4, inaudible), not byte-identical.",
    }
    if engine == "chatterbox":
        prof["watermark_note"] = "Chatterbox outputs carry an inaudible Perth watermark (accepted)."
        prof["embedding"] = candidate.get("embedding")
        # Everything needed to re-synthesize, relative to the profile root (locked with the profile's sha256 manifest).
        prof["owner_ref"] = candidate["owner_ref"]
        prof["donor_refs"] = candidate["donor_refs"]
        prof["speed"] = float(tempo)
        prof["time_stretch"] = time_stretch_filter(tempo) or "none"
        prof["synthesis"] = {"unit": "sentence", "asr_check": {"min_coverage": 0.85, "ending_must_be_heard": True},
                             "max_takes": 4, "paragraph_gap_s": 0.45, "sentence_gap_s": 0.16, "max_words_per_chunk": 30}
        prof["notes"] = ("Per-sentence Chatterbox synthesis, each sentence ASR-checked and re-rolled if cut short; speed < 1 is a "
                         "pitch-preserving time-stretch applied before the polish chain (Chatterbox has no native speed control). "
                         "Seeded, reproducible up to GPU jitter, not byte-identical.")
    return prof


def pick_reference_window(y: Any, sr: int, seconds: float = 10.0) -> tuple[float, dict[str, Any]]:
    """Start time (s) of the cleanest continuous-speech window of ``seconds`` in a long read.

    Chatterbox only conditions on the first ~10 s of a reference clip, so handing it a 3-minute file means it
    hears whatever the recording starts with (silence, a breath, "okay, ready"). Score = share of voiced frames,
    minus a penalty for the longest pause, and windows that clip are excluded.
    """
    import numpy as np

    hop = max(1, int(sr * 0.02))
    n = (len(y) - 1024) // hop
    rms = np.array([np.sqrt(np.mean(y[i * hop:i * hop + 1024] ** 2) + 1e-12) for i in range(max(n, 1))])
    db = 20 * np.log10(rms + 1e-9)
    voiced = db > np.percentile(db, 10) + 12
    fps = sr / hop
    w = int(seconds * fps)
    if len(db) <= w:
        return 0.0, {"voiced": float(voiced.mean()), "longest_pause_s": 0.0}
    best: tuple[float, int, float, float] | None = None
    for i in range(0, len(db) - w, max(1, int(fps / 2))):
        seg = voiced[i:i + w]
        gap = run = 0
        for b in seg:
            run = 0 if b else run + 1
            gap = max(gap, run)
        a, b_ = int(i / fps * sr), int((i + w) / fps * sr)
        if float(np.abs(y[a:b_]).max()) > 0.95:
            continue
        score = float(seg.mean()) - 0.2 * (gap / fps)
        if best is None or score > best[0]:
            best = (score, i, float(seg.mean()), gap / fps)
    if best is None:
        return 0.0, {"voiced": 0.0, "longest_pause_s": 0.0, "note": "every window clips; using the start"}
    return best[1] / fps, {"voiced": round(best[2], 3), "longest_pause_s": round(best[3], 2)}


def make_voice_reference(raw: Path, dst: Path, seconds: float = 10.0) -> dict[str, Any]:
    """Cut the cleanest ``seconds`` of the owner's voice read into a mono 24 kHz wav (loudness-levelled).

    It is still the owner's raw voice: it lives under ``raw/working/`` of the private profile, is never published,
    and is only a reference for local synthesis.
    """
    import tempfile

    import librosa

    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        mono = Path(td) / "mono.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ac", "1", "-ar", "24000", str(mono)],
                       check=True, timeout=300)
        y, sr = librosa.load(str(mono), sr=24000)
        start, info = pick_reference_window(y, sr, seconds)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-t", f"{seconds:.2f}", "-i", str(mono),
                        "-af", "highpass=f=70,loudnorm=I=-20:TP=-2:LRA=7", "-ar", "24000", "-ac", "1", str(dst)],
                       check=True, timeout=120)
    dst.chmod(0o600)
    return {"file": dst.name, "start_s": round(start, 2), "seconds": seconds, **info}


def _words(text: str) -> list[str]:
    import re

    return re.findall(r"[a-z0-9']+", text.lower())


def write_listening_pack(cdir: Path, ordered: list[tuple[str, Path]], announce: Any) -> dict[str, str]:
    """Phone/Mac-friendly audio: ``all_candidates.m4a`` (spoken "Voice N", then the sample, N = 1..) and one m4a per voice.

    ``announce(text) -> (float32 array, sample_rate)`` makes the neutral spoken number labels. Numbers follow ``ordered``.
    """
    import numpy as np
    import soundfile as sf

    out: dict[str, str] = {}
    parts: list[Path] = []
    for n, (cid, wav) in enumerate(ordered, 1):
        m4a = cdir / f"{n}_{cid}.m4a"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "aac", "-b:a", "128k", str(m4a)], check=True, timeout=120)
        m4a.chmod(0o600)
        out[cid] = m4a.name
        lab, lsr = announce(f"Voice {n}.")
        lab_p = cdir / f".label_{n}.wav"
        sf.write(str(lab_p), np.concatenate([np.asarray(lab, dtype="float32"), np.zeros(int(0.5 * lsr), dtype="float32")]), int(lsr))
        parts += [lab_p, wav]
    lst = cdir / ".concat.txt"
    inputs: list[str] = []
    filt = []
    for i, p_ in enumerate(parts):
        inputs += ["-i", str(p_)]
        filt.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=mono[a{i}]")
    chain = "".join(f"[a{i}]" for i in range(len(parts)))
    allp = cdir / "all_candidates.m4a"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filt) + f";{chain}concat=n={len(parts)}:v=0:a=1[o]",
                    "-map", "[o]", "-c:a", "aac", "-b:a", "128k", str(allp)], check=True, timeout=300)
    allp.chmod(0o600)
    for p_ in parts[::2]:
        p_.unlink(missing_ok=True)
    lst.unlink(missing_ok=True)
    out["_all"] = allp.name
    return out


def split_sentences(text: str) -> list[str]:
    import re

    return [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]


def chunk_ok(target: str, heard: str, coverage: float, min_coverage: float = 0.85) -> bool:
    """A sentence is complete when most words are recovered AND its ending was actually spoken.

    Early-EOS truncation drops the tail, so besides coverage at least one of the last two target words must
    appear among the last few heard words.
    """
    tail = _words(target)[-2:]
    heard_tail = _words(heard)[-4:]
    return coverage >= min_coverage and any(w in heard_tail for w in tail)


def assemble_chunks(paths: list[Path], dst: Path, gap_s: float | list[float] = 0.16) -> float:
    """Concatenate per-sentence wavs with a short pause; returns the duration in seconds."""
    import numpy as np
    import soundfile as sf

    parts, sr = [], None
    gaps = list(gap_s) if isinstance(gap_s, (list, tuple)) else [gap_s] * len(paths)
    for p, g in zip(paths, gaps):
        a, r = sf.read(str(p), dtype="float32")
        if a.ndim > 1:
            a = a.mean(axis=1)
        sr = sr or r
        if r != sr:
            raise ValueError("chunks have different sample rates")
        parts += [a, np.zeros(int(g * r), dtype="float32")]
    out = np.concatenate(parts[:-1]) if parts else np.zeros(1, dtype="float32")
    sf.write(str(dst), out, sr)
    return round(len(out) / sr, 2)


_WHISPER: dict[str, Any] = {}


def _whisper(model_size: str) -> Any:
    if model_size not in _WHISPER:
        from faster_whisper import WhisperModel

        _WHISPER[model_size] = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _WHISPER[model_size]


def asr_coverage(wav: Path, text: str, model_size: str = "base") -> dict[str, Any]:
    """Share of the target paragraph's words that an ASR pass recovers in order (catches Chatterbox's occasional early-EOS truncation)."""
    import difflib

    import librosa

    y, _ = librosa.load(str(wav), sr=16000)  # decode with librosa (PyAV in some builds rejects faster-whisper's open() kwargs)
    segs, _ = _whisper(model_size).transcribe(y, language="en")
    heard, target = _words(" ".join(s.text for s in segs)), _words(text)
    sm = difflib.SequenceMatcher(a=target, b=heard, autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    return {"coverage": round(matched / max(1, len(target)), 3), "heard": " ".join(heard)}
