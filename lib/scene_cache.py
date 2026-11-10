"""Scene-level content hashing and caching utility for OpenMontage.

Enables incremental re-renders where modifying a single scene in a script
or scene plan only re-synthesizes and re-renders that specific scene clip,
leaving all other scene assets untouched.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Optional


def compute_scene_hash(
    scene_id: str,
    narration_text: str,
    scene_props: dict[str, Any],
    style_name: str = "",
    duration_s: float = 0.0,
    voice: str = "af_heart",
    speed: float = 1.0,
    resolution: str = "1920x1080",
) -> str:
    """Compute deterministic SHA-256 hash for a scene's full specification."""
    spec = {
        "scene_id": scene_id,
        "narration": narration_text.strip(),
        "props": scene_props,
        "style": style_name,
        "duration": round(duration_s, 2),
        "voice": voice,
        "speed": round(float(speed), 2),
        "resolution": resolution,
    }
    dumped = json.dumps(spec, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()[:16]


class SceneCacheManager:
    """Manages immutable scene-level caching of audio and video clips for a project."""

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir).resolve()
        self.cache_dir = self.project_dir / ".cache" / "scenes"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.cache_dir / "cache_manifest.json"
        self._manifest = self._load_manifest()

    def _load_manifest(self) -> dict[str, Any]:
        if self.manifest_path.is_file():
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_manifest(self) -> None:
        fd, tmp_path = tempfile.mkstemp(dir=str(self.cache_dir), prefix="manifest_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._manifest, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.manifest_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def get_cached_audio(self, scene_id: str, scene_hash: str) -> Optional[Path]:
        """Return path to cached audio blob if valid, else None."""
        entry = self.get_cached_audio_entry(scene_id, scene_hash)
        if entry:
            return Path(entry["blob_path"])
        return None

    def get_cached_audio_entry(self, scene_id: str, scene_hash: str) -> Optional[dict[str, Any]]:
        """Return cached audio entry including metadata if valid, else None."""
        entry = self._manifest.get(f"{scene_id}:audio")
        if entry and entry.get("hash") == scene_hash:
            blob = Path(entry.get("blob_path", entry.get("path", "")))
            if blob.is_file():
                return entry
        return None

    def put_cached_audio(
        self,
        scene_id: str,
        scene_hash: str,
        audio_path: Path,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Path:
        """Copy generated audio into immutable scene cache and update manifest."""
        src = Path(audio_path).resolve()
        ext = src.suffix or ".wav"
        blob_path = self.cache_dir / f"{scene_id}_{scene_hash}_audio{ext}"
        if src != blob_path:
            shutil.copy2(src, blob_path)
        self._manifest[f"{scene_id}:audio"] = {
            "hash": scene_hash,
            "path": str(src),
            "blob_path": str(blob_path),
            "metadata": metadata or {},
            "cached_at": time.time(),
        }
        self._save_manifest()
        return blob_path

    def get_cached_clip(self, scene_id: str, scene_hash: str) -> Optional[Path]:
        """Return path to cached video clip blob if valid, else None."""
        entry = self._manifest.get(f"{scene_id}:clip")
        if entry and entry.get("hash") == scene_hash:
            blob = Path(entry.get("blob_path", entry.get("path", "")))
            if blob.is_file():
                return blob
        return None

    def put_cached_clip(self, scene_id: str, scene_hash: str, clip_path: Path) -> Path:
        """Copy rendered video clip into immutable scene cache and update manifest."""
        src = Path(clip_path).resolve()
        ext = src.suffix or ".mp4"
        blob_path = self.cache_dir / f"{scene_id}_{scene_hash}_clip{ext}"
        if src != blob_path:
            shutil.copy2(src, blob_path)
        self._manifest[f"{scene_id}:clip"] = {
            "hash": scene_hash,
            "path": str(src),
            "blob_path": str(blob_path),
            "cached_at": time.time(),
        }
        self._save_manifest()
        return blob_path
