"""EBU R128 loudness measurement and two-pass mastering (spec D19: -14 LUFS ±1, TP ≤ -1 dBTP)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

TARGET_LUFS = -14.0
LUFS_TOLERANCE = 1.0
TP_LIMIT = -1.0        # delivered true peak must be <= this
TP_TARGET = -1.5       # mastering target leaves headroom under the limit
LRA_TARGET = 11.0


def _loudnorm_json(stderr: str) -> dict[str, Any]:
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.S)
    if not m:
        raise RuntimeError("loudnorm produced no measurement (does the file have an audio stream?)")
    return json.loads(m.group(0))


def measure(path: Path) -> dict[str, float]:
    """Integrated loudness (LUFS), true peak (dBTP), loudness range (LU) of the file's audio."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
         f"loudnorm=I={TARGET_LUFS}:TP={TP_TARGET}:LRA={LRA_TARGET}:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, timeout=1200)
    j = _loudnorm_json(proc.stderr)
    return {"integrated_lufs": float(j["input_i"]), "true_peak_dbtp": float(j["input_tp"]), "lra": float(j["input_lra"]),
            "threshold": float(j["input_thresh"])}


def within_target(m: dict[str, float], target: float = TARGET_LUFS) -> bool:
    return abs(m["integrated_lufs"] - target) <= LUFS_TOLERANCE and m["true_peak_dbtp"] <= TP_LIMIT


def master_two_pass(src: Path, dst: Path, target: float = TARGET_LUFS, video_copy: bool = True) -> dict[str, Any]:
    """Two-pass loudnorm: pass 1 measures, pass 2 applies linear gain with the measured values."""
    first = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-vn", "-af",
         f"loudnorm=I={target}:TP={TP_TARGET}:LRA={LRA_TARGET}:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, timeout=1200)
    j = _loudnorm_json(first.stderr)
    af = (f"loudnorm=I={target}:TP={TP_TARGET}:LRA={LRA_TARGET}:measured_I={j['input_i']}:measured_TP={j['input_tp']}:"
          f"measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true")
    dst.parent.mkdir(parents=True, exist_ok=True)
    has_video = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=index", "-of", "csv=p=0", str(src)],
                               capture_output=True, text=True).stdout.strip() != ""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
    if has_video and video_copy:
        cmd += ["-c:v", "copy"]
    cmd += ["-af", af, "-ar", "48000", "-c:a", "aac", "-b:a", "256k", str(dst)] if dst.suffix in {".mp4", ".mov", ".m4a"} else ["-af", af, "-ar", "48000", str(dst)]
    subprocess.run(cmd, check=True, timeout=1800)
    after = measure(dst)
    return {"before": {"integrated_lufs": float(j["input_i"]), "true_peak_dbtp": float(j["input_tp"])}, "after": after,
            "within_target": within_target(after, target), "output": str(dst)}
