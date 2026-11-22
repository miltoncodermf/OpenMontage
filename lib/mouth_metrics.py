"""Mouth naturalness measurements for the presenter twin (MediaPipe landmarks + simple image statistics).

Per frame, normalised by face width so a real recording and a render at another scale can be compared:
* ``open_h``  inner-lip height / face width          (how far the mouth opens)
* ``width``   mouth corner distance / face width     (sideways stretch: a smile or an "ee" is wide)
* ``aspect``  inner-lip height / mouth width         (round "oh" ~ tall, wide "ee" ~ flat)
* ``teeth``   share of the inside of the lips that is bright and unsaturated (teeth visible)
* ``crease``  edge energy in the cheek bands beside the mouth corners, relative to a calm cheek reference (marionette/diagonal crease)
* ``sharp_ratio``  Laplacian variance of the lower face over that of the upper face (below 1 = the mouth area is blurrier than the eyes)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from lib import face_tools

INNER_LIPS = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95]


def _lap_var(g: np.ndarray) -> float:
    import cv2

    return float(cv2.Laplacian(g, cv2.CV_32F, ksize=3).var()) if g.size > 64 else float("nan")


def _grad(g: np.ndarray) -> float:
    import cv2

    g = cv2.GaussianBlur(g, (0, 0), 1.2)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    return float(np.mean(np.sqrt(gx ** 2 + gy ** 2))) if g.size else float("nan")


def frame_metrics(img: Image.Image) -> dict[str, float] | None:
    import cv2

    lm = face_tools.face_landmarks(img)
    if lm is None:
        return None
    w, h = img.size
    px = lm[:, :2] * np.array([w, h], dtype=np.float32)
    fw = float(np.linalg.norm(px[234] - px[454]))
    mw = float(np.linalg.norm(px[61] - px[291]))
    ih = float(np.linalg.norm(px[13] - px[14]))
    arr = np.asarray(img.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY).astype(np.float32)
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    # teeth: bright, unsaturated pixels inside the inner lip polygon
    poly = px[INNER_LIPS].astype(np.int32)
    mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(mask, [poly], 255)
    inside = mask > 0
    teeth = float(((hsv[..., 2] > 140) & (hsv[..., 1] < 130) & inside).sum() / max(1, inside.sum())) if ih > 0.02 * fw else 0.0
    # crease: gradient energy in a band beside each mouth corner, going down toward the jaw
    bands = []
    for corner, sign in ((61, -1), (291, 1)):
        cx, cy = px[corner]
        x0, x1 = sorted((cx - sign * 0.04 * fw * -1, cx + sign * 0.20 * fw))
        y0, y1 = cy - 0.03 * fw, cy + 0.28 * fw
        bands.append(gray[max(0, int(y0)):int(y1), max(0, int(x0)):int(x1)])
    ref_y0 = px[1][1] - 0.02 * fw
    ref = gray[max(0, int(ref_y0)):int(ref_y0 + 0.12 * fw), int(px[1][0] - 0.45 * fw):int(px[1][0] - 0.2 * fw)]  # calm cheek beside the nose
    crease = float(np.nanmean([_grad(b) for b in bands]) / (_grad(ref) + 1e-6))
    upper = gray[int(px[10][1]): int(px[9][1] + 0.35 * fw), int(px[234][0] + 0.12 * fw): int(px[454][0] - 0.12 * fw)]
    lower = gray[int(px[2][1]): int(px[152][1]), int(px[234][0] + 0.2 * fw): int(px[454][0] - 0.2 * fw)]
    return {"open_h": ih / fw, "width": mw / fw, "aspect": ih / max(mw, 1e-6), "teeth": teeth, "crease": crease,
            "sharp_ratio": _lap_var(lower) / max(_lap_var(upper), 1e-6)}


def video_metrics(video: Path, fps: float = 25.0, start: float | None = None, duration: float | None = None) -> dict[str, np.ndarray]:
    import subprocess
    import tempfile

    out: dict[str, list[float]] = {k: [] for k in ("open_h", "width", "aspect", "teeth", "crease", "sharp_ratio")}
    pre = (["-ss", str(start)] if start is not None else []) + (["-t", str(duration)] if duration is not None else [])
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["ffmpeg", "-y", "-v", "error", *pre, "-i", str(video), "-vf", f"fps={fps}", str(Path(td) / "f_%05d.png")], check=True, timeout=1800)
        for f in sorted(Path(td).glob("f_*.png")):
            m = frame_metrics(Image.open(f))
            for k in out:
                out[k].append(m[k] if m else float("nan"))
    return {k: np.array(v, dtype=np.float32) for k, v in out.items()}


def summarize(sig: dict[str, np.ndarray]) -> dict[str, Any]:
    def q(x, p):
        return round(float(np.nanpercentile(x, p)), 3)

    ih = sig["open_h"]
    speaking = ih > 0.02  # mouth visibly open
    return {"open_h_mean_when_open": round(float(np.nanmean(ih[speaking])), 3) if speaking.any() else None, "open_h_p90": q(ih, 90), "open_h_max": q(ih, 100),
            "width_mean": round(float(np.nanmean(sig["width"])), 3), "width_p90": q(sig["width"], 90),
            "aspect_mean_when_open": round(float(np.nanmean(sig["aspect"][speaking])), 3) if speaking.any() else None,
            "teeth_frames_pct": round(100 * float(np.nanmean(sig["teeth"] > 0.12)), 1), "crease_mean": round(float(np.nanmean(sig["crease"])), 3),
            "crease_p90": q(sig["crease"], 90), "sharp_ratio_mean": round(float(np.nanmean(sig["sharp_ratio"])), 3)}
