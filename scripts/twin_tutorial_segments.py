#!/usr/bin/env python
"""Batched, resumable local-engine presenter segments for a whole tutorial (P6).

    python scripts/twin_tutorial_segments.py run    <manifest.json>      # all segments, resumes where it stopped
    python scripts/twin_tutorial_segments.py status <manifest.json>      # state + wall time per narrated second
    python scripts/twin_tutorial_segments.py stage  <manifest.json> <segment_id> <stage> --parent-pid N   (internal: one stage in its own process)

Manifest (JSON):
    {"run_id": "p6_dry", "profile": "ming", "motion_pool": ["performance/c_hair1.mp4"], "variant_id": "hair1",
     "backdrop": "bg_home_office", "presenter_scale": null, "seed": 0, "preview": true, "lipsync_options": {...},
     "segments": [{"segment_id": "s1", "beat_id": "b1", "title": "...", "text": "..."}]}

Outputs (gitignored): projects/presenter-onboarding-<profile>/engine_p6/<run_id>/{run_state.json, run_report.json, <segment>/...}.
Narration is cached by hash (voice profile + text) under engine_p6/_cache/narration so a re-run or a second run never re-synthesizes.
No paid call is ever made. A segment that fails QA is marked ``fallback`` (no presenter beat) with the reason; the run continues.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from lib import twin_segments as ts  # noqa: E402

CANVAS = {"width": 1920, "height": 1080}


# ------------------------------------------------------------------------------------------------------------------ manifest / paths


class Ctx:
    def __init__(self, manifest_path: Path):
        self.manifest_path = Path(manifest_path).resolve()
        self.m = json.loads(self.manifest_path.read_text())
        self.profile = self.m.get("profile", "ming")
        from lib import presenter_profile as pp

        self.pdir = pp.profile_dir(self.profile)
        self.root = REPO / "projects" / f"presenter-onboarding-{self.profile}" / "engine_p6"
        self.run = self.root / self.m["run_id"]
        self.cache = self.root / "_cache" / "narration"
        self.segments = {s["segment_id"]: s for s in self.m["segments"]}
        self.order = [s["segment_id"] for s in self.m["segments"]]
        self.voice_profile = self.pdir / "voice" / "voice_profile.json"
        self.pool = {Path(p).stem: (self.pdir / p) for p in self.m["motion_pool"]}
        self.mouth = self.m.get("lipsync_options") or ts.DEFAULT_MOUTH

    def sd(self, sid: str) -> Path:
        d = self.run / sid
        d.mkdir(parents=True, exist_ok=True)
        return d


def _registry():
    from tools.tool_registry import registry

    registry.discover()
    return registry


def _duration(path: Path) -> float:
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], text=True))


# ------------------------------------------------------------------------------------------------------------------ stage keys and outputs


def stage_key(ctx: Ctx, sid: str, stage: str) -> str:
    sd, seg = ctx.run / sid, ctx.segments[sid]
    if stage == "narration":
        return ts.key_of(seg["text"], ts.sha_file(ctx.voice_profile))
    if stage == "align":
        return ts.key_of(seg["text"], ts.sha_file(sd / "narration.wav"))
    if stage == "motion":
        durs = _durations_through(ctx, sid)
        return ts.key_of(durs, {k: ts.sha_file(p) for k, p in ctx.pool.items()}, ctx.m.get("seed", 0), ts.CHUNK_S, ts.OVERLAP_S)
    if stage == "lipsync":
        return ts.key_of(ts.sha_file(sd / "motion.mp4"), ts.sha_file(sd / "narration.wav"), ctx.mouth)
    if stage == "qa":
        return ts.key_of(ts.sha_file(sd / "lipsync.mp4"), ts.QA_VERSION)
    if stage == "matte":
        return ts.key_of(ts.sha_file(sd / "lipsync.mp4"))
    if stage == "preview":
        return ts.key_of(ts.sha_file(sd / "alpha.mov"), ts.sha_file(sd / "narration.wav"), ctx.m.get("backdrop"), ctx.m.get("presenter_scale"), seg.get("title"))
    raise KeyError(stage)


def stage_outputs(ctx: Ctx, sid: str, stage: str) -> list[Path]:
    sd = ctx.run / sid
    return {"narration": [sd / "narration.wav"], "align": [sd / "alignment.json"], "motion": [sd / "motion.mp4", sd / "motion_plan.json"],
            "lipsync": [sd / "lipsync.mp4"], "qa": [sd / "qa.json"], "matte": [sd / "alpha.mov"],
            "preview": [sd / "render_full.mp4", sd / "assets.json"]}[stage]


def _durations_through(ctx: Ctx, sid: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for s in ctx.order:
        a = ctx.run / s / "narration.wav"
        out[s] = round(_duration(a), 3)
        if s == sid:
            break
    return out


# ------------------------------------------------------------------------------------------------------------------ stage workers (own process)


def w_narration(ctx: Ctx, sid: str) -> dict:
    seg, sd = ctx.segments[sid], ctx.sd(sid)
    key = stage_key(ctx, sid, "narration")
    cached = ctx.cache / f"{key}.wav"
    if cached.is_file():
        shutil.copy2(cached, sd / "narration.wav")
        return {"cache": "hit", "key": key}
    res = _registry().get("mlx_tts").execute({"text": seg["text"], "voice_profile": str(ctx.voice_profile), "output_path": str(sd / "narration.wav")})
    if not res.success:
        raise SystemExit(f"narration failed: {res.error}")
    ctx.cache.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sd / "narration.wav", cached)
    d = res.data
    (ctx.cache / f"{key}.json").write_text(json.dumps({"voice_profile_sha256": d.get("voice_profile_sha256"), "synthesis": d.get("synthesis"), "text": seg["text"]}, indent=2, default=str))
    return {"cache": "miss", "key": key, "voice_profile_sha256": d.get("voice_profile_sha256"), "duration_s": d.get("duration_seconds")}


def w_align(ctx: Ctx, sid: str) -> dict:
    sd, seg = ctx.sd(sid), ctx.segments[sid]
    _registry()
    from tools.audio.script_aligner import ScriptAligner

    res = ScriptAligner().execute({"audio_path": str(sd / "narration.wav"), "text": seg["text"]})
    if not res.success:
        raise SystemExit(f"alignment failed: {res.error}")
    (sd / "alignment.json").write_text(json.dumps({"duration_s": _duration(sd / "narration.wav"), **{k: res.data[k] for k in res.data if k != "audio_path"}}, indent=2, default=str))
    return {"alignment_method": res.data.get("alignment_method"), "confidence": res.data.get("confidence")}


def w_motion(ctx: Ctx, sid: str) -> dict:
    sd = ctx.sd(sid)
    from lib import twin_media

    clips = [{"id": k, "duration_s": float(twin_media.probe(p)["duration_seconds"])} for k, p in ctx.pool.items()]
    durs = _durations_through(ctx, sid)
    plan = ts.plan_motion(durs, clips, seed=ctx.m.get("seed", 0), boundary_distance=ts.gray_boundary_distance(ctx.pool))
    pieces = plan["segments"][sid]
    ts.compose_motion(pieces, ctx.pool, sd / "motion.mp4", durs[sid] + 0.2)
    (sd / "motion_plan.json").write_text(json.dumps({"pieces": pieces, "reuse_through_this_segment": plan["reuse"], "durations": durs}, indent=2))
    return {"pieces": len(pieces), "reuse": plan["reuse"]}


def w_lipsync(ctx: Ctx, sid: str) -> dict:
    sd = ctx.sd(sid)
    _registry()
    from tools.presenters.twin_lipsync import TwinLipsync

    res = TwinLipsync().execute({"backend": "musetalk_mlx", "motion_source": str(sd / "motion.mp4"), "output_dir": str(sd), "loop_mode": "loop",
                                 "lipsync_options": ctx.mouth, "segments": [{"segment_id": "lipsync", "audio": str(sd / "narration.wav")}]})
    if not res.success:
        raise SystemExit(f"lipsync failed: {res.error}")
    (sd / "lipsync.mp4").chmod(0o600)
    return {"loop": res.data["segments"][0]["loop"] if res.data["segments"] else "resumed"}


def _asset(ctx: Ctx, path: Path, asset_type: str) -> dict:
    from lib import presenter_profile as pp

    return pp.mint_presenter_asset(ctx.profile, path, asset_type=asset_type, variant_id=ctx.m.get("variant_id", "hair1"), source_tool="twin_lipsync")


def w_qa(ctx: Ctx, sid: str) -> dict:
    sd = ctx.sd(sid)
    from lib import mouth_metrics as mm
    from lib import presenter_qa as qa

    clip, audio = sd / "lipsync.mp4", sd / "narration.wav"
    raw = sorted((ctx.pdir / "raw" / "working").glob("*.sdr.mp4"))  # compared by hash only; never rendered
    rep = qa.presenter_qa_report(_asset(ctx, clip, "presenter_video"), clip, audio, 25.0, raw)
    sig = mm.video_metrics(clip, 25.0)
    rep["checks"]["crease_flicker"] = qa.check_crease_flicker(sig["crease_l"], sig["crease_r"], 25.0)
    rep["checks"]["mouth_opening"] = qa.check_mouth_opening(sig["open_h"])
    verdict = ts.evaluate_qa(rep)
    out = {"verdict": verdict, "report": rep, "mouth": mm.summarize(sig)}
    (sd / "qa.json").write_text(json.dumps(out, indent=2, default=str))
    return {"passed": verdict["passed"], "reason": verdict["reason"], "warnings": verdict["warnings"]}


def w_matte(ctx: Ctx, sid: str) -> dict:
    sd = ctx.sd(sid)
    from lib.model_store import configure_cache_env

    configure_cache_env()
    _registry()
    from tools.presenters.presenter_matte import PresenterMatte

    res = PresenterMatte().execute({"input_path": str(sd / "lipsync.mp4"), "output_path": str(sd / "alpha.mov"), "fps": 25})
    if not res.success:
        raise SystemExit(f"matte failed: {res.error}")
    return {"frames": res.data.get("frames")}


def w_preview(ctx: Ctx, sid: str) -> dict:
    """Full-screen presenter beat for this segment (what the tutorial render will do), plus the minted presenter assets."""
    sd, seg = ctx.sd(sid), ctx.segments[sid]
    from lib import backdrops, loudness
    from tools.audio.script_aligner import ScriptAligner
    from tools.video.scene_plan_adapter import ScenePlanAdapter
    from tools.video.video_compose import VideoCompose

    os.environ.pop("OPENMONTAGE_TEST_MODE", None)
    dur = _duration(sd / "narration.wav")
    al = json.loads((sd / "alignment.json").read_text())
    video_asset, matte_asset = _asset(ctx, sd / "lipsync.mp4", "presenter_video"), _asset(ctx, sd / "alpha.mov", "presenter_matte")
    beat = {"beat_id": seg.get("beat_id", "b1"), "visual_type": "presenter_fullscreen", "duration_hint_seconds": dur, "layout": {"preset": "presenter_fullscreen"},
            "presenter_backdrop": backdrops.remotion_spec(ctx.pdir, ctx.m.get("backdrop", "bg_home_office")),
            **({"presenter_scale": float(ctx.m["presenter_scale"])} if ctx.m.get("presenter_scale") else {})}
    plan = {"version": "2.0", "sections": [{"section_id": "a", "script_section_id": "s1", "learning_objective": seg.get("title", sid), "visual_beats": [beat]}]}
    compiled = ScenePlanAdapter().compile(plan, {"assets": [matte_asset]}, [{"scene_id": "s1", "duration_s": dur, "timestamps": al["timestamps"]}], {"s1": dur}, canvas=CANVAS)
    mastered = sd / "narration_mastered.wav"
    if not mastered.exists():
        loudness.master_two_pass(sd / "narration.wav", mastered)
    ed = {**compiled["edit_decisions"], "cuts": compiled["cuts"], "captions": compiled["captions"], "canvas": compiled["canvas"],
          "audio": {"narration": {"src": str(mastered)}}, "total_duration_seconds": dur}
    vc = VideoCompose()
    res = vc._remotion_render({"edit_decisions": ed, "output_path": str(sd / "render_full.mp4"), "remotion_timeout_ms": 600_000})
    if not res.success:
        raise SystemExit(f"render failed: {res.error}")
    review = vc._run_final_review(sd / "render_full.mp4", ed, asset_manifest={"assets": [matte_asset]})
    (sd / "assets.json").write_text(json.dumps({"presenter_video": video_asset, "presenter_matte": matte_asset, "final_review": review["status"]}, indent=2, default=str))
    return {"final_review": review["status"]}


WORKERS = {"narration": w_narration, "align": w_align, "motion": w_motion, "lipsync": w_lipsync, "qa": w_qa, "matte": w_matte, "preview": w_preview}


# ------------------------------------------------------------------------------------------------------------------ orchestrator


def run_stage_subprocess(ctx: Ctx, sid: str, stage: str) -> dict:
    t0 = time.perf_counter()
    proc = subprocess.run(["/usr/bin/time", "-l", sys.executable, str(Path(__file__)), "stage", str(ctx.manifest_path), sid, stage, "--parent-pid", str(os.getpid())],
                          capture_output=True, text=True, cwd=str(REPO))
    wall = time.perf_counter() - t0
    foot = re.search(r"(\d+)\s+peak memory footprint", proc.stderr)
    out = {"returncode": proc.returncode, "wall_s": round(wall, 1), "peak_footprint_gb": round(int(foot.group(1)) / 1e9, 2) if foot else None}
    if proc.returncode != 0:
        out["error"] = (proc.stderr or proc.stdout)[-1500:]
    else:
        try:
            out["result"] = json.loads(proc.stdout.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            out["result"] = {}
    return out


def run(ctx: Ctx) -> dict:
    state = ts.RunState(ctx.run)
    state.data.setdefault("manifest", {"run_id": ctx.m["run_id"], "segments": ctx.order})
    state.event("run_start", resumed=bool(state.data["segments"]))
    for sid in ctx.order:
        seg = state.seg(sid)
        if seg["status"] in ("done", "fallback"):
            continue
        ctx.sd(sid)
        for stage in ts.STAGES:
            if stage == "preview" and not ctx.m.get("preview", True):
                continue
            key = stage_key(ctx, sid, stage)
            if state.is_done(sid, stage, key, stage_outputs(ctx, sid, stage)):
                print(f"[{sid}] {stage}: cached", flush=True)
                continue
            seg["status"] = "running"
            state.save()
            r = run_stage_subprocess(ctx, sid, stage)
            if r["returncode"] != 0:
                seg["status"] = "error"
                seg["error"] = {"stage": stage, **{k: r[k] for k in ("error", "wall_s")}}
                state.event("stage_error", segment=sid, stage=stage)
                state.save()
                print(f"[{sid}] {stage}: FAILED\n{r.get('error')}", flush=True)
                return finish(ctx, state, ok=False)
            state.mark(sid, stage, key, wall_s=r["wall_s"], peak_footprint_gb=r["peak_footprint_gb"], result=r.get("result"))
            print(f"[{sid}] {stage}: {r['wall_s']} s, peak {r['peak_footprint_gb']} GB", flush=True)
            if stage == "qa":
                v = json.loads((ctx.run / sid / "qa.json").read_text())["verdict"]
                if not v["passed"]:
                    seg["status"] = "fallback"
                    seg["fallback_reason"] = f"presenter QA failed: {v['reason']}"
                    state.event("segment_fallback", segment=sid, reason=seg["fallback_reason"])
                    print(f"[{sid}] QA FAILED -> no-presenter beat ({v['reason']})", flush=True)
                    break
        else:
            seg["status"] = "done"
        if seg["status"] == "running":
            seg["status"] = "done"
        state.save()
    return finish(ctx, state, ok=True)


def finish(ctx: Ctx, state: "ts.RunState", ok: bool) -> dict:
    durs = {sid: round(_duration(ctx.run / sid / "narration.wav"), 3) for sid in ctx.order if (ctx.run / sid / "narration.wav").is_file()}
    summ = ts.segment_summary(state.data, durs)
    seg_status = {sid: state.data["segments"].get(sid, {}).get("status", "pending") for sid in ctx.order}
    fb = {sid: state.data["segments"][sid]["fallback_reason"] for sid in ctx.order if state.data["segments"].get(sid, {}).get("fallback_reason")}
    beats = {ctx.segments[sid].get("beat_id", sid): reason for sid, reason in fb.items()}
    rep = {"run_id": ctx.m["run_id"], "ok": ok and all(s in ("done", "fallback") for s in seg_status.values()), "segments": seg_status,
           "no_presenter_fallbacks": beats, "timing": summ,
           "events": state.data["events"][-20:]}
    ts.write_json_atomic(ctx.run / "run_report.json", rep)
    return rep


def watch_parent(pid: int) -> None:
    def loop() -> None:
        while True:
            time.sleep(2)
            try:
                os.kill(pid, 0)
            except OSError:
                os._exit(75)  # the orchestrator was killed: do not leave a heavy stage running and holding the lock

    threading.Thread(target=loop, daemon=True).start()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "status", "stage"])
    ap.add_argument("manifest")
    ap.add_argument("segment", nargs="?")
    ap.add_argument("stage", nargs="?")
    ap.add_argument("--parent-pid", type=int)
    a = ap.parse_args()
    ctx = Ctx(Path(a.manifest))
    if a.cmd == "stage":
        if a.parent_pid:
            watch_parent(a.parent_pid)
        print(json.dumps(WORKERS[a.stage](ctx, a.segment), default=str))
    elif a.cmd == "run":
        print(json.dumps(run(ctx), indent=2, default=str))
    else:
        print(json.dumps(finish(ctx, ts.RunState(ctx.run), ok=True), indent=2, default=str))


if __name__ == "__main__":
    main()
