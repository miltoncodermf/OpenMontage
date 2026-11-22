"""Presenter QA (spec §5.5 step 5) — honest: checks that cannot run report ``not_run``, never pass.

* face present in ≥ 98 % of frames           (needs a face detector; MediaPipe — injectable)
* mouth–audio offset within ±2 frames        (mouth-open series vs audio envelope; series provider injectable)
* no frame identical to raw/ recordings      (16x16 difference hash vs raw frames; pure PIL/ffmpeg)
* identity_transform == "beautified"         (presenter guard)
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
from PIL import Image

FACE_PRESENCE_MIN = 0.98
MAX_OFFSET_FRAMES = 2
RAW_HASH_MAX_DISTANCE = 6  # of 256 bits
BROW_MIRROR_MAX = 0.80  # mirror correlation of the brow series (see check_brow_repetition); real footage 0.66, ping-pong 0.87-0.92
BROW_AUTOCORR_MAX = 0.75
BLINKS_PER_MIN = (6.0, 30.0)  # natural range (the owner's own recording: 15/min)
FACE_SCALE_MAX_VARIATION = 0.03  # head size may vary at most ~3% over the clip (owner feedback: head resizing)


def dhash(img: Image.Image, size: int = 16) -> int:
    g = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    a = np.asarray(g, dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def video_frame_hashes(video: Path, fps: float = 2.0) -> list[int]:
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf", f"fps={fps},scale=256:-2", str(Path(td) / "f_%05d.png")],
                       check=True, timeout=600)
        return [dhash(Image.open(f)) for f in sorted(Path(td).glob("f_*.png"))]


def check_no_raw_frames(clip: Path, raw_videos: Sequence[Path], fps: float = 2.0) -> dict[str, Any]:
    """Fail if any sampled frame of ``clip`` is perceptually identical to a frame of an owner recording."""
    raw_hashes = [h for r in raw_videos for h in video_frame_hashes(r, fps)]
    if not raw_hashes:
        return {"status": "not_run", "passed": None, "reason": "no raw recordings to compare against"}
    clip_hashes = video_frame_hashes(clip, fps)
    worst = min((hamming(c, r) for c in clip_hashes for r in raw_hashes), default=256)
    return {"status": "run", "passed": worst > RAW_HASH_MAX_DISTANCE, "min_hamming_distance": worst, "threshold": RAW_HASH_MAX_DISTANCE}


def audio_envelope(wav: Path, fps: float, n_frames: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True, timeout=300).stdout
    x = np.abs(np.frombuffer(raw, dtype=np.float32))
    per = 16000.0 / fps
    env = np.array([x[int(i * per): int((i + 1) * per)].mean() if int((i + 1) * per) <= len(x) else 0.0 for i in range(n_frames)])
    return env


def estimate_offset_frames(mouth_open: np.ndarray, envelope: np.ndarray, max_lag: int = 10) -> int:
    """Lag (frames) at which the mouth-open series best matches the audio envelope. +ve = mouth lags audio."""
    m = (mouth_open - mouth_open.mean()) / (mouth_open.std() + 1e-9)
    a = (envelope - envelope.mean()) / (envelope.std() + 1e-9)
    n = min(len(m), len(a))
    best, best_lag = -1e9, 0
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            x, y = m[lag:n], a[: n - lag]
        else:
            x, y = m[: n + lag], a[-lag:n]
        if len(x) < 5:
            continue
        score = float(np.dot(x, y)) / len(x)
        if score > best:
            best, best_lag = score, lag
    return best_lag


def lag_scores(mouth_open: np.ndarray, envelope: np.ndarray, max_lag: int = 10) -> list[tuple[int, float]]:
    m = (mouth_open - mouth_open.mean()) / (mouth_open.std() + 1e-9)
    a = (envelope - envelope.mean()) / (envelope.std() + 1e-9)
    n = min(len(m), len(a))
    out = []
    for lag in range(-max_lag, max_lag + 1):
        x, y = (m[lag:n], a[: n - lag]) if lag >= 0 else (m[: n + lag], a[-lag:n])
        if len(x) >= 5:
            out.append((lag, float(np.dot(x, y)) / len(x)))
    return out


def significant_offset(mouth_open: np.ndarray, envelope: np.ndarray, max_lag: int = 10, n_null: int = 200, seed: int = 0) -> dict[str, Any]:
    """Best lag plus a null test: the peak correlation must beat the 95th percentile of peaks obtained with the audio
    envelope circularly shifted by random amounts (so unrelated audio cannot 'pass'). Lip-gap vs RMS envelope is a weak
    proxy; when the peak is not significant the check is *inconclusive* (never a pass)."""
    scores = lag_scores(mouth_open, envelope, max_lag)
    lag, peak = max(scores, key=lambda t: t[1])
    rng = np.random.default_rng(seed)
    n = min(len(mouth_open), len(envelope))
    nulls = []
    for _ in range(n_null):
        sh = int(rng.integers(max(30, n // 8), max(31, n - max(30, n // 8))))
        nulls.append(max(s for _, s in lag_scores(mouth_open, np.roll(envelope, sh), max_lag)))
    p95 = float(np.percentile(nulls, 95))
    return {"offset_frames": lag, "peak_correlation": round(peak, 3), "null_p95": round(p95, 3), "significant": bool(peak > p95)}


def check_face_presence(video: Path, detector: Callable[[Image.Image], bool] | None, fps: float = 5.0) -> dict[str, Any]:
    if detector is None:
        return {"status": "not_run", "passed": None, "reason": "no face detector available (install mediapipe)"}
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf", f"fps={fps}", str(Path(td) / "f_%05d.png")], check=True, timeout=600)
        frames = sorted(Path(td).glob("f_*.png"))
        hits = sum(1 for f in frames if detector(Image.open(f).convert("RGB")))
    ratio = hits / max(1, len(frames))
    return {"status": "run", "passed": ratio >= FACE_PRESENCE_MIN, "face_ratio": round(ratio, 4), "frames": len(frames)}


def check_mouth_sync(video: Path, audio: Path, fps: float,
                     mouth_series: Callable[[Path], np.ndarray] | None) -> dict[str, Any]:
    if mouth_series is None:
        return {"status": "not_run", "passed": None, "reason": "no mouth-landmark provider available (install mediapipe)"}
    m = mouth_series(video)
    res = significant_offset(m, audio_envelope(audio, fps, len(m)))
    if not res["significant"]:
        return {"status": "inconclusive", "passed": None, **res, "limit": MAX_OFFSET_FRAMES,
                "reason": "lip-gap vs audio-envelope correlation is not above the unrelated-audio null; offset not trustworthy — review by eye/ear"}
    return {"status": "run", "passed": abs(res["offset_frames"]) <= MAX_OFFSET_FRAMES, **res, "limit": MAX_OFFSET_FRAMES}


def check_face_scale(video: Path, width_series: Callable[[Path], np.ndarray] | None, max_variation: float = FACE_SCALE_MAX_VARIATION,
                     fps: float = 5.0) -> dict[str, Any]:
    """The face must keep its size: (max - min) of the 1-second median face widths over their overall median <= ``max_variation``
    (a steady lean or zoom shows up as a trend, a nod only as brief jitter that the 1 s median removes)."""
    if width_series is None:
        return {"status": "not_run", "passed": None, "reason": "no face-width provider available (install mediapipe)"}
    w = np.asarray(width_series(video), dtype=float)
    step = max(1, int(round(fps)))
    meds = [float(np.nanmedian(w[i:i + step])) for i in range(0, len(w), step) if np.isfinite(w[i:i + step]).sum() >= max(1, step // 2)]
    if len(meds) < 3:
        return {"status": "not_run", "passed": None, "reason": "fewer than 3 seconds with a detectable face"}
    ref = float(np.median(meds))
    var = (max(meds) - min(meds)) / ref
    return {"status": "run", "passed": var <= max_variation, "variation": round(var, 4), "threshold": max_variation,
            "min_width_px": round(min(meds), 1), "max_width_px": round(max(meds), 1), "seconds": len(meds)}


def _detrended(x, fps: float):
    x = np.asarray(x, dtype=float)
    idx = np.arange(len(x))
    ok = np.isfinite(x)
    if ok.sum() < 3:
        return None
    x = np.interp(idx, idx[ok], x[ok])
    k = max(3, int(1.5 * fps))
    ma = np.convolve(np.pad(x, (k // 2, k // 2), mode="edge"), np.ones(k) / k, mode="valid")[: len(x)]
    d = x - ma
    from scipy.ndimage import gaussian_filter1d

    d = gaussian_filter1d(d, max(1.0, 0.15 * fps))  # landmark jitter, not expression
    return d / (d.std() + 1e-9)


def check_brow_repetition(brow, fps: float = 25.0, max_mirror: float = BROW_MIRROR_MAX, max_autocorr: float = BROW_AUTOCORR_MAX) -> dict[str, Any]:
    """Brow movement must not repeat. Two statistics on the (detrended, jitter-smoothed) brow height:
    * mirror correlation: the series before a point against its own time-reversal after it, over windows of up to 8 s each side — a ping-pong
      loop reverses the motion, so this stays high (0.87-0.92 measured) while free movement does not (0.66 and -0.01 on the owner's real footage);
    * autocorrelation at lags of 2-10 s — a plain repeat shows up here (real footage 0.34-0.64).
    Heuristic, calibrated on the owner's recording and the earlier ping-pong renders; the peak values are reported."""
    if brow is None:
        return {"status": "not_run", "passed": None, "reason": "no face-signal provider available (install mediapipe)"}
    x = _detrended(brow, fps)
    n = 0 if x is None else len(x)
    if x is None or n < int(12 * fps):
        return {"status": "not_run", "passed": None, "reason": "fewer than 12 seconds of brow data"}
    best_ac, ac_lag = -1.0, 0.0
    for lag in range(int(2.0 * fps), min(int(10 * fps), int(n * 0.55))):
        a_, b_ = x[: n - lag], x[lag:]
        r = float(np.dot(a_, b_) / (len(a_) * a_.std() * b_.std() + 1e-9))
        if r > best_ac:
            best_ac, ac_lag = r, lag / fps
    k = int(min(8.0, 0.4 * n / fps) * fps)
    best_m, m_at = -1.0, 0.0
    for m in range(k, n - k + 1, 5):
        r = float(np.corrcoef(x[m - k: m], x[m: m + k][::-1])[0, 1])
        if r > best_m:
            best_m, m_at = r, m / fps
    passed = best_m <= max_mirror and best_ac <= max_autocorr
    return {"status": "run", "passed": passed, "mirror_peak": round(best_m, 3), "mirror_at_s": round(m_at, 1), "mirror_threshold": max_mirror,
            "autocorr_peak": round(best_ac, 3), "autocorr_lag_s": round(ac_lag, 1), "autocorr_threshold": max_autocorr, "window_s": round(k / fps, 1)}


def count_blinks(lid, fps: float = 25.0, thr: float = 0.7) -> int:
    x = np.asarray(lid, dtype=float)
    ok = np.isfinite(x)
    if ok.sum() < 3:
        return 0
    x = np.where(ok, x, np.nanmedian(x))
    below = x < thr * np.percentile(x, 60)
    events, i, n = 0, 0, len(x)
    while i < n:
        if below[i]:
            j = i
            while j < n and below[j]:
                j += 1
            if 1 <= j - i <= max(2, int(0.4 * fps)):
                events += 1
            i = j
        else:
            i += 1
    return events


def check_blink_rate(lid, fps: float = 25.0, limits: tuple[float, float] = BLINKS_PER_MIN) -> dict[str, Any]:
    """A natural presenter blinks every few seconds: eyelid-opening dips of 1-10 frames, counted per minute."""
    if lid is None:
        return {"status": "not_run", "passed": None, "reason": "no face-signal provider available (install mediapipe)"}
    n = len(lid)
    if n < int(10 * fps):
        return {"status": "not_run", "passed": None, "reason": "fewer than 10 seconds of eyelid data"}
    ev = count_blinks(lid, fps)
    rate = ev * 60.0 * fps / n
    return {"status": "run", "passed": limits[0] <= rate <= limits[1], "blinks": ev, "per_minute": round(rate, 1), "limits_per_minute": list(limits), "seconds": round(n / fps, 1)}


def default_face_signals() -> Callable[[Path], dict[str, np.ndarray]] | None:
    from lib import face_tools

    return face_tools.face_signals_from_video if face_tools.mediapipe_available()[0] else None


def default_face_width_series() -> Callable[[Path], np.ndarray] | None:
    from lib import face_tools

    return face_tools.face_width_series_from_video if face_tools.mediapipe_available()[0] else None


def default_detector() -> Callable[[Image.Image], bool] | None:
    """MediaPipe face detector when installed and its small model files are present, else None (-> not_run)."""
    from lib import face_tools

    return face_tools.has_face if face_tools.mediapipe_available()[0] else None


def default_mouth_series() -> Callable[[Path], np.ndarray] | None:
    from lib import face_tools

    return face_tools.mouth_series_from_video if face_tools.mediapipe_available()[0] else None


def presenter_qa_report(asset: dict[str, Any], clip: Path, audio: Path, fps: float, raw_videos: Sequence[Path],
                        detector: Callable | None = None, mouth_series: Callable | None = None, use_defaults: bool = True,
                        width_series: Callable | None = None, signals: Callable | None = None) -> dict[str, Any]:
    from lib.presenter_guard import presenter_asset_problems

    if use_defaults:  # real MediaPipe checks unless the caller injected its own (tests) or opted out
        detector = detector or default_detector()
        mouth_series = mouth_series or default_mouth_series()
        signals = signals or (default_face_signals() if width_series is None else None)

    sig = signals(clip) if signals is not None else None
    if sig is not None and width_series is None:
        width_series = lambda _v, _w=sig["width"]: _w  # noqa: E731  (one MediaPipe pass serves all three checks)
    problems = presenter_asset_problems(asset)
    checks = {
        "identity": {"status": "run", "passed": not problems, "problems": problems,
                     **({"standin": True} if asset.get("standin") else {})},
        "face_presence": check_face_presence(clip, detector),
        "mouth_sync": check_mouth_sync(clip, audio, fps, mouth_series),
        "face_scale": check_face_scale(clip, width_series, fps=fps if sig is not None else 5.0),
        "brow_repetition": check_brow_repetition(sig["brow"] if sig else None, fps),
        "blink_rate": check_blink_rate(sig["lid"] if sig else None, fps),
        "no_raw_frames": check_no_raw_frames(clip, raw_videos),
    }
    failed = [k for k, v in checks.items() if v["passed"] is False]
    not_run = [k for k, v in checks.items() if v["passed"] is None]
    return {"checks": checks, "failed": failed, "not_run": not_run,
            "passed": not failed and not not_run,  # "not run" never counts as a pass
            "verdict": "fail" if failed else ("incomplete" if not_run else "pass")}


def landmark_signature(img: Image.Image) -> np.ndarray | None:
    """Scale/translation-normalised face-mesh geometry (x, y of every landmark), or None when no face is found."""
    from lib import face_tools

    lm = face_tools.face_landmarks(img)
    if lm is None:
        return None
    pts = np.asarray(lm, dtype=np.float32)[:, :2]
    pts = pts - pts.mean(axis=0)
    return pts / max(float(np.sqrt((pts ** 2).sum(axis=1).mean())), 1e-6)


def landmark_distance(a: Image.Image, b: Image.Image) -> float | None:
    """Mean per-landmark distance between two faces (0 = same geometry). Used only to keep the *locked twin*
    consistent across hairstyles/outfits (canonical vs its own variants) — never against the owner's raw footage."""
    sa, sb = landmark_signature(a), landmark_signature(b)
    if sa is None or sb is None:
        return None
    return float(np.linalg.norm(sa - sb, axis=1).mean())


MAX_VARIANT_LANDMARK_DISTANCE = 0.015  # measured: hairstyle edits of one portrait 0.005-0.012; other candidates 0.017-0.040


def check_variant_consistency(canonical: Image.Image, variant: Image.Image, max_distance: float = MAX_VARIANT_LANDMARK_DISTANCE) -> dict[str, Any]:
    dist = landmark_distance(canonical, variant)
    if dist is None:
        return {"status": "not_run", "passed": None, "reason": "no face found in one of the images"}
    return {"status": "run", "passed": dist <= max_distance, "landmark_distance": round(dist, 4), "threshold": max_distance}
