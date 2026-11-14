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


def default_detector() -> Callable[[Image.Image], bool] | None:
    """MediaPipe face detector when installed and its small model files are present, else None (-> not_run)."""
    from lib import face_tools

    return face_tools.has_face if face_tools.mediapipe_available()[0] else None


def default_mouth_series() -> Callable[[Path], np.ndarray] | None:
    from lib import face_tools

    return face_tools.mouth_series_from_video if face_tools.mediapipe_available()[0] else None


def presenter_qa_report(asset: dict[str, Any], clip: Path, audio: Path, fps: float, raw_videos: Sequence[Path],
                        detector: Callable | None = None, mouth_series: Callable | None = None, use_defaults: bool = True) -> dict[str, Any]:
    from lib.presenter_guard import presenter_asset_problems

    if use_defaults:  # real MediaPipe checks unless the caller injected its own (tests) or opted out
        detector = detector or default_detector()
        mouth_series = mouth_series or default_mouth_series()

    problems = presenter_asset_problems(asset)
    checks = {
        "identity": {"status": "run", "passed": not problems, "problems": problems,
                     **({"standin": True} if asset.get("standin") else {})},
        "face_presence": check_face_presence(clip, detector),
        "mouth_sync": check_mouth_sync(clip, audio, fps, mouth_series),
        "no_raw_frames": check_no_raw_frames(clip, raw_videos),
    }
    failed = [k for k, v in checks.items() if v["passed"] is False]
    not_run = [k for k, v in checks.items() if v["passed"] is None]
    return {"checks": checks, "failed": failed, "not_run": not_run,
            "passed": not failed and not not_run,  # "not run" never counts as a pass
            "verdict": "fail" if failed else ("incomplete" if not_run else "pass")}
