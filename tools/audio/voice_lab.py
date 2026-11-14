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
                return self._lock(inputs["profile_id"], inputs.get("candidate", ""))
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
        page = vl.write_candidates_page(cdir, page_items)
        page.chmod(0o600)
        return ToolResult(success=True, data={
            "page": str(page), "built": built,
            "chatterbox": ("unavailable — tell the owner before switching engines (spec §5.6/§9): " + reason) if not cb_ok else "built",
            "chatterbox_api": (cb_report or {}).get("api"),
            "candidates": [i["id"] for i in page_items],
        })

    def _chatterbox_candidates(self, d: Path, owner_ref: Path, cdir: Path, tts: Any) -> dict[str, Any]:
        """Blend the owner's reference embedding with Kokoro donor voices (speaker-embedding interpolation, see worker docs)."""
        import subprocess

        from lib import chatterbox_runner

        donors = sorted({dn["voice"] for rec in vl.CHATTERBOX_BLENDS for dn in rec["donors"]})
        with tempfile.TemporaryDirectory() as td:
            donor_refs: dict[str, Path] = {}
            for v in donors:
                res = vl.kokoro_synthesize(tts, vl.SAMPLE_PARAGRAPH, {"voices": [[v, 1.0]], "speed": 1.0})
                p = Path(td) / f"donor_{v}.wav"
                sf.write(str(p), np.asarray(res.audio, dtype=np.float32), int(res.sample_rate))
                donor_refs[v] = p
            rep = chatterbox_runner.synthesize(owner_ref, donor_refs, vl.CHATTERBOX_BLENDS, vl.SAMPLE_PARAGRAPH, Path(td) / "out")
            # Chatterbox sometimes stops early (EOS) and drops the end of a sentence/paragraph: verify every candidate
            # with ASR and re-synthesize the failures with a new seed (max 3 attempts), keeping the best attempt.
            best: dict[str, dict[str, Any]] = {c["candidate_id"]: c for c in rep["candidates"]}
            for c in best.values():
                c["asr"] = vl.asr_coverage(Path(c["raw"]), vl.SAMPLE_PARAGRAPH)
                c["attempts"] = 1
            for attempt in (2, 3):
                bad = [cid for cid, c in best.items() if c["asr"]["coverage"] < 0.92]
                if not bad:
                    break
                retry = chatterbox_runner.synthesize(owner_ref, donor_refs, [r for r in vl.CHATTERBOX_BLENDS if r["candidate_id"] in bad],
                                                     vl.SAMPLE_PARAGRAPH, Path(td) / f"out{attempt}", seed=1234 + 101 * attempt)
                for c in retry["candidates"]:
                    cov = vl.asr_coverage(Path(c["raw"]), vl.SAMPLE_PARAGRAPH)
                    if cov["coverage"] > best[c["candidate_id"]]["asr"]["coverage"]:
                        best[c["candidate_id"]] = {**c, "asr": cov}
                    best[c["candidate_id"]]["attempts"] = attempt
            rep["candidates"] = list(best.values())
            for c in rep["candidates"]:
                raw = Path(c["raw"])
                final = cdir / f"{c['candidate_id']}.wav"
                rec = next(r for r in vl.CHATTERBOX_BLENDS if r["candidate_id"] == c["candidate_id"])
                src = raw
                if abs(rec.get("pitch_semitones", 0.0)) > 1e-6:  # small pitch shift keeping duration
                    src = Path(td) / f"{c['candidate_id']}.pitch.wav"
                    f = 2 ** (rec["pitch_semitones"] / 12)
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-af", f"asetrate={int(c['sr'] * f)},aresample={c['sr']},atempo={1 / f:.6f}", str(src)],
                                   check=True, timeout=120)
                vl.polish(src, final)
                final.chmod(0o600)
                c["file"] = final.name
                if c["asr"]["coverage"] < 0.92:
                    c["warning"] = f"ASR coverage {c['asr']['coverage']} after {c['attempts']} attempts — audio may be truncated"
        return rep

    def _lock(self, pid: str, candidate: str) -> ToolResult:
        d = pp.profile_dir(pid)
        rec = next((r for r in vl.KOKORO_BLENDS if r["candidate_id"] == candidate), None)
        if rec is None:
            if any(r["candidate_id"] == candidate for r in vl.CHATTERBOX_BLENDS):
                return ToolResult(success=False, error=f"candidate {candidate!r} is a Chatterbox candidate: locking/narrating with Chatterbox is not wired into mlx_tts yet (candidates are for audition only) — ask the owner before switching engines")
            return ToolResult(success=False, error=f"candidate {candidate!r} is not a built Kokoro candidate")
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
