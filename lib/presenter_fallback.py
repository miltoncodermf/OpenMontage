"""No-presenter fallback (spec D2, §5.5 step 6).

If the twin cannot be produced or fails QA the video is made WITHOUT a presenter: presenter beats
are re-planned into visual beats, the policy is disabled, and the reason is recorded
(``presenter_status: skipped_failed``) so the assets gate can surface it. No stylized stand-in.
"""

from __future__ import annotations

import copy
from typing import Any

PRESENTER_BEATS = {"presenter_fullscreen", "presenter_pip", "presenter_screen_split"}


def _diagram_for(section: dict[str, Any], beat: dict[str, Any]) -> dict[str, Any]:
    title = beat.get("title") or section.get("learning_objective") or "Overview"
    nodes = [title[:28], "How it works", "Result"]
    return {"title": title, "nodes": nodes, "edges": [[nodes[0], nodes[1]], [nodes[1], nodes[2]]]}


def replan_without_presenter(scene_plan: dict[str, Any], reason: str) -> dict[str, Any]:
    """Return a copy of the v2 scene plan with every presenter beat converted to a visual beat."""
    plan = copy.deepcopy(scene_plan)
    converted = 0
    for section in plan.get("sections", []):
        for beat in section.get("visual_beats", []):
            vt = beat.get("visual_type")
            layout = beat.get("layout") or {}
            if vt in PRESENTER_BEATS or layout.get("presenter_pip"):
                if vt == "presenter_fullscreen":
                    beat["visual_type"] = "diagram"
                    beat.setdefault("diagram_spec", _diagram_for(section, beat))
                elif vt in {"presenter_pip", "presenter_screen_split"}:
                    beat["visual_type"] = "diagram"
                    beat.setdefault("diagram_spec", _diagram_for(section, beat))
                layout = dict(layout)
                layout.pop("presenter_pip", None)
                layout["preset"] = beat["visual_type"]
                beat["layout"] = layout
                beat["presenter_removed"] = True
                converted += 1
    policy = plan.setdefault("presenter_policy", {})
    policy.update({"enabled": False, "preferred_source": "none", "fallback": "visual_explainer", "pip_allowed": False})
    meta = plan.setdefault("metadata", {})
    meta["presenter_status"] = "skipped_failed"
    meta["presenter_status_reason"] = reason
    meta["presenter_beats_replanned"] = converted
    return plan
