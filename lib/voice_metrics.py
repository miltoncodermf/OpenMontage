"""Objective voice-quality measurements used to diagnose "echo" and "thin" complaints (no ML, numpy/scipy only).

* ``tail``: how speech decays into a pause (a dry voice keeps falling after a phrase ends; a roomy recording, or a
  clone of one, flattens out) and how far below speech the pauses sit.
* ``bands``: long-term spectrum in octave bands relative to the 1-4 kHz level, plus the share of energy below 250 Hz
  ("body") and the spectral centroid (a thin voice has little body and a high centroid).
"""

from __future__ import annotations

from typing import Any

import numpy as np

BANDS = [(80, 160), (160, 320), (320, 640), (640, 1280), (1280, 2560), (2560, 5120), (5120, 10240)]


def _env_db(y: np.ndarray, sr: int, win_ms: float = 10.0) -> tuple[np.ndarray, float]:
    n = max(1, int(sr * win_ms / 1000))
    m = len(y) // n
    e = np.sqrt((y[: m * n].reshape(m, n) ** 2).mean(axis=1) + 1e-12)
    return 20 * np.log10(e + 1e-9), win_ms / 1000


def tail(y: np.ndarray, sr: int) -> dict[str, Any]:
    """Phrase-end behaviour. ``tail_drop_150ms_db``: how much further the level falls 150 ms after speech has
    dropped 15 dB below its normal level (dry voice: 15-25 dB more; a roomy one flattens out at a few dB).
    ``pause_floor_db``: level of the quietest 200 ms stretches relative to speech (dry TTS ~ -55..-65, a bedroom ~ -25..-35)."""
    env, dt = _env_db(y, sr)
    speech = float(np.percentile(env, 90))
    hi = speech - 8.0
    drops: list[float] = []
    i, k = 0, int(0.15 / dt)
    while i < len(env) - k - 1:
        if env[i] >= hi:
            j = i + 1
            while j < len(env) - k - 1 and env[j] >= hi - 15:
                j += 1
            if j < len(env) - k - 1 and j - i < int(0.4 / dt):
                drops.append(float(env[j] - env[j + k]))
            i = j + k
        else:
            i += 1
    w = int(0.2 / dt)
    floor = None
    if len(env) > w:
        roll = np.convolve(env, np.ones(w) / w, mode="valid")
        floor = round(float(np.percentile(roll, 10)) - speech, 1)
    return {"edges": len(drops), "tail_drop_150ms_db": round(float(np.median(drops)), 1) if drops else None, "pause_floor_db": floor}


def bands(y: np.ndarray, sr: int) -> dict[str, Any]:
    from scipy.signal import welch

    f, p = welch(y, fs=sr, nperseg=4096)
    def band(lo: float, hi: float) -> float:
        m = (f >= lo) & (f < hi)
        return float(p[m].sum() + 1e-18)
    ref = band(1280, 4096)
    rel = {f"{lo}-{hi}": round(10 * np.log10(band(lo, hi) / ref), 1) for lo, hi in BANDS}
    tot = band(80, 10240)
    return {"rel_db_vs_1.3-4k": rel, "body_share_below_250hz": round(band(80, 250) / tot, 3),
            "centroid_hz": round(float((f * p)[(f >= 80) & (f < 10240)].sum() / p[(f >= 80) & (f < 10240)].sum()), 0)}


def measure(path: str) -> dict[str, Any]:
    import librosa

    y, sr = librosa.load(path, sr=24000)
    return {"seconds": round(len(y) / sr, 1), **tail(y, sr), **bands(y, sr)}
