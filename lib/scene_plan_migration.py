"""Scene plan migration utilities between v1.0 and v2.0 beat-level IR."""

from __future__ import annotations

from typing import Any


def migrate_scene_plan_v1_to_v2(v1_data: dict[str, Any]) -> dict[str, Any]:
    """Migrate legacy v1.0 scene plan to v2.0 beat-level IR."""
    if v1_data.get("version") == "2.0" and "sections" in v1_data:
        return v1_data

    scenes = v1_data.get("scenes", [])
    sections = []

    for sc in scenes:
        scene_id = str(sc.get("id", ""))
        sec_id = sc.get("script_section_id") or scene_id
        duration = float(sc.get("end_seconds", 0)) - float(sc.get("start_seconds", 0))
        if duration <= 0:
            duration = 5.0

        v_type_raw = str(sc.get("type", "diagram")).lower()
        if v_type_raw in ("text_card", "stat_card"):
            visual_type = v_type_raw
        elif v_type_raw in ("talking_head", "presenter"):
            visual_type = "presenter_fullscreen"
        elif v_type_raw in ("broll", "generated"):
            visual_type = "image_broll"
        elif v_type_raw == "screen_recording":
            visual_type = "screen_recording"
        else:
            visual_type = "diagram"

        beat = {
            "beat_id": f"{scene_id}_beat_1",
            "duration_hint_seconds": round(duration, 2),
            "visual_type": visual_type,
            "visual_reason": f"Migrated from v1.0 scene {scene_id} ({sc.get('description', '')})",
            "layout": {
                "preset": visual_type,
                "presenter_pip": visual_type == "presenter_pip",
            },
            "asset_requirements": [
                req.get("id") or req.get("type")
                for req in sc.get("required_assets", [])
                if isinstance(req, dict)
            ],
            "transition_in": sc.get("transition_in", "cut"),
            "transition_out": sc.get("transition_out", "fade"),
        }

        sections.append({
            "section_id": f"section_{sec_id}",
            "script_section_id": sec_id,
            "learning_objective": sc.get("information_role") or sc.get("description", ""),
            "key_takeaway": sc.get("shot_intent") or "",
            "visual_beats": [beat],
        })

    v2_data = {
        "version": "2.0",
        "style_playbook": v1_data.get("style_playbook", "software-technical"),
        "fps": 30,
        "canvas": {"width": 1920, "height": 1080, "aspect_ratio": "16:9"},
        "presenter_policy": {
            "enabled": any("presenter" in b["visual_type"] for s in sections for b in s["visual_beats"]),
            "preferred_source": "twin_auto",
            "fallback": "visual_explainer",
            "pip_allowed": True,
        },
        "sections": sections,
        "scenes": scenes,
    }
    if "metadata" in v1_data:
        v2_data["metadata"] = v1_data["metadata"]

    return v2_data
