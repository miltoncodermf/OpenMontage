"""Face detection, landmarks and mouth-openness with MediaPipe Tasks (Apache-2.0; no InsightFace).

Used by presenter QA (face presence, mouth sync), the lip-sync crop/paste-back and identity-still picking.
Model files (BlazeFace detector, Face Landmarker) are small (< 4 MB) and live in the model store under
``mediapipe/``; ``ensure_models`` downloads them once from Google's public model bucket.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from lib.model_store import model_path

_URLS = {
    "blaze_face_short_range.tflite": "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite",
    "face_landmarker.task": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
}
# Face-mesh indices: inner lips 13 (upper) / 14 (lower); mouth corners 61 / 291; forehead 10, chin 152.
UPPER_LIP, LOWER_LIP, MOUTH_L, MOUTH_R, FOREHEAD, CHIN = 13, 14, 61, 291, 10, 152


def mediapipe_available() -> tuple[bool, str]:
    try:
        from mediapipe.tasks.python import vision  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"mediapipe tasks API not importable: {exc}"
    missing = [n for n in _URLS if not model_path("mediapipe", n).is_file()]
    return (False, f"model files missing in {model_path('mediapipe')}: {missing} (call ensure_models)") if missing else (True, "ok")


def ensure_models() -> Path:
    d = model_path("mediapipe")
    d.mkdir(parents=True, exist_ok=True)
    for name, url in _URLS.items():
        if not (d / name).is_file():
            urllib.request.urlretrieve(url, d / name)  # noqa: S310 — fixed https URLs
    return d


_detector = None
_landmarker = None


def _mp_image(img: Image.Image):
    import mediapipe as mp

    return mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(np.asarray(img.convert("RGB"))))


def detector():
    global _detector
    if _detector is None:
        from mediapipe.tasks.python import BaseOptions, vision

        _detector = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=str(model_path("mediapipe", "blaze_face_short_range.tflite"))),
            min_detection_confidence=0.5))
    return _detector


def landmarker():
    global _landmarker
    if _landmarker is None:
        from mediapipe.tasks.python import BaseOptions, vision

        _landmarker = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path("mediapipe", "face_landmarker.task"))),
            num_faces=1, min_face_detection_confidence=0.4, min_face_presence_confidence=0.4, min_tracking_confidence=0.4))
    return _landmarker


def detect_faces(img: Image.Image) -> list[dict[str, Any]]:
    """[{bbox:(x,y,w,h) px, score}] best first."""
    res = detector().detect(_mp_image(img))
    out = []
    for d in res.detections:
        b = d.bounding_box
        out.append({"bbox": (b.origin_x, b.origin_y, b.width, b.height), "score": float(d.categories[0].score)})
    return sorted(out, key=lambda f: -f["score"])


def has_face(img: Image.Image) -> bool:
    return bool(detect_faces(img))


def face_landmarks(img: Image.Image) -> np.ndarray | None:
    """(478, 3) normalized landmarks of the first face, or None."""
    res = landmarker().detect(_mp_image(img))
    if not res.face_landmarks:
        return None
    return np.array([[p.x, p.y, p.z] for p in res.face_landmarks[0]], dtype=np.float32)


def mouth_openness(lm: np.ndarray) -> float:
    """Inner-lip gap relative to face height (0 = closed)."""
    face_h = abs(lm[CHIN][1] - lm[FOREHEAD][1]) + 1e-6
    return float(abs(lm[LOWER_LIP][1] - lm[UPPER_LIP][1]) / face_h)


def mouth_series_from_video(video: Path, fps: float = 25.0) -> np.ndarray:
    """Per-frame mouth openness (NaN-free: frames without a face repeat the previous value)."""
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf", f"fps={fps}", str(Path(td) / "f_%05d.png")], check=True, timeout=900)
        vals, prev = [], 0.0
        for f in sorted(Path(td).glob("f_*.png")):
            lm = face_landmarks(Image.open(f))
            prev = mouth_openness(lm) if lm is not None else prev
            vals.append(prev)
    return np.array(vals, dtype=np.float32)
