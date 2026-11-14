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
    return importlib.util.find_spec("chatterbox") is not None


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
        "Kokoro candidates need `kokoro-mlx` (installed). Chatterbox candidates need the MIT `chatterbox` MLX "
        "backend and its weights (large download: requires the owner's OK per the 500 MB rule)."
    )
    capabilities = ["voice_candidates", "candidate_page", "voice_lock"]
    supports = {"engines": ["kokoro", "chatterbox"], "chatterbox_installed": False}
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
        reason = ("chatterbox backend not installed" if not chatterbox_available() else "raw/voice_read.* missing")
        for rec in vl.CHATTERBOX_BLENDS:
            vl.validate_chatterbox_recipe(rec)
            if not cb_ok:
                page_items.append({"id": rec["candidate_id"], "status": "unavailable", "reason": reason,
                                   "recipe": {"engine": "chatterbox", **{k: v for k, v in rec.items() if k != "candidate_id"}}})
                continue
            # Real Chatterbox synthesis is intentionally not faked here: the speaker-embedding
            # interpolation API must be verified against the installed backend first (spec §5.6).
            page_items.append({"id": rec["candidate_id"], "status": "unavailable",
                               "reason": "chatterbox backend installed but embedding-interpolation API not yet verified",
                               "recipe": {"engine": "chatterbox", **{k: v for k, v in rec.items() if k != "candidate_id"}}})
        page = vl.write_candidates_page(cdir, page_items)
        page.chmod(0o600)
        return ToolResult(success=True, data={
            "page": str(page), "built": built,
            "chatterbox": "unavailable — tell the owner before switching engines (spec §5.6/§9)" if not cb_ok else "needs API verification",
            "candidates": [i["id"] for i in page_items],
        })

    def _lock(self, pid: str, candidate: str) -> ToolResult:
        d = pp.profile_dir(pid)
        rec = next((r for r in vl.KOKORO_BLENDS if r["candidate_id"] == candidate), None)
        if rec is None:
            return ToolResult(success=False, error=f"candidate {candidate!r} is not a built Kokoro candidate (chatterbox candidates are unavailable)")
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
