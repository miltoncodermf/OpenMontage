"""ffprobe/ffmpeg validation of the owner's onboarding recordings (spec §5.5 step 1).

face_turn   : ~30 s, >= 1080p, good even light, plain background
performance : ~60 s natural talking, head-and-shoulders, >= 1080p
voice_read  : ~3 min, quiet room, >= 44.1 kHz (48 kHz recommended), low noise floor, no clipping
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

REQUIREMENTS = {
    "face_turn": {"video": True, "min_duration": 20.0, "max_duration": 90.0},
    "performance": {"video": True, "min_duration": 45.0, "max_duration": 180.0},
    "voice_read": {"video": False, "min_duration": 150.0, "max_duration": 420.0},
}
MIN_SHORT_SIDE = 1080
MIN_FPS = 24.0
MIN_SAMPLE_RATE = 44100
MAX_NOISE_FLOOR_DBFS = -45.0
MAX_PEAK_DBFS = -1.0


def _probe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout
    return json.loads(out)


def _decode_mono(path: Path, rate: int = 16000) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"],
        capture_output=True, timeout=300, check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32)


def audio_levels(samples: np.ndarray, rate: int = 16000) -> dict[str, float]:
    """Noise floor = 10th-percentile RMS (dBFS) over 50 ms windows; peak = max |x| (dBFS)."""
    if samples.size == 0:
        return {"noise_floor_dbfs": 0.0, "peak_dbfs": 0.0, "speech_rms_dbfs": 0.0}
    win = int(rate * 0.05)
    n = samples.size // win
    frames = samples[: n * win].reshape(n, win)
    rms = np.sqrt((frames ** 2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(rms)
    peak = 20 * math.log10(max(float(np.abs(samples).max()), 1e-9))
    return {
        "noise_floor_dbfs": round(float(np.percentile(db, 10)), 1),
        "speech_rms_dbfs": round(float(np.percentile(db, 90)), 1),
        "peak_dbfs": round(peak, 1),
    }


def validate_recording(kind: str, path: Path) -> dict[str, Any]:
    """Return {ok, problems[], probe{}}. Never raises for bad media (reports it)."""
    if kind not in REQUIREMENTS:
        raise ValueError(f"unknown recording kind {kind!r}; expected {sorted(REQUIREMENTS)}")
    req = REQUIREMENTS[kind]
    path = Path(path)
    problems: list[str] = []
    probe_summary: dict[str, Any] = {}
    if not path.is_file():
        return {"ok": False, "problems": [f"file not found: {path}"], "probe": {}}
    try:
        info = _probe(path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "problems": [f"ffprobe failed: {exc}"], "probe": {}}
    duration = float(info["format"].get("duration", 0))
    probe_summary["duration_seconds"] = round(duration, 2)
    if duration < req["min_duration"]:
        problems.append(f"too short: {duration:.0f}s (< {req['min_duration']:.0f}s)")
    if duration > req["max_duration"]:
        problems.append(f"too long: {duration:.0f}s (> {req['max_duration']:.0f}s)")
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if req["video"]:
        if not v:
            problems.append("no video stream")
        else:
            w, h = int(v["width"]), int(v["height"])
            num, _, den = v.get("avg_frame_rate", "0/1").partition("/")
            fps = int(num) / max(int(den or 1), 1) if num else 0.0
            probe_summary.update(width=w, height=h, fps=round(fps, 2))
            if min(w, h) < MIN_SHORT_SIDE:
                problems.append(f"resolution {w}x{h} is below 1080p")
            if fps and fps < MIN_FPS:
                problems.append(f"frame rate {fps:.1f} fps is below {MIN_FPS:.0f}")
        if kind == "performance" and not a:
            problems.append("performance recording has no audio (needed to check talking)")
    if a:
        rate = int(a.get("sample_rate", 0))
        probe_summary["sample_rate"] = rate
        if not req["video"] and rate < MIN_SAMPLE_RATE:
            problems.append(f"sample rate {rate} Hz is below {MIN_SAMPLE_RATE} Hz (record at 48 kHz)")
        try:
            levels = audio_levels(_decode_mono(path))
            probe_summary.update(levels)
            if levels["noise_floor_dbfs"] > MAX_NOISE_FLOOR_DBFS:
                problems.append(f"noise floor {levels['noise_floor_dbfs']} dBFS is too high (> {MAX_NOISE_FLOOR_DBFS}); use a quieter room")
            if levels["peak_dbfs"] > MAX_PEAK_DBFS:
                problems.append(f"audio peaks at {levels['peak_dbfs']} dBFS (clipping); lower the input gain")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"audio analysis failed: {exc}")
    elif not req["video"]:
        problems.append("no audio stream")
    return {"ok": not problems, "problems": problems, "probe": probe_summary}
