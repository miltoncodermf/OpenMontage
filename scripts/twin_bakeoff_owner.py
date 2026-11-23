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
TAG = os.environ.get("BAKEOFF_TAG", "local")  # output folder name; use e.g. "local_smile" with BAKEOFF_PORTRAIT
PORTRAIT = os.environ.get("BAKEOFF_PORTRAIT")  # portrait image relative to the profile dir (default: the default-hairstyle portrait)
VARIANT = os.environ.get("BAKEOFF_VARIANT", "default_hair1")
OUT = REPO / "projects" / f"presenter-onboarding-{PROFILE}" / "bakeoff" / TAG
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
    vref = os.environ.get("BAKEOFF_VOICE_REF")  # owner-only voice from an explicit reference file (relative to the profile)
    if vref:
        from lib import chatterbox_voice, voice_lab as vl
        from lib.heavy_lock import heavy_job

        d = pdir()
        base = json.loads((d / "voice" / "voice_profile.json").read_text())
        base.update({"candidate_id": "c5_owner100", "owner_ref": vref, "donor_refs": {}, "voice_variant": f"ref:{vref}", "speed": 0.95,
                     "recipe": {"owner_weight": 1.0, "donors": [], "exaggeration": float(os.environ.get("BAKEOFF_VOICE_EXAG", "0.5")), "cfg": 0.5, "pitch_semitones": 0.0},
                     "polish_chain": {"name": "om-voice-polish-v1"}, "stretch_engine": "rubberband-r3"})
        scratch = d / "derived" / "bakeoff_ref_voice_profile.json"
        scratch.write_text(json.dumps(base))
        try:
            with heavy_job("bakeoff_narration", wait=900):
                rep = chatterbox_voice.synthesize_narration(scratch, TEXT, NARRATION)
        finally:
            scratch.unlink(missing_ok=True)
        (OUT / "narration.txt").write_text(TEXT)
        return {"voice_ref": vref, "exaggeration": base["recipe"]["exaggeration"], "takes": rep["takes"], "rerolled": rep["rerolled"], "incomplete_sentences": rep["incomplete_sentences"]}
    variant = os.environ.get("BAKEOFF_VOICE_VARIANT")  # a voice variant not (yet) baked into the profile: synthesize via a scratch copy
    if variant:
        from lib import chatterbox_voice, voice_lab as vl
        from lib.heavy_lock import heavy_job

        d = pdir()
        base = json.loads((d / "voice" / "voice_profile.json").read_text())
        v = vl.VOICE_VARIANTS[variant]
        base.update({"owner_ref": v["reference"], "voice_variant": variant, "speed": base.get("speed", 0.95)})
        scratch = d / "derived" / f"bakeoff_{variant}_voice_profile.json"
        scratch.parent.mkdir(exist_ok=True)
        scratch.write_text(json.dumps(base))
        try:
            with heavy_job("bakeoff_narration", wait=900):
                rep = chatterbox_voice.synthesize_narration(scratch, TEXT, NARRATION)
        finally:
            scratch.unlink(missing_ok=True)
        (OUT / "narration.txt").write_text(TEXT)
        return {"voice_variant": variant, "takes": rep["takes"], "rerolled": rep["rerolled"], "incomplete_sentences": rep["incomplete_sentences"]}
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


NATURAL = os.environ.get("BAKEOFF_NATURAL") == "1"  # long continuous driving window, calmer expression, smoothed head, natural blinks
NATURAL_WINDOW = (36.0, 24.0)  # 33-65 s of the performance has no hands in frame
# Owner's pick (variant C2): big MuseTalk mouth (openness 1.0, kept), LivePortrait lip motion held still so it cannot fight the regenerated mouth,
# and a lips-and-chin-only paste mask so the folds beside the mouth come from the stable portrait. Crease flicker 0.076 -> 0.029, opening 0.052 -> 0.052.
NATURAL_LIP_GAIN = "0.0"
NATURAL_MOUTH = {"mask": "lips", "lip_dilate": 0.05, "chin_half": 0.22, "color_match": 1.0}


def natural_args() -> list[str]:
    """LivePortrait worker flags for the natural driving: blinks follow the owner's own recording (derived/blink_templates.json, made by
    lib.blink_model.extract from the lid signal of raw/working/performance.sdr.mp4), else scripted blinks."""
    model = pdir() / "derived" / "blink_templates.json"
    blink = ["--blink-model", str(model)] if model.is_file() else ["--blinks"]
    return [*blink, "--pose-smooth", "0.35", "--pose-damp", "0.6", "--max-rot-deg", "5", "--max-trans-sigma", "1.5", "--exp-smooth", "0.25",
            "--hold-frames", str(HOLD_FRAMES), "--lip-gain", os.environ.get("BAKEOFF_LIP_GAIN", NATURAL_LIP_GAIN)]


NATURAL_GAIN = 0.6


def stage_driving_natural() -> dict:
    d = pdir()
    src = d / "raw" / "working" / "performance.sdr.mp4"
    dst = d / "derived" / "driving_performance_long.mp4"
    dst.parent.mkdir(parents=True, exist_ok=True)
    start, length = NATURAL_WINDOW
    first = OUT / "driving_first.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-i", str(src), "-frames:v", "1", str(first)], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", str(HOLD_FRAMES / 25), "-framerate", "25", "-i", str(first), "-ss", str(start), "-t", str(length),
                    "-i", str(src), "-filter_complex", "[0:v]fps=25,format=yuv420p[a];[1:v]fps=25,format=yuv420p[b];[a][b]concat=n=2:v=1[v]", "-map", "[v]",
                    "-c:v", "libx264", "-crf", "14", str(dst)], check=True)
    dst.chmod(0o600)
    return {"driving": str(dst), "window_s": [start, start + length], "hold_frames": HOLD_FRAMES}


def stage_driving() -> dict:
    if NATURAL:
        return stage_driving_natural()
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
    portrait = (d / PORTRAIT) if PORTRAIT else pp.default_portrait(PROFILE)
    driving = d / "derived" / ("driving_performance_long.mp4" if NATURAL else "driving_performance_seg.mp4")
    res = TwinPerformanceTransfer().execute({"profile_id": PROFILE, "variant_id": VARIANT, "variant_image": str(portrait), "driving_video": str(driving),
                                             "lock_eyes": True, "lock_scale": True, "expression_gain": NATURAL_GAIN if NATURAL else EXPRESSION_GAIN,
                                             "worker_args": natural_args() if NATURAL else []})
    if not res.success:
        raise SystemExit(f"liveportrait failed: {res.error}")
    out = Path(res.data["output"])
    tmp = out.with_suffix(".trim.mp4")  # drop the held reference frames
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(HOLD_FRAMES / 25), "-i", str(out), "-an", "-r", "25", "-c:v", "libx264", "-crf", "12",
                    "-pix_fmt", "yuv420p", str(tmp)], check=True)
    tmp.replace(out)
    out.chmod(0o600)
    return {**res.data, "lock_eyes": True, "lock_scale": True, "expression_gain": NATURAL_GAIN if NATURAL else EXPRESSION_GAIN, "worker_args": natural_args() if NATURAL else [], "held_frames_trimmed": HOLD_FRAMES}


def stage_lipsync() -> dict:
    _registry()
    from tools.presenters.twin_lipsync import TwinLipsync

    motion = (pdir() / "loops" / VARIANT / "idle.mp4") if os.environ.get("BAKEOFF_ENGINE") == "hybrid" else (pdir() / "performance" / f"{VARIANT}.mp4")
    res = TwinLipsync().execute({"backend": "musetalk_mlx", "motion_source": str(motion), "output_dir": str(OUT),
                                 "loop_mode": "auto_crossfade", **({"lipsync_options": json.loads(os.environ["BAKEOFF_MOUTH"]) if os.environ.get("BAKEOFF_MOUTH") else NATURAL_MOUTH} if (NATURAL or os.environ.get("BAKEOFF_MOUTH")) else {}), "segments": [{"segment_id": "seg1", "audio": str(NARRATION)}]})
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
                "presenter_backdrop": backdrops.remotion_spec(pdir(), "bg_home_office"),
                **({"presenter_scale": float(os.environ["BAKEOFF_PRESENTER_SCALE"])} if os.environ.get("BAKEOFF_PRESENTER_SCALE") else {})}
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
    out = OUT / f"render_{layout}{os.environ.get('BAKEOFF_RENDER_SUFFIX', '')}.mp4"
    vc = VideoCompose()
    res = vc._remotion_render({"edit_decisions": ed, "output_path": str(out), "remotion_timeout_ms": 240_000})
    if not res.success:
        raise SystemExit(f"render failed: {res.error}")
    review = vc._run_final_review(out, ed, asset_manifest=manifest)
    (OUT / f"final_review_{layout}.json").write_text(json.dumps(review, indent=2, default=str))
    va = compiled["visual_analytics"]
    return {"output": str(out), "final_review_status": review["status"], "presenter_percentage": va["presenter_percentage"],
            "cut_has_backdrop": any("presenterBackdrop" in c for c in compiled["cuts"]), "layout_warning": [c.get("layoutWarning") for c in compiled["cuts"] if c.get("layoutWarning")]}


def stage_qa_render() -> dict:
    """Face-scale, brow-repetition and blink-rate checks on the finished full-screen render (the PIP face is too small for landmarks)."""
    from lib import face_tools
    from lib.presenter_qa import check_blink_rate, check_brow_repetition, check_face_scale

    res = {}
    r = OUT / "render_full.mp4"
    if r.exists():
        sig = face_tools.face_signals_from_video(r, 25.0)
        res["full"] = {"face_scale": check_face_scale(r, lambda _v: sig["width"], fps=25.0), "brow_repetition": check_brow_repetition(sig["brow"], 25.0),
                       "blink_rate": check_blink_rate(sig["lid"], 25.0)}
    (OUT / "qa_render.json").write_text(json.dumps(res, indent=2))
    return res


STAGES = {"narration": stage_narration, "driving": stage_driving, "liveportrait": stage_liveportrait, "lipsync": stage_lipsync,
          "matte": stage_matte, "qa": stage_qa, "qa_render": stage_qa_render}


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
        hybrid = os.environ.get("BAKEOFF_ENGINE") == "hybrid"
        plan = [[s] for s in STAGES if s != "qa_render" and not (hybrid and s in ("driving", "liveportrait"))] + [["render", "--layout", "pip"], ["render", "--layout", "full"], ["qa_render"]]
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
