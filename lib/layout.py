"""Normalized layout (spec §5.9) — Python mirror of remotion-composer/src/layouts/*.

Layout is expressed in normalized units relative to the canvas; pixels are computed from
``canvas = {width, height}``. 16:9 is implemented; ``portrait`` is the trivial 9:16 seam
(a placeholder that proves the same scene plan compiles for a portrait canvas).
"""

from __future__ import annotations

from typing import Any

MARGIN_X = 0.05
MARGIN_Y = 0.06
CAPTION_CLEARANCE = 0.055
PIP_POSITIONS = ("bottom-right", "bottom-left", "top-right", "top-left")
FULL = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}

Rect = dict[str, float]


def aspect_of(canvas: dict[str, Any]) -> str:
    return "portrait" if canvas["height"] > canvas["width"] else "landscape"


def validate_focus_region(r: Rect) -> list[str]:
    problems = []
    for k in ("x", "y", "w", "h"):
        if k not in r or not isinstance(r[k], (int, float)):
            problems.append(f"focus_region missing numeric {k}")
    if problems:
        return problems
    if not (0 <= r["x"] <= 1 and 0 <= r["y"] <= 1 and 0 < r["w"] <= 1 and 0 < r["h"] <= 1):
        problems.append("focus_region values must be normalized 0-1 (w,h > 0)")
    elif r["x"] + r["w"] > 1.0001 or r["y"] + r["h"] > 1.0001:
        problems.append("focus_region extends beyond the canvas")
    return problems


def pip_rect(position: str, width_fraction: float, canvas: dict[str, Any]) -> Rect:
    if aspect_of(canvas) == "portrait":
        w = min(0.9, width_fraction * 2.2)
        return {"x": (1 - w) / 2, "y": 0.62, "w": w, "h": (w * canvas["width"] * 9 / 16) / canvas["height"]}
    w = width_fraction
    h = (w * canvas["width"] * 9 / 16) / canvas["height"]
    x = 1 - MARGIN_X - w if position.endswith("right") else MARGIN_X
    y = 1 - MARGIN_Y - CAPTION_CLEARANCE - h if position.startswith("bottom") else MARGIN_Y
    return {"x": x, "y": y, "w": w, "h": h}


def caption_safe(canvas: dict[str, Any]) -> Rect:
    if aspect_of(canvas) == "portrait":
        return {"x": 0.06, "y": 0.7, "w": 0.88, "h": 0.12}
    return {"x": 0.08, "y": 0.8, "w": 0.84, "h": 0.14}


def split_rects(side: str, ratio: float, canvas: dict[str, Any]) -> dict[str, Rect]:
    if aspect_of(canvas) == "portrait":
        ph = min(0.45, ratio + 0.1)
        return {"presenter": {"x": 0, "y": 1 - ph, "w": 1, "h": ph}, "content": {"x": 0, "y": 0, "w": 1, "h": 1 - ph}}
    left = side == "left"
    return {"presenter": {"x": 0 if left else 1 - ratio, "y": 0, "w": ratio, "h": 1},
            "content": {"x": ratio if left else 0, "y": 0, "w": 1 - ratio, "h": 1}}


def overlap_area(a: Rect, b: Rect) -> float:
    w = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    h = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    return max(0.0, w) * max(0.0, h)


def covers_focus(rect: Rect, focus: Rect, tolerance: float = 0.05) -> bool:
    """True if ``rect`` hides more than ``tolerance`` of the focus region's area."""
    return overlap_area(rect, focus) > tolerance * focus["w"] * focus["h"]


def choose_pip_position(preferred: str, width_fraction: float, canvas: dict[str, Any], focus: Rect | None) -> tuple[str, bool]:
    """First PIP corner that does not cover the focus region. Returns (position, covers_focus_anyway)."""
    if not focus:
        return preferred, False
    order = [preferred] + [p for p in PIP_POSITIONS if p != preferred]
    for pos in order:
        if not covers_focus(pip_rect(pos, width_fraction, canvas), focus):
            return pos, False
    return preferred, True


def to_px(r: Rect, canvas: dict[str, Any]) -> dict[str, int]:
    return {"x": round(r["x"] * canvas["width"]), "y": round(r["y"] * canvas["height"]),
            "w": round(r["w"] * canvas["width"]), "h": round(r["h"] * canvas["height"])}
