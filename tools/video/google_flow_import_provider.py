"""Google Flow Manual Export/Import Provider.

Imports MP4 clips created and downloaded by the user in Google Flow (using their
Google AI Pro Flow credits), probes media metadata, verifies integrity, and
registers the B-roll asset in the project asset manifest.
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


class GoogleFlowImportProvider(BaseTool):
    name = "google_flow_import"
    version = "1.0.0"
    tier = ToolTier.SOURCE
    capability = "video_generation"
    provider = "google_flow_import"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["binary:ffprobe"]
    capabilities = ["flow_broll_import", "flow_metadata_validation"]

    best_for = [
        "importing high-quality B-roll generated manually using Google AI Pro Flow credits",
        "zero-API-cost video asset ingestion from official Google Flow exports",
    ]

    input_schema = {
        "type": "object",
        "required": ["input_path"],
        "properties": {
            "input_path": {
                "type": "string",
                "description": "Path to user-exported Flow MP4 file or export directory",
            },
            "output_path": {
                "type": "string",
                "description": "Destination path in project assets",
            },
            "prompt": {
                "type": "string",
                "description": "Generation prompt used in Flow",
            },
            "credits_used": {
                "type": "number",
                "description": "Estimated Flow credits consumed for this clip",
            },
            "audio_policy": {
                "type": "string",
                "enum": ["keep", "mute", "replace"],
                "default": "mute",
                "description": "Tutorials typically mute illustrative B-roll audio",
            },
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
            return ToolResult(success=False, error=f"Flow export file not found: {in_path}")

        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration,size:stream=codec_name,codec_type,width,height",
                "-of", "json", str(in_path)
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            probe = json.loads(res.stdout)
        except Exception as e:
            return ToolResult(success=False, error=f"ffprobe failed on Flow clip: {e}")

        streams = probe.get("streams", [])
        v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        if not v_stream:
            return ToolResult(success=False, error="No video stream detected in Flow clip")

        duration = float(probe.get("format", {}).get("duration", 0.0))
        width = int(v_stream.get("width", 1280))
        height = int(v_stream.get("height", 720))

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

        asset_id = f"flow_broll_{sha256[:8]}"
        elapsed = round(time.time() - started, 2)

        asset_record = {
            "asset_id": asset_id,
            "id": asset_id,
            "asset_type": "generated_broll_video",
            "type": "video",
            "path": str(dest_file),
            "provider_id": "google_flow_import",
            "runtime": "manual_import",
            "source_type": "google_flow",
            "source_reference": str(in_path),
            "sha256": sha256,
            "prompt": inputs.get("prompt", ""),
            "duration_seconds": round(duration, 2),
            "width": width,
            "height": height,
            "fps": 30.0,
            "audio_policy": inputs.get("audio_policy", "mute"),
            "status": "validated",
            "cost_estimate_usd": 0.0,
            "actual_cost_usd": 0.0,
            "metadata": {
                "flow_credits_used": inputs.get("credits_used", 0),
            },
        }

        return ToolResult(
            success=True,
            data={"asset": asset_record, "asset_id": asset_id, "path": str(dest_file)},
            artifacts=[str(dest_file)],
            duration_seconds=elapsed,
            cost_usd=0.0,
        )
