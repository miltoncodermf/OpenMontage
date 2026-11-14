"""twin_performance_transfer — LivePortrait motion transfer (local engine, spec D7(i), §5.5).

Retargets the motion of ``raw/performance.mov`` onto the beautified variant portrait →
``performance/<variant>.mp4``. The raw recording is read as a *driving* input only inside the
private profile; the output is a beautified synthetic. LivePortrait (MIT code) with MediaPipe in
place of InsightFace (non-commercial weights). **Not integrated yet**: the tool reports exactly what
is missing and never fabricates output. Overnight-OK; run alone (heavy-job lock).
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
    version = "0.1.0"
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
        "properties": {"profile_id": {"type": "string"}, "variant_id": {"type": "string"}, "variant_image": {"type": "string"}},
    }
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=12000, vram_mb=0, disk_mb=3000, network_required=False)
    retry_policy = RetryPolicy(max_retries=0)
    side_effects = ["writes performance/<variant>.mp4 in the private profile"]

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if twin_backends.liveportrait_available()[0] else ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        try:
            d = pp.profile_dir(inputs["profile_id"])
        except (pp.ProfileError, KeyError) as exc:
            return ToolResult(success=False, error=str(exc))
        driving = next(iter(sorted((d / "raw").glob("performance.*"))), None)
        if driving is None:
            return ToolResult(success=False, error="raw/performance.* not found — run capture_session")
        ok, why = twin_backends.liveportrait_available()
        if not ok:
            return ToolResult(success=False, error=f"LivePortrait unavailable: {why}. Not integrated/verified yet (P5 bake-off).")
        return ToolResult(success=False, error="LivePortrait MPS invocation is not integrated yet (P5 bake-off work)")
