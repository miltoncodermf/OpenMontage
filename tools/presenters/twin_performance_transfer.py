"""twin_performance_transfer — LivePortrait motion transfer (local engine, spec D7(i), §5.5).

Retargets the motion of ``raw/performance.mov`` onto the beautified variant portrait →
``performance/<variant>.mp4``. The raw recording is read as a *driving* input only inside the
private profile; the output is a beautified synthetic. LivePortrait (MIT code) with MediaPipe in
place of InsightFace (non-commercial weights). Integrated via ``lib/liveportrait_runner.py`` (isolated worker; MPS).
If the backend is missing the tool reports exactly what and never fabricates output. Overnight-OK; takes the
heavy-job lock. ``driving_video`` may be passed explicitly (e.g. an idle clip for a stand-in test; record its licence).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lib import presenter_profile as pp
from lib import twin_backends
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


class TwinPerformanceTransfer(BaseTool):
    name = "twin_performance_transfer"
    version = "1.0.0"
    tier = ToolTier.GENERATE
    capability = "avatar"
    provider = "liveportrait"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.LOCAL_GPU
    dependencies = ["binary:ffmpeg"]
    agent_skills = ["ffmpeg"]
    install_instructions = "Clone LivePortrait (MIT), install for MPS, set LIVEPORTRAIT_DIR; replace InsightFace with MediaPipe (InsightFace weights are non-commercial). Weights need owner OK (≥500 MB)."
    capabilities = ["performance_transfer"]
    supports = {"overnight": True}
    best_for = ["local-engine motion for the twin from the owner's own performance"]
    not_good_for = ["rendering the raw performance (it is only a driving signal)"]
    input_schema = {
        "type": "object",
        "required": ["profile_id", "variant_id"],
        "properties": {"profile_id": {"type": "string"}, "variant_id": {"type": "string"}, "variant_image": {"type": "string"},
                       "driving_video": {"type": "string", "description": "Explicit driving clip (never raw/ unless it is the owner's own performance inside the private profile); default raw/performance.*"},
                       "lock_eyes": {"type": "boolean", "default": False, "description": "Drop blinks and eye/gaze motion from the driving clip so the twin keeps looking straight at the viewer"},
                       "lock_scale": {"type": "boolean", "default": False, "description": "Keep the head size constant (ignore the driving clip's lean toward/away from the camera)"},
                       "expression_gain": {"type": "number", "default": 1.0, "description": "Scale the driving brow/cheek expression change (>1 = livelier, less stern)"},
                       "driving_license": {"type": "string", "description": "Required with an explicit driving_video outside the profile: its licence/provenance"}},
    }
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=12000, vram_mb=0, disk_mb=3000, network_required=False)
    retry_policy = RetryPolicy(max_retries=0)
    side_effects = ["writes performance/<variant>.mp4 in the private profile"]

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if twin_backends.liveportrait_available()[0] else ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        from lib import liveportrait_runner
        from lib.heavy_lock import DEFAULT_RENDER_WAIT_S, HeavyJobBusy, heavy_job

        try:
            d = pp.profile_dir(inputs["profile_id"])
            prof = pp.read_profile(inputs["profile_id"])
        except (pp.ProfileError, KeyError) as exc:
            return ToolResult(success=False, error=str(exc))
        if inputs.get("driving_video"):
            driving = Path(inputs["driving_video"])
            if not driving.is_file():
                return ToolResult(success=False, error=f"driving_video not found: {driving}")
            inside_profile = driving.resolve().is_relative_to(d.resolve())
            if not inside_profile and not inputs.get("driving_license"):
                return ToolResult(success=False, error="an explicit driving_video outside the profile needs driving_license (provenance/licence)")
        else:
            driving = pp.working_video(d, "performance", raw_fallback=True)
            if driving is None:
                return ToolResult(success=False, error="no usable performance recording: raw/performance.* is missing, or it is HDR/rotated and has no SDR working copy (run presenter_profile normalize_raw), or pass driving_video")
        ok, why = twin_backends.liveportrait_available()
        if not ok:
            return ToolResult(success=False, error=f"LivePortrait unavailable: {why}")
        vid = inputs["variant_id"]
        src = Path(inputs["variant_image"]) if inputs.get("variant_image") else d / "identity" / ("wardrobe" if (d / "identity" / "wardrobe" / f"{vid}.png").is_file() else "") / (f"{vid}.png" if (d / "identity" / "wardrobe" / f"{vid}.png").is_file() else "canonical.png")
        if not src.is_file():
            return ToolResult(success=False, error=f"variant image not found: {src}")
        prefix = "STANDIN_" if prof.get("standin") else ""
        out = d / "performance" / f"{prefix}{vid}.mp4"
        try:
            with heavy_job("twin_performance_transfer", wait=DEFAULT_RENDER_WAIT_S):
                import shutil
                import tempfile

                with tempfile.TemporaryDirectory() as td:
                    res = liveportrait_runner.animate(src, driving, Path(td), lock_eyes=bool(inputs.get("lock_eyes")), lock_scale=bool(inputs.get("lock_scale")), expression_gain=float(inputs.get("expression_gain", 1.0)))
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(res["output"], out)
        except (RuntimeError, HeavyJobBusy) as exc:
            return ToolResult(success=False, error=str(exc))
        out.chmod(0o600)
        return ToolResult(success=True, artifacts=[str(out)], data={"output": str(out), "seconds": res["seconds"], "standin": bool(prof.get("standin")),
                                                                    "driving": str(driving), "driving_license": inputs.get("driving_license")})
