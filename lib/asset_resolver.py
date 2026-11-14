"""Asset requirement resolver for Topic-Tutorial pipeline.

Resolves visual beat asset requirements into validated asset manifest records,
ensuring every scene has real media assets or deterministic graphics.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("openmontage.asset_resolver")


class AssetResolver:
    """Fulfills and validates assets required by the Scene Plan IR."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.assets_dir = self.project_dir / "assets"
        self.images_dir = self.assets_dir / "images"
        self.video_dir = self.assets_dir / "video"
        self.audio_dir = self.assets_dir / "audio"
        self.presenter_dir = self.assets_dir / "presenter"

        for d in [self.images_dir, self.video_dir, self.audio_dir, self.presenter_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def resolve_assets(
        self,
        scene_plan: dict[str, Any],
        narration_items: list[dict[str, Any]],
        presenter_video_path: Path | str | None = None,
        screenshot_path: Path | str | None = None,
        screen_demo_path: Path | str | None = None,
    ) -> dict[str, Any]:
        """Resolve all required assets and build a canonical asset_manifest dict.

        Returns:
            dict conforming to asset_manifest.schema.json (v2.0 / v1.0 compatible)
        """
        manifest_assets: list[dict[str, Any]] = []

        # 1. Register audio narration assets
        for item in narration_items:
            path_str = item.get("output") or item.get("path")
            if not path_str:
                continue
            wav_path = Path(path_str).resolve()
            if not wav_path.is_file():
                continue

            h = hashlib.sha256(wav_path.read_bytes()).hexdigest()
            sid = item.get("scene_id", "scene_unknown")
            asset_id = f"narration_{sid}"

            manifest_assets.append({
                "asset_id": asset_id,
                "id": asset_id,
                "asset_type": "narration",
                "type": "narration",
                "path": str(wav_path.relative_to(self.project_dir)) if wav_path.is_relative_to(self.project_dir) else str(wav_path),
                "source_tool": item.get("provider", "mlx_tts"),
                "provider_id": "mlx_tts",
                "runtime": "local",
                "scene_id": sid,
                "sha256": h,
                "model": item.get("model", "kokoro-mlx/af_heart"),
                "duration_seconds": round(float(item.get("duration_s", 0.0)), 3),
                "sample_rate": int(item.get("sample_rate", 24000)),
                "format": "wav",
                "status": "validated",
                "cost_estimate_usd": 0.0,
                "actual_cost_usd": 0.0,
            })

        # 2. Resolve presenter video asset if supplied or present in project
        cand_presenter = None
        if presenter_video_path and Path(presenter_video_path).is_file():
            cand_presenter = Path(presenter_video_path)
        else:
            # Check inputs/presenter/ or assets/presenter/
            for p_dir in [self.project_dir / "inputs" / "presenter", self.presenter_dir]:
                if p_dir.is_dir():
                    vids = list(p_dir.glob("*.mp4")) + list(p_dir.glob("*.mov"))
                    if vids:
                        cand_presenter = vids[0]
                        break

        if cand_presenter and cand_presenter.is_file():
            from tools.presenters.recorded_video_provider import RecordedVideoProvider
            rec_provider = RecordedVideoProvider()
            out_presenter = self.presenter_dir / cand_presenter.name
            rec_res = rec_provider.execute({
                "video_path": str(cand_presenter),
                "output_path": str(out_presenter),
                "sync_mode": "external_driving_audio",
            })
            if rec_res.success and rec_res.data.get("asset"):
                rec_asset = rec_res.data["asset"]
                rel_path = str(Path(rec_asset["path"]).relative_to(self.project_dir)) if Path(rec_asset["path"]).is_relative_to(self.project_dir) else rec_asset["path"]
                rec_asset["path"] = rel_path
                manifest_assets.append(rec_asset)

        # 3. Resolve screenshot asset if present
        cand_screenshot = None
        if screenshot_path and Path(screenshot_path).is_file():
            cand_screenshot = Path(screenshot_path)
        else:
            for s_dir in [self.project_dir / "inputs" / "screenshots", self.images_dir]:
                if s_dir.is_dir():
                    imgs = list(s_dir.glob("*.png")) + list(s_dir.glob("*.jpg"))
                    if imgs:
                        cand_screenshot = imgs[0]
                        break

        if cand_screenshot and cand_screenshot.is_file():
            from tools.visuals.screenshot_provider import ScreenshotProvider
            s_prov = ScreenshotProvider()
            out_shot = self.images_dir / cand_screenshot.name
            s_res = s_prov.execute({
                "input_path": str(cand_screenshot),
                "output_path": str(out_shot),
            })
            if s_res.success and s_res.data.get("asset"):
                s_asset = s_res.data["asset"]
                rel_path = str(Path(s_asset["path"]).relative_to(self.project_dir)) if Path(s_asset["path"]).is_relative_to(self.project_dir) else s_asset["path"]
                s_asset["path"] = rel_path
                manifest_assets.append(s_asset)

        # 4. Resolve screen recording asset if present
        cand_screen_vid = None
        if screen_demo_path and Path(screen_demo_path).is_file():
            cand_screen_vid = Path(screen_demo_path)
        else:
            for v_dir in [self.project_dir / "inputs" / "screen_recordings", self.video_dir]:
                if v_dir.is_dir():
                    v_clips = list(v_dir.glob("*.mp4")) + list(v_dir.glob("*.mov"))
                    if v_clips:
                        cand_screen_vid = v_clips[0]
                        break

        if cand_screen_vid and cand_screen_vid.is_file():
            from tools.visuals.screen_recording_provider import ScreenRecordingProvider
            sr_prov = ScreenRecordingProvider()
            out_demo = self.video_dir / cand_screen_vid.name
            sr_res = sr_prov.execute({
                "input_path": str(cand_screen_vid),
                "output_path": str(out_demo),
            })
            if sr_res.success and sr_res.data.get("asset"):
                sr_asset = sr_res.data["asset"]
                rel_path = str(Path(sr_asset["path"]).relative_to(self.project_dir)) if Path(sr_asset["path"]).is_relative_to(self.project_dir) else sr_asset["path"]
                sr_asset["path"] = rel_path
                manifest_assets.append(sr_asset)

        # 5. Register deterministic diagrams from scene plan
        sections = scene_plan.get("sections", [])
        for s_idx, sec in enumerate(sections):
            for b_idx, beat in enumerate(sec.get("visual_beats", [])):
                if beat.get("visual_type") in ("diagram", "presenter_pip") and beat.get("diagram_spec"):
                    diag_id = f"diagram_{beat.get('beat_id', f's{s_idx}_b{b_idx}')}"
                    spec_path = self.assets_dir / f"{diag_id}.json"
                    with open(spec_path, "w", encoding="utf-8") as f:
                        json.dump(beat["diagram_spec"], f, indent=2)

                    manifest_assets.append({
                        "asset_id": diag_id,
                        "id": diag_id,
                        "asset_type": "diagram",
                        "type": "diagram",
                        "path": str(spec_path.relative_to(self.project_dir)),
                        "source_tool": "diagram_gen",
                        "provider_id": "diagram_gen",
                        "runtime": "local",
                        "scene_id": sec.get("section_id", f"sec_{s_idx}"),
                        "status": "validated",
                        "cost_estimate_usd": 0.0,
                        "actual_cost_usd": 0.0,
                    })

        manifest = {
            "version": "2.0",
            "assets": manifest_assets,
            "total_cost_usd": 0.0,
            "estimated_total_cost_usd": 0.0,
            "actual_total_cost_usd": 0.0,
            "provider_usage": [
                {"provider": "mlx_tts", "cost_usd": 0.0, "runtime": "local"},
                {"provider": "recorded_video", "cost_usd": 0.0, "runtime": "local"},
                {"provider": "diagram_gen", "cost_usd": 0.0, "runtime": "local"},
                {"provider": "screenshot_import", "cost_usd": 0.0, "runtime": "local"},
            ],
            "metadata": {
                "total_assets": len(manifest_assets),
                "visual_assets": len([a for a in manifest_assets if (a.get("asset_type") or a.get("type")) != "narration"]),
            },
        }

        return manifest
