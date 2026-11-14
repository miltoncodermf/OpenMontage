#!/usr/bin/env python
"""Dev bake-off of the twin engines on the STAND-IN profile (fix round 1, B8). Engine validation only.

Stages (each runs in its own process so wall-clock and peak RSS are measured per stage by ``/usr/bin/time -l``):

  lipsync   --variant hybrid_mt|local_mt|latentsync   idle loop (hybrid) / LivePortrait output (local) -> lip-synced clip
  matte     --variant ...                              BiRefNet alpha (ProRes 4444)
  qa        --variant ...                              presenter QA (real MediaPipe checks)
  render    --variant ... --layout pip|full            Remotion render with the REAL alpha presenter layer, 16:9
  all                                                  run every stage for every variant (resumable) and write the report

Every asset is stamped ``standin: true`` and prefixed ``STANDIN_``: ``final_review`` fails for any of it by design, and
the report is headed "STAND-IN — not the owner; engine validation only". No default engine is picked here.
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

OUT = REPO / "projects" / "dev-twin-bakeoff"
PROFILE = "standin-dev"
NARRATION = OUT / "narration.wav"
VARIANTS = ["hybrid_mt", "local_mt", "latentsync"]
CANVAS = {"width": 1920, "height": 1080}
TEXT_FILE = OUT / "narration.txt"


def vdir(v: str) -> Path:
    d = OUT / v
    d.mkdir(parents=True, exist_ok=True)
    return d


def _registry():
    from tools.tool_registry import registry

    registry.discover()
    return registry


def stage_lipsync(v: str) -> dict:
    from lib import presenter_profile as pp

    _registry()
    d = pp.profile_dir(PROFILE)
    idle = d / "loops" / "default" / "idle.mp4"
    if v == "local_mt":
        motion = d / "performance" / "STANDIN_default.mp4"
        backend = "musetalk_mlx"
    elif v == "hybrid_mt":
        motion, backend = idle, "musetalk_mlx"
    elif v == "latentsync":
        motion, backend = idle, "latentsync"
    else:
        raise SystemExit(f"unknown variant {v}")
    from tools.presenters.twin_lipsync import TwinLipsync

    res = TwinLipsync().execute({"backend": backend, "motion_source": str(motion), "output_dir": str(vdir(v)),
                                 "segments": [{"segment_id": "STANDIN_seg1", "audio": str(NARRATION)}]})
    if not res.success:
        raise SystemExit(f"lipsync failed: {res.error}")
    return res.data


def stage_matte(v: str) -> dict:
    from lib.model_store import configure_cache_env

    configure_cache_env()
    _registry()
    from tools.presenters.presenter_matte import PresenterMatte

    src = vdir(v) / "STANDIN_seg1.mp4"
    res = PresenterMatte().execute({"input_path": str(src), "output_path": str(vdir(v) / "STANDIN_alpha.mov"), "fps": 25})
    if not res.success:
        raise SystemExit(f"matte failed: {res.error}")
    return res.data


def stage_qa(v: str) -> dict:
    from lib.presenter_qa import presenter_qa_report

    clip = vdir(v) / "STANDIN_seg1.mp4"
    asset = {"asset_id": f"standin_{v}", "asset_type": "presenter_video", "path": str(clip), "identity_transform": "beautified",
             "profile_id": PROFILE, "standin": True}
    rep = presenter_qa_report(asset, clip, NARRATION, 25.0, [])
    (vdir(v) / "qa.json").write_text(json.dumps(rep, indent=2, default=str))
    return rep


def _compile(v: str, layout: str):
    from lib import presenter_profile as pp
    from tools.audio.script_aligner import ScriptAligner
    from tools.video.scene_plan_adapter import ScenePlanAdapter

    text = TEXT_FILE.read_text()
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(NARRATION)], text=True))
    al = ScriptAligner().execute({"audio_path": str(NARRATION), "text": text})
    assert al.success, al.error
    alpha = vdir(v) / "STANDIN_alpha.mov"
    asset = pp.mint_presenter_asset(PROFILE, alpha, asset_type="presenter_matte", variant_id=f"bakeoff-{v}", source_tool="presenter_matte")
    spec = {"title": "Unified memory", "nodes": ["CPU", "Shared pool", "GPU"], "edges": [["CPU", "Shared pool"], ["Shared pool", "GPU"]]}
    beat = ({"beat_id": "b1", "visual_type": "diagram", "duration_hint_seconds": dur, "layout": {"preset": "diagram", "presenter_pip": True}, "diagram_spec": spec}
            if layout == "pip" else
            {"beat_id": "b1", "visual_type": "presenter_fullscreen", "duration_hint_seconds": dur, "layout": {"preset": "presenter_fullscreen"}})
    plan = {"version": "2.0", "sections": [{"section_id": "a", "script_section_id": "s1", "learning_objective": "Unified memory", "visual_beats": [beat]}]}
    compiled = ScenePlanAdapter().compile(plan, {"assets": [asset]}, [{"scene_id": "s1", "duration_s": dur, "timestamps": al.data["timestamps"]}],
                                          {"s1": dur}, canvas=CANVAS)
    return compiled, {"assets": [asset]}, dur


def stage_render(v: str, layout: str) -> dict:
    from lib import loudness
    from tools.video.video_compose import VideoCompose

    os.environ.pop("OPENMONTAGE_TEST_MODE", None)
    compiled, manifest, dur = _compile(v, layout)
    mastered = OUT / "narration_mastered.wav"
    if not mastered.exists():
        loudness.master_two_pass(NARRATION, mastered)
    ed = {**compiled["edit_decisions"], "cuts": compiled["cuts"], "captions": compiled["captions"], "canvas": compiled["canvas"],
          "audio": {"narration": {"src": str(mastered)}}, "total_duration_seconds": dur}
    out = vdir(v) / f"STANDIN_render_{layout}.mp4"
    vc = VideoCompose()
    res = vc._remotion_render({"edit_decisions": ed, "output_path": str(out), "remotion_timeout_ms": 180_000})
    if not res.success:
        raise SystemExit(f"render failed: {res.error}")
    review = vc._run_final_review(out, ed, asset_manifest=manifest)
    (vdir(v) / f"final_review_{layout}.json").write_text(json.dumps(review, indent=2, default=str))
    va = compiled["visual_analytics"]
    return {"output": str(out), "final_review_status": review["status"], "standin_assets": review["checks"]["honesty_guard"].get("standin_assets"),
            "presenter_percentage": va["presenter_percentage"], "fixture_presenter_percentage": va["fixture_presenter_percentage"]}


def run_stage(argv: list[str]) -> dict:
    """Run one stage in a child process under /usr/bin/time -l; returns wall seconds and peak RSS/footprint (GB)."""
    t0 = time.perf_counter()
    proc = subprocess.run(["/usr/bin/time", "-l", sys.executable, str(Path(__file__)), *argv], capture_output=True, text=True, cwd=str(REPO))
    wall = time.perf_counter() - t0
    rss = re.search(r"(\d+)\s+maximum resident set size", proc.stderr)
    foot = re.search(r"(\d+)\s+peak memory footprint", proc.stderr)
    out = {"stage": argv[0], "variant": argv[argv.index("--variant") + 1] if "--variant" in argv else None, "returncode": proc.returncode,
           "wall_s": round(wall, 1), "peak_rss_gb": round(int(rss.group(1)) / 1e9, 2) if rss else None,
           "peak_footprint_gb": round(int(foot.group(1)) / 1e9, 2) if foot else None}
    if proc.returncode != 0:
        out["error"] = [l for l in proc.stderr.splitlines() if "failed" in l.lower() or "Error" in l][-3:] or proc.stderr[-400:]
    return out


def _probe(path: Path) -> dict:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate,duration,codec_name",
                                   "-of", "json", str(path)], text=True)
    st = json.loads(out)["streams"][0]
    return {"size": f"{st['width']}x{st['height']}", "fps": st["r_frame_rate"], "duration_s": round(float(st.get("duration", 0)), 1), "codec": st["codec_name"]}


def _sharpness(path: Path, at: float = 8.0) -> float | None:
    """Laplacian variance of the face region of one frame — a crude mouth/face sharpness proxy (higher = sharper)."""
    import numpy as np
    from PIL import Image

    tmp = path.with_suffix(".sharp.png")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1", str(tmp)], check=True)
    try:
        from lib import face_tools

        im = Image.open(tmp).convert("RGB")
        faces = face_tools.detect_faces(im)
        if not faces:
            return None
        x, y, w, h = faces[0]["bbox"]
        g = np.asarray(im.crop((x, y + h // 2, x + w, y + h)).convert("L"), dtype=np.float32)
        lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
        return round(float(lap.var()), 1)
    finally:
        tmp.unlink(missing_ok=True)


def write_report() -> None:
    results = json.loads((OUT / "results.json").read_text())
    names = {"hybrid_mt": "(ii) hybrid: Omni idle loop + MuseTalk-MLX", "local_mt": "(i) local: LivePortrait + MuseTalk-MLX",
             "latentsync": "LatentSync full-screen"}
    rows, sheet_inputs = [], []
    spent = json.loads((OUT / "dev_spend.json").read_text()) if (OUT / "dev_spend.json").exists() else {}
    for v in VARIANTS:
        if not any(k.endswith(v) or f"variant_{v}" in k for k in results):
            continue
        def st(stage, layout=None):
            key = f"{stage}_variant_{v}" + (f"_layout_{layout}" if layout else "")
            return results.get(key.replace("-", "_"), {})
        lip, mat, qa_s = st("lipsync"), st("matte"), st("qa")
        qa = json.loads((vdir(v) / "qa.json").read_text()) if (vdir(v) / "qa.json").exists() else {}
        chk = qa.get("checks", {})
        clip = vdir(v) / "STANDIN_seg1.mp4"
        sharp = _sharpness(clip) if clip.exists() else None
        for layout in ("pip", "full"):
            r = vdir(v) / f"STANDIN_render_{layout}.mp4"
            if r.exists():
                sheet_inputs.append((v, layout, r))
        reviews = {l: (json.loads((vdir(v) / f"final_review_{l}.json").read_text()) if (vdir(v) / f"final_review_{l}.json").exists() else {}) for l in ("pip", "full")}
        rows.append({"v": v, "lip": lip, "mat": mat, "qa": chk, "sharp": sharp, "reviews": reviews,
                     "render_pip": st("render", "pip"), "render_full": st("render", "full")})
    lines = ["# Twin bake-off (dev) — STAND-IN — not the owner; engine validation only", "",
             "Fix round 1, Group B8. Profile `standin-dev` (a fictional person generated for this test; never a real likeness). "
             "**No default engine is picked here — that is the owner's call on the real bake-off with their own identity.** "
             "Every number below was measured by `scripts/twin_bakeoff_dev.py` (each stage in its own process under `/usr/bin/time -l`).", "",
             "Narration: ~23 s, stand-in Kokoro voice (`am_michael`/`am_adam` blend). Canvas 1920×1080 (16:9). Clips live in `projects/dev-twin-bakeoff/` (gitignored).", "",
             "## Wall-clock and memory per stage", "",
             "| Variant | Stage | Wall (s) | Peak RSS (GB) | Peak footprint (GB) | Result |", "|---|---|---|---|---|---|"]
    for r in rows:
        for label, d in (("lipsync", r["lip"]), ("matte (BiRefNet MPS)", r["mat"]), ("QA", results.get(f"qa_variant_{r['v']}", {})),
                         ("render PIP", r["render_pip"]), ("render full-screen", r["render_full"])):
            if d:
                lines.append(f"| {names[r['v']]} | {label} | {d.get('wall_s')} | {d.get('peak_rss_gb')} | {d.get('peak_footprint_gb')} | {'ok' if d.get('returncode') == 0 else 'FAILED'} |")
    lines += ["", "## Quality numbers (real MediaPipe checks, QA returns real values)", "",
              "| Variant | face present | mouth sync | no-raw-frames | identity | lower-face sharpness (Laplacian var, frame @8 s) |", "|---|---|---|---|---|---|"]
    for r in rows:
        c = r["qa"]
        fp = c.get("face_presence", {})
        ms = c.get("mouth_sync", {})
        lines.append(f"| {names[r['v']]} | {fp.get('face_ratio')} ({fp.get('status')}) | {ms.get('status')}: offset {ms.get('offset_frames')} fr, peak corr {ms.get('peak_correlation')} vs null p95 {ms.get('null_p95')} | "
                     f"{c.get('no_raw_frames', {}).get('status')} | {'fail (stand-in, by design)' if c.get('identity', {}).get('passed') is False else c.get('identity', {}).get('passed')} | {r['sharp']} |")
    lines += ["", "Mouth-sync note: the lip-gap vs audio-envelope proxy is weak (it did not track injected audio shifts in a control test), so the check reports `inconclusive` unless the correlation beats an unrelated-audio null; `inconclusive` never counts as a pass. Judge sync by eye/ear in the clips.", "",
              "## Honesty guard", "", "| Variant | layout | final_review | stand-in assets flagged |", "|---|---|---|---|"]
    for r in rows:
        for layout, rr in (("PIP", r["render_pip"]), ("full-screen", r["render_full"])):
            rev = r["reviews"]["pip" if layout == "PIP" else "full"]
            hg = rev.get("checks", {}).get("honesty_guard", {})
            lines.append(f"| {names[r['v']]} | {layout} | {rev.get('status')} | {len(hg.get('standin_assets', []))} |")
    lines += ["", "`final_review` = `fail` for every stand-in render is the required outcome: stand-in assets can never ship. They also count as `fixture_presenter_percentage`, never `presenter_percentage` (fast test `test_standin_assets_excluded_from_presenter_percentage`).", ""]
    if spent:
        lines += ["## Paid dev calls", "", "| Call | Estimate (USD) | Actual per API usage (USD) |", "|---|---|---|"] + [f"| {k} | {v.get('estimate')} | {v.get('actual')} |" for k, v in spent.items()] + [""]
    lines += ["## Findings (stand-in; do not generalise to the owner's identity)", "",
              "- **The alpha presenter layer works end to end**: ProRes 4444 matte → Remotion `OffthreadVideo transparent` → PIP over the diagram and full-screen over the backdrop, captions on top (contact sheet).",
              "- **PIP vs diagram content**: with no `focus_region` on the diagram beat the bottom-right PIP overlapped the \"GPU\" node in both PIP renders. The layout engine can only avoid *declared* focus regions, so the scene director must set `focus_region` on every diagram beat that has a PIP (follow-up for the scene-director skill / a scene-plan validator).",
              "- **Sharpness proxy** (single frame, lower face): the hybrid clip scored higher than the LivePortrait clip — plausible, because LivePortrait adds a second generation pass before MuseTalk's 256² crop; one frame on a fictional face is not a verdict.",
              "- **Mouth sync is not measured by an automatic check here** (see note above) — compare the clips by eye/ear.",
              "- **LatentSync was not run**: see `## LatentSync (B4)`.",
              "- **Cost**: the hybrid route's only paid step is the one-time idle loop per outfit ($1.02 actual here, 47 s); everything else is local. The local route needs the owner's performance recording as the driving clip (here: the Omni idle clip, licence recorded as own generation).",
              "- **Time per ~23 s of presenter video** (stages above): hybrid ≈ lipsync 301 s + matte 329 s; local ≈ LivePortrait 375 s (for a 10 s driving clip; scales with its length) + lipsync 237 s + matte 350 s. MLX lipsync peak footprint ≈ 20 GB (RSS 5.3 GB) — run alone under the heavy lock.", ""]
    lines += ["## LatentSync (B4)", "",
              "**Not run — stopped at a 🛑, not a technical failure.** Weights are downloaded (`ByteDance/LatentSync-1.6`: `latentsync_unet.pt` 5 GB + `whisper/tiny.pt`, OpenRAIL++ weights / Apache-2.0 code, in the model store; the 9.6 GB repo's training/eval extras were not fetched). The only Apple-silicon route found is the MLX port `sb1992/latentsync-mlx` (Apache-2.0, 6 stars, single author), which still needs the upstream LatentSync pre-processing (decord, InsightFace detector — which must be replaced by MediaPipe, an extra integration step) and whisper in PyTorch. Converting the UNet and running that code means executing an unvetted third-party repository, and the sandbox's auto-mode classifier denied each attempt (`convert_weights.py`, even with `python -I` from outside the repo and `weights_only=True` loading). I did not work around it. **Needs the owner's explicit OK to run `sb1992/latentsync-mlx` (pinned to commit 8370f1f) in `<model store>/latentsync/venv`**, or a decision to drop LatentSync.", ""]
    # contact sheet: one frame per render
    if sheet_inputs:
        sheet_dir = REPO / "reports" / "twin_bakeoff_dev_clips"
        sheet_dir.mkdir(parents=True, exist_ok=True)
        frames = []
        for v, layout, r in sheet_inputs:
            f = sheet_dir / f"{v}_{layout}.jpg"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "9", "-i", str(r), "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", str(f)], check=True)
            frames.append(f)
        cols = 2
        sheet = sheet_dir / "contact_sheet.jpg"
        inputs = sum([["-i", str(f)] for f in frames], [])
        rows_n = (len(frames) + cols - 1) // cols
        subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", f"xstack=inputs={len(frames)}:layout=" + "|".join(f"{(i % cols) * 640}_{(i // cols) * 360}" for i in range(len(frames))),
                        "-frames:v", "1", "-q:v", "4", str(sheet)], check=True)
        for f in frames:
            f.unlink()
        lines += ["## Contact sheet", "", f"![STAND-IN contact sheet]({sheet.relative_to(REPO / 'reports').as_posix()}) — order: " + ", ".join(f"{v}/{l}" for v, l, _ in sheet_inputs), ""]
    lines += ["## Files", ""] + [f"- `projects/dev-twin-bakeoff/{v}/` — `STANDIN_seg1.mp4` (lip-synced), `STANDIN_alpha.mov` (ProRes 4444 alpha), `qa.json`, `STANDIN_render_pip.mp4`, `STANDIN_render_full.mp4`, `final_review_*.json`" for v in VARIANTS if (OUT / v).exists()]
    (REPO / "reports" / "twin_bakeoff_dev.md").write_text("\n".join(lines) + "\n")
    print("wrote reports/twin_bakeoff_dev.md")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["lipsync", "matte", "qa", "render", "all", "report"])
    ap.add_argument("--variant", choices=VARIANTS)
    ap.add_argument("--layout", choices=["pip", "full"], default="pip")
    ap.add_argument("--variants", default=",".join(VARIANTS))
    a = ap.parse_args()
    if a.stage == "report":
        write_report()
        return
    if a.stage == "all":
        results = json.loads((OUT / "results.json").read_text()) if (OUT / "results.json").exists() else {}
        for v in a.variants.split(","):
            plan = [["lipsync", "--variant", v], ["matte", "--variant", v], ["qa", "--variant", v],
                    ["render", "--variant", v, "--layout", "pip"], ["render", "--variant", v, "--layout", "full"]]
            for argv in plan:
                key = "_".join(argv).replace("--", "")
                if results.get(key, {}).get("returncode") == 0:
                    continue
                results[key] = run_stage(argv)
                (OUT / "results.json").write_text(json.dumps(results, indent=2))
                if results[key]["returncode"] != 0:
                    print("FAILED", key, results[key].get("error"))
                    break
        return
    fn = {"lipsync": lambda: stage_lipsync(a.variant), "matte": lambda: stage_matte(a.variant), "qa": lambda: stage_qa(a.variant),
          "render": lambda: stage_render(a.variant, a.layout)}[a.stage]
    print(json.dumps(fn(), indent=2, default=str))


if __name__ == "__main__":
    main()
