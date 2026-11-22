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


EYES_IDX = [11, 13, 15, 16, 18]  # LivePortrait expression keypoints of the eyes (blink and gaze live here)


LIP_IDX = [6, 12, 14, 17, 19, 20]  # mouth keypoints: MuseTalk repaints the mouth, so they are left alone


def blink_weight(dt: float, close_s: float = 0.10, open_s: float = 0.18) -> float:
    """How closed the eye is (0..1) ``dt`` seconds after the lids are fully down: eased close (fast) then eased, slower re-open."""
    if dt <= -close_s or dt >= open_s:
        return 0.0
    if dt < 0:
        u = (dt + close_s) / close_s
        return float(0.5 - 0.5 * np.cos(np.pi * u))  # smooth start, smooth landing
    return float(0.5 + 0.5 * np.cos(np.pi * dt / open_s))  # lids rise gently


def _smooth(x, sigma_frames: float):
    from scipy.ndimage import gaussian_filter1d

    return x if sigma_frames <= 0 else gaussian_filter1d(x, sigma_frames, axis=0, mode="nearest")


def edit_template(tpl: dict, *, lock_eyes: bool = False, gain: float = 1.0, lock_scale: bool = False, pose_smooth_s: float = 0.0,
                  pose_damp: float = 1.0, max_rot_deg: float = 0.0, max_trans_sigma: float = 0.0, exp_smooth_s: float = 0.0,
                  blinks: bool = False, blink_seed: int = 7, blink_gap_s: tuple = (3.0, 6.5), blink_depth: tuple = (0.8, 1.0), blink_double_prob: float = 0.15,
                  hold_frames: int = 0, fps: float = 25.0) -> dict:
    """Edit the driving template in place before animation (pure function so it can be tested without LivePortrait).

    lock_eyes: every frame's eye keypoints become the open-eye median (no gaze wander, no real blinks);
    blinks: then add scripted blinks at natural, jittered intervals (about 12-14 a minute): eased close in ~100 ms and a slower ~180 ms re-open, depth
      80-100 % of the driving clip's most closed eye frame, an occasional double blink;
    lock_scale: head scale of every frame = first frame's (no growing or shrinking);
    pose_smooth_s / pose_damp / max_rot_deg / max_trans_sigma: low-pass the head rotation and translation, damp their amplitude around the
      clip mean and cap the drift (rotation in degrees, translation in standard deviations);
    exp_smooth_s / gain: low-pass the brow/cheek expression and scale its change around the clip mean (gain < 1 = calmer brows);
    hold_frames: the first frames are replaced by the clip-mean pose/expression so LivePortrait's relative motion is measured against
      the average, not against whatever the first frame happened to be (the caller trims those frames from the output).
    """
    motion = tpl["motion"]
    n = len(motion)
    other = [i for i in range(21) if i not in EYES_IDX and i not in LIP_IDX]
    h = hold_frames
    body = slice(h, n)
    # -- brow/cheek expression: smooth, then scale around the mean --------------------------------------------------
    if exp_smooth_s > 0 or gain != 1.0:
        ex = np.stack([m["exp"][0, other, :] for m in motion])  # (n, k, 3)
        ex_s = _smooth(ex, exp_smooth_s * fps)
        mean = ex_s[body].mean(axis=0, keepdims=True)
        ex_n = mean + gain * (ex_s - mean)
        for i, m in enumerate(motion):
            m["exp"][0, other, :] = ex_n[i]
    # -- head pose ------------------------------------------------------------------------------------------------
    if "R" in motion[0] and (pose_smooth_s > 0 or pose_damp != 1.0 or max_rot_deg > 0 or max_trans_sigma > 0):
        from scipy.spatial.transform import Rotation as Rot

        rots = Rot.from_matrix(np.stack([m["R"][0] for m in motion]))
        mean_r = rots[body].mean()
        rel = (mean_r.inv() * rots).as_rotvec()  # (n, 3) rotation of every frame relative to the clip's mean orientation
        rel = _smooth(rel, pose_smooth_s * fps) * pose_damp
        if max_rot_deg > 0:
            lim = np.deg2rad(max_rot_deg)
            norms = np.linalg.norm(rel, axis=1, keepdims=True)
            rel = rel * np.minimum(1.0, lim / np.maximum(norms, 1e-9))
        new_r = (mean_r * Rot.from_rotvec(rel)).as_matrix().astype(np.float32)
        tr = np.stack([m["t"][0] for m in motion])  # (n, 3)
        tr_mean = tr[body].mean(axis=0, keepdims=True)
        dt = _smooth(tr - tr_mean, pose_smooth_s * fps) * pose_damp
        if max_trans_sigma > 0:
            sd = np.maximum(dt[body].std(axis=0, keepdims=True), 1e-9)
            dt = np.clip(dt, -max_trans_sigma * sd, max_trans_sigma * sd)
        for i, m in enumerate(motion):
            m["R"] = new_r[i:i + 1].copy()
            m["t"] = (tr_mean + dt[i:i + 1]).astype(np.float32)
    # -- scale ----------------------------------------------------------------------------------------------------
    if lock_scale:
        sc = np.median(np.stack([m["scale"] for m in motion[body]]), axis=0)
        for m in motion:
            m["scale"] = sc.copy()
    # -- eyes -----------------------------------------------------------------------------------------------------
    if lock_eyes:
        ratio = np.array([float(np.mean(c)) for c in tpl["c_eyes_lst"]])
        open_frames = [i for i in range(h, n) if ratio[i] >= np.median(ratio[body])]
        ref = np.median(np.stack([motion[i]["exp"][:, EYES_IDX, :] for i in open_frames]), axis=0)
        closed = motion[int(np.argmin(np.where(np.arange(n) >= h, ratio, 9)))]["exp"][:, EYES_IDX, :].copy()
        for m in motion:
            m["exp"][:, EYES_IDX, :] = ref
        if blinks:
            rng = np.random.default_rng(blink_seed)
            seconds = (n - h) / fps
            t = 1.4 + rng.uniform(0, 1.2)
            while t < seconds - 0.5:
                centres = [t]
                if rng.uniform() < blink_double_prob:  # an occasional double blink
                    centres.append(t + float(rng.uniform(0.28, 0.40)))
                for c in centres:
                    depth = float(rng.uniform(*blink_depth))  # not every blink closes completely
                    shift = float(rng.uniform(-0.5, 0.5)) / fps  # sub-frame jitter so the frames sample the curve differently each time
                    for j in range(h, n):
                        w = depth * blink_weight((j - h) / fps - c - shift)
                        if w > 1e-3:
                            motion[j]["exp"][:, EYES_IDX, :] = ref + w * (closed - ref)
                t = centres[-1] + float(rng.uniform(*blink_gap_s))
    # -- the held reference frames: the clip mean ---------------------------------------------------------------------
    if h > 0:
        keys = ("exp", "R", "t", "scale")
        for i in range(h):
            for k in keys:
                if k == "R" and "R" not in motion[0]:
                    continue
                motion[i][k] = np.mean(np.stack([m[k] for m in motion[body]]), axis=0).astype(np.float32) if k != "R" else _mean_rot(motion[body])
    return tpl


def _mean_rot(items):
    from scipy.spatial.transform import Rotation as Rot

    return Rot.from_matrix(np.stack([m["R"][0] for m in items])).mean().as_matrix().astype(np.float32)[None]


def _install_template_edits(pipeline_cls, *, lock_eyes: bool = False, gain: float = 1.0, lock_scale: bool = False, **edits) -> None:
    """Wrap ``make_motion_template`` so every driving clip goes through :func:`edit_template` (see there for the options)."""
    original = pipeline_cls.make_motion_template

    def patched(self, I_lst, c_eyes_lst, c_lip_lst, **kwargs):
        tpl = original(self, I_lst, c_eyes_lst, c_lip_lst, **kwargs)
        return edit_template(tpl, lock_eyes=lock_eyes, gain=gain, lock_scale=lock_scale, **edits)

    pipeline_cls.make_motion_template = patched


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lp-dir", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--driving", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--half", action="store_true")
    ap.add_argument("--no-pasteback", action="store_true")
    ap.add_argument("--expression-gain", type=float, default=1.0, help="scale the driving brow/cheek expression change relative to its first frame (>1 = livelier)")
    ap.add_argument("--lock-scale", action="store_true", help="keep the head size constant: ignore the driving clip's lean-in/lean-out")
    ap.add_argument("--lock-eyes", action="store_true", help="drop blinks and eye/gaze motion from the driving clip (eyes stay as in the portrait)")
    ap.add_argument("--blinks", action="store_true", help="with --lock-eyes: add scripted natural blinks")
    ap.add_argument("--pose-smooth", type=float, default=0.0, help="head pose low-pass sigma in seconds")
    ap.add_argument("--pose-damp", type=float, default=1.0, help="head pose amplitude factor around the clip mean")
    ap.add_argument("--max-rot-deg", type=float, default=0.0)
    ap.add_argument("--max-trans-sigma", type=float, default=0.0)
    ap.add_argument("--exp-smooth", type=float, default=0.0, help="brow/cheek expression low-pass sigma in seconds")
    ap.add_argument("--hold-frames", type=int, default=0, help="leading frames of the driving clip that only serve as the neutral reference")
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
    edits = {"blinks": a.blinks, "pose_smooth_s": a.pose_smooth, "pose_damp": a.pose_damp, "max_rot_deg": a.max_rot_deg,
             "max_trans_sigma": a.max_trans_sigma, "exp_smooth_s": a.exp_smooth, "hold_frames": a.hold_frames}
    if a.lock_eyes or a.lock_scale or a.expression_gain != 1.0 or a.pose_smooth or a.pose_damp != 1.0 or a.max_rot_deg or a.exp_smooth or a.hold_frames:
        _install_template_edits(LivePortraitPipeline, lock_eyes=a.lock_eyes, gain=a.expression_gain, lock_scale=a.lock_scale, **edits)
    pipe = LivePortraitPipeline(inference_cfg=inf, crop_cfg=crop)
    out = pipe.execute(args)
    print("LP_OUTPUT", out)


if __name__ == "__main__":
    main()
