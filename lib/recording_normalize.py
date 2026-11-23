"""Working copies of the owner's phone recordings: HDR -> SDR and baked-in rotation.

An iPhone records HEVC HLG (``arib-std-b67`` / bt2020, often Dolby Vision profile 8.4) and stores
the upright orientation as a *display matrix* side-data flag instead of rotating the pixels.
ffmpeg honours that flag, but OpenCV, MediaPipe and the MLX tools read the raw pixels: they see
upside-down (or sideways) frames and wash-out/over-bright HDR. So every consumer works from an SDR
bt709 8-bit H.264 *working copy* whose pixels are already upright; the raw file stays byte-identical.

Working copies are still the owner's raw footage: they live under ``raw/working/`` of the private
profile and are covered by the same raw guard (never rendered, never copied out).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

HLG = "arib-std-b67"
PQ = "smpte2084"
WORKING_DIRNAME = "working"


def _ffprobe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout
    return json.loads(out)


def video_info(path: Path) -> dict[str, Any]:
    """Color + orientation facts for the first video stream."""
    info = _ffprobe(Path(path))
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if v is None:
        raise ValueError(f"{path} has no video stream")
    rotation = 0
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            rotation = int(round(float(sd["rotation"])))
    for k in ("rotate",):  # legacy tag
        if (v.get("tags") or {}).get(k):
            rotation = int(float(v["tags"][k]))
    pix_fmt = v.get("pix_fmt") or ""
    trc = v.get("color_transfer") or ""
    num, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
    fps = int(num) / max(int(den or 1), 1) if num and num != "0" else 0.0
    return {
        "width": int(v["width"]), "height": int(v["height"]), "codec": v.get("codec_name"),
        "pix_fmt": pix_fmt, "bit_depth": 10 if "10" in pix_fmt else 12 if "12" in pix_fmt else 8,
        "color_transfer": trc, "color_primaries": v.get("color_primaries") or "",
        "color_space": v.get("color_space") or "", "rotation": rotation % 360,
        "hdr": trc in (HLG, PQ), "fps": round(fps, 3),
        "has_audio": any(s["codec_type"] == "audio" for s in info["streams"]),
        "duration_seconds": round(float(info["format"].get("duration", 0)), 3),
    }


TAG_BT709 = ",setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv"


def tonemap_filter(info: dict[str, Any]) -> str:
    """ffmpeg -vf chain that yields bt709 limited-range 8-bit yuv420p from the described source."""
    return _tonemap_core(info) + TAG_BT709


def _tonemap_core(info: dict[str, Any]) -> str:
    trc, prim = info.get("color_transfer"), info.get("color_primaries")
    if trc in (HLG, PQ):
        matrix = info.get("color_space") or "bt2020nc"
        return (f"zscale=tin={trc}:pin={prim or 'bt2020'}:min={matrix}:t=linear:npl=100,format=gbrpf32le,"
                "zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
    if prim == "bt2020":  # wide gamut but SDR transfer
        return "zscale=pin=bt2020:min=bt2020nc:tin=bt709:p=bt709:t=bt709:m=bt709:r=tv,format=yuv420p"
    return "format=yuv420p"


def normalize_video(src: Path, dst: Path, *, crf: int = 14) -> dict[str, Any]:
    """Write ``dst`` = SDR bt709 8-bit H.264, upright pixels, no rotation flag, no metadata (GPS, device).

    ffmpeg's default autorotate bakes the display matrix into the pixels and drops the flag. The source
    is never modified. Returns a report with before/after probes; raises when the result fails verification.
    """
    src, dst = Path(src), Path(dst)
    before = video_info(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    fps = round(before["fps"]) if before["fps"] else 30
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?",
           "-vf", tonemap_filter(before), "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
           "-color_range", "tv", "-fps_mode", "cfr", "-r", str(fps),
           "-c:a", "aac", "-b:a", "192k", "-map_metadata", "-1", "-map_chapters", "-1",
           "-movflags", "+faststart", str(dst)]
    subprocess.run(cmd, check=True, timeout=1800)
    after = video_info(dst)
    problems = verify_normalized(after, before)
    if problems:
        raise ValueError("working copy failed verification: " + "; ".join(problems))
    return {"source": src.name, "filter": tonemap_filter(before), "before": before, "after": after,
            "rotation_baked": before["rotation"], "tonemapped": before["hdr"]}


def verify_normalized(after: dict[str, Any], before: dict[str, Any] | None = None) -> list[str]:
    problems = []
    if after["rotation"] != 0:
        problems.append(f"rotation flag still {after['rotation']}")
    for key, label in (("color_transfer", "transfer"), ("color_primaries", "primaries"), ("color_space", "matrix")):
        if after[key] != "bt709":
            problems.append(f"{label} is {after[key]!r}, expected bt709")
    if after["pix_fmt"] != "yuv420p" or after["bit_depth"] != 8:
        problems.append(f"pix_fmt {after['pix_fmt']!r} is not 8-bit yuv420p")
    if after["codec"] != "h264":
        problems.append(f"codec {after['codec']!r} is not h264")
    if before is not None:
        quarter = before["rotation"] in (90, 270)
        want = (before["height"], before["width"]) if quarter else (before["width"], before["height"])
        if (after["width"], after["height"]) != want:
            problems.append(f"size {after['width']}x{after['height']} != expected {want[0]}x{want[1]}")
    return problems


def needs_normalizing(path: Path) -> bool:
    """True when a video would confuse pixel-reading tools (HDR, rotated, or not 8-bit)."""
    i = video_info(path)
    return bool(i["hdr"] or i["rotation"] or i["bit_depth"] != 8 or i["color_primaries"] == "bt2020")
