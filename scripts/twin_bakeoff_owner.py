#!/usr/bin/env python
"""Owner twin bake-off, LOCAL path only (LivePortrait driven by the owner's performance + MuseTalk-MLX).

Runs on the owner's real private profile (default ``ming``), unlocked or locked. Every stage runs in its own
process under ``/usr/bin/time -l`` so wall-clock and peak memory are measured per stage. No paid call is made.

Stages: narration, driving, liveportrait, lipsync, matte, qa, render (--layout pip|full), report.
Outputs go to ``projects/presenter-onboarding-<id>/bakeoff/local/`` (gitignored); the LivePortrait clip is cached
in the profile's ``performance/`` (derived cache). The raw performance recording is read only as a driving
signal; only a trimmed video-only working copy goes to the profile's ``derived/`` and nothing raw is rendered.
Because the profile may be unlocked, assets are built by hand (same fields as ``mint_presenter_asset``) and marked
``profile_locked: false``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

PROFILE = os.environ.get("BAKEOFF_PROFILE", "ming")
OUT = REPO / "projects" / f"presenter-onboarding-{PROFILE}" / "bakeoff" / "local"
OUT.mkdir(parents=True, exist_ok=True)
NARRATION = OUT / "narration.wav"
TEXT = ("Unified memory lets the CPU and the GPU share one pool of fast memory. That is why a laptop can hold a very large "
        "model without copying it across a bus. But holding a model is not the same as running it quickly. Each new token has "
        "to read the weights again, so the speed you get is set by memory bandwidth divided by the size of the model.")
DRIVE_START, DRIVE_LEN = 35.3, 9.7  # talking, no hands in frame, one short pause
CANVAS = {"width": 1920, "height": 1080}


def _registry():
    from tools.tool_registry import registry

    registry.discover()
    return registry


def pdir() -> Path:
    from lib import presenter_profile as pp

    return pp.profile_dir(PROFILE)


def stage_narration() -> dict:
    from tools.tool_registry import registry

    registry.discover()
    tool = registry.get("mlx_tts")
    res = tool.execute({"text": TEXT, "voice_profile": str(pdir() / "voice" / "voice_profile.json"), "output_path": str(NARRATION)})
    if not res.success:
        raise SystemExit(f"narration failed: {res.error}")
    d = res.data
    (OUT / "narration.txt").write_text(TEXT)
    return {k: d.get(k) for k in ("duration_seconds", "speed", "synthesis")}


HOLD_FRAMES = 3  # prepended copies of the owner's sternest open-eyed frame; LivePortrait animates relative to frame 0
EXPRESSION_GAIN = 1.6


def stage_driving() -> dict:
    """Trim the driving window and put the sternest frame first (relative motion then makes every later frame livelier)."""
    import numpy as np

    d = pdir()
    src = d / "raw" / "working" / "performance.sdr.mp4"
    dst = d / "derived" / "driving_performance_seg.mp4"
    dst.parent.mkdir(parents=True, exist_ok=True)
    win = OUT / "driving_window.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(DRIVE_START), "-t", str(DRIVE_LEN), "-i", str(src), "-an", "-r", "25",
                    "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(win)], check=True)
    from PIL import Image
    import tempfile, glob
    from lib import face_tools

    scores = []
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(win), f"{td}/%05d.jpg"], check=True)
        for f in sorted(glob.glob(td + "/*.jpg")):
            lm = face_tools.face_landmarks(Image.open(f))
            if lm is None:
                scores.append(None)
                continue
            def lid(c1, c2, top, bot):
                return abs(lm[bot, 1] - lm[top, 1]) / (np.linalg.norm(lm[c1, :2] - lm[c2, :2]) + 1e-6)
            openness = (lid(33, 133, 159, 145) + lid(362, 263, 386, 374)) / 2
            fw = np.linalg.norm(lm[234, :2] - lm[454, :2])
            mouth_w = np.linalg.norm(lm[61, :2] - lm[291, :2]) / fw
            brow = (lm[[105, 334], 1].mean() - lm[[159, 386], 1].mean()) / fw  # least negative = lowest brows = sternest
            scores.append((float(openness), float(mouth_w), float(brow)))
    cand = [i for i, sc in enumerate(scores) if sc and sc[0] > 0.6 and sc[1] < 0.34]
    stern = max(cand, key=lambda i: scores[i][2])
    hold = OUT / "driving_hold.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(win), "-vf", f"select=eq(n\\,{stern})", "-frames:v", "1", str(hold)], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", str(HOLD_FRAMES / 25), "-framerate", "25", "-i", str(hold), "-i", str(win),
                    "-filter_complex", "[0:v]fps=25,format=yuv420p[a];[1:v]fps=25,format=yuv420p[b];[a][b]concat=n=2:v=1[v]", "-map", "[v]",
                    "-c:v", "libx264", "-crf", "14", str(dst)], check=True)
    dst.chmod(0o600)
    return {"driving": str(dst), "stern_frame": stern, "hold_frames": HOLD_FRAMES}


def stage_liveportrait() -> dict:
    from lib import presenter_profile as pp

    _registry()
    from tools.presenters.twin_performance_transfer import TwinPerformanceTransfer

    d = pdir()
    portrait = pp.default_portrait(PROFILE)
    res = TwinPerformanceTransfer().execute({"profile_id": PROFILE, "variant_id": "default_hair1", "variant_image": str(portrait),
                                             "driving_video": str(d / "derived" / "driving_performance_seg.mp4"),
                                             "lock_eyes": True, "expression_gain": EXPRESSION_GAIN})
    if not res.success:
        raise SystemExit(f"liveportrait failed: {res.error}")
    out = Path(res.data["output"])
    tmp = out.with_suffix(".trim.mp4")  # drop the held reference frames
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(HOLD_FRAMES / 25), "-i", str(out), "-an", "-r", "25", "-c:v", "libx264", "-crf", "12",
                    "-pix_fmt", "yuv420p", str(tmp)], check=True)
    tmp.replace(out)
    out.chmod(0o600)
    return {**res.data, "lock_eyes": True, "expression_gain": EXPRESSION_GAIN, "held_frames_trimmed": HOLD_FRAMES}


def stage_lipsync() -> dict:
    _registry()
    from tools.presenters.twin_lipsync import TwinLipsync

    motion = pdir() / "performance" / "default_hair1.mp4"
    res = TwinLipsync().execute({"backend": "musetalk_mlx", "motion_source": str(motion), "output_dir": str(OUT),
                                 "segments": [{"segment_id": "seg1", "audio": str(NARRATION)}]})
    if not res.success:
        raise SystemExit(f"lipsync failed: {res.error}")
    return res.data


def stage_matte() -> dict:
    from lib.model_store import configure_cache_env

    configure_cache_env()
    _registry()
    from tools.presenters.presenter_matte import PresenterMatte

    res = PresenterMatte().execute({"input_path": str(OUT / "seg1.mp4"), "output_path": str(OUT / "alpha.mov"), "fps": 25})
    if not res.success:
        raise SystemExit(f"matte failed: {res.error}")
    return res.data


def _asset(path: Path, asset_type: str, variant: str) -> dict:
    from lib import presenter_profile as pp

    sha = pp.sha256_file(path)
    aid = f"presenter_{variant}_{sha[:8]}"
    return {"asset_id": aid, "id": aid, "asset_type": asset_type, "type": asset_type, "path": str(path.resolve()),
            "source_tool": "twin_lipsync", "provider_id": "twin_lipsync", "runtime": "local_gpu", "source_type": "digital_twin",
            "sha256": sha, "identity_transform": "beautified", "profile_id": PROFILE, "variant_id": variant, "status": "validated",
            "cost_estimate_usd": 0.0, "actual_cost_usd": 0.0, "profile_locked": bool(pp.read_profile(PROFILE).get("locked"))}


def stage_qa() -> dict:
    from lib.presenter_qa import presenter_qa_report

    clip = OUT / "seg1.mp4"
    rep = presenter_qa_report(_asset(clip, "presenter_video", "bakeoff-local"), clip, NARRATION, 25.0, [])
    (OUT / "qa.json").write_text(json.dumps(rep, indent=2, default=str))
    return rep


def _compile(layout: str):
    from lib import backdrops
    from tools.audio.script_aligner import ScriptAligner
    from tools.video.scene_plan_adapter import ScenePlanAdapter

    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(NARRATION)], text=True))
    al = ScriptAligner().execute({"audio_path": str(NARRATION), "text": TEXT})
    assert al.success, al.error
    asset = _asset(OUT / "alpha.mov", "presenter_matte", "bakeoff-local")
    spec = {"title": "Unified memory", "nodes": ["CPU", "Shared pool", "GPU"], "edges": [["CPU", "Shared pool"], ["Shared pool", "GPU"]]}
    if layout == "pip":
        beat = {"beat_id": "b1", "visual_type": "diagram", "duration_hint_seconds": dur, "layout": {"preset": "diagram", "presenter_pip": True},
                "diagram_spec": spec, "focus_region": {"x": 0.1, "y": 0.38, "w": 0.8, "h": 0.28}}
    else:
        beat = {"beat_id": "b1", "visual_type": "presenter_fullscreen", "duration_hint_seconds": dur, "layout": {"preset": "presenter_fullscreen"},
                "presenter_backdrop": backdrops.remotion_spec(pdir(), "bg_home_office")}
    plan = {"version": "2.0", "sections": [{"section_id": "a", "script_section_id": "s1", "learning_objective": "Unified memory", "visual_beats": [beat]}]}
    compiled = ScenePlanAdapter().compile(plan, {"assets": [asset]}, [{"scene_id": "s1", "duration_s": dur, "timestamps": al.data["timestamps"]}],
                                          {"s1": dur}, canvas=CANVAS)
    return compiled, {"assets": [asset]}, dur


def stage_render(layout: str) -> dict:
    from lib import loudness
    from tools.video.video_compose import VideoCompose

    os.environ.pop("OPENMONTAGE_TEST_MODE", None)
    compiled, manifest, dur = _compile(layout)
    mastered = OUT / "narration_mastered.wav"
    if not mastered.exists():
        loudness.master_two_pass(NARRATION, mastered)
    ed = {**compiled["edit_decisions"], "cuts": compiled["cuts"], "captions": compiled["captions"], "canvas": compiled["canvas"],
          "audio": {"narration": {"src": str(mastered)}}, "total_duration_seconds": dur}
    out = OUT / f"render_{layout}.mp4"
    vc = VideoCompose()
    res = vc._remotion_render({"edit_decisions": ed, "output_path": str(out), "remotion_timeout_ms": 240_000})
    if not res.success:
        raise SystemExit(f"render failed: {res.error}")
    review = vc._run_final_review(out, ed, asset_manifest=manifest)
    (OUT / f"final_review_{layout}.json").write_text(json.dumps(review, indent=2, default=str))
    va = compiled["visual_analytics"]
    return {"output": str(out), "final_review_status": review["status"], "presenter_percentage": va["presenter_percentage"],
            "cut_has_backdrop": any("presenterBackdrop" in c for c in compiled["cuts"]), "layout_warning": [c.get("layoutWarning") for c in compiled["cuts"] if c.get("layoutWarning")]}


STAGES = {"narration": stage_narration, "driving": stage_driving, "liveportrait": stage_liveportrait, "lipsync": stage_lipsync,
          "matte": stage_matte, "qa": stage_qa}


def run_stage(argv: list[str]) -> dict:
    t0 = time.perf_counter()
    proc = subprocess.run(["/usr/bin/time", "-l", sys.executable, str(Path(__file__)), *argv], capture_output=True, text=True, cwd=str(REPO))
    wall = time.perf_counter() - t0
    rss = re.search(r"(\d+)\s+maximum resident set size", proc.stderr)
    foot = re.search(r"(\d+)\s+peak memory footprint", proc.stderr)
    out = {"stage": "_".join(argv), "returncode": proc.returncode, "wall_s": round(wall, 1),
           "peak_rss_gb": round(int(rss.group(1)) / 1e9, 2) if rss else None, "peak_footprint_gb": round(int(foot.group(1)) / 1e9, 2) if foot else None}
    if proc.returncode != 0:
        out["error"] = proc.stderr[-1200:]
    else:
        out["stdout_tail"] = proc.stdout[-600:]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=[*STAGES, "render", "all"])
    ap.add_argument("--layout", choices=["pip", "full"], default="pip")
    a = ap.parse_args()
    if a.stage == "all":
        rp = OUT / "results.json"
        results = json.loads(rp.read_text()) if rp.exists() else {}
        plan = [[s] for s in STAGES] + [["render", "--layout", "pip"], ["render", "--layout", "full"]]
        for argv in plan:
            key = "_".join(argv).replace("--", "")
            if results.get(key, {}).get("returncode") == 0:
                continue
            results[key] = run_stage(argv)
            rp.write_text(json.dumps(results, indent=2))
            print(key, results[key]["returncode"], results[key]["wall_s"], flush=True)
            if results[key]["returncode"] != 0:
                print("FAILED", key, results[key].get("error"))
                break
        return
    fn = (lambda: stage_render(a.layout)) if a.stage == "render" else STAGES[a.stage]
    print(json.dumps(fn(), indent=2, default=str))


if __name__ == "__main__":
    main()
