"""presenter_matte — alpha version of a presenter clip (spec §5.5 step 4).

Per-frame BiRefNet matting (BiRefNet on MPS, ~0.5 s/frame; rembg ONNX CPU fallback; MIT) → ProRes 4444 ``.mov`` with
alpha, so Remotion composites the presenter as a separate layer (never baked into a plate). The
segmenter is injectable for tests; the real one needs ``rembg`` + BiRefNet weights (owner OK ≥ 500 MB).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from lib import twin_backends, twin_media
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

Segmenter = Callable[[Image.Image], Image.Image]  # RGB frame -> RGBA frame


def default_segmenter() -> Segmenter:
    """BiRefNet on MPS when available (≈ 0.5 s/frame), else the rembg ONNX fallback (CPU, ≈ 7 s/frame)."""
    from lib import birefnet_mps

    if birefnet_mps.available()[0]:
        return birefnet_mps.segmenter()
    return rembg_birefnet_segmenter()


def rembg_birefnet_segmenter(model: str | None = None) -> Segmenter:
    from lib.model_store import configure_cache_env

    configure_cache_env()  # rembg weights live in the model store (external drive when configured)
    import rembg

    session = rembg.new_session(model or twin_backends.BIREFNET_MODEL)
    return lambda im: rembg.remove(im, session=session).convert("RGBA")


class PresenterMatte(BaseTool):
    name = "presenter_matte"
    version = "1.0.0"
    tier = ToolTier.ENHANCE
    capability = "avatar"
    provider = "rembg_birefnet"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL_GPU
    dependencies = ["binary:ffmpeg", "python:PIL"]
    agent_skills = ["ffmpeg"]
    install_instructions = "pip install rembg onnxruntime; weights (birefnet-general-lite 224 MB; birefnet-portrait 973 MB needs owner OK) are cached under the model store (U2NET_HOME)."
    capabilities = ["alpha_matte_video"]
    supports = {"formats": ["prores_4444_mov"]}
    best_for = ["separate alpha presenter layer for Remotion"]
    not_good_for = ["baking the presenter into a background plate"]
    input_schema = {
        "type": "object",
        "required": ["input_path", "output_path"],
        "properties": {"input_path": {"type": "string"}, "output_path": {"type": "string"}, "fps": {"type": "integer", "default": 30}},
    }
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=4000, vram_mb=0, disk_mb=3000, network_required=False)
    retry_policy = RetryPolicy(max_retries=0)
    side_effects = ["writes an alpha .mov"]

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if twin_backends.birefnet_available()[0] else ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def _segmenter(self) -> Segmenter:
        ok, why = twin_backends.birefnet_available()
        if not ok:
            raise RuntimeError(f"BiRefNet matting unavailable: {why}")
        return default_segmenter()

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        src, dst = Path(inputs["input_path"]), Path(inputs["output_path"])
        if dst.suffix.lower() != ".mov":
            return ToolResult(success=False, error="output_path must be .mov (ProRes 4444 with alpha)")
        if not src.is_file():
            return ToolResult(success=False, error=f"input not found: {src}")
        try:
            seg = self._segmenter()
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc))
        fps = int(inputs.get("fps", 30))
        dst.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as td:
            fr_in, fr_out = Path(td) / "in", Path(td) / "out"
            fr_in.mkdir()
            fr_out.mkdir()
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-r", str(fps), str(fr_in / "f_%05d.png")], check=True, timeout=900)
            frames = sorted(fr_in.glob("f_*.png"))
            for f in frames:
                seg(Image.open(f).convert("RGB")).save(fr_out / f.name)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(fps), "-i", str(fr_out / "f_%05d.png"),
                            "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-vendor", "apl0", str(dst)],
                           check=True, timeout=900)
        info = twin_media.probe(dst)
        if not info.get("has_alpha"):
            return ToolResult(success=False, error="output has no alpha channel")
        return ToolResult(success=True, data={"output": str(dst), "frames": len(frames), "probe": info}, artifacts=[str(dst)])
