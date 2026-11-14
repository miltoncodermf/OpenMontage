"""MuseTalk-1.5 (MLX) lip-sync with MediaPipe face handling — fix round 1, B3.

The ``musetalk_mlx`` port owns the neural core (VAE → UNet(t=0) → VAE, whisper encoder). Everything
around it that upstream MuseTalk does with S3FD / DWPose / BiSeNet is replaced here by MediaPipe (Apache-2.0;
no InsightFace, no mmpose, no torch):

  frame → 478-pt face mesh → crop box (upstream rule: symmetric about the nose bridge, down to the chin,
  + 10 px extra margin) → 256² crop → masked⊕ref latent → UNet with per-frame whisper chunk → 256² face →
  resize to the box → feathered paste-back (mask = face oval below the nose bridge, eroded and Gaussian-blurred)
  → frame at the SOURCE resolution.

Frames are processed at 25 fps (MuseTalk's training rate); the caller loops the motion source to the audio length.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from lib import face_tools
from lib.model_store import model_path

FPS = 25
EXTRA_MARGIN = 10          # upstream v1.5 `extra_margin`
NOSE_BRIDGE = 195          # mesh point ≈ iBUG-68 point 29 (lower nose bridge) used by upstream for the crop centre
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149,
             150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
CHIN, LEFT_EDGE, RIGHT_EDGE = 152, 234, 454


def weights_dir() -> Path:
    env = os.environ.get("MUSETALK_MLX_DIR")
    return Path(env).expanduser() if env else model_path("musetalk", "MuseTalk-1.5-fp16")


def available() -> tuple[bool, str]:
    try:
        import musetalk_mlx  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"python package `musetalk_mlx` not importable: {exc} (pip install --no-deps git+https://github.com/xocialize/musetalk-mlx)"
    d = weights_dir()
    missing = [f for f in ("config.json", "unet.safetensors", "vae.safetensors", "whisper_encoder.safetensors") if not (d / f).is_file()]
    if missing:
        return False, f"MuseTalk-MLX weights incomplete in {d}: missing {missing} (mlx-community/MuseTalk-1.5-fp16, ≈1.9 GB)"
    ok, why = face_tools.mediapipe_available()
    return (True, "ok") if ok else (False, why)


def crop_box(lm: np.ndarray, w: int, h: int, extra_margin: int = EXTRA_MARGIN) -> tuple[int, int, int, int]:
    """Upstream MuseTalk crop rule on MediaPipe landmarks (pixel box x1, y1, x2, y2)."""
    pts = lm[:, :2] * np.array([w, h], dtype=np.float32)
    bridge_y = pts[NOSE_BRIDGE, 1]
    max_y = pts[CHIN, 1]
    dist = max_y - bridge_y
    x1, x2 = pts[LEFT_EDGE, 0], pts[RIGHT_EDGE, 0]
    y1 = bridge_y - dist
    y2 = max_y + extra_margin
    x1, y1 = max(0, int(round(x1))), max(0, int(round(y1)))
    x2, y2 = min(w, int(round(x2))), min(h, int(round(y2)))
    return x1, y1, x2, y2


def smooth_boxes(boxes: list[tuple[int, int, int, int] | None], k: int = 5) -> list[tuple[int, int, int, int]]:
    """Fill gaps (previous box, else first valid) and temporally smooth with a centred moving average."""
    first = next((b for b in boxes if b is not None), None)
    if first is None:
        raise RuntimeError("no face detected in any frame of the motion source")
    filled, prev = [], first
    for b in boxes:
        prev = b if b is not None else prev
        filled.append(prev)
    arr = np.array(filled, dtype=np.float32)
    pad = k // 2
    padded = np.pad(arr, ((pad, pad), (0, 0)), mode="edge")
    sm = np.stack([padded[i:i + len(arr)] for i in range(k)]).mean(axis=0)
    return [tuple(int(round(v)) for v in row) for row in sm]


def blend_mask(shape: tuple[int, int], lm: np.ndarray, box: tuple[int, int, int, int], feather: int = 0) -> np.ndarray:
    """Float mask (0..1, HxW): face oval below the crop's mid-line (the region MuseTalk regenerates), feathered."""
    import cv2

    h, w = shape
    x1, y1, x2, y2 = box
    pts = (lm[FACE_OVAL, :2] * np.array([w, h], dtype=np.float32)).astype(np.int32)
    mask = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(pts), 255)
    mid = y1 + (y2 - y1) // 2
    mask[:mid, :] = 0
    mask[:, :x1] = 0
    mask[:, x2:] = 0
    k = max(3, int((x2 - x1) * 0.04)) | 1
    mask = cv2.erode(mask, np.ones((k, k), np.uint8))
    sigma = feather or max(3.0, (x2 - x1) * 0.035)
    mask = cv2.GaussianBlur(mask, (0, 0), sigma)
    return mask.astype(np.float32) / 255.0


def paste_back(frame_bgr: np.ndarray, face_bgr256: np.ndarray, box: tuple[int, int, int, int], mask: np.ndarray) -> np.ndarray:
    import cv2

    x1, y1, x2, y2 = box
    resized = cv2.resize(face_bgr256, (x2 - x1, y2 - y1), interpolation=cv2.INTER_LANCZOS4)
    canvas = frame_bgr.copy()
    canvas[y1:y2, x1:x2] = resized
    m = mask[..., None]
    return (canvas.astype(np.float32) * m + frame_bgr.astype(np.float32) * (1.0 - m)).round().astype(np.uint8)


_pipe_cache: dict[str, Any] = {}


def _pipeline():
    from musetalk_mlx.pipeline_mlx import MuseTalkPipeline

    key = str(weights_dir())
    if key not in _pipe_cache:
        _pipe_cache[key] = MuseTalkPipeline.from_pretrained_mlx(weights_dir())
    return _pipe_cache[key]


def lipsync(motion_video: Path, audio: Path, out: Path, fps: int = FPS, batch_size: int = 8) -> dict[str, Any]:
    """Lip-sync ``motion_video`` (already looped to the audio length) to ``audio`` → ``out`` (mp4 with audio)."""
    import cv2
    import mlx.core as mx

    ok, why = available()
    if not ok:
        raise RuntimeError(why)
    t0 = time.time()
    pipe = _pipeline()
    with tempfile.TemporaryDirectory() as td:
        fdir, odir = Path(td) / "in", Path(td) / "out"
        fdir.mkdir()
        odir.mkdir()
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(motion_video), "-an", "-r", str(fps), str(fdir / "f_%06d.png")], check=True, timeout=1800)
        paths = sorted(fdir.glob("f_*.png"))
        frames = [cv2.imread(str(p)) for p in paths]
        h, w = frames[0].shape[:2]
        lms = [face_tools.face_landmarks(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))) for f in frames]
        boxes = smooth_boxes([crop_box(lm, w, h) if lm is not None else None for lm in lms])
        det_ratio = sum(lm is not None for lm in lms) / len(lms)

        chunks = pipe.encode_audio_from_wav(str(audio), fps=fps)
        n = int(chunks.shape[0])
        latents, crops = [], []
        for f, b in zip(frames, boxes):
            x1, y1, x2, y2 = b
            crop = cv2.resize(f[y1:y2, x1:x2], (256, 256), interpolation=cv2.INTER_LANCZOS4)
            crops.append(crop)
            latents.append(pipe.get_latents_for_unet(crop))

        def cyc(lst, i):  # ping-pong cycle if the motion source is shorter than the audio
            c = lst + lst[::-1]
            return c[i % len(c)]

        lat = mx.concatenate([cyc(latents, i) for i in range(n)], axis=0)
        faces = pipe.run_batched(lat, chunks, batch_size=batch_size)
        last_lm = next(lm for lm in lms if lm is not None)
        for i in range(n):
            j = i % (2 * len(frames))
            j = j if j < len(frames) else 2 * len(frames) - 1 - j
            lm = lms[j] if lms[j] is not None else last_lm
            frame = frames[j]
            res = paste_back(frame, faces[i], boxes[j], blend_mask((h, w), lm, boxes[j]))
            cv2.imwrite(str(odir / f"o_{i:06d}.png"), res)
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(fps), "-i", str(odir / "o_%06d.png"), "-i", str(audio),
                        "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)],
                       check=True, timeout=1800)
    return {"frames": n, "fps": fps, "size": [w, h], "face_detected_ratio": round(det_ratio, 4), "seconds": round(time.time() - t0, 1)}
