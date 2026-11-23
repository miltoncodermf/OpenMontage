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


def mouth_mask(shape: tuple[int, int], lm: np.ndarray, box: tuple[int, int, int, int], reach: float = 0.30, feather: float = 0.045) -> np.ndarray:
    """Float mask limited to the lips and chin (an ellipse around the mouth and jaw tip), feathered, nothing above the nose base or on the cheeks.

    The default mask is the whole lower face oval, so MuseTalk's slightly different skin tone/texture/shading shows up as a seam and a diagonal dip
    along the cheek from each mouth corner. This one only lets the generated pixels replace the mouth and the chin that moves with it."""
    import cv2

    h, w = shape
    pts = lm[:, :2] * np.array([w, h], dtype=np.float32)
    fw = float(np.linalg.norm(pts[234] - pts[454]))
    cx = float(pts[[61, 291], 0].mean())
    top = float(pts[[61, 291], 1].mean())
    chin = float(pts[CHIN, 1])
    cy = (top + chin) / 2
    mask = np.zeros((h, w), np.uint8)
    cv2.ellipse(mask, (int(cx), int(cy)), (int(reach * fw), int(max(8, (chin - top) / 2 + 0.07 * fw))), 0, 0, 360, 255, -1)
    mask[: int(pts[2][1] + 0.02 * fw), :] = 0  # nothing above the nose base
    sigma = max(2.0, feather * fw)
    mask = cv2.GaussianBlur(mask, (0, 0), sigma).astype(np.float32) / 255.0
    # the generated face only exists inside the crop box: fade to zero before its borders so there is no seam along them
    x1, y1, x2, y2 = box
    fade = max(6, int(0.04 * fw))
    win = np.zeros((h, w), np.float32)
    win[y1:y2, x1:x2] = 1.0
    win = cv2.GaussianBlur(cv2.erode(win, np.ones((2 * fade + 1, 2 * fade + 1), np.uint8)), (0, 0), fade / 2.0)
    return mask * win


def color_match(gen_bgr: np.ndarray, src_bgr: np.ndarray, mask: np.ndarray, lm: np.ndarray, strength: float = 1.0) -> np.ndarray:
    """Shift the regenerated skin to the portrait's own skin tone (mean and spread in LAB, measured on skin pixels inside the mask, lips excluded).

    MuseTalk's decoder returns a slightly lighter, greyer skin than the portrait, which shows as a pale patch with a visible edge around the mouth."""
    import cv2

    h, w = gen_bgr.shape[:2]
    pts = lm[:, :2] * np.array([w, h], dtype=np.float32)
    lips = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(lips, cv2.convexHull(pts[[61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146]].astype(np.int32)), 255)
    lips = cv2.dilate(lips, np.ones((int(0.06 * np.linalg.norm(pts[234] - pts[454])) | 1,) * 2, np.uint8))
    skin = (mask > 0.15) & (lips == 0)
    if skin.sum() < 200:
        return gen_bgr
    g = cv2.cvtColor(gen_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    s_ = cv2.cvtColor(src_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    mg, sg = g[skin].mean(axis=0), g[skin].std(axis=0) + 1e-3
    ms, ss = s_[skin].mean(axis=0), s_[skin].std(axis=0) + 1e-3
    gain = np.clip(ss / sg, 0.7, 1.3)  # never invent or flatten texture by much
    out = (g - mg) * (1.0 + strength * (gain - 1.0)) + mg + strength * (ms - mg)
    return cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def lips_chin_mask(shape: tuple[int, int], lm: np.ndarray, box: tuple[int, int, int, int], dilate: float = 0.05, chin_half: float = 0.22,
                   feather: float = 0.03) -> np.ndarray:
    """Tightest useful mask: the lips (outer lip outline grown by ``dilate`` x face width) plus an ellipse on the chin/lower lip area that moves with
    the jaw. Everything beside the mouth corners (nasolabial fold, cheeks) stays the stable, warped-portrait pixels, so the crease cannot pulse
    with the generated mouth. Fades to zero before the crop-box border."""
    import cv2

    h, w = shape
    pts = lm[:, :2] * np.array([w, h], dtype=np.float32)
    fw = float(np.linalg.norm(pts[234] - pts[454]))
    outer = pts[[61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146]].astype(np.int32)
    mask = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(outer), 255)
    k = max(3, int(2 * dilate * fw)) | 1
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    cx, lip_bottom, chin = float(pts[[61, 291], 0].mean()), float(pts[17, 1]), float(pts[CHIN, 1])
    cy = (lip_bottom + chin) / 2
    cv2.ellipse(mask, (int(cx), int(cy)), (int(chin_half * fw), int(max(6, (chin - lip_bottom) / 2 + 0.03 * fw))), 0, 0, 360, 255, -1)
    mask[: int(pts[2][1] + 0.02 * fw), :] = 0
    mask = cv2.GaussianBlur(mask, (0, 0), max(2.0, feather * fw)).astype(np.float32) / 255.0
    x1, y1, x2, y2 = box
    fade = max(6, int(0.04 * fw))
    win = np.zeros((h, w), np.float32)
    win[y1:y2, x1:x2] = 1.0
    win = cv2.GaussianBlur(cv2.erode(win, np.ones((2 * fade + 1, 2 * fade + 1), np.uint8)), (0, 0), fade / 2.0)
    return mask * win


def sharpen_in_mask(frame_bgr: np.ndarray, mask: np.ndarray, amount: float, sigma: float = 1.6) -> np.ndarray:
    """Unsharp mask applied only where ``mask`` is set (the regenerated mouth is softer than the rest of the face)."""
    import cv2

    if amount <= 0:
        return frame_bgr
    f = frame_bgr.astype(np.float32)
    blur = cv2.GaussianBlur(f, (0, 0), sigma)
    out = f + amount * (f - blur) * mask[..., None]
    return np.clip(out, 0, 255).round().astype(np.uint8)


def texture_restore(res_bgr: np.ndarray, src_bgr: np.ndarray, mask: np.ndarray, lm: np.ndarray, amount: float = 1.0, sigma: float = 1.5) -> np.ndarray:
    """Give the regenerated skin the portrait's own fine texture (stubble, pores).

    MuseTalk decodes a 256 px face, so the pasted skin is smoother than the 1000+ px portrait around it: the stubble shadow above the lip and the
    chin read as a pale, matte patch. Inside the paste mask, on skin-coloured pixels only (so lips, teeth and the mouth opening are never touched), the
    pasted frame's high-frequency band is blended toward the source frame's: ``res += amount * gate * (hp(src) - hp(res))``."""
    import cv2

    if amount <= 0:
        return res_bgr
    h, w = res_bgr.shape[:2]
    pts = lm[:, :2] * np.array([w, h], dtype=np.float32)
    fw = float(np.linalg.norm(pts[234] - pts[454]))
    lab = cv2.cvtColor(res_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    lips = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(lips, cv2.convexHull(pts[[61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146]].astype(np.int32)), 255)
    ref = (mask > 0.15) & (lips == 0)
    if ref.sum() < 200:
        return res_bgr
    # skin statistics come from the cheek-side ring just outside the lips, where nothing but skin lives
    ring = cv2.dilate(lips, np.ones((int(0.12 * fw) | 1,) * 2, np.uint8)) - cv2.dilate(lips, np.ones((int(0.05 * fw) | 1,) * 2, np.uint8))
    sel = (ring > 0) & ref
    sel = sel if sel.sum() >= 200 else ref
    mu, sd = lab[sel].mean(axis=0), lab[sel].std(axis=0) + 2.0
    dist = np.sqrt((((lab - mu) / (2.5 * sd)) ** 2).sum(axis=2))
    gate = cv2.GaussianBlur(np.clip(1.5 - dist, 0.0, 1.0), (0, 0), 1.5)
    f_res, f_src = res_bgr.astype(np.float32), src_bgr.astype(np.float32)
    hp_res = f_res - cv2.GaussianBlur(f_res, (0, 0), sigma)
    hp_src = f_src - cv2.GaussianBlur(f_src, (0, 0), sigma)
    wgt = (amount * gate * mask)[..., None]
    return np.clip(f_res + wgt * (hp_src - hp_res), 0, 255).round().astype(np.uint8)


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


def lipsync(motion_video: Path, audio: Path, out: Path, fps: int = FPS, batch_size: int = 8, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Lip-sync ``motion_video`` (already looped to the audio length) to ``audio`` → ``out`` (mp4 with audio).

    ``options`` (all optional): ``open_scale`` (0.5-1.0: pull the audio features toward silence, i.e. a less wide-open mouth), ``mask`` ("oval" = whole lower
    face, the original; "mouth" = an ellipse around mouth and chin; "lips" = only the lips and the chin, cheeks stay the stable portrait), ``sharpen`` (unsharp amount inside the mouth mask), ``texture`` (0-1: restore the portrait's own stubble/pore detail on skin inside the mask), ``mask_reach`` (ellipse half-width / face width).
    """
    opts = {"open_scale": 1.0, "mask": "oval", "sharpen": 0.0, "mask_reach": 0.30, "color_match": 0.0, "texture": 0.0, "lip_dilate": 0.05, "chin_half": 0.22, **(options or {})}
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
        if opts["open_scale"] < 1.0:  # shrink the mouth movement: audio features -> silence features
            sil = os.path.join(td, "silence.wav")
            import soundfile as sf

            sf.write(sil, np.zeros(16000 * 2, dtype="float32"), 16000)
            sil_chunks = pipe.encode_audio_from_wav(sil, fps=fps)
            sil_mean = mx.mean(sil_chunks, axis=0, keepdims=True)
            chunks = sil_mean + opts["open_scale"] * (chunks - sil_mean)
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
            if opts["mask"] == "lips":
                m = lips_chin_mask((h, w), lm, boxes[j], dilate=opts["lip_dilate"], chin_half=opts["chin_half"])
            elif opts["mask"] == "mouth":
                m = mouth_mask((h, w), lm, boxes[j], reach=opts["mask_reach"])
            else:
                m = blend_mask((h, w), lm, boxes[j])
            if opts["color_match"] > 0 and opts["mask"] in ("mouth", "lips"):
                import cv2 as _cv

                x1, y1, x2, y2 = boxes[j]
                gen_full = frame.copy()
                gen_full[y1:y2, x1:x2] = _cv.resize(faces[i], (x2 - x1, y2 - y1), interpolation=_cv.INTER_LANCZOS4)  # no 256 round trip: keep the detail
                matched = color_match(gen_full, frame, m, lm, opts["color_match"])
                mm_ = m[..., None]
                res = (matched.astype(np.float32) * mm_ + frame.astype(np.float32) * (1.0 - mm_)).round().astype(np.uint8)
            else:
                res = paste_back(frame, faces[i], boxes[j], m)
            if opts["texture"] > 0:
                res = texture_restore(res, frame, m, lm, opts["texture"])
            if opts["sharpen"] > 0:
                res = sharpen_in_mask(res, m, opts["sharpen"])
            cv2.imwrite(str(odir / f"o_{i:06d}.png"), res)
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(fps), "-i", str(odir / "o_%06d.png"), "-i", str(audio),
                        "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)],
                       check=True, timeout=1800)
    return {"options": opts, "frames": n, "fps": fps, "size": [w, h], "face_detected_ratio": round(det_ratio, 4), "seconds": round(time.time() - t0, 1)}
