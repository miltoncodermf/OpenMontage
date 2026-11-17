"""LivePortrait performance transfer (path i) via an isolated worker process — fix round 1, B5."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from lib import face_tools
from lib.model_store import model_path

WORKER = Path(__file__).resolve().parent / "_liveportrait_worker.py"
REQUIRED = ["base_models/appearance_feature_extractor.pth", "base_models/motion_extractor.pth", "base_models/spade_generator.pth",
            "base_models/warping_module.pth", "retargeting_models/stitching_retargeting_module.pth", "landmark.onnx"]


def lp_dir() -> Path:
    env = os.environ.get("LIVEPORTRAIT_DIR")
    return Path(env).expanduser() if env else model_path("liveportrait", "src")


def available() -> tuple[bool, str]:
    d = lp_dir()
    if not (d / "src" / "live_portrait_pipeline.py").is_file():
        return False, f"LivePortrait code not found in {d} (git clone https://github.com/KwaiVGI/LivePortrait, MIT)"
    wdir = d / "pretrained_weights" / "liveportrait"
    missing = [f for f in REQUIRED if not (wdir / f).is_file()]
    if missing:
        return False, f"LivePortrait weights missing in {wdir}: {missing} (HF KwaiVGI/LivePortrait liveportrait/*, ~0.7 GB; never the insightface folder)"
    ok, why = face_tools.mediapipe_available()
    return (True, "ok") if ok else (False, why)


def animate(source_image: Path, driving_video: Path, out_dir: Path, *, half: bool = False, lock_eyes: bool = False, expression_gain: float = 1.0, timeout_s: int = 3600) -> dict[str, Any]:
    """Animate ``source_image`` with the motion of ``driving_video``. Returns {output, concat, seconds}."""
    ok, why = available()
    if not ok:
        raise RuntimeError(why)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    cmd = [sys.executable, str(WORKER), "--lp-dir", str(lp_dir()), "--source", str(source_image), "--driving", str(driving_video),
           "--output-dir", str(out_dir)] + (["--half"] if half else []) + (["--lock-eyes"] if lock_eyes else []) + (["--expression-gain", str(expression_gain)] if expression_gain != 1.0 else [])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, cwd=str(lp_dir()))
    if proc.returncode != 0:
        raise RuntimeError(f"LivePortrait worker failed (exit {proc.returncode}):\n{(proc.stderr or proc.stdout)[-1500:]}")
    outs = sorted(p for p in out_dir.glob("*.mp4") if not p.stem.endswith("_concat"))
    if not outs:
        raise RuntimeError("LivePortrait produced no output video")
    newest = max(outs, key=lambda p: p.stat().st_mtime)
    return {"output": str(newest), "seconds": round(time.time() - t0, 1)}
