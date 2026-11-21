"""voice_lab — build the ~8 presenter-voice candidates and lock the owner's pick (spec D9, §5.6).

Kokoro blends (weighted style vectors) run locally via kokoro-mlx. Chatterbox clone/blend
candidates need the `chatterbox` backend, which is NOT bundled: the tool reports it as
unavailable and never silently substitutes another engine (🛑 owner is told first).
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from lib import presenter_profile as pp
from lib import voice_lab as vl
from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


def chatterbox_available() -> bool:
    from lib import chatterbox_runner

    return chatterbox_runner.available()[0]


def chatterbox_runner_available() -> tuple[bool, str]:
    from lib import chatterbox_runner

    return chatterbox_runner.available()


def chatterbox_unavailable_reason() -> str:
    from lib import chatterbox_runner

    return chatterbox_runner.available()[1]


class VoiceLab(BaseTool):
    name = "voice_lab"
    version = "1.0.0"
    tier = ToolTier.VOICE
    capability = "voice_design"
    provider = "local"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["binary:ffmpeg", "python:kokoro_mlx"]
    agent_skills = ["text-to-speech"]
    install_instructions = (
        "Kokoro candidates need `kokoro-mlx` (installed). Chatterbox candidates need `chatterbox-mlx` (MIT) in its own venv "
        "(lib/chatterbox_runner.py) and the ResembleAI/chatterbox weights (≈ 3.2 GB: the owner's OK per the 500 MB rule)."
    )
    capabilities = ["voice_candidates", "candidate_page", "voice_lock"]
    supports = {"engines": ["kokoro", "chatterbox"], "chatterbox": "dedicated venv (lib/chatterbox_runner.py)"}
    best_for = ["one-time presenter voice design with fair A/B comparison"]
    not_good_for = ["per-video narration (use mlx_tts with the locked voice_profile)"]
    input_schema = {
        "type": "object",
        "required": ["operation", "profile_id"],
        "properties": {
            "operation": {"type": "string", "enum": ["build_candidates", "lock_voice"]},
            "profile_id": {"type": "string"},
            "candidate": {"type": "string", "description": "candidate_id to lock"},
            "variant": {"type": "string", "enum": ["current", "clean_ref", "clean_ref_fuller", "clean_ref_fuller_dereverb"], "description": "lock_voice (chatterbox): voice-quality variant (reference cleaning, polish chain, output de-reverb)"},
            "speed": {"type": "number", "description": "lock_voice (chatterbox): narration tempo factor, e.g. 0.95 = 5% slower (pitch-preserving)"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=2048, vram_mb=0, disk_mb=500, network_required=False)
    retry_policy = RetryPolicy(max_retries=0)
    side_effects = ["writes voice/candidates/* and voice/voice_profile.json in the presenter profile"]

    def get_status(self) -> ToolStatus:
        if importlib.util.find_spec("kokoro_mlx") is None:
            return ToolStatus.UNAVAILABLE
        return ToolStatus.AVAILABLE if chatterbox_available() else ToolStatus.DEGRADED

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        try:
            if inputs.get("operation") == "build_candidates":
                return self._build(inputs["profile_id"])
            if inputs.get("operation") == "lock_voice":
                return self._lock(inputs["profile_id"], inputs.get("candidate", ""), float(inputs.get("speed", 1.0)), inputs.get("variant", "current"))
            return ToolResult(success=False, error=f"unknown operation {inputs.get('operation')!r}")
        except (pp.ProfileError, KeyError, ValueError) as exc:
            return ToolResult(success=False, error=str(exc))

    def _kokoro(self):
        from kokoro_mlx import KokoroTTS

        return KokoroTTS.from_pretrained()

    def _build(self, pid: str) -> ToolResult:
        d = pp.profile_dir(pid)
        cdir = d / "voice" / "candidates"
        cdir.mkdir(parents=True, exist_ok=True)
        page_items: list[dict[str, Any]] = []
        tts = self._kokoro()
        built = []
        for rec in vl.KOKORO_BLENDS:
            recipe = {"voices": rec["voices"], "speed": rec["speed"]}
            res = vl.kokoro_synthesize(tts, vl.SAMPLE_PARAGRAPH, recipe)
            with tempfile.TemporaryDirectory() as td:
                raw = Path(td) / "r.wav"
                sf.write(str(raw), np.asarray(res.audio, dtype=np.float32), int(res.sample_rate))
                vl.polish(raw, cdir / f"{rec['candidate_id']}.wav")
            (cdir / f"{rec['candidate_id']}.wav").chmod(0o600)
            page_items.append({"id": rec["candidate_id"], "audio": f"{rec['candidate_id']}.wav",
                               "recipe": {"engine": "kokoro", **recipe}})
            built.append(rec["candidate_id"])
        raw_voice = next(iter(sorted((d / "raw").glob("voice_read.*"))), None)
        cb_ok = chatterbox_available() and raw_voice is not None
        if cb_ok:  # Chatterbox only hears ~10 s of reference: hand it the cleanest 10 s of the read, not the whole file
            ref = d / "raw" / "working" / "voice_ref.wav"
            if not ref.is_file():
                vl.make_voice_reference(raw_voice, ref)
            raw_voice = ref
        reason = (chatterbox_unavailable_reason() if not chatterbox_available() else "raw/voice_read.* missing")
        cb_report = None
        cb_audio: dict[str, str] = {}
        if cb_ok:
            try:
                cb_report = self._chatterbox_candidates(d, raw_voice, cdir, tts)
                cb_audio = {c["candidate_id"]: c["file"] for c in cb_report["candidates"]}
            except Exception as exc:  # noqa: BLE001
                cb_ok, reason = False, f"chatterbox synthesis failed: {exc}"
        for rec in vl.CHATTERBOX_BLENDS:
            vl.validate_chatterbox_recipe(rec)
            recipe = {"engine": "chatterbox", **{k: v for k, v in rec.items() if k != "candidate_id"}}
            if not cb_ok or rec["candidate_id"] not in cb_audio:
                page_items.append({"id": rec["candidate_id"], "status": "unavailable", "reason": reason, "recipe": recipe})
                continue
            info = next(c for c in cb_report["candidates"] if c["candidate_id"] == rec["candidate_id"])
            page_items.append({"id": rec["candidate_id"], "audio": cb_audio[rec["candidate_id"]],
                               "recipe": {**recipe, "asr_coverage": info["asr"]["coverage"], "attempts": info["attempts"], **({"warning": info["warning"]} if info.get("warning") else {})}})
            built.append(rec["candidate_id"])
        ok_items = [i for i in page_items if i.get("audio")]
        for n, it in enumerate(ok_items, 1):
            it["n"] = n
        pack = {}
        try:  # phone/Mac listening pack: one numbered m4a per voice + all_candidates.m4a ("Voice 1." sample, "Voice 2." ...)
            import numpy as _np

            def _announce(text: str):
                r = tts.generate(text, voice="bf_emma", speed=1.0, sample_rate=24000)
                return _np.asarray(r.audio, dtype="float32"), 24000

            pack = vl.write_listening_pack(cdir, [(i["id"], cdir / i["audio"]) for i in ok_items], _announce)
        except Exception as exc:  # noqa: BLE001  (the wavs and the page are still delivered)
            pack = {"error": str(exc)}
        page = vl.write_candidates_page(cdir, page_items)
        page.chmod(0o600)
        return ToolResult(success=True, data={
            "page": str(page), "built": built,
            "chatterbox": ("unavailable — tell the owner before switching engines (spec §5.6/§9): " + reason) if not cb_ok else "built",
            "chatterbox_api": (cb_report or {}).get("api"),
            "candidates": [i["id"] for i in page_items],
            "listening_pack": pack,
        })

    def _chatterbox_candidates(self, d: Path, owner_ref: Path, cdir: Path, tts: Any) -> dict[str, Any]:
        """Blend the owner's reference embedding with Kokoro donor voices (speaker-embedding interpolation, see worker docs).

        Truncation fix: Chatterbox sometimes emits EOS early and drops the end of what it was asked to say. Synthesis is
        therefore done per sentence; every sentence is ASR-checked (coverage + the sentence ending must be heard) and only
        a failing sentence is re-rolled (new seed, up to MAX_ATTEMPTS), keeping the best take. The assembled paragraph is
        then ASR-checked as a whole; a candidate that is still incomplete is labelled with a warning.
        """
        import subprocess

        from lib import chatterbox_runner

        MAX_ATTEMPTS = 4
        sentences = vl.split_sentences(vl.SAMPLE_PARAGRAPH)
        donors = sorted({dn["voice"] for rec in vl.CHATTERBOX_BLENDS for dn in rec["donors"]})
        with tempfile.TemporaryDirectory() as td:
            donor_refs: dict[str, Path] = {}
            for v in donors:
                res = vl.kokoro_synthesize(tts, vl.SAMPLE_PARAGRAPH, {"voices": [[v, 1.0]], "speed": 1.0})
                p = Path(td) / f"donor_{v}.wav"
                sf.write(str(p), np.asarray(res.audio, dtype=np.float32), int(res.sample_rate))
                donor_refs[v] = p
            rep = chatterbox_runner.synthesize(owner_ref, donor_refs, vl.CHATTERBOX_BLENDS, sentences, Path(td) / "out")
            # best take per (candidate, sentence)
            best: dict[str, dict[str, Any]] = {}
            for c in rep["candidates"]:
                for ch in c["chunks"]:
                    key = f"{c['candidate_id']}:{ch['idx']}"
                    cov = vl.asr_coverage(Path(ch["raw"]), ch["text"])
                    best[key] = {**ch, "asr": cov, "attempts": 1, "ok": vl.chunk_ok(ch["text"], cov["heard"], cov["coverage"])}
            for attempt in range(2, MAX_ATTEMPTS + 1):
                bad = [k for k, v in best.items() if not v["ok"]]
                if not bad:
                    break
                seeds = {k: 1234 + 101 * attempt + int(k.split(":")[1]) for k in bad}
                retry = chatterbox_runner.synthesize(owner_ref, donor_refs, vl.CHATTERBOX_BLENDS, sentences,
                                                     Path(td) / f"out{attempt}", only=bad, seeds=seeds)
                for c in retry["candidates"]:
                    for ch in c["chunks"]:
                        key = f"{c['candidate_id']}:{ch['idx']}"
                        cov = vl.asr_coverage(Path(ch["raw"]), ch["text"])
                        ok = vl.chunk_ok(ch["text"], cov["heard"], cov["coverage"])
                        best[key]["attempts"] = attempt
                        if ok or cov["coverage"] > best[key]["asr"]["coverage"]:
                            best[key] = {**ch, "asr": cov, "attempts": attempt, "ok": ok}
            out_cands = []
            for c in rep["candidates"]:
                cid = c["candidate_id"]
                rec = next(r for r in vl.CHATTERBOX_BLENDS if r["candidate_id"] == cid)
                keys = [f"{cid}:{i}" for i in range(len(sentences))]
                raw = Path(td) / f"{cid}.assembled.wav"
                vl.assemble_chunks([Path(best[k]["raw"]) for k in keys], raw)
                src = raw
                if abs(rec.get("pitch_semitones", 0.0)) > 1e-6:  # small pitch shift keeping duration
                    src = Path(td) / f"{cid}.pitch.wav"
                    f = 2 ** (rec["pitch_semitones"] / 12)
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-af", f"asetrate={int(c['sr'] * f)},aresample={c['sr']},atempo={1 / f:.6f}", str(src)],
                                   check=True, timeout=120)
                final = cdir / f"{cid}.wav"
                vl.polish(src, final)
                final.chmod(0o600)
                whole = vl.asr_coverage(final, vl.SAMPLE_PARAGRAPH)
                info = {"candidate_id": cid, "file": final.name, "sr": c["sr"], "weights": c["weights"],
                        "asr": {"coverage": whole["coverage"]}, "attempts": max(best[k]["attempts"] for k in keys),
                        "sentence_attempts": [best[k]["attempts"] for k in keys],
                        "sentences_complete": [bool(best[k]["ok"]) for k in keys]}
                if whole["coverage"] < 0.92 or not all(info["sentences_complete"]):
                    bad_i = [i + 1 for i, ok in enumerate(info["sentences_complete"]) if not ok]
                    info["warning"] = (f"ASR coverage {whole['coverage']} after {info['attempts']} attempts"
                                       + (f"; sentence(s) {bad_i} may still be cut short" if bad_i else "") + " — audio may be truncated")
                out_cands.append(info)
            rep["candidates"] = out_cands
        return rep

    def _lock_chatterbox(self, pid: str, candidate: str, speed: float, variant: str = "current") -> ToolResult:
        """Lock a Chatterbox blend: recipe + owner reference + donor references + speed, then regenerate the sample through
        the real narration path (per-sentence ASR-checked synthesis, speed factor, polish chain)."""
        from lib import chatterbox_voice

        d = pp.profile_dir(pid)
        rec = vl.find_chatterbox_recipe(candidate)
        vl.validate_chatterbox_recipe(rec)
        ok, why = chatterbox_runner_available()
        if not ok:
            return ToolResult(success=False, error=f"chatterbox unavailable: {why} — nothing locked; ask the owner before switching engines")
        raw_voice = next(iter(sorted((d / "raw").glob("voice_read.*"))), None)
        if raw_voice is None:
            return ToolResult(success=False, error="raw/voice_read.* missing — the owner's voice reading is required")
        if variant not in vl.VOICE_VARIANTS:
            return ToolResult(success=False, error=f"unknown voice variant {variant!r}; have {sorted(vl.VOICE_VARIANTS)}")
        var = vl.VOICE_VARIANTS[variant]
        if var.get("raw"):  # a later recording than raw/voice_read.*
            raw_voice = d / "raw" / var["raw"]
            if not raw_voice.is_file():
                return ToolResult(success=False, error=f"raw/{var['raw']} missing — variant {variant!r} needs it")
        ref = d / var["reference"]
        if not ref.is_file():
            if var["tilt_eq"] is None:
                vl.make_voice_reference(raw_voice, ref)
            else:  # cleaned working copy of the owner's read (the raw file is never modified)
                from lib import voice_clean

                voice_clean.make_clean_reference(raw_voice, ref, tilt_eq=bool(var["tilt_eq"]), **(var.get("clean") or {}))
        donors_dir = d / "voice" / "donors"
        donors_dir.mkdir(parents=True, exist_ok=True)
        donors_dir.chmod(0o700)
        tts = self._kokoro()
        donor_rel: dict[str, str] = {}
        for dn in rec["donors"]:
            v = dn["voice"]
            res = vl.kokoro_synthesize(tts, vl.SAMPLE_PARAGRAPH, {"voices": [[v, 1.0]], "speed": 1.0})
            p = donors_dir / f"{v}.wav"
            sf.write(str(p), np.asarray(res.audio, dtype=np.float32), int(res.sample_rate))
            p.chmod(0o600)
            donor_rel[v] = f"voice/donors/{v}.wav"
        recipe = {k: rec[k] for k in ("owner_weight", "donors", "exaggeration", "cfg", "pitch_semitones")}
        prof_json = vl.build_voice_profile(
            {"candidate_id": candidate, "engine": "chatterbox", "recipe": recipe, "sample": "voice/sample.wav",
             "owner_ref": var["reference"], "donor_refs": donor_rel},
            model_version="ResembleAI/chatterbox via chatterbox-mlx (dedicated venv)", tempo=speed,
            polish_chain=var["polish"], stretch_engine=var["stretch"], output_dereverb=var["output_dereverb"], variant=variant)
        vp = d / "voice" / "voice_profile.json"
        vp.write_text(json.dumps(prof_json, indent=2))
        vp.chmod(0o600)
        sample = d / "voice" / "sample.wav"
        rep = chatterbox_voice.synthesize_narration(vp, vl.SAMPLE_PARAGRAPH, sample)
        sample.chmod(0o600)
        cov = vl.asr_coverage(sample, vl.SAMPLE_PARAGRAPH)
        prof = pp.read_profile(pid)
        prof["voice"] = {"profile": "voice/voice_profile.json", "picked_candidate": candidate, "engine": "chatterbox",
                         "speed": speed, "variant": variant, "watermark_note": prof_json["watermark_note"]}
        pp.write_profile(d, prof)
        info = sf.info(str(sample))
        return ToolResult(success=True, data={
            "voice_profile": str(vp), "candidate": candidate, "engine": "chatterbox", "speed": speed,
            "time_stretch": prof_json["time_stretch"], "sample": str(sample),
            "sample_seconds": round(info.frames / float(info.samplerate), 2),
            "sample_asr_coverage": cov["coverage"], "synthesis": rep})

    def _lock(self, pid: str, candidate: str, speed: float = 1.0, variant: str = "current") -> ToolResult:
        d = pp.profile_dir(pid)
        rec = next((r for r in vl.KOKORO_BLENDS if r["candidate_id"] == candidate), None)
        if rec is None:
            if any(r["candidate_id"] == candidate for r in [*vl.CHATTERBOX_BLENDS, *vl.OWNER_ONLY_BLENDS]):
                return self._lock_chatterbox(pid, candidate, speed, variant)
            return ToolResult(success=False, error=f"candidate {candidate!r} is not a built candidate")
        wav = d / "voice" / "candidates" / f"{candidate}.wav"
        if not wav.is_file():
            return ToolResult(success=False, error="candidate audio not found — run build_candidates first")
        import kokoro_mlx  # noqa: F401  (version recorded in the profile)

        sample = d / "voice" / "sample.wav"
        sample.write_bytes(wav.read_bytes())
        sample.chmod(0o600)
        prof_json = vl.build_voice_profile(
            {"candidate_id": candidate, "engine": "kokoro", "recipe": {"voices": rec["voices"], "speed": rec["speed"]},
             "sample": "voice/sample.wav"},
            model_version="mlx-community/Kokoro-82M-bf16 + kokoro-mlx " + getattr(kokoro_mlx, "__version__", "0.1.4"),
        )
        vp = d / "voice" / "voice_profile.json"
        vp.write_text(json.dumps(prof_json, indent=2))
        vp.chmod(0o600)
        prof = pp.read_profile(pid)
        prof["voice"] = {"profile": "voice/voice_profile.json", "picked_candidate": candidate, "engine": "kokoro"}
        pp.write_profile(d, prof)
        return ToolResult(success=True, data={"voice_profile": str(vp), "candidate": candidate})
