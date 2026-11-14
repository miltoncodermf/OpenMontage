"""topic-tutorial v3 smoke test (spec §7). Opt-in: `.venv/bin/pytest -m smoke tests/contracts/test_topic_tutorial_smoke.py -q`.

Local only, no paid APIs, ~1 minute: Kokoro narration (2 sentences) → script-anchored alignment → loudness
mastering → real Remotion render (1280×720, diagram beat + a TEST_ONLY presenter layer) → ffprobe /
loudness / caption checks → final_review must FAIL because of the TEST_ONLY asset (honesty guard), while a
variant without it passes. Skips cleanly (never fails) when Kokoro / Remotion / ffmpeg are unavailable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "topic_tutorial" / "TEST_ONLY_presenter_fixture.mp4"
TEXT = ("Unified memory lets the GPU and the CPU share one pool of fast memory on Apple Silicon. "
        "That is why local models run quickly without copying data back and forth between chips.")
CANVAS = {"width": 1280, "height": 720}


def _need(cond: bool, why: str) -> None:
    if not cond:
        pytest.skip(why)


@pytest.fixture(scope="module")
def narration(tmp_path_factory, request):
    mp = pytest.MonkeyPatch()
    mp.setenv("HF_HUB_OFFLINE", "1")  # tests block the network; the Kokoro/whisper models must already be cached
    request.addfinalizer(mp.undo)
    _need(shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None, "ffmpeg/ffprobe not installed")
    _need(shutil.which("npx") is not None and (REPO / "remotion-composer" / "node_modules").is_dir(), "Remotion (npx + remotion-composer/node_modules) not available")
    from tools.audio.mlx_tts_provider import MlxTTSProvider

    work = tmp_path_factory.mktemp("smoke")
    res = MlxTTSProvider().execute({"text": TEXT, "output_path": str(work / "n.wav"), "allow_fallback": False})
    _need(res.success, f"Kokoro narration unavailable: {res.error}")
    return work, res.data


def _compile(narr, with_presenter: bool):
    from tools.audio.script_aligner import ScriptAligner
    from tools.video.scene_plan_adapter import ScenePlanAdapter

    work, data = narr
    dur = data["duration_s"]
    al = ScriptAligner().execute({"audio_path": str(work / "n.wav"), "text": TEXT})
    assert al.success, al.error
    plan = {"version": "2.0", "sections": [{"section_id": "a", "script_section_id": "s1", "learning_objective": "Unified memory", "visual_beats": [
        {"beat_id": "b1", "visual_type": "diagram", "duration_hint_seconds": dur, "layout": {"preset": "diagram", "presenter_pip": with_presenter},
         "diagram_spec": {"title": "Unified memory", "nodes": ["CPU", "Shared pool", "GPU"], "edges": [["CPU", "Shared pool"], ["Shared pool", "GPU"]]}}]}]}
    assets = {"assets": []}
    if with_presenter:
        # claims to be a beautified twin, but the path is a TEST_ONLY fixture -> must never count as real
        assets["assets"].append({"asset_id": "p", "asset_type": "presenter_video", "path": str(FIXTURE),
                                 "identity_transform": "beautified", "profile_id": "smoke"})
    compiled = ScenePlanAdapter().compile(plan, assets, [{"scene_id": "s1", "duration_s": dur, "timestamps": al.data["timestamps"]}],
                                          {"s1": dur}, canvas=CANVAS)
    return compiled, assets, al.data


def _render(narr, compiled, name: str) -> Path:
    from lib import loudness
    from tools.video.video_compose import VideoCompose

    work, data = narr
    mastered = work / "n_mastered.wav"
    if not mastered.exists():
        loudness.master_two_pass(work / "n.wav", mastered)
    ed = {**compiled["edit_decisions"], "cuts": compiled["cuts"], "captions": compiled["captions"], "canvas": compiled["canvas"],
          "audio": {"narration": {"src": str(mastered)}}, "total_duration_seconds": data["duration_s"]}
    out = work / f"{name}.mp4"
    res = VideoCompose()._remotion_render({"edit_decisions": ed, "output_path": str(out)})
    _need(res.success or "Chrome" not in (res.error or ""), f"Remotion cannot render here: {(res.error or '')[-300:]}")
    assert res.success, res.error
    compiled["_ed"] = ed
    return out


def test_smoke_pipeline_and_honesty_guard(narration, monkeypatch):
    from lib import loudness
    from tools.video.video_compose import VideoCompose

    monkeypatch.delenv("OPENMONTAGE_TEST_MODE", raising=False)
    work, data = narration
    audio_dur = data["duration_s"]
    assert 7.0 < audio_dur < 16.0, f"narration should be ~10 s, got {audio_dur}"

    # ---- variant WITH the TEST_ONLY presenter layer ----
    compiled, assets, align = _compile(narration, with_presenter=True)
    # alignment: method is stated, timestamps monotonic and inside the audio
    assert align["alignment_method"] in {"asr_anchored", "heuristic"}
    prev = 0.0
    for w in compiled["captions"]:
        assert w["startMs"] >= prev - 1 and w["endMs"] > w["startMs"] and w["endMs"] <= audio_dur * 1000 + 60, w
        prev = w["startMs"]
    # the fixture is not a real presenter in any metric
    va = compiled["visual_analytics"]
    assert va["presenter_percentage"] == 0.0 and va["fixture_presenter_percentage"] > 0.0
    video = _render(narration, compiled, "with_fixture")

    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(video)],
                                      capture_output=True, text=True, check=True).stdout)
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert next(s for s in probe["streams"] if s["codec_type"] == "audio")
    assert (v["width"], v["height"]) == (1280, 720) and v["r_frame_rate"] == "30/1"
    assert abs(float(probe["format"]["duration"]) - (audio_dur + 1.0)) < 0.6  # narration + 1 s tail padding
    m = loudness.measure(video)
    assert abs(m["integrated_lufs"] - -14.0) <= 1.5 and m["true_peak_dbtp"] <= -0.5, m  # mastered narration through the render

    vc = VideoCompose()
    bad = vc._run_final_review(video, compiled["_ed"], asset_manifest=assets)
    assert bad["status"] == "fail" and bad["checks"]["honesty_guard"]["blocking"] is True
    assert any("TEST_ONLY_" in a for a in bad["checks"]["honesty_guard"]["test_only_assets"])

    # ---- variant WITHOUT it (diagram only) ----
    compiled2, assets2, _ = _compile(narration, with_presenter=False)
    video2 = _render(narration, compiled2, "no_fixture")
    good = vc._run_final_review(video2, compiled2["_ed"], asset_manifest=assets2)
    assert good["checks"]["honesty_guard"]["test_only_assets"] == []
    assert good["status"] == "pass", good["issues_found"]
