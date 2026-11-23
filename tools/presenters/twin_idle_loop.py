"""twin_idle_loop — seamless 8–10 s idle loop per outfit (hybrid engine, spec D7/D8, §5.5).

Generates the idle clip once per wardrobe variant via ``gemini_omni_video`` (paid; the key lists
Omni flash models but no Veo models) with the variant portrait as the first-frame reference,
checks the loop seam, and stores ``loops/<variant>/idle.mp4`` in the private profile. If the API
route fails, the agent asks the owner before using the Google Flow browser fallback (D8) and then
calls ``import_flow``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from lib import presenter_profile as pp
from lib import twin_media
from lib.paid_call_guard import check_paid_call
from lib.twin_prompts import IDLE_LOOP_PROMPT
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


class TwinIdleLoop(BaseTool):
    name = "twin_idle_loop"
    version = "1.0.0"
    tier = ToolTier.GENERATE
    capability = "avatar"
    provider = "gemini_omni"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API
    dependencies = ["binary:ffmpeg", "env:GEMINI_API_KEY"]
    agent_skills = ["gemini-omni"]
    install_instructions = "Needs GEMINI_API_KEY with Gemini Omni access and ALLOW_PAID_APIS=true for an approved run (this tool is the topic-tutorial paid-call gate; the stock gemini_omni_video tool is unmodified)."
    fallback_tools = ["google_flow_import"]
    capabilities = ["idle_loop_generation", "loop_seam_check", "flow_import"]
    supports = {"operations": ["plan", "generate", "import_flow", "check_loop", "make_motion_source"]}
    best_for = ["one-time per-outfit idle motion for the hybrid twin engine"]
    not_good_for = ["talking (lip-sync is a separate local step)"]
    input_schema = {
        "type": "object",
        "required": ["operation", "profile_id", "variant_id"],
        "properties": {
            "operation": {"type": "string", "enum": ["plan", "generate", "import_flow", "check_loop", "make_motion_source"]},
            "profile_id": {"type": "string"},
            "variant_id": {"type": "string"},
            "variant_image": {"type": "string", "description": "Relative path in the profile; default identity/canonical.png or wardrobe/<variant>.png"},
            "paid_call_approved": {"type": "boolean", "default": False},
            "proposal_packet": {"type": "object"},
            "actual_spent_usd": {"type": "number", "default": 0},
            "budget_cap_usd": {"type": "number", "description": "Owner-approved dev spend cap; blocks the call if spent + estimate exceeds it."},
            "flow_clip": {"type": "string"},
            "duration_s": {"type": "number"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=200, network_required=True)
    retry_policy = RetryPolicy(max_retries=0)
    side_effects = ["writes loops/<variant>/idle.mp4 in the private profile", "one paid Gemini Omni call (generate)"]

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if os.environ.get("GEMINI_API_KEY") else ToolStatus.DEGRADED

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        from tools.video.gemini_omni_video import GeminiOmniVideo

        return GeminiOmniVideo().estimate_cost({"duration_seconds": 10})

    def _omni(self):
        from tools.video.gemini_omni_video import GeminiOmniVideo

        return GeminiOmniVideo()

    def _variant_image(self, d: Path, inputs: dict[str, Any]) -> Path:
        if inputs.get("variant_image"):
            return d / inputs["variant_image"]
        w = d / "identity" / "wardrobe" / f"{inputs['variant_id']}.png"
        return w if w.is_file() else d / "identity" / "canonical.png"

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        op = inputs.get("operation")
        try:
            d = pp.profile_dir(inputs["profile_id"])
            vid = inputs["variant_id"]
            loop = d / "loops" / vid / "idle.mp4"
            if op == "plan":
                img = self._variant_image(d, inputs)
                return ToolResult(success=True, data={
                    "announce": {"tool": "twin_idle_loop → gemini_omni_video", "provider": "gemini", "mode": "sample (1 clip, once per outfit)",
                                 "reference_image": str(img), "reference_exists": img.is_file(), "prompt": IDLE_LOOP_PROMPT},
                    "estimated_usd": self.estimate_cost(inputs), "output": str(loop),
                    "fallback": "On API failure ask the owner before the Google Flow browser fallback (D8), then use import_flow.",
                })
            if op == "generate":
                return self._generate(d, vid, loop, inputs)
            if op == "import_flow":
                clip = Path(inputs["flow_clip"])
                info = twin_media.probe(clip)
                loop.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(clip, loop)
                loop.chmod(0o600)
                return ToolResult(success=True, data={"loop": str(loop), "probe": info, "seam_score": round(twin_media.seam_score(loop), 4),
                                                      "seamless": twin_media.is_seamless(loop), "source": "google_flow_import"})
            if op == "check_loop":
                if not loop.is_file():
                    return ToolResult(success=False, error=f"{loop} not found")
                return ToolResult(success=True, data={"seam_score": round(twin_media.seam_score(loop), 4), "seamless": twin_media.is_seamless(loop),
                                                      "probe": twin_media.probe(loop)})
            if op == "make_motion_source":
                if not loop.is_file():
                    return ToolResult(success=False, error=f"{loop} not found — generate or import_flow first")
                out = Path(inputs["output_path"])
                data = twin_media.loop_to_duration(loop, out, float(inputs["duration_s"]))
                return ToolResult(success=True, data=data)
            return ToolResult(success=False, error=f"unknown operation {op!r}")
        except (pp.ProfileError, KeyError, ValueError) as exc:
            return ToolResult(success=False, error=str(exc))

    def _generate(self, d: Path, vid: str, loop: Path, inputs: dict[str, Any]) -> ToolResult:
        if not inputs.get("paid_call_approved"):
            return ToolResult(success=False, error="paid Gemini Omni call not approved: announce tool/model/estimate and get the owner's OK first (spec 🛑)")
        if os.environ.get("ALLOW_PAID_APIS", "").lower() != "true":
            return ToolResult(success=False, error="ALLOW_PAID_APIS is not 'true' for this run — set it only after the owner approved the paid call")
        est = self.estimate_cost(inputs)
        cap = inputs.get("budget_cap_usd")
        if cap is not None and float(inputs.get("actual_spent_usd", 0)) + est > float(cap):
            return ToolResult(success=False, error=f"dev budget cap ${float(cap):.2f} would be exceeded (spent ${float(inputs.get('actual_spent_usd', 0)):.2f} + est ${est:.2f})")
        packet = inputs.get("proposal_packet")
        if packet is not None:
            verdict = check_paid_call(packet, tool="gemini_omni_video", provider="gemini", model=None, est_usd=est,
                                      actual_spent_usd=float(inputs.get("actual_spent_usd", 0)))
            if not verdict["allowed"]:
                return ToolResult(success=False, error=f"paid-call guard: {verdict['reason']} — pause and ask the owner")
        img = self._variant_image(d, inputs)
        if not img.is_file():
            return ToolResult(success=False, error=f"variant image not found: {img}")
        loop.parent.mkdir(parents=True, exist_ok=True)
        res = self._omni().execute({
            "operation": "image_to_video", "prompt": IDLE_LOOP_PROMPT, "reference_image_path": str(img),
            "aspect_ratio": "16:9", "output_path": str(loop),
        })
        if not res.success or not loop.is_file():
            return ToolResult(success=False, error=f"Gemini Omni failed: {res.error}. Ask the owner before using the Google Flow browser fallback (D8).",
                              data={"fallback": "google_flow_browser"})
        loop.chmod(0o600)
        score = twin_media.seam_score(loop)
        return ToolResult(success=True, cost_usd=res.cost_usd, data={
            "loop": str(loop), "seam_score": round(score, 4), "seamless": score < twin_media.SEAM_THRESHOLD,
            "note": "If not seamless, lip-sync ping-pongs the clip instead of looping it.", "probe": twin_media.probe(loop)})
