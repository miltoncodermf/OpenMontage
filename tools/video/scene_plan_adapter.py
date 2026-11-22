"""Adapter translating versioned visual-beat scene plan into Remotion cuts and edit decisions.

Replaces hardcoded in-script visual dictionaries with deterministic mapping
from the canonical Scene Plan IR v2.0 to Remotion component props.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("openmontage.scene_plan_adapter")


class ScenePlanAdapter:
    """Translates a validated ScenePlan (v2.0 IR or migrated v1.0) into Remotion Explainer cuts."""

    def __init__(
        self,
        style_palette: dict[str, Any] | None = None,
        project_dir: Path | str | None = None,
    ) -> None:
        self.project_dir = Path(project_dir).resolve() if project_dir else None
        self.palette = style_palette or {
            "primary": ["#0F172A", "#1E293B"],
            "accent": ["#22D3EE", "#06B6D4"],
            "text": ["#F8FAFC", "#94A3B8"],
            "background": "#0F172A",
            "surface": "#1E293B",
        }

    def compile(
        self,
        scene_plan: dict[str, Any],
        asset_manifest: dict[str, Any],
        audio_items: list[dict[str, Any]],
        padded_durations: dict[str, float],
        canvas: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Compile scene plan and assets into Remotion cuts, all_captions, and edit_decisions.

        Returns:
            dict containing:
                "cuts": list[dict] (Remotion cuts)
                "captions": list[dict] (global millisecond captions)
                "edit_decisions": dict (conforming to edit_decisions schema)
                "visual_analytics": dict (card ratio, visual density, presenter presence)
        """
        # Ensure v2 IR format
        from lib.scene_plan_migration import migrate_scene_plan_v1_to_v2
        plan_v2 = migrate_scene_plan_v1_to_v2(scene_plan)
        from lib import layout as nlayout
        from lib.diagram_legibility import split_diagram_spec
        from lib.diagram_legibility import validate_cuts as validate_diagram_cuts

        plan_c = plan_v2.get("canvas") or {}
        canvas = dict(canvas or {"width": plan_c.get("width", 1920), "height": plan_c.get("height", 1080)})
        # Oversized diagrams become progressive-reveal beats (<= 7 nodes each).
        for _sec in plan_v2.get("sections", []):
            _beats = []
            for _b in _sec.get("visual_beats", []):
                _spec = _b.get("diagram_spec")
                if _b.get("visual_type") == "diagram" and _spec and len(_spec.get("nodes") or []) > 7:
                    _chunks = split_diagram_spec(_spec)
                    for _k, _chunk in enumerate(_chunks, 1):
                        _nb = dict(_b)
                        _nb["beat_id"] = f"{_b.get('beat_id', 'beat')}_p{_k}"
                        _nb["diagram_spec"] = _chunk
                        _nb["duration_hint_seconds"] = float(_b.get("duration_hint_seconds", 4.0)) / len(_chunks)
                        _beats.append(_nb)
                else:
                    _beats.append(_b)
            _sec["visual_beats"] = _beats

        # Index assets by id, type, and scene_ids
        assets = asset_manifest.get("assets", [])
        asset_by_id = {a.get("asset_id") or a.get("id"): a for a in assets}
        presenter_assets = [
            a for a in assets if (a.get("asset_type") or a.get("type")) in ("presenter_video", "presenter", "presenter_matte")
        ]
        presenter_assets.sort(key=lambda a: 0 if (a.get("asset_type") or a.get("type")) == "presenter_matte" else 1)  # alpha layer first
        default_presenter_video = presenter_assets[0]["path"] if presenter_assets else None
        from lib.presenter_guard import is_real_presenter_asset

        def _abs(path: str) -> str:
            pth = Path(path)
            if not pth.is_absolute() and self.project_dir:
                pth = self.project_dir / pth
            return str(pth.resolve())

        real_presenter_paths = {
            _abs(a["path"]) for a in presenter_assets if a.get("path") and is_real_presenter_asset(a)
        }

        sections = plan_v2.get("sections", [])
        accent_color = self.palette.get("accent", ["#22D3EE"])[0]
        bg_color = self.palette.get("background", "#0F172A")
        text_color = self.palette.get("text", ["#F8FAFC"])[0]

        cuts: list[dict[str, Any]] = []
        all_captions: list[dict[str, Any]] = []
        edit_cuts: list[dict[str, Any]] = []
        overlays: list[dict[str, Any]] = []
        # Running playback offset per source recording: consecutive beats that use the same capture continue where the
        # previous one stopped instead of replaying the file from 0 s (a beat may override with ``source_in_seconds``).
        source_offsets: dict[str, float] = {}
        prev_diagram_id: str | None = None

        current_time_s = 0.0
        audio_map = {a.get("scene_id"): a for a in audio_items}

        total_runtime_s = 0.0
        text_card_duration_s = 0.0
        presenter_duration_s = 0.0  # real (beautified-twin) presenter seconds only
        fixture_presenter_duration_s = 0.0  # test-only / unverified presenter seconds — never counted as real

        def _count_presenter(path: str | None, dur: float) -> None:
            nonlocal presenter_duration_s, fixture_presenter_duration_s
            if path and str(Path(path).resolve()) in real_presenter_paths:
                presenter_duration_s += dur
            else:
                fixture_presenter_duration_s += dur
        meaningful_visual_duration_s = 0.0

        for sec_idx, section in enumerate(sections):
            sec_id = section.get("section_id") or f"sec_{sec_idx}"
            script_sec_id = section.get("script_section_id") or sec_id
            beats = section.get("visual_beats", [])
            if not beats:
                continue

            # Section audio duration
            audio_info = audio_map.get(sec_id) or audio_map.get(script_sec_id) or (audio_items[sec_idx] if sec_idx < len(audio_items) else None)
            total_sec_duration = padded_durations.get(sec_id) or padded_durations.get(script_sec_id) or 8.0

            # Proportional duration distribution across beats
            raw_hints = [float(b.get("duration_hint_seconds", 4.0)) for b in beats]
            total_hint = sum(raw_hints) if sum(raw_hints) > 0 else float(len(beats))
            beat_durations = [(h / total_hint) * total_sec_duration for h in raw_hints]

            section_start_time = current_time_s

            for b_idx, (beat, b_dur) in enumerate(zip(beats, beat_durations)):
                beat_id = beat.get("beat_id") or f"{sec_id}_b{b_idx+1}"
                in_s = round(current_time_s, 2)
                out_s = round(current_time_s + b_dur, 2)
                actual_beat_dur = out_s - in_s
                current_time_s = out_s
                total_runtime_s += actual_beat_dur

                v_type = beat.get("visual_type", "diagram")
                layout = beat.get("layout", {})
                reqs = beat.get("asset_requirements", [])

                # Resolve presenter requirement
                pip_requested = layout.get("presenter_pip", False) or v_type == "presenter_pip"
                presenter_path = None
                if pip_requested or v_type in ("presenter_fullscreen", "presenter_screen_split"):
                    # Find matching presenter asset
                    for req in reqs:
                        req_name = req if isinstance(req, str) else req.get("id") or req.get("type")
                        if req_name in asset_by_id:
                            cand = asset_by_id[req_name]
                            if (cand.get("asset_type") or cand.get("type")) in ("presenter_video", "presenter", "presenter_matte"):
                                presenter_path = cand.get("path")
                                break
                    if not presenter_path:
                        presenter_path = default_presenter_video

                presenter_is_alpha = any(
                    a.get("path") == presenter_path and (a.get("asset_type") or a.get("type")) == "presenter_matte"
                    for a in presenter_assets
                ) if presenter_path else False
                if presenter_path and self.project_dir and not Path(presenter_path).is_absolute():
                    presenter_path = str((self.project_dir / presenter_path).resolve())

                scene_local_captions = [
                    {
                        "word": ts["word"],
                        "startMs": int(round(ts["startMs"])),
                        "endMs": int(round(ts["endMs"])),
                    }
                    for ts in (audio_info.get("timestamps", []) if audio_info else [])
                ]

                cut: dict[str, Any] = {
                    "id": beat_id,
                    "in_seconds": in_s,
                    "out_seconds": out_s,
                    "backgroundColor": bg_color,
                    "accentColor": accent_color,
                    "color": text_color,
                    "narrationText": audio_info.get("text", "") if audio_info else "",
                    "captions": scene_local_captions,
                }

                focus = beat.get("focus_region")
                if focus is not None:
                    bad = nlayout.validate_focus_region(focus)
                    if bad:
                        raise ValueError(f"beat '{beat_id}': {'; '.join(bad)}")
                    cut["focusRegion"] = focus
                if presenter_path:
                    cut["presenterAlpha"] = bool(presenter_is_alpha)
                    cut["presenterVideo"] = presenter_path
                    cut["presenterStartFrom"] = 0.0
                    # Owner's background catalog entry (lib.backdrops.remotion_spec): beat overrides plan default.
                    bd = beat.get("presenter_backdrop") or plan_v2.get("presenter_backdrop")
                    if bd and presenter_is_alpha:
                        from lib.backdrops import validate_remotion_spec
                        bad_bd = validate_remotion_spec(bd)
                        if bad_bd:
                            raise ValueError(f"beat '{beat_id}': {'; '.join(bad_bd)}")
                        cut["presenterBackdrop"] = bd
                    ps = beat.get("presenter_scale") or plan_v2.get("presenter_scale")
                    if ps is not None and presenter_is_alpha:
                        if not (isinstance(ps, (int, float)) and 0.5 <= float(ps) <= 1.0):
                            raise ValueError(f"beat '{beat_id}': presenter_scale must be a number between 0.5 and 1.0")
                        cut["presenterScale"] = float(ps)
                    if pip_requested:
                        cut["presenterPip"] = True
                        cut["presenterLabel"] = "Presenter"
                        pos, covers = nlayout.choose_pip_position("bottom-right", 0.25, canvas, focus)
                        cut["presenterPipPosition"] = pos
                        cut["layoutPx"] = {"pip": nlayout.to_px(nlayout.pip_rect(pos, 0.25, canvas), canvas),
                                           "caption_safe": nlayout.to_px(nlayout.caption_safe(canvas), canvas)}
                        if covers:
                            cut["layoutWarning"] = "presenter PIP covers the focus_region at every corner"

                # Map visual types to Remotion Explainer props
                if v_type == "presenter_fullscreen":
                    if presenter_path:
                        cut["type"] = "presenter_fullscreen"
                        cut["title"] = beat.get("title") or section.get("learning_objective", "")
                        cut["subtitle"] = section.get("key_takeaway", "")
                        _count_presenter(presenter_path, actual_beat_dur)
                        meaningful_visual_duration_s += actual_beat_dur
                    else:
                        # Graceful fallback when presenter not provided
                        cut["type"] = "diagram"
                        cut["diagramSpec"] = {
                            "title": section.get("learning_objective", "Tutorial Architecture"),
                            "nodes": ["Introduction", "Workflow", "Result"],
                            "edges": [["Introduction", "Workflow"], ["Workflow", "Result"]],
                        }
                        meaningful_visual_duration_s += actual_beat_dur

                elif v_type in ("diagram", "presenter_pip"):
                    cut["type"] = "diagram"
                    spec = beat.get("diagram_spec")
                    if not spec:
                        # Auto-generate diagram spec from section objectives
                        spec = {
                            "title": section.get("learning_objective", "Workflow Overview"),
                            "subtitle": section.get("key_takeaway", ""),
                            "nodes": ["Ingest Input", "MLX Processing", "Verified Output"],
                            "edges": [["Ingest Input", "MLX Processing"], ["MLX Processing", "Verified Output"]],
                        }
                    cut["diagramSpec"] = spec
                    if beat.get("diagram_id") and beat.get("diagram_id") == prev_diagram_id:
                        cut["diagramContinue"] = True  # same diagram as the previous beat: no re-pop of the build animation
                    meaningful_visual_duration_s += actual_beat_dur
                    if pip_requested and presenter_path:
                        _count_presenter(presenter_path, actual_beat_dur)

                elif v_type in ("screenshot_scene", "screenshot_callout"):
                    cut["type"] = "screenshot_scene"
                    shot_spec = beat.get("screenshot_spec", {}) or {}
                    req_ids = [r if isinstance(r, str) else (r.get("id") or r.get("type")) for r in reqs]
                    wanted = [shot_spec.get("asset_id"), shot_spec.get("source_screenshot"), *req_ids]
                    screen_asset = next((asset_by_id[w] for w in wanted if w and w in asset_by_id), None)
                    if screen_asset is None:
                        if any(w for w in wanted):
                            raise ValueError(f"beat '{beat_id}' ({v_type}): none of its assets {[w for w in wanted if w]} is in the asset_manifest")
                        # legacy beats that name no asset at all keep the old 'first screenshot' behaviour
                        screen_asset = next((a for a in assets if (a.get("asset_type") or a.get("type")) in ("screenshot", "image")), None)
                    screen_path = screen_asset["path"] if screen_asset else "assets/images/ui_screenshot.png"
                    if screen_path and self.project_dir and not Path(screen_path).is_absolute():
                        screen_path = str((self.project_dir / screen_path).resolve())
                    cut["backgroundImage"] = screen_path
                    cut["screenshotSteps"] = shot_spec.get("steps") or [
                        {"kind": "highlight_box", "region": {"x": 0.2, "y": 0.25, "w": 0.6, "h": 0.45}, "color": accent_color, "durationSeconds": actual_beat_dur * 0.7},
                        {"kind": "callout_balloon", "anchor": [0.5, 0.45], "text": section.get("learning_objective", "Key Interface Control"), "position": "top", "durationSeconds": actual_beat_dur * 0.5},
                    ]
                    meaningful_visual_duration_s += actual_beat_dur
                    if pip_requested and presenter_path:
                        _count_presenter(presenter_path, actual_beat_dur)

                elif v_type in ("sandbox_capture", "sourced_clip"):
                    want = "sandbox_capture" if v_type == "sandbox_capture" else "sourced_clip"
                    req_ids = [r if isinstance(r, str) else (r.get("id") or r.get("type")) for r in reqs]
                    asset = next((asset_by_id[r] for r in req_ids if r in asset_by_id), None) or next(
                        (a for a in assets if (a.get("asset_type") or a.get("type")) == want), None)
                    if asset is None:
                        raise ValueError(f"beat '{beat_id}' ({v_type}) has no {want} asset in the asset_manifest")
                    cut["type"] = "video"
                    vp = asset["path"]
                    if self.project_dir and not Path(vp).is_absolute():
                        vp = str((self.project_dir / vp).resolve())
                    cut["source"] = vp
                    start_at = float(beat["source_in_seconds"]) if beat.get("source_in_seconds") is not None else source_offsets.get(vp, 0.0)
                    cut["source_in_seconds"] = round(start_at, 3)
                    source_offsets[vp] = start_at + actual_beat_dur
                    meaningful_visual_duration_s += actual_beat_dur
                    if pip_requested and presenter_path:
                        _count_presenter(presenter_path, actual_beat_dur)

                elif v_type == "sourced_image":
                    req_ids = [r if isinstance(r, str) else (r.get("id") or r.get("type")) for r in reqs]
                    asset = next((asset_by_id[r] for r in req_ids if r in asset_by_id), None) or next(
                        (a for a in assets if (a.get("asset_type") or a.get("type")) == "sourced_image"), None)
                    if asset is None:
                        raise ValueError(f"beat '{beat_id}' (sourced_image) has no sourced_image asset in the asset_manifest")
                    ip = asset["path"]
                    if self.project_dir and not Path(ip).is_absolute():
                        ip = str((self.project_dir / ip).resolve())
                    cut["source"] = ip
                    cut["animation"] = beat.get("animation", {}).get("kind", "ken-burns")
                    meaningful_visual_duration_s += actual_beat_dur

                elif v_type == "screen_recording":
                    cut["type"] = "video"
                    video_asset = next(
                        (a for a in assets if (a.get("asset_type") or a.get("type")) in ("screen_recording", "video")),
                        None
                    )
                    video_path = video_asset["path"] if video_asset else "assets/video/screen_demo.mp4"
                    if video_path and self.project_dir and not Path(video_path).is_absolute():
                        video_path = str((self.project_dir / video_path).resolve())
                    cut["source"] = video_path
                    start_at = float(beat["source_in_seconds"]) if beat.get("source_in_seconds") is not None else source_offsets.get(video_path, 0.0)
                    cut["source_in_seconds"] = round(start_at, 3)
                    source_offsets[video_path] = start_at + actual_beat_dur
                    meaningful_visual_duration_s += actual_beat_dur
                    if pip_requested and presenter_path:
                        _count_presenter(presenter_path, actual_beat_dur)

                elif v_type in ("chart", "bar_chart", "line_chart", "pie_chart", "kpi_grid"):
                    cut["type"] = v_type if v_type != "chart" else "bar_chart"
                    cut["chartData"] = beat.get("chart_spec", {}).get("data") or [
                        {"label": "Local Compute", "value": 13.5},
                        {"label": "Cloud Latency", "value": 2.1},
                    ]
                    cut["title"] = beat.get("title") or section.get("learning_objective", "")
                    meaningful_visual_duration_s += actual_beat_dur

                elif v_type == "image_broll":
                    broll_asset = next(
                        (a for a in assets if (a.get("asset_type") or a.get("type")) in ("image", "broll", "generated_broll_video")),
                        None
                    )
                    cut["source"] = broll_asset["path"] if broll_asset else "assets/images/broll_asset.png"
                    cut["animation"] = beat.get("animation", {}).get("kind", "ken-burns")
                    meaningful_visual_duration_s += actual_beat_dur

                elif v_type == "stat_card":
                    cut["type"] = "stat_card"
                    cut["stat"] = beat.get("stat", "100%")
                    cut["subtitle"] = beat.get("subtitle") or section.get("learning_objective", "")
                    meaningful_visual_duration_s += actual_beat_dur

                elif v_type == "text_card":
                    cut["type"] = "text_card"
                    cut["text"] = beat.get("text") or section.get("learning_objective", "")
                    text_card_duration_s += actual_beat_dur
                else:
                    raise ValueError(f"Unknown visual_type '{v_type}' on beat '{beat_id}'")

                prev_diagram_id = beat.get("diagram_id") if cut.get("type") == "diagram" else None
                for ov in layout.get("overlays") or []:
                    item = {"type": "label", "kind": ov.get("kind", "label"), "rect": ov.get("rect"),
                            "in_seconds": in_s, "out_seconds": out_s, "beat_id": beat_id}
                    if ov.get("items") is not None:
                        item["items"] = [str(i) for i in ov["items"]]
                    if ov.get("text") is not None:
                        item["text"] = str(ov["text"])
                    overlays.append(item)
                cuts.append(cut)
                edit_cuts.append({
                    "id": f"cut-{len(cuts)}",
                    "source": cut.get("source") or cut.get("backgroundImage") or cut.get("presenterVideo") or "procedural",
                    "in_seconds": in_s,
                    "out_seconds": out_s,
                    "layer": "primary",
                    "backgroundColor": bg_color,
                    "reason": f"Beat {beat_id} ({v_type}) - {beat.get('visual_reason', '')}",
                })

            # Append aligned captions for this section
            if audio_info and "timestamps" in audio_info:
                offset_ms = int(section_start_time * 1000)
                for ts in audio_info["timestamps"]:
                    all_captions.append({
                        "word": ts["word"],
                        "startMs": int(round(ts["startMs"])) + offset_ms,
                        "endMs": int(round(ts["endMs"])) + offset_ms,
                    })

        # Consecutive beats on the same still image become ONE cut (overlays stay per-beat), so the fade-in and
        # push-in of the image do not restart every few seconds.
        merged_cuts: list[dict[str, Any]] = []
        merged_edit: list[dict[str, Any]] = []
        for c, e in zip(cuts, edit_cuts):
            prev = merged_cuts[-1] if merged_cuts else None
            if (prev is not None and c.get("source") and prev.get("source") == c.get("source")
                    and c.get("type") is None and prev.get("type") is None
                    and c.get("animation") == prev.get("animation")
                    and abs(prev["out_seconds"] - c["in_seconds"]) < 0.011):
                prev["out_seconds"] = c["out_seconds"]
                prev["narrationText"] = (prev.get("narrationText", "") + " " + c.get("narrationText", "")).strip()
                merged_edit[-1]["out_seconds"] = e["out_seconds"]
                continue
            merged_cuts.append(c)
            merged_edit.append(e)
        cuts, edit_cuts = merged_cuts, merged_edit
        for n, e in enumerate(edit_cuts, 1):
            e["id"] = f"cut-{n}"

        # Calculate analytics
        text_card_ratio = round((text_card_duration_s / max(0.1, total_runtime_s)), 3)
        presenter_ratio = round((presenter_duration_s / max(0.1, total_runtime_s)), 3)
        fixture_ratio = round((fixture_presenter_duration_s / max(0.1, total_runtime_s)), 3)
        meaningful_visual_ratio = round((meaningful_visual_duration_s / max(0.1, total_runtime_s)), 3)

        visual_analytics = {
            "total_runtime_seconds": round(total_runtime_s, 2),
            "text_card_duration_seconds": round(text_card_duration_s, 2),
            "text_card_percentage": round(text_card_ratio * 100, 1),
            "presenter_percentage": round(presenter_ratio * 100, 1),
            "fixture_presenter_percentage": round(fixture_ratio * 100, 1),
            "meaningful_visual_percentage": round(meaningful_visual_ratio * 100, 1),
            "total_cuts": len(cuts),
            "average_beat_duration_seconds": round(total_runtime_s / max(1, len(cuts)), 2),
        }

        legibility_problems = validate_diagram_cuts(cuts, canvas)
        visual_analytics["legibility_problems"] = legibility_problems

        edit_decisions = {
            "version": "1.0",
            "render_runtime": "remotion",
            "cuts": edit_cuts,
            "subtitles": {
                "enabled": True,
                "source": "captions",
                "style": "word-by-word",
            },
            "metadata": {
                "analytics": visual_analytics,
                "visual_analytics": visual_analytics,
                "canvas": canvas,
                "aspect": nlayout.aspect_of(canvas),
                # Re-validated against the actual rendered size at compose QA (spec §5.9).
                "diagram_cuts": [
                    {"id": c.get("id"), "type": "diagram", "diagramSpec": c["diagramSpec"], "color": c.get("color")}
                    for c in cuts if c.get("type") == "diagram" and c.get("diagramSpec")
                ],
                "loudness_target_lufs": -14.0,
                "true_peak_limit_dbtp": -1.0,
            },
        }

        return {
            "canvas": canvas,
            "cuts": cuts,
            "captions": all_captions,
            "overlays": overlays,
            "edit_decisions": edit_decisions,
            "visual_analytics": visual_analytics,
        }
