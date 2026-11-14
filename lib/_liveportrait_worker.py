"""LivePortrait worker (run as a subprocess by ``lib/liveportrait_runner.py``; fix round 1, B5).

LivePortrait's code is MIT, but its default face detector/landmarks come from InsightFace whose models are
**non-commercial research only** (see its LICENSE). This worker never loads InsightFace: it injects a MediaPipe-backed
replacement for ``src.utils.face_analysis_diy.FaceAnalysisDIY`` before the pipeline is imported, so no InsightFace
weights are needed or touched. LivePortrait's own 203-point landmark model and appearance/motion/warping/SPADE/stitching
weights (MIT) are used as-is.
"""

from __future__ import annotations

import argparse
import os
import sys
import types
from pathlib import Path

import numpy as np

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def _mediapipe_face_analysis():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from PIL import Image

    from lib import face_tools

    # iBUG-106 indices used by LivePortrait's crop (parse_pt2_from_pt106): eyes 33,35,40,39 / 87,89,94,93, lips 52,61
    LEFT_EYE = [33, 133, 159, 145]     # MediaPipe mesh ring of the image-left eye
    RIGHT_EYE = [362, 263, 386, 374]
    LIPS = [13, 14, 61, 291]
    OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149,
            150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]

    class _Face:
        def __init__(self, lmk106):
            self.landmark_2d_106 = lmk106

    class MediaPipeFaceAnalysis:
        def __init__(self, *a, **k):
            pass

        def prepare(self, *a, **k):
            pass

        def warmup(self):
            pass

        def get(self, img_bgr, **kwargs):
            h, w = img_bgr.shape[:2]
            lm = face_tools.face_landmarks(Image.fromarray(img_bgr[..., ::-1].copy()))
            if lm is None:
                return []
            px = lm[:, :2] * np.array([w, h], dtype=np.float32)
            lmk = np.tile(px[OVAL], (3, 1))[:106].astype(np.float32)  # bbox source; unused rows = face-oval points
            lc, rc = px[LEFT_EYE].mean(0), px[RIGHT_EYE].mean(0)
            for i in (33, 35, 40, 39):
                lmk[i] = lc
            for i in (87, 89, 94, 93):
                lmk[i] = rc
            for i in (52, 61):
                lmk[i] = px[LIPS].mean(0)
            return [_Face(lmk)]

    return MediaPipeFaceAnalysis


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lp-dir", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--driving", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--half", action="store_true")
    ap.add_argument("--no-pasteback", action="store_true")
    a = ap.parse_args()

    sys.path.insert(0, a.lp_dir)
    stub = types.ModuleType("src.utils.face_analysis_diy")
    stub.FaceAnalysisDIY = _mediapipe_face_analysis()
    sys.modules["src.utils.face_analysis_diy"] = stub  # InsightFace is never imported

    from src.config.argument_config import ArgumentConfig
    from src.config.crop_config import CropConfig
    from src.config.inference_config import InferenceConfig
    from src.live_portrait_pipeline import LivePortraitPipeline

    args = ArgumentConfig(source=a.source, driving=a.driving, output_dir=a.output_dir,
                          flag_use_half_precision=a.half, flag_pasteback=not a.no_pasteback)
    inf = InferenceConfig(flag_use_half_precision=a.half, flag_pasteback=not a.no_pasteback)
    crop = CropConfig()
    pipe = LivePortraitPipeline(inference_cfg=inf, crop_cfg=crop)
    out = pipe.execute(args)
    print("LP_OUTPUT", out)


if __name__ == "__main__":
    main()
