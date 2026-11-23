"""Rights-checked import of ONE sourced still image from an allow-listed open-media host.

The topic-tutorial pipeline never lets an unlabelled or third-party image into a video (D13): every ``sourced_image``
needs ``rights_status``, ``license``, ``source_url``, ``attribution`` and ``retrieved_at``. This tool downloads a
specific, owner-approved URL (not a search result), verifies it really is an image, records the rights metadata and the
SHA-256, and returns an ``asset_manifest`` record. Hosts are allow-listed; every redirect hop is re-checked; the body is
size-capped; private/loopback addresses are refused.
"""

from __future__ import annotations

import hashlib
import io
import time
import urllib.parse
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

ALLOWED_HOSTS = (
    "upload.wikimedia.org",
    "commons.wikimedia.org",
    "images-assets.nasa.gov",
    "images.nasa.gov",
    "images.pexels.com",
    "cdn.pixabay.com",
)
MAX_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
RIGHTS_FIELDS = ("rights_status", "license", "source_url", "attribution")


def _host_ok(url: str, allowed: tuple[str, ...]) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host in allowed


class SourcedImageImport(BaseTool):
    name = "sourced_image_import"
    version = "1.0.0"
    tier = ToolTier.SOURCE
    capability = "visuals"
    provider = "sourced_image_import"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL
    capabilities = ["sourced_image_import", "rights_recording"]
    best_for = ["importing one owner-approved open-licensed still with its rights record"]

    input_schema = {
        "type": "object",
        "required": ["url", "output_path", "rights_status", "license", "source_url", "attribution"],
        "properties": {
            "url": {"type": "string", "description": "Direct image URL on an allow-listed host (https)."},
            "output_path": {"type": "string", "description": "Destination under projects/<id>/assets/."},
            "asset_id": {"type": "string"},
            "rights_status": {"type": "string"},
            "license": {"type": "string"},
            "source_url": {"type": "string", "description": "Page that proves the licence (e.g. the Commons file page)."},
            "attribution": {"type": "string"},
            "expected_sha256": {"type": "string", "description": "Optional: refuse the file if the hash differs."},
            "expected_bytes": {"type": "integer", "description": "Optional: refuse the file if the size differs."},
            "allowed_hosts": {"type": "array", "items": {"type": "string"}},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=20, network_required=True)
    retry_policy = RetryPolicy(max_retries=0)

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        missing = [f for f in RIGHTS_FIELDS if not str(inputs.get(f) or "").strip()]
        if missing:
            return ToolResult(success=False, error=f"rights fields required before import: {missing}")
        url = str(inputs["url"])
        allowed = tuple(h.lower() for h in (inputs.get("allowed_hosts") or ALLOWED_HOSTS))
        if urllib.parse.urlparse(url).scheme != "https":
            return ToolResult(success=False, error="only https URLs are imported")

        try:
            body, ctype, final_url = self._fetch(url, allowed)
        except Exception as exc:  # noqa: BLE001 - surfaced verbatim
            return ToolResult(success=False, error=f"fetch failed: {exc}")

        ext = IMAGE_TYPES.get(ctype)
        if not ext:
            return ToolResult(success=False, error=f"not an image (content-type {ctype!r})")
        sha = hashlib.sha256(body).hexdigest()
        if inputs.get("expected_bytes") is not None and len(body) != int(inputs["expected_bytes"]):
            return ToolResult(success=False, error=f"size mismatch: got {len(body)} bytes, expected {inputs['expected_bytes']}")
        if inputs.get("expected_sha256") and sha != str(inputs["expected_sha256"]).lower():
            return ToolResult(success=False, error=f"sha256 mismatch: got {sha}")
        try:
            from PIL import Image

            with Image.open(io.BytesIO(body)) as img:
                img.verify()
            with Image.open(io.BytesIO(body)) as img:
                width, height = img.size
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"downloaded bytes are not a valid image: {exc}")

        dest = Path(inputs["output_path"]).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)

        asset_id = str(inputs.get("asset_id") or f"sourced_image_{sha[:8]}")
        retrieved_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record = {
            "asset_id": asset_id,
            "id": asset_id,
            "asset_type": "sourced_image",
            "type": "image",
            "path": str(dest),
            "provider_id": "sourced_image_import",
            "runtime": "local",
            "source_type": "sourced",
            "download_url": final_url,
            "sha256": sha,
            "byte_size": len(body),
            "width": width,
            "height": height,
            "format": ext,
            "rights_status": str(inputs["rights_status"]),
            "license": str(inputs["license"]),
            "source_url": str(inputs["source_url"]),
            "attribution": str(inputs["attribution"]),
            "retrieved_at": retrieved_at,
            "status": "validated",
            "cost_estimate_usd": 0.0,
            "actual_cost_usd": 0.0,
        }
        return ToolResult(success=True, data={"asset": record, "asset_id": asset_id, "path": str(dest)},
                          artifacts=[str(dest)], duration_seconds=round(time.time() - started, 2), cost_usd=0.0)

    def _fetch(self, url: str, allowed: tuple[str, ...]) -> tuple[bytes, str, str]:
        import requests

        from tools.ingestion.universal_ingestor import _validate_public_url

        current = url
        for _ in range(4):
            if not _host_ok(current, allowed):
                raise ValueError(f"host not allow-listed: {urllib.parse.urlparse(current).hostname}")
            err = _validate_public_url(current)
            if err:
                raise ValueError(err)
            resp = requests.get(current, timeout=30, stream=True, allow_redirects=False,
                                headers={"User-Agent": "OpenMontage-sourced-image-import/1.0"})
            try:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                    current = urllib.parse.urljoin(current, resp.headers["Location"])
                    continue
                if resp.status_code != 200:
                    raise ValueError(f"HTTP {resp.status_code}")
                ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                chunks, size = [], 0
                for chunk in resp.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError(f"larger than {MAX_BYTES} bytes")
                    chunks.append(chunk)
                return b"".join(chunks), ctype, current
            finally:
                resp.close()
        raise ValueError("too many redirects")
