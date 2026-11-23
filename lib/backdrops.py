"""Background styles for the presenter (owner decision, gate 1): a small catalog the owner picks from.

The presenter is always a separate alpha layer; the backdrop is composited *behind* it by Remotion, never baked
into the twin. Two kinds of style:

* ``procedural`` — drawn from a spec (gradient stops, optional grid/glow); costs $0 and renders in Remotion or PIL.
* ``plate``      — a person-free 16:9 Gemini image stored in the profile (paid, once); reused for every video.

Plates keep the centre third clean for the presenter and all essential detail inside the centre 9:16 column
(``SAFE_REGION``), so a vertical re-crop stays usable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

CATALOG = "backgrounds/backgrounds_catalog.json"
# fractions of the 16:9 frame: the presenter sits in the middle third; a 9:16 crop keeps x in [0.3203, 0.6797]
SAFE_REGION = {"presenter_x": [0.333, 0.667], "vertical_crop_9x16_x": [0.3203, 0.6797]}

PROCEDURAL: list[dict[str, Any]] = [
    {"id": "bg_soft_gradient", "kind": "procedural", "label": "Soft gradient", "angle": 160,
     "stops": [[0.0, "#E9EEF5"], [0.55, "#C9D6E8"], [1.0, "#9FB4D1"]], "overlay": None, "cost": "$0"},
    {"id": "bg_dark_tech", "kind": "procedural", "label": "Dark tech", "angle": 135,
     "stops": [[0.0, "#0B1220"], [0.6, "#101B33"], [1.0, "#16284A"]], "overlay": "grid_glow", "cost": "$0"},
    {"id": "bg_clean_light", "kind": "procedural", "label": "Clean light", "angle": 180,
     "stops": [[0.0, "#FAFAF7"], [1.0, "#E7E7E1"]], "overlay": "vignette", "cost": "$0"},
]


def _hex(c: str) -> np.ndarray:
    c = c.lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


def render_procedural(spec: dict[str, Any], size: tuple[int, int] = (1920, 1080)) -> Image.Image:
    """Deterministic PIL rendering of a procedural spec (preview; Remotion draws the same spec at render time)."""
    w, h = size
    ang = np.deg2rad(spec.get("angle", 180))
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    t = (xs / w - 0.5) * np.sin(ang) - (ys / h - 0.5) * np.cos(ang)
    t = (t - t.min()) / max(float(t.max() - t.min()), 1e-6)
    stops = spec["stops"]
    img = np.zeros((h, w, 3), np.float32)
    pos = [s[0] for s in stops]
    for ch in range(3):
        img[..., ch] = np.interp(t, pos, [float(_hex(s[1])[ch]) for s in stops])
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    ov = spec.get("overlay")
    if ov == "grid_glow":
        d = ImageDraw.Draw(im, "RGBA")
        for x in range(0, w, 60):
            d.line([(x, 0), (x, h)], fill=(120, 170, 255, 14))
        for y in range(0, h, 60):
            d.line([(0, y), (w, y)], fill=(120, 170, 255, 14))
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse([w * 0.62, -h * 0.2, w * 1.15, h * 0.7], fill=(40, 120, 255, 70))
        im = Image.alpha_composite(im.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(120))).convert("RGB")
    elif ov == "vignette":
        a = np.asarray(im, np.float32)
        r = np.sqrt(((xs / w - 0.5) * 1.2) ** 2 + ((ys / h - 0.5)) ** 2)
        a *= (1.0 - 0.12 * np.clip(r / 0.8, 0, 1))[..., None]
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    return im


def _read(d: Path) -> list[dict[str, Any]]:
    f = d / CATALOG
    return json.loads(f.read_text()) if f.is_file() else []


def upsert(d: Path, entry: dict[str, Any]) -> list[dict[str, Any]]:
    cat = [c for c in _read(d) if c["id"] != entry["id"]] + [entry]
    f = d / CATALOG
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(cat, indent=2))
    f.chmod(0o600)
    return cat


def install_procedural(d: Path) -> list[dict[str, Any]]:
    cat = _read(d)
    for spec in PROCEDURAL:
        cat = upsert(d, spec)
    return cat


def backdrop_image(d: Path, entry: dict[str, Any], size: tuple[int, int] = (1920, 1080)) -> Image.Image:
    if entry["kind"] == "procedural":
        return render_procedural(entry, size)
    return Image.open(d / entry["image"]).convert("RGB").resize(size, Image.LANCZOS)


def composite(portrait_rgba: Image.Image, backdrop: Image.Image) -> Image.Image:
    """Matted presenter (RGBA, same 16:9 frame) over a backdrop."""
    bg = backdrop.convert("RGBA").resize(portrait_rgba.size, Image.LANCZOS)
    return Image.alpha_composite(bg, portrait_rgba.convert("RGBA")).convert("RGB")


def matte_portrait(path: Path, segmenter: Callable[[Image.Image], Image.Image] | None = None) -> Image.Image:
    """RGBA cut-out of a portrait (BiRefNet on MPS by default)."""
    if segmenter is None:
        from tools.presenters.presenter_matte import default_segmenter

        segmenter = default_segmenter()
    return segmenter(Image.open(path).convert("RGB")).convert("RGBA")


def get_entry(d: Path, backdrop_id: str) -> dict[str, Any]:
    for e in _read(d):
        if e["id"] == backdrop_id:
            return e
    raise KeyError(f"background '{backdrop_id}' is not in {d / CATALOG}; have: {[e['id'] for e in _read(d)]}")


def remotion_spec(d: Path, backdrop_id: str) -> dict[str, Any]:
    """The `presenterBackdrop` cut prop for Remotion: a procedural spec (drawn at render time) or a plate path.

    Plates are person-free generated images, not raw footage, so an absolute path into the profile is fine here.
    """
    e = get_entry(d, backdrop_id)
    if e["kind"] == "procedural":
        return {"kind": "procedural", "id": e["id"], "angle": e.get("angle", 180), "stops": e["stops"],
                "overlay": e.get("overlay")}
    img = (d / e["image"]).resolve()
    if not img.is_file():
        raise FileNotFoundError(f"plate image for '{backdrop_id}' is missing: {img}")
    return {"kind": "plate", "id": e["id"], "src": str(img)}


def validate_remotion_spec(spec: Any) -> list[str]:
    """Problems with a `presenterBackdrop` value (empty list = fine). Used by the scene-plan adapter."""
    if not isinstance(spec, dict):
        return ["presenter_backdrop must be an object"]
    kind = spec.get("kind")
    if kind == "plate":
        return [] if isinstance(spec.get("src"), str) and spec["src"] else ["plate backdrop needs 'src'"]
    if kind == "procedural":
        stops = spec.get("stops")
        if not (isinstance(stops, list) and len(stops) >= 2 and all(
                isinstance(s, (list, tuple)) and len(s) == 2 and isinstance(s[1], str) for s in stops)):
            return ["procedural backdrop needs 'stops': [[pos, '#hex'], ...] (>= 2)"]
        if spec.get("overlay") not in (None, "grid_glow", "vignette"):
            return [f"unknown overlay {spec.get('overlay')!r}"]
        return []
    return [f"unknown backdrop kind {kind!r} (expected 'procedural' or 'plate')"]
