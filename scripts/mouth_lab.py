#!/usr/bin/env python
"""Mouth lab: lip-sync one excerpt with several MuseTalk settings and measure the mouth (analysis only; outputs stay in the project folder).

usage: mouth_lab.py <motion.mp4> <narration.wav> <out_dir> <start_s> <dur_s> name=json_options ...
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def main() -> None:
    motion, audio, out_dir, start, dur = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
    variants = {a.split("=", 1)[0]: json.loads(a.split("=", 1)[1] or "{}") for a in sys.argv[6:]}
    out_dir.mkdir(parents=True, exist_ok=True)
    m_ex, a_ex = out_dir / "excerpt_motion.mp4", out_dir / "excerpt_audio.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-t", str(dur), "-i", str(motion), "-an", "-r", "25", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(m_ex)], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-t", str(dur), "-i", str(audio), "-ar", "16000", "-ac", "1", str(a_ex)], check=True)
    from lib import mouth_metrics as mm, musetalk_runner as mr
    from lib.heavy_lock import heavy_job

    report = json.loads((out_dir / "report.json").read_text()) if (out_dir / "report.json").exists() else {}
    with heavy_job("mouth_lab", wait=1800):
        for name, opts in variants.items():
            t0 = time.time()
            out = out_dir / f"{name}.mp4"
            mr.lipsync(m_ex, a_ex, out, options=opts)
            sig = mm.video_metrics(out, 25.0)
            report[name] = {"options": opts, "seconds": round(time.time() - t0, 1), **mm.summarize(sig)}
            (out_dir / "report.json").write_text(json.dumps(report, indent=1))
            print(name, json.dumps(report[name]), flush=True)


if __name__ == "__main__":
    main()
