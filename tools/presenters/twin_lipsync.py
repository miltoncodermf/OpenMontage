"""twin_lipsync — lip-sync presenter segments to narration (spec §5.5 step 3).

Backends: MuseTalk-MLX (default, 256² mouth region) and LatentSync (full-screen if MuseTalk is too
soft). The motion source (idle loop or LivePortrait performance) is looped/ping-ponged to each
segment's length (real, tested); per-segment outputs plus ``progress.json`` make overnight runs
resumable. **Neither backend is bundled or integrated yet** — ``get_status`` reports exactly what is
missing and ``execute`` fails loudly rather than faking a presenter.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Protocol

from lib import twin_backends, twin_media
from lib.heavy_lock import DEFAULT_RENDER_WAIT_S, HeavyJobBusy, heavy_job
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


class LipsyncBackend(Protocol):
    name: str

    def lipsync(self, motion_video: Path, audio: Path, out: Path) -> None: ...


class BackendUnavailable(RuntimeError):
    pass


class MuseTalkMLXBackend:
    name = "musetalk_mlx"
    last_info: dict[str, Any] = {}

    def lipsync(self, motion_video: Path, audio: Path, out: Path) -> None:
        from lib import musetalk_runner

        ok, why = twin_backends.musetalk_mlx_available()
        if not ok:
            raise BackendUnavailable(f"MuseTalk-MLX unavailable: {why}")
        self.last_info = musetalk_runner.lipsync(motion_video, audio, out)


class LatentSyncBackend:
    name = "latentsync"

    def lipsync(self, motion_video: Path, audio: Path, out: Path) -> None:
        ok, why = twin_backends.latentsync_available()
        raise BackendUnavailable(f"LatentSync unavailable: {why}" if not ok else "LatentSync MPS invocation not integrated yet — P5 bake-off work")


BACKENDS: dict[str, type] = {"musetalk_mlx": MuseTalkMLXBackend, "latentsync": LatentSyncBackend}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


class TwinLipsync(BaseTool):
    name = "twin_lipsync"
    version = "1.0.0"
    tier = ToolTier.GENERATE
    capability = "avatar"
    provider = "local"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.LOCAL_GPU
    dependencies = ["binary:ffmpeg"]
    agent_skills = ["ffmpeg"]
    install_instructions = (
        "MuseTalk-MLX: install the `musetalk_mlx` package (MIT) and download mlx-community/MuseTalk-1.5-fp16 (~1.9 GB, needs owner OK), "
        "set MUSETALK_MLX_DIR. LatentSync 1.5/1.6 (Apache-2.0, MPS fork): set LATENTSYNC_DIR."
    )
    capabilities = ["lipsync_segments", "motion_source_looping", "resumable_batches"]
    supports = {"backends": ["musetalk_mlx", "latentsync"], "modes": ["pip", "fullscreen"]}
    best_for = ["lip-syncing the beautified twin to the locked-voice narration"]
    not_good_for = ["anything involving the owner's raw recordings as the rendered video"]
    input_schema = {
        "type": "object",
        "required": ["segments", "motion_source", "output_dir"],
        "properties": {
            "backend": {"type": "string", "enum": ["musetalk_mlx", "latentsync"], "default": "musetalk_mlx"},
            "motion_source": {"type": "string", "description": "idle loop or performance clip (from the profile; never raw/)"},
            "segments": {"type": "array", "items": {"type": "object", "required": ["segment_id", "audio"]}},
            "output_dir": {"type": "string"},
            "loop_mode": {"type": "string", "enum": ["auto", "loop", "pingpong", "crossfade", "auto_crossfade"], "default": "auto", "description": "How a short motion source is extended to the audio length; crossfade dissolves the repeats instead of reversing the motion"},
            "fps": {"type": "integer", "default": 25, "description": "MuseTalk is trained at 25 fps; keep 25 for musetalk_mlx"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=8000, vram_mb=0, disk_mb=2000, network_required=False)
    retry_policy = RetryPolicy(max_retries=0)
    side_effects = ["writes per-segment mp4 + progress.json", "takes the host heavy-job lock"]

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if twin_backends.musetalk_mlx_available()[0] else ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def _backend(self, name: str) -> LipsyncBackend:
        return BACKENDS[name]()

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        from lib.presenter_profile import is_inside_profile_raw

        motion = Path(inputs["motion_source"])
        if is_inside_profile_raw(motion):
            return ToolResult(success=False, error="motion_source is inside a profile raw/ directory: raw owner recordings are never used as a rendered source")
        if not motion.is_file():
            return ToolResult(success=False, error=f"motion_source not found: {motion}")
        out_dir = Path(inputs["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        fps = int(inputs.get("fps", 25))
        try:
            backend = self._backend(inputs.get("backend", "musetalk_mlx"))
        except KeyError:
            return ToolResult(success=False, error=f"unknown backend {inputs.get('backend')!r}")
        progress_path = out_dir / "progress.json"
        progress = json.loads(progress_path.read_text()) if progress_path.is_file() else {"done": {}}
        motion_hash = _sha(motion)
        results, skipped = [], []
        try:
            with heavy_job("twin_lipsync", wait=DEFAULT_RENDER_WAIT_S):
                for seg in inputs["segments"]:
                    sid, audio = seg["segment_id"], Path(seg["audio"])
                    out = out_dir / f"{sid}.mp4"
                    key = f"{motion_hash}:{_sha(audio)}:{backend.name}"
                    if progress["done"].get(sid) == key and out.is_file():
                        skipped.append(sid)
                        continue
                    dur = twin_media.probe(audio)["duration_seconds"]
                    looped = out_dir / f"{sid}.motion.mp4"
                    loop_info = twin_media.loop_to_duration(motion, looped, dur, fps, mode=inputs.get("loop_mode", "auto"))
                    try:
                        backend.lipsync(looped, audio, out)
                    finally:
                        looped.unlink(missing_ok=True)
                    progress["done"][sid] = key
                    progress_path.write_text(json.dumps(progress, indent=2))  # resumable after each segment
                    results.append({"segment_id": sid, "output": str(out), "loop": loop_info["mode"], "duration_s": dur})
        except BackendUnavailable as exc:
            return ToolResult(success=False, error=str(exc), data={"completed": results, "skipped": skipped})
        except HeavyJobBusy as exc:
            return ToolResult(success=False, error=str(exc))
        except subprocess.CalledProcessError as exc:
            return ToolResult(success=False, error=f"ffmpeg failed: {exc}")
        return ToolResult(success=True, data={"backend": backend.name, "segments": results, "resumed_skipped": skipped})
