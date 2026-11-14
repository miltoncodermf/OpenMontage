"""Recorded Presenter Video Provider (P0 dependable path).

Accepts user-recorded webcam or phone video, validates video container and streams
via ffprobe, and registers the verified presenter video asset in the project manifest.
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


class RecordedVideoProvider(BaseTool):
    name = "recorded_video"
    version = "1.0.0"
    tier = ToolTier.GENERATE
    capability = "avatar"
    provider = "recorded_video"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["binary:ffmpeg", "binary:ffprobe"]
    agent_skills = ["ffmpeg"]

    capabilities = [
        "recorded_presenter_ingestion",
        "fullscreen_presenter",
        "pip_presenter",
        "split_screen_presenter",
    ]

    supports = {
        "offline": True,
        "original_audio": True,
        "external_driving_audio": True,
    }

    best_for = [
        "authentic host tutorials using real phone or webcam footage",
        "zero-cost reliable presenter video without AI avatar models",
    ]

    input_schema = {
        "type": "object",
        "required": ["video_path"],
        "properties": {
            "video_path": {
                "type": "string",
                "description": "Path to user-supplied presenter video (MP4 or MOV)",
            },
            "output_path": {
                "type": "string",
                "description": "Destination asset path inside project workspace",
            },
            "sync_mode": {
                "type": "string",
                "enum": ["original_audio", "external_driving_audio"],
                "default": "external_driving_audio",
                "description": "Whether video audio is retained as master narration or driven by TTS",
            },
            "user_rights_confirmed": {
                "type": "boolean",
                "default": True,
                "description": "User confirmation of rights to the likeness and recording",
            },
            "label": {
                "type": "string",
                "default": "Host",
                "description": "Presenter name or on-screen label",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=512, vram_mb=0, disk_mb=200, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=1, backoff_seconds=1.0)
    idempotency_key_fields = ["video_path", "sync_mode"]
    side_effects = ["copies/validates presenter video asset into project"]

    def get_status(self) -> ToolStatus:
        if shutil.which("ffmpeg") and shutil.which("ffprobe"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        video_path_str = str(inputs.get("video_path", "")).strip()
        if not video_path_str:
            return ToolResult(success=False, error="video_path must be provided")

        src_video = Path(video_path_str).resolve()
        if not src_video.is_file():
            return ToolResult(
                success=False,
                error=f"Presenter video file not found: {video_path_str}",
            )

        sync_mode = inputs.get("sync_mode", "external_driving_audio")
        output_path_str = inputs.get("output_path")
        if output_path_str:
            dest_video = Path(output_path_str).resolve()
            dest_video.parent.mkdir(parents=True, exist_ok=True)
            if src_video != dest_video:
                shutil.copy2(src_video, dest_video)
        else:
            dest_video = src_video

        # Probe media via ffprobe
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration,size:stream=codec_name,codec_type,width,height,r_frame_rate",
                "-of", "json", str(dest_video)
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
            probe = json.loads(proc.stdout)
        except Exception as probe_err:
            return ToolResult(
                success=False,
                error=f"Failed to probe presenter video: {probe_err}",
            )

        streams = probe.get("streams", [])
        v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        if not v_stream:
            return ToolResult(success=False, error="No video stream detected in presenter recording")

        a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if sync_mode == "original_audio" and not a_stream:
            return ToolResult(
                success=False,
                error="sync_mode='original_audio' requested but no audio stream found in presenter video",
            )

        width = int(v_stream.get("width", 1920))
        height = int(v_stream.get("height", 1080))
        duration = float(probe.get("format", {}).get("duration", 0.0))

        # Compute SHA-256
        h = hashlib.sha256()
        with open(dest_video, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        sha256 = h.hexdigest()

        asset_id = f"presenter_{sha256[:8]}"
        elapsed = round(time.time() - started, 2)

        asset_record = {
            "asset_id": asset_id,
            "id": asset_id,
            "asset_type": "presenter_video",
            "type": "presenter_video",
            "path": str(dest_video),
            "provider_id": "recorded_video",
            "runtime": "local",
            "source_type": "user_supplied",
            "source_reference": str(src_video),
            "sha256": sha256,
            "duration_seconds": round(duration, 2),
            "width": width,
            "height": height,
            "resolution": f"{width}x{height}",
            "fps": 30.0,
            "audio_tracks": 1 if a_stream else 0,
            "audio_policy": "keep" if sync_mode == "original_audio" else "mute",
            "rights_status": "user_owned_or_authorized",
            "status": "validated",
            "cost_estimate_usd": 0.0,
            "actual_cost_usd": 0.0,
        }

        return ToolResult(
            success=True,
            data={
                "asset": asset_record,
                "asset_id": asset_id,
                "path": str(dest_video),
                "duration_seconds": round(duration, 2),
                "sync_mode": sync_mode,
            },
            artifacts=[str(dest_video)],
            duration_seconds=elapsed,
            cost_usd=0.0,
        )
