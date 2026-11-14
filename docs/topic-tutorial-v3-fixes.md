# `topic-tutorial` v3 — Audit Findings & Fix Instructions

**Audience:** Claude Sonnet 5.5 (implementer), continuing on branch `feat/topic-tutorial-v3`.
**Author:** Claude Opus 5.5, audit of commits `4197a86..7cef90c` against `docs/topic-tutorial-v3-handoff.md` (2026-11-13).
**Scope:** everything left undone or deviating from the spec **except the steps that need the owner's
recordings** (face turn, talking performance, voice read → identity pick → voice pick → real bake-off).
Those are listed in §4 and stay blocked.

The handoff spec remains the source of truth. This document adds fix tasks; where it amends the spec
it says so explicitly (§5). Same working rules as the spec §0: commit per fix group as
`fix(topic-tutorial-v3): <group> — <summary>`, append results to `reports/topic_tutorial_v3_progress.md`
under a new heading `## Fix round 1`, never push, stop at every 🛑.

---

## 1. What I verified (so you don't redo it)

- Branch has 10 commits P0–P8, clean tree. Progress report is detailed and mostly honest.
- Fast tests: `.venv/bin/pytest tests/contracts -q -k topic_tutorial` → **112 passed, 1 skipped** (12.6 s). ✅
- Smoke test: **flaky** — I ran it 4 times: **1 failed** (first, cold run), 3 passed (~55 s each). The failure output was not captured. See F5.
- Sandbox image `openmontage-capture:1` exists in Apple `container` 1.7.1; capture evidence in the report is plausible.
- Installed in `.venv`: `faster_whisper` only. **Not installed:** `mediapipe`, `rembg`, `chatterbox`, `mlx_audio`, `whisperx`, MuseTalk/LatentSync/LivePortrait code or weights.
- `tests/tools/test_gemini_omni_video.py`: **25 failed / 8 passed**. Sonnet reported these as "pre-existing on main" — true, but they were **caused by our own earlier commit `b4d5baf`**, which modified the stock tool (default model switched to `gemini-omni-1.2-flash` via env, new `GEMINI_VIDEO_ENABLED` gate). See F6.

---

## 2. Findings (ordered by priority)

| ID | Severity | Finding | Spec ref |
|---|---|---|---|
| F1 | High | Twin engines are adapters that fail loudly: MuseTalk-MLX, LatentSync, LivePortrait have no working inference, no face crop/paste-back. `lib/twin_backends.py` checks for a Python package `musetalk_mlx` that may not exist — the HF repo `mlx-community/MuseTalk-1.5-fp16` holds weights; the inference code must be identified. | §5.5, P5/P6 |
| F2 | High | No twin clip has ever been produced, so none of the twin plumbing (idle loop → lip-sync → matte → QA → Remotion alpha layer) is validated end to end. | §5.5, P5 |
| F3 | High | Chatterbox not installed; the speaker-embedding interpolation the voice plan depends on is unverified. 4 of 8 voice candidates are "unavailable". | §5.6, D9 |
| F4 | High | Presenter QA face/mouth checks and the matte cannot run: `mediapipe` and `rembg`/BiRefNet are missing, so QA reports `not_run` and `presenter_matte` has no real segmenter. | §5.5 steps 4–5 |
| F5 | High | Smoke test is flaky (1 of 4 runs failed). | §7 |
| F6 | Medium | Stock tool `tools/video/gemini_omni_video.py` was changed by our branch history and breaks 25 stock tests. Topic-tutorial guards belong in our own tools, not in a stock tool. | AGENT_GUIDE "thin extension" |
| F7 | Medium | Diagram legibility validator (`lib/diagram_legibility.py`) is **not wired into compose QA** — `video_compose._run_final_review` has no legibility check. Spec requires enforcement at compose QA. | §5.9 |
| F8 | Medium | `lib/heavy_lock.py` is used only by `sandbox_capture` and `twin_lipsync`. Remotion renders (`video_compose`), LatentSync and LivePortrait do not take the lock, so a capture can overlap a render. | §5.7, §9 |
| F9 | Medium | Playbook `verified` flag (D20) exists only as prose in `proposal-director.md`; no flag in `styles/topic-tutorial/*.yaml` and no sidecar. | §5.10 |
| F10 | Medium | Research stage `tools_available` lacks `sandbox_capture` (URL screenshots) and image/stock search tools; it still lists `video_downloader`, which conflicts with "no third-party video clips" unless restricted to reference analysis. Deep research and media sourcing have never been exercised. | §5.3, §5.4 |
| F11 | Medium | No real pipeline run exists. A **no-presenter validation run** (D2 path) can be done now without recordings and would exercise research, captures, diagrams, alignment, R128 and publish. | P9 |
| F12 | Low | `faster-whisper` was `pip install`ed ad hoc (not in requirements); PyAV workaround in `transcriber.py` undocumented in requirements. | §5.8 |
| F13 | Low | No Gemini image price entry — proposals cannot itemize identity/wardrobe calls. | D18 |
| F14 | Low | Recording session prep is ad hoc: the "phonetically rich script the agent provides" doesn't exist as a file; no one-page owner guide. Prepare it now so the recording session is smooth. | §5.5 step 1 |
| F15 | Low | Owner-login (noVNC) capture flow never exercised. | D15 |

---

## 3. Fix instructions

### Group A — Hygiene (F6, F7, F8, F9, F12, F13). No owner input needed.

**F6 — restore the stock Gemini Omni tool.**
1. `git diff fecb9a1 HEAD -- tools/video/gemini_omni_video.py` to see our changes.
2. Restore the upstream contract so `tests/tools/test_gemini_omni_video.py` passes unmodified. Move the opt-in/budget guard into our layer: `tools/presenters/twin_idle_loop.py` + `lib/paid_call_guard.py` already gate paid calls — make sure they are the only gate topic-tutorial relies on.
3. If `gemini-omni-1.2-flash` is genuinely needed (the key lists it), support it through the tool's normal model parameter in an upstream-compatible way (extend the enum, keep 1.1 default) and update only the assertions that test the enum. Do not change stock defaults via env vars.
4. ✅ `.venv/bin/pytest tests/ -q` fully green, **no exclusions**.

**F7 — wire diagram legibility into compose QA.** In `VideoCompose._run_final_review` add `checks.diagram_legibility` computed from the composition props' diagram cuts via `lib/diagram_legibility.py` at the actual canvas size; any violation → `status: "revise"` with the problem list. Update `final_review.schema.json`. Fast test: a props file with 20 px labels at 1080p → revise; compliant → pass.

**F8 — heavy lock everywhere heavy.** Take `heavy_lock` around the Remotion render path in `video_compose` (and HyperFrames), LatentSync and LivePortrait execution, and MLX TTS batch synthesis if > 30 s. Make the lock re-entrant per process or scoped so nested calls don't deadlock. Fast test: two concurrent acquisitions serialize (mocked work).

**F9 — playbook verified flag.** Check `schemas/styles/playbook.schema.json`; if `verified` is not allowed, create `styles/topic-tutorial/verification.yaml` (`software-technical: false` until P9, others `false`). Expose a loader (`lib/playbook_verification.py`), make the proposal skill read it, add a fast test that every topic-tutorial playbook has an entry. Set `software-technical: true` only after the owner approves the F11 run's compose gate.

**F12 — dependencies.** Add the local-only optional deps actually used to the repo's requirements mechanism (find how optional deps are declared — e.g. a `requirements-*.txt` or extras; follow the existing convention): `faster-whisper`, plus those installed in Groups B/C. Document the PyAV pre-decode workaround in a comment next to the dependency. Record `alignment_method = asr_anchored` as the documented default (see §5 amendment).

**F13 — Gemini image pricing.** Add Gemini image model prices to `tools/provider_pricing.py` (or the repo's pricing table) with source URL + `as_of` date, looked up from Google's official pricing page at implementation time. `twin_identity.estimate_cost` must return a number. Fast test: estimate for 6 beautify calls > 0.

### Group B — Local engine integration with a STAND-IN presenter (F1, F2, F3, F4)

The owner's recordings are not available. Validate all plumbing with a **clearly labeled stand-in**
so the real bake-off later is just "swap the profile".

**B0 — 🛑 one combined ask to the owner before starting Group B.** Present one table and wait for OK:
- Model downloads (each ≥ 500 MB needs approval): MuseTalk 1.5 (MLX or PyTorch) weights + its dependency models (VAE, whisper-tiny, face parsing), LatentSync 1.5/1.6, LivePortrait, Chatterbox, BiRefNet. For each: size, license (verify upstream LICENSE files — commercial-OK only; **no InsightFace weights**), destination path, free disk before/after (`df -h` for internal and external volumes). Weights go under the existing cache env vars (external SSD if `OPENMONTAGE_STORAGE_ROOT` is set); only presenter profiles live on the internal drive.
- Paid dev calls (Gemini API, billing is on): 1 stand-in portrait (image model) + 1–2 Omni idle loops (8–10 s). Give the per-call estimate from F13 and `gemini_omni_video.estimate_cost`; propose a **dev cap of $3**.

**B1 — Stand-in profile.** Create a dev-only profile `standin-dev` via `lib/presenter_profile.py` with `profile.json` field `standin: true` (add to schema). Identity: one Gemini-generated **fictional** adult presenter portrait (photoreal, head-and-shoulders, studio background, neutral, mouth closed; prompt must say "fictional person, not resembling any real individual"). Voice reference: a Kokoro-rendered 30 s clip. Never use a real person's likeness or voice for the stand-in.
- **Guard change:** `lib/honesty_guard.py` / `lib/presenter_guard.py` must treat any asset from a `standin: true` profile like `TEST_ONLY_` — `final_review` = `fail` outside test mode, and it never counts toward `presenter_percentage`. Fast test for this.

**B2 — Dependencies.** Install `mediapipe` and `rembg` (with a BiRefNet model; if rembg can't load BiRefNet, call BiRefNet directly — MIT). Wire the real face detector + mouth landmarks into `lib/presenter_qa.py` and the real segmenter into `presenter_matte`. QA checks must now return real values, not `not_run`.

**B3 — MuseTalk.** Find the actual inference implementation for MuseTalk 1.5 on Apple Silicon:
1. Look for MLX inference code that pairs with `mlx-community/MuseTalk-1.5-fp16` (HF model card / linked repo). If it exists and works, use it.
2. Otherwise use the official MuseTalk 1.5 PyTorch code on MPS (CPU fallback for unsupported ops), replacing any InsightFace/mmpose face pipeline with MediaPipe for detection, crop, and paste-back.
3. Implement in `lib/twin_backends.py` + `tools/presenters/twin_lipsync.py`: face crop → lip-sync → paste-back with feathered blend → output at source resolution; per-segment resumability already exists — keep it.
4. Update `musetalk_mlx_available()` to check what you actually use.

**B4 — LatentSync (full-screen variant).** Integrate LatentSync 1.5/1.6 (Apache-2.0) on MPS via a maintained fork or the official code with MPS patches. Must run unattended (overnight-safe), under `heavy_lock`. If it cannot run on this Mac after a time-boxed attempt (~half a day), stop, record findings in `reports/twin_bakeoff_dev.md`, and 🛑 tell the owner rather than switching engines.

**B5 — LivePortrait (path i).** Integrate LivePortrait (MIT code) with MediaPipe in place of InsightFace. Driving video for the stand-in test: the Omni idle loop from B6 or another clip with a commercial-OK license (record its license). Same time-box and 🛑 rule as B4.

**B6 — Idle loop (path ii).** With the B0 approval, call `twin_idle_loop` → `gemini_omni_video` on the stand-in portrait for one 8–10 s idle clip. Run the seam check; if no native loop, ping-pong. Record actual cost from the API response/usage metadata against the estimate.

**B7 — Chatterbox (F3).** Install `chatterbox-mlx` (or the official `chatterbox` on MPS). Verify whether the speaker-conditioning embedding can be extracted and interpolated. Build the 4 Chatterbox candidates on the stand-in voice (stand-in Kokoro clip blended with 2 donor Kokoro voices) and regenerate the candidate page. If interpolation is not possible, write down exactly what the API exposes and 🛑 present alternatives (e.g. Qwen3-TTS base cloning via `mlx-audio`) — do not switch silently.

**B8 — Dev bake-off on the stand-in.** Same 20 s narration (stand-in Kokoro voice) produced as:
(ii) idle loop + MuseTalk — PIP and full-screen; (i) LivePortrait + MuseTalk — PIP and full-screen;
LatentSync full-screen variant. Each through matte → QA → a short Remotion render using the real
alpha presenter layer over a diagram beat (16:9). Record wall-clock, peak memory (`/usr/bin/time -l`),
QA numbers, cost. Write `reports/twin_bakeoff_dev.md` with file paths and a contact sheet, headed
**"STAND-IN — not the owner; engine validation only"**. Do not pick a default engine — that is the owner's
call on the real bake-off.

✅ Group B done when: every twin tool runs for real on the stand-in; QA returns real values; the
Remotion alpha layer renders; `final_review` correctly fails any video containing stand-in assets;
fast tests green.

### Group C — Smoke flakiness (F5)

Run `.venv/bin/pytest -m smoke tests/contracts/test_topic_tutorial_smoke.py --tb=long` **5 times**,
including at least one cold run (fresh shell; clear any Remotion bundle cache the test reuses and the
Kokoro model cache in-process). Capture every failure to a log, find the root cause (timeouts, cold
model load, Remotion bundling, port/lock contention, loudness tolerance), and fix it in the code or the
test — not by loosening assertions that guard real behavior. ✅ 5/5 passes, logs summarized in the
progress report.

### Group D — Research & capture readiness (F10, F14, F15)

**F10.**
- Add `sandbox_capture` to the research stage (URL screenshots), and add the registry's image/stock search tools to research and assets (discover by capability; don't hardcode names that don't exist).
- Keep `video_downloader`/`transcript_fetcher` only for **reference-video analysis**; add a hard rule in `research-director.md` and a check in `lib/research_contract.py` that no `sourced_clip` may originate from `video_downloader`.
- Dry-run the research protocol on a **topic-only** input (e.g. "How Apple Silicon unified memory speeds up local AI inference") through the deep-research pattern (deep planner, standard workers): produce a schema-valid `research_brief` + `fact_sheet` that passes `brief_problems() == []`, with ≥ 3 media candidates carrying rights fields, and one sandbox screenshot of an allowed public page. Save under `projects/dev-research-dryrun/` (gitignored). Note the run in the progress report.

**F14 — recording session prep.**
- Write an **original** ~450-word reading script at `config/presenter-onboarding/voice_read_script.md` (≈3 min): pangram-style sentences, numbers, dates, code identifiers (`pytest`, `JSON`, `async`), acronyms, questions, an excited sentence, a calm explanatory paragraph. No copyrighted text.
- Write a one-page owner guide `docs/presenter-onboarding-recording-guide.md`: equipment, light, framing, background, the three takes with durations, file formats, where to drop the files, and what the validator checks. Point `capture-session-director.md` to both files.
- Expand the 6 onboarding skills with failure handling (validator failure → re-record request; Gemini identity drift → regenerate within budget; voice candidates rejected → second round with new ratios).

**F15 — owner login flow.** Leave for the F11 run: only exercise `await_owner_login` if a planned capture actually needs an account; otherwise mark "not run" in the progress report.

### Group E — No-presenter validation run (F11) — owner at gates, no recordings

After Groups A–D:
1. 🛑 Ask the owner for an input (suggest: this repo `/Users/nathan/workspace/OpenMontage` with focus on `pipeline_defs/topic-tutorial.yaml` + `skills/pipelines/topic-tutorial/`, plus one public docs URL; or a topic-only prompt).
2. Run `topic-tutorial` **as an agent per AGENT_GUIDE Rule Zero** — init project, open Backlot, stage by stage via director skills, model routing via sub-agents, presenter policy `none` (D2 path, logged as `presenter_status: skipped_unavailable` with reason "presenter profile not yet created"), gates at proposal / scene_plan / assets / compose (end your turn at each).
3. The video must include at least: one real sandbox capture (code running), one browser capture of a public page, ≥ 2 diagrams passing legibility, one sourced image with rights, aligned captions, R128 master, publish bundle with attributions.
4. Fix defects found; re-run only affected stages.
5. ✅ Owner approves at compose; `final_review` passes honestly; then set `software-technical: true` (F9).

This run does **not** replace P9 — P9 (with the twin) happens after the recording session.

---

## 4. Still blocked on the owner's recordings (do not attempt)

1. Recording session (face turn, performance, voice read) → `validate_recording` → `record_raw`.
2. Real beautify (first paid identity calls on the owner's likeness) → 🛑 identity pick → wardrobe starters.
3. Real voice lab with the owner's voice → 🛑 voice pick → lock.
4. Real twin bake-off on the owner's identity → 🛑 owner picks default engine.
5. P9 validation run with the twin presenter.

When the owner is ready, steps 1–5 reuse everything Group B validated on the stand-in.

---

## 5. Spec amendments (apply to `docs/topic-tutorial-v3-handoff.md`)

- **D22 / §5.8:** primary alignment is `asr_anchored` (faster-whisper word timings anchored to known script tokens), not whisperX forced alignment — whisperX is not part of this repo. Accepted.
- **§5.6:** voice synthesis is "reproducible to float jitter" (seeded), not byte-identical. Accepted.
- **§5.5:** add the `standin` profile concept (dev-only, always fails `final_review` outside test mode).
- **§5.10:** playbook verification lives in `styles/topic-tutorial/verification.yaml` if the playbook schema forbids extra keys.

---

## 6. Definition of done for this fix round

- Group A merged; `pytest tests/ -q` fully green with no exclusions; smoke 5/5.
- Group B: all twin tools run for real on the stand-in; `reports/twin_bakeoff_dev.md` written; stand-in assets provably cannot ship.
- Group D: research dry-run artifacts valid; recording guide + reading script ready.
- Group E: owner approved a no-presenter tutorial at the compose gate.
- Progress report updated with actual commands and outputs; nothing claimed that wasn't run.
