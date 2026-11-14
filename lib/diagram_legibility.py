"""Diagram legibility validator (spec §5.9) — used at compose QA and in fast tests.

At 1080p: node labels >= 28 px, titles >= 44 px, text contrast >= 4.5:1, <= 7 nodes per beat
(progressive reveal / splitting for more). Sizes scale with canvas height. The constants mirror
remotion-composer/src/layouts/diagramMetrics.ts (a fast test keeps them in sync).
"""

from __future__ import annotations

import re
from typing import Any

BASE_HEIGHT = 1080
MIN_LABEL_PX = 28
MIN_TITLE_PX = 44
MIN_SUBLABEL_PX = 22
MIN_EDGE_LABEL_PX = 22
MAX_NODES_PER_BEAT = 7
MIN_CONTRAST = 4.5
CARD_BACKGROUND = "#0F172A"  # the node-card colour DiagramScene draws text on (lightest stop: #1E293B)
CARD_BACKGROUND_LIGHTEST = "#1E293B"


def font_sizes(canvas_height: int) -> dict[str, int]:
    s = canvas_height / BASE_HEIGHT
    return {"label": round(MIN_LABEL_PX * s), "title": round(MIN_TITLE_PX * s),
            "sublabel": round(MIN_SUBLABEL_PX * s), "edge_label": round(MIN_EDGE_LABEL_PX * s)}


def _lin(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast_ratio(fg: str, bg: str) -> float:
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


_HEX = re.compile(r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")


def node_count(spec: dict[str, Any]) -> int:
    return len(spec.get("nodes") or [])


def split_diagram_spec(spec: dict[str, Any], max_nodes: int = MAX_NODES_PER_BEAT) -> list[dict[str, Any]]:
    """Split an oversized diagram into consecutive chunks of <= max_nodes (progressive reveal across beats)."""
    nodes = list(spec.get("nodes") or [])
    if len(nodes) <= max_nodes:
        return [spec]

    def name(n: Any, i: int) -> str:
        return n if isinstance(n, str) else n.get("label") or n.get("id") or f"node_{i}"

    chunks = [nodes[i:i + max_nodes] for i in range(0, len(nodes), max_nodes)]
    out = []
    for k, chunk in enumerate(chunks, 1):
        names = {name(n, 0) for n in chunk} | {n.get("id") for n in chunk if isinstance(n, dict)}
        edges = [e for e in (spec.get("edges") or [])
                 if (e[0] if isinstance(e, (list, tuple)) else e["from"]) in names and (e[1] if isinstance(e, (list, tuple)) else e["to"]) in names]
        title = spec.get("title") or "Diagram"
        out.append({**spec, "title": f"{title} ({k}/{len(chunks)})", "nodes": chunk, "edges": edges})
    return out


def validate_diagram_spec(spec: dict[str, Any], canvas: dict[str, int], text_color: str = "#F8FAFC") -> list[str]:
    """Problems that would make this diagram illegible on ``canvas`` (empty list = OK)."""
    problems: list[str] = []
    n = node_count(spec)
    if n > MAX_NODES_PER_BEAT:
        problems.append(f"{n} nodes in one beat (max {MAX_NODES_PER_BEAT}); split into progressive-reveal beats")
    fonts = font_sizes(canvas["height"])
    floor = canvas["height"] / BASE_HEIGHT
    if fonts["label"] < MIN_LABEL_PX * floor - 0.5 or fonts["title"] < MIN_TITLE_PX * floor - 0.5:
        problems.append("rendered font sizes fall below the 1080p-scaled legibility floor")
    # Explicit per-diagram font overrides (px at the rendered canvas) must also respect the floor.
    for key, floor_px, what in (("label_font_px", MIN_LABEL_PX, "label"), ("title_font_px", MIN_TITLE_PX, "title")):
        px = spec.get(key)
        if px is not None and float(px) < floor_px * floor - 0.5:
            problems.append(f"{what} font {px}px is below the {round(floor_px * floor)}px legibility floor at this canvas")
    if _HEX.match(text_color or ""):
        for bg in (CARD_BACKGROUND, CARD_BACKGROUND_LIGHTEST):
            c = contrast_ratio(text_color, bg)
            if c < MIN_CONTRAST:
                problems.append(f"text colour {text_color} on card {bg} has contrast {c:.2f}:1 (< {MIN_CONTRAST}:1)")
    else:
        problems.append(f"text colour {text_color!r} is not a hex colour; contrast cannot be verified")
    for i, node in enumerate(spec.get("nodes") or []):
        label = node if isinstance(node, str) else node.get("label", "")
        if len(label) > 36:
            problems.append(f"node {i} label is {len(label)} chars (> 36): too long to stay legible at the label size")
    return problems


def validate_cuts(cuts: list[dict[str, Any]], canvas: dict[str, int]) -> list[str]:
    """Check every diagram cut in compiled Remotion props."""
    problems = []
    for cut in cuts:
        if cut.get("type") == "diagram" and cut.get("diagramSpec"):
            for p in validate_diagram_spec(cut["diagramSpec"], canvas, cut.get("color") or "#F8FAFC"):
                problems.append(f"{cut.get('id')}: {p}")
    return problems
