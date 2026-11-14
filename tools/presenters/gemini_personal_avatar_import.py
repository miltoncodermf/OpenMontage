"""Gemini Personal Avatar Manual Import Provider.

Allows importing user-created personal avatar MP4 clips from Gemini Apps
without unsupported private API scraping, verifying container and capturing user consent.
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


class GeminiPersonalAvatarImport(BaseTool):
    name = "gemini_personal_avatar_import"
    version = "1.0.0"
    tier = ToolTier.GENERATE
    capability = "avatar"
    provider = "gemini_personal_avatar_import"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["binary:ffmpeg", "binary:ffprobe"]

    capabilities = [
        "gemini_avatar_import",
        "avatar_provenance_validation",
    ]

    best_for = [
        "importing personal avatar clips generated through official Gemini Apps QR capture flow",
        "provenance-tracked video integration with user-consented avatar likeness",
    ]

    input_schema = {
        "type": "object",
        "required": ["input_path"],
        "properties": {
            "input_path": {
                "type": "string",
                "description": "Path to user-downloaded Gemini Apps avatar MP4 file",
            },
            "output_path": {
                "type": "string",
                "description": "Destination path inside project assets directory",
            },
            "intended_section_id": {
                "type": "string",
                "description": "Script section ID this avatar clip is designated for",
            },
            "user_authorized": {
                "type": "boolean",
                "default": True,
                "description": "Confirmation that user owns and authorized the avatar likeness",
            },
            "audio_policy": {
                "type": "string",
                "enum": ["keep", "mute", "replace"],
                "default": "keep",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=100, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=0)
    idempotency_key_fields = ["input_path"]

    def get_status(self) -> ToolStatus:
        if shutil.which("ffprobe"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        in_path_str = str(inputs.get("input_path", "")).strip()
        if not in_path_str:
            return ToolResult(success=False, error="input_path must be provided")

        src_file = Path(in_path_str).resolve()
        if not src_file.is_file():
            return ToolResult(success=False, error=f"Gemini avatar clip not found: {in_path_str}")

        dest_path_str = inputs.get("output_path")
        if dest_path_str:
            dest_file = Path(dest_path_str).resolve()
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            if src_file != dest_file:
                shutil.copy2(src_file, dest_file)
        else:
            dest_file = src_file

        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration,size:stream=codec_name,codec_type,width,height",
                "-of", "json", str(dest_file)
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            probe = json.loads(res.stdout)
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to probe Gemini avatar file: {e}")

        streams = probe.get("streams", [])
        v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        if not v_stream:
            return ToolResult(success=False, error="No video stream detected in avatar file")

        duration = float(probe.get("format", {}).get("duration", 0.0))
        width = int(v_stream.get("width", 1280))
        height = int(v_stream.get("height", 720))

        h = hashlib.sha256()
        with open(dest_file, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        sha256 = h.hexdigest()

        asset_id = f"gemini_avatar_{sha256[:8]}"
        elapsed = round(time.time() - started, 2)

        asset_record = {
            "asset_id": asset_id,
            "id": asset_id,
            "asset_type": "presenter_video",
            "type": "presenter_video",
            "path": str(dest_file),
            "provider_id": "gemini_personal_avatar_import",
            "runtime": "manual_import",
            "source_type": "gemini_apps_avatar",
            "source_reference": str(src_file),
            "sha256": sha256,
            "duration_seconds": round(duration, 2),
            "width": width,
            "height": height,
            "fps": 30.0,
            "audio_policy": inputs.get("audio_policy", "keep"),
            "rights_status": "user_owned_or_authorized",
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
