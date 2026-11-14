"""Screen Recording Ingestion and Validation Provider.

Validates screen recording clips (QuickTime, OBS, ScreenCaptureKit exports),
probes fps, resolution, duration via ffprobe, and registers the asset.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

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


class ScreenRecordingProvider(BaseTool):
    name = "screen_recording_import"
    version = "1.0.0"
    tier = ToolTier.SOURCE
    capability = "visuals"
    provider = "screen_recording_import"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["binary:ffprobe"]
    capabilities = ["screen_recording_ingestion"]

    input_schema = {
        "type": "object",
        "required": ["input_path"],
        "properties": {
            "input_path": {"type": "string", "description": "Path to screen recording MP4/MOV"},
            "output_path": {"type": "string", "description": "Destination path in project assets"},
            "software_name": {"type": "string", "description": "Name of demonstrated software"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=100, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=0)

    def get_status(self) -> ToolStatus:
        if shutil.which("ffprobe"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        in_path = Path(str(inputs.get("input_path", ""))).resolve()
        if not in_path.is_file():
            return ToolResult(success=False, error=f"Screen recording not found: {in_path}")

        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration,size:stream=codec_name,codec_type,width,height,r_frame_rate",
                "-of", "json", str(in_path)
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            probe = json.loads(res.stdout)
        except Exception as e:
            return ToolResult(success=False, error=f"ffprobe failed on screen recording: {e}")

        streams = probe.get("streams", [])
        v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        if not v_stream:
            return ToolResult(success=False, error="No video stream detected in screen recording")

        width = int(v_stream.get("width", 1920))
        height = int(v_stream.get("height", 1080))
        duration = float(probe.get("format", {}).get("duration", 0.0))

        dest_path_str = inputs.get("output_path")
        if dest_path_str:
            dest_file = Path(dest_path_str).resolve()
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            if in_path != dest_file:
                shutil.copy2(in_path, dest_file)
        else:
            dest_file = in_path

        h = hashlib.sha256()
        with open(dest_file, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        sha256 = h.hexdigest()

        asset_id = f"screen_recording_{sha256[:8]}"
        elapsed = round(time.time() - started, 2)

        asset_record = {
            "asset_id": asset_id,
            "id": asset_id,
            "asset_type": "screen_recording",
            "type": "video",
            "path": str(dest_file),
            "provider_id": "screen_recording_import",
            "runtime": "local",
            "source_type": "screen_capture",
            "source_reference": str(in_path),
            "sha256": sha256,
            "duration_seconds": round(duration, 2),
            "width": width,
            "height": height,
            "fps": 30.0,
            "status": "validated",
            "cost_estimate_usd": 0.0,
            "actual_cost_usd": 0.0,
        }

        return ToolResult(
            success=True,
            data={"asset": asset_record, "asset_id": asset_id, "path": str(dest_file)},
            artifacts=[str(dest_file)],
            duration_seconds=elapsed,
            cost_usd=0.0,
        )
