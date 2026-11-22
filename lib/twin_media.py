"""ffmpeg utilities for the digital twin: probing, loop-seam check, ping-pong looping.

Pure local media plumbing (no models), shared by twin_idle_loop / twin_lipsync.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

SEAM_THRESHOLD = 0.03  # mean abs gray diff (0..1) between first and last frame


def probe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout
    info = json.loads(out)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    res: dict[str, Any] = {"duration_seconds": round(float(info["format"].get("duration", 0)), 3), "has_audio": a is not None}
    if v:
        num, _, den = v.get("avg_frame_rate", "0/1").partition("/")
        res.update(width=int(v["width"]), height=int(v["height"]),
                   fps=round(int(num) / max(int(den or 1), 1), 3) if num else 0.0, codec=v.get("codec_name"),
                   has_alpha=any(k in (v.get("pix_fmt") or "") for k in ("yuva", "rgba", "bgra", "argb")))
    return res


def _gray_frame(path: Path, at: str, size: tuple[int, int] = (160, 90)) -> np.ndarray:
    args = ["ffmpeg", "-v", "error"]
    args += ["-sseof", "-0.1"] if at == "last" else ["-ss", "0"]
    args += ["-i", str(path), "-frames:v", "1", "-vf", f"scale={size[0]}:{size[1]},format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(args, capture_output=True, timeout=60, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(size[1], size[0]).astype(np.float32) / 255.0


def seam_score(path: Path) -> float:
    """Mean abs difference (0..1) between the first and last frame. Small = seamless loop."""
    return float(np.abs(_gray_frame(path, "first") - _gray_frame(path, "last")).mean())


def is_seamless(path: Path, threshold: float = SEAM_THRESHOLD) -> bool:
    return seam_score(path) < threshold


def pingpong_to_duration(src: Path, dst: Path, duration_s: float, fps: int = 30) -> Path:
    """Forward+reverse the clip and repeat it to exactly ``duration_s`` (no jump cut at the seam)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        pp = Path(td) / "pp.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-an", "-filter_complex",
             "[0:v]split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0[v]", "-map", "[v]",
             "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(pp)],
            check=True, timeout=600)
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(pp), "-t", f"{duration_s:.3f}", "-r", str(fps),
             "-an", "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(dst)],
            check=True, timeout=600)
    return dst


def plain_loop_to_duration(src: Path, dst: Path, duration_s: float, fps: int = 30) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(src), "-t", f"{duration_s:.3f}", "-r", str(fps),
         "-an", "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(dst)],
        check=True, timeout=600)
    return dst


def crossfade_to_duration(src: Path, dst: Path, duration_s: float, fps: int = 30, overlap_s: float = 0.7) -> Path:
    """Repeat the clip with a cross-dissolve of ``overlap_s`` at every seam (no ping-pong, so motion never reverses). A clip that is
    already long enough is just trimmed."""
    import math

    dst.parent.mkdir(parents=True, exist_ok=True)
    length = float(probe(src)["duration_seconds"])
    ov = min(overlap_s, length / 3)
    k = 1 if length >= duration_s else int(math.ceil((duration_s - length) / (length - ov))) + 1
    if k == 1:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-t", f"{duration_s:.3f}", "-r", str(fps), "-an", "-c:v", "libx264",
                        "-crf", "14", "-pix_fmt", "yuv420p", str(dst)], check=True, timeout=600)
        return dst
    parts = "".join(f"[v{i}]" for i in range(k))
    chain = [f"[0:v]fps={fps},setpts=PTS-STARTPTS,format=yuv420p,split={k}{parts}"]
    prev = "v0"
    for i in range(1, k):
        out = f"x{i}"
        chain.append(f"[{prev}][v{i}]xfade=transition=fade:duration={ov:.3f}:offset={i * (length - ov):.3f}[{out}]")
        prev = out
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-an", "-filter_complex", ";".join(chain), "-map", f"[{prev}]", "-t", f"{duration_s:.3f}",
                    "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(dst)], check=True, timeout=1200)
    return dst


def loop_to_duration(src: Path, dst: Path, duration_s: float, fps: int = 30, mode: str = "auto") -> dict[str, Any]:
    """Loop a motion source to the narration length. ``auto`` = plain loop if the seam is clean, else ping-pong;
    ``auto_crossfade`` = plain loop if the seam is clean, else cross-dissolve repeats; ``crossfade`` always dissolves."""
    if mode not in {"auto", "loop", "pingpong", "crossfade", "auto_crossfade"}:
        raise ValueError(f"unknown loop mode {mode!r}")
    score = seam_score(src)
    if mode == "crossfade" or (mode == "auto_crossfade" and score >= SEAM_THRESHOLD):
        crossfade_to_duration(src, dst, duration_s, fps)
        return {"mode": "crossfade", "seam_score": round(score, 4), "output": str(dst)}
    chosen = "loop" if mode in ("loop", "auto_crossfade") or (mode == "auto" and score < SEAM_THRESHOLD) else "pingpong"
    (plain_loop_to_duration if chosen == "loop" else pingpong_to_duration)(src, dst, duration_s, fps)
    return {"mode": chosen, "seam_score": round(score, 4), "output": str(dst)}
