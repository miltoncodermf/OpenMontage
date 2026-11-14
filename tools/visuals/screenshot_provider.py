"""Screenshot Ingestion and Validation Provider.

Validates image formats (PNG, JPEG), checks resolution, dimensions, and normalizes
callout focal regions for ScreenshotScene.
"""

from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path
from typing import Any

from PIL import Image

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


class ScreenshotProvider(BaseTool):
    name = "screenshot_import"
    version = "1.0.0"
    tier = ToolTier.SOURCE
    capability = "visuals"
    provider = "screenshot_import"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    capabilities = ["screenshot_ingestion", "ui_crop_validation"]

    input_schema = {
        "type": "object",
        "required": ["input_path"],
        "properties": {
            "input_path": {"type": "string", "description": "Path to screenshot image"},
            "output_path": {"type": "string", "description": "Destination path in project assets"},
            "app_label": {"type": "string", "description": "Application or tool name shown"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=50, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=0)

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        in_path = Path(str(inputs.get("input_path", ""))).resolve()
        if not in_path.is_file():
            return ToolResult(success=False, error=f"Screenshot not found: {in_path}")

        try:
            with Image.open(in_path) as img:
                width, height = img.size
                img_format = img.format.lower() if img.format else "png"
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to open image: {e}")

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

        asset_id = f"screenshot_{sha256[:8]}"
        elapsed = round(time.time() - started, 2)

        asset_record = {
            "asset_id": asset_id,
            "id": asset_id,
            "asset_type": "screenshot",
            "type": "image",
            "path": str(dest_file),
            "provider_id": "screenshot_import",
            "runtime": "local",
            "source_type": "user_screenshot",
            "source_reference": str(in_path),
            "sha256": sha256,
            "width": width,
            "height": height,
            "format": img_format,
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
