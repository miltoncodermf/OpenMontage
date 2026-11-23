#!/usr/bin/env python
"""LivePortrait-side mouth lab: animate a short driving clip with different lip/cheek settings and base portraits, then lip-sync each with MuseTalk
and measure the mouth (analysis only). usage: mouth_lp_lab.py <driving.mp4> <narration.wav> <out_dir> <seconds> name=json ...
json keys: source (path relative to the profile), lip_gain, gain, mouth (musetalk options dict)"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def main() -> None:
    driving, narration, out_dir, seconds = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), float(sys.argv[4])
    variants = {a.split("=", 1)[0]: json.loads(a.split("=", 1)[1]) for a in sys.argv[5:]}
    out_dir.mkdir(parents=True, exist_ok=True)
    from lib import liveportrait_runner as lr, mouth_metrics as mm, musetalk_runner as mr, presenter_profile as pp
    from lib.heavy_lock import heavy_job

    home = pp.profile_dir("ming")
    audio = out_dir / "audio.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-t", str(seconds), "-i", str(narration), "-ar", "16000", "-ac", "1", str(audio)], check=True)
    report = json.loads((out_dir / "report.json").read_text()) if (out_dir / "report.json").exists() else {}
    blink = home / "derived" / "blink_templates.json"
    for name, v in variants.items():
        t0 = time.time()
        args = ["--blink-model", str(blink), "--pose-smooth", "0.35", "--pose-damp", "0.6", "--max-rot-deg", "5", "--max-trans-sigma", "1.5", "--exp-smooth", "0.25",
                "--hold-frames", "3", "--lip-gain", str(v.get("lip_gain", 1.0))]
        with heavy_job("mouth_lp_lab", wait=3600):
            res = lr.animate(home / v["source"], driving, out_dir / f"lp_{name}", lock_eyes=True, lock_scale=True, expression_gain=v.get("gain", 0.6), extra_args=args)
        lp = out_dir / f"{name}_lp.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "0.12", "-i", res["output"], "-an", "-r", "25", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(lp)], check=True)
        out = out_dir / f"{name}.mp4"
        with heavy_job("mouth_lp_lab", wait=3600):
            mr.lipsync(lp, audio, out, options=v.get("mouth", {}))
        sig = mm.video_metrics(out, 25.0)
        report[name] = {"variant": v, "seconds": round(time.time() - t0, 1), **mm.summarize(sig)}
        (out_dir / "report.json").write_text(json.dumps(report, indent=1))
        print(name, json.dumps(report[name]), flush=True)


if __name__ == "__main__":
    main()
