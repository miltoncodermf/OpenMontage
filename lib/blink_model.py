"""Natural blinks from the owner's own recording (numbers only: eyelid-opening curves, no footage).

The owner's recording shows how they really blink: the lids drop in 1-2 frames, stay shut for 2-3 frames, then re-open quickly at first
and slowly at the end over 200-300 ms, about 13 times a minute, usually 1.5-8 s apart and rarely twice in a row. Interpolating eye keypoints
in LivePortrait gave a lid that snapped shut, stayed half-open on the way back and closed the two eyes unevenly, so blinks are now
generated as an eyelid-opening trajectory (1 = open, 0 = shut) that is resampled from the owner's real blinks, then rendered by
LivePortrait's own symmetric eye-retargeting module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

OPEN_ENOUGH = 0.92  # fraction of the open baseline at which a blink starts / ends
CLOSED_BELOW = 0.75


def extract(lid, fps: float) -> dict[str, Any]:
    """Blink templates + inter-blink intervals from a per-frame eyelid-opening series (e.g. ``face_tools.face_signals_from_video``)."""
    from scipy.ndimage import percentile_filter

    x = np.asarray(lid, dtype=float)
    ok = np.isfinite(x)
    if ok.sum() < int(10 * fps):
        raise ValueError("need at least 10 seconds of eyelid data")
    x = np.where(ok, x, np.nanmedian(x))
    base = percentile_filter(x, 70, size=max(3, int(3 * fps)), mode="nearest")
    r = x / np.maximum(base, 1e-6)
    n = len(x)
    templates, centres, i = [], [], 0
    while i < n:
        if r[i] < CLOSED_BELOW:
            j = i
            while j < n and r[j] < CLOSED_BELOW:
                j += 1
            a = i
            while a > 0 and r[a - 1] < OPEN_ENOUGH:
                a -= 1
            b = j
            while b < n and r[b] < OPEN_ENOUGH:
                b += 1
            lo, hi = max(0, a - 2), min(n, b + 3)
            templates.append([round(float(v), 3) for v in np.clip(r[lo:hi], 0.0, 1.05)])
            centres.append(a + int(np.argmin(r[a:b])))
            i = b
        else:
            i += 1
    return {"fps": float(fps), "templates": templates, "intervals_s": [round(float(d), 2) for d in np.diff(centres) / fps]}


def save(model: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model))
    path.chmod(0o600)


def load(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def schedule(model: dict[str, Any], n_frames: int, fps: float = 25.0, hold_frames: int = 0, seed: int = 7, stretch: tuple = (0.92, 1.1),
             interval_limits: tuple = (1.3, 9.0)) -> np.ndarray:
    """Per-frame eyelid opening (1 = open) for ``n_frames`` output frames: the owner's real blinks, resampled with a random time stretch and
    sub-frame jitter, spaced by the owner's real intervals. The first ``hold_frames`` frames stay open."""
    rng = np.random.default_rng(seed)
    templates = [np.asarray(t, dtype=float) for t in model["templates"] if len(t) >= 5]
    intervals = [d for d in model["intervals_s"] if d > 0.25] or [3.2]
    tfps = float(model["fps"])
    lid = np.ones(n_frames)
    seconds = (n_frames - hold_frames) / fps
    t = 1.2 + float(rng.uniform(0, 1.5))
    while t < seconds - 0.6:
        tpl = templates[int(rng.integers(len(templates)))]
        s = float(rng.uniform(*stretch))
        jitter = float(rng.uniform(-0.5, 0.5)) / fps
        t0 = t + jitter - 2.0 * s / tfps  # the template starts two frames before the lids move
        for j in range(hold_frames, n_frames):
            tau = ((j - hold_frames) / fps - t0) / s * tfps
            if 0 <= tau <= len(tpl) - 1:
                lid[j] = min(lid[j], float(np.interp(tau, np.arange(len(tpl)), tpl)))
        gap = float(np.clip(rng.choice(intervals), *interval_limits))
        t += gap
    return np.clip(lid, 0.0, 1.0)
