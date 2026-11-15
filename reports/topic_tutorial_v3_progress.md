# topic-tutorial v3 — progress report (append-only)

Source of truth: `docs/topic-tutorial-v3-handoff.md`. One section per phase. Anything not run is marked "not run".

## Phase 0 — Truth reset & cleanup

Done:
- Deleted `scripts/phase7_tutorial_pipeline_e2e.py` (hand-coded 1,240-line "8/8 E2E").
- SUPERSEDED banners on `reports/topic_tutorial_baseline_audit.md`, `topic_tutorial_implementation_report.md`, `phase1_environment_report.md`; `_superseded` key in `phase1_tool_classification.json`, `phase3_tts_benchmark.json`, `phase4_avatar_feasibility.json`, `render_manifest.json`.
- Fixtures renamed `TEST_ONLY_*` in `tests/fixtures/topic_tutorial/`.
- Honesty guard `lib/honesty_guard.py`: any asset path containing `TEST_ONLY_` or `tests/fixtures` sets `final_review.status = "fail"` (`recommended_action: replace_test_assets`) unless `OPENMONTAGE_TEST_MODE=1`. Wired into `VideoCompose._run_final_review` (all four render paths; schema updated with `checks.honesty_guard`).
- Presenter guard `lib/presenter_guard.py` (D3): only assets with `identity_transform == "beautified"` and a `profile_id`, not test-only and not raw, count as a real presenter. `ScenePlanAdapter` now reports `presenter_percentage` for real presenter assets only and `fixture_presenter_percentage` separately.
- `AssetResolver` no longer registers raw recordings as presenter; accepts only a guard-validated `presenter_asset`.
- `recorded_video` is now an onboarding-only intake (`asset_type: onboarding_source`; refuses output under `projects/`).
- Ingestor trimmed to markdown/text/code/PDF/URL (docx/pptx/xlsx/csv/media handlers removed; no requirement files referenced those deps).
- Manifest: removed `local_talking_head`, `recorded_video`, `gemini_personal_avatar_import`, `cap_recorder`, `screen_recorder` from `assets.tools_available`. (Kling was never in this manifest.)
- scene_plan `presenter_policy.preferred_source` enum now `twin_auto | twin_hybrid | twin_local | none`.

Acceptance:
- `grep -rn presenter_fixture tools lib skills pipeline_defs` → no matches.
- `.venv/bin/pytest tests/contracts/test_topic_tutorial.py -q` → 31 passed.
- `.venv/bin/pytest tests/contracts -q` → 1573 passed, 9 skipped.

## Phase 1 — Skills, routing, gates

Done:
- `config/topic-tutorial/model_routing.yaml` (deep/standard/fast tiers, per-stage routing, onboarding routes) + `lib/model_routing.py` loader/validator. Gemini CLI model names are placeholders (not verified against an installed Gemini CLI — not run).
- 11 director skills in `skills/pipelines/topic-tutorial/` rewritten as deltas on stock skills (each starts with a `**Read first:**` line pointing at existing `explainer/`, `screen-demo/` or `avatar-spokesperson/` files). `executive-producer` now defines the per-stage sub-agent protocol, presenter rule, cost rule, decision-log categories.
- Manifest: version 3.0; gates proposal/scene_plan/assets/compose = true, all other stages false; success criteria no longer claim $0.00.
- `proposal_packet.cost_estimate` gains `paid_calls[]` + `total_est_usd`; `lib/paid_call_guard.py` enforces "listed + approved + ≤ 1.2× total".

Acceptance:
- Manifest validates (`load_pipeline("topic-tutorial")` → version 3.0).
- Routing coverage test, skills-reference-existing-stock-files test, gates test, paid-call guard tests → in `tests/contracts/test_topic_tutorial.py` (40 passed).
- `.venv/bin/pytest tests/contracts -q` → 1584 passed, 9 skipped.

## Phase 2 — Inputs & research

Done:
- `inputs.yaml` contract (`schemas/artifacts/inputs.schema.json`, `lib/inputs_contract.py`): only `topic`, `repos[{path,focus}]`, `urls`, `pdfs` (any other key is rejected).
- `universal_ingestor` accepts `inputs_spec` (modes repo/url/pdf/topic); repo `focus` filter; every fact now carries `source_ref` (file+line / PDF page / URL), `retrieved_at`, `confidence`, `corroborated_by[]`, `untrusted_source: true`. Scanned PDFs → `status: unsupported` (no OCR).
- New schemas `input_manifest`, `fact_sheet`; `research_brief` gains optional `data_points[].source_ref` and `media_candidates[]` (rights fields required); `asset_manifest` gains `sourced_image|sourced_clip|sandbox_capture|presenter_matte|presenter_loop|onboarding_source` types, rights/identity fields, and **requires** `rights_status, license, source_url, attribution, retrieved_at` for `sourced_*` assets.
- `lib/research_contract.py` (source_ref on every data point; ≥1 source per script claim, ≥2 for key claims; rights on media) and `lib/attributions.py` (publish attributions list); skills updated to call them.
- Not done / not run: the live deep-research workers and Gemini Deep Research toggle are agent-protocol only (in the skill); no network research was executed. Sandbox URL screenshots depend on P3.

Acceptance:
- Fast tests (repo, PDF, URL mocked, topic-only, combined; unsupported keys; removed formats; rights fields) → `tests/contracts/test_topic_tutorial.py`: 49 passed.
- `.venv/bin/pytest tests/contracts -q` → 1593 passed, 9 skipped.

## Phase 3 — Capture sandbox

Owner step: Apple `container` 1.7.1 was already installed and verified (`/usr/local/bin/container`, `container system status` → running); no install 🛑 was needed.

Done:
- `sandbox/Dockerfile` (Ubuntu 24.04 arm64; Xvfb 1920×1080, openbox, Chromium via Playwright 1.49.1, code-server 4.96.4 pinned, ttyd, ffmpeg, python3, node; non-root `capture` user; no secrets baked in), `sandbox/entrypoint.sh` (iptables owner-match policy applied before anything runs as `capture`), `sandbox/egress_proxy.py` (allow-list HTTP/CONNECT proxy; refuses non-public IPs; logs every decision), `sandbox/runner.py` (drives Chromium in app mode over code-server / ttyd / pages; ffmpeg x11grab 1080p30 H.264 CRF 18; pauses recording during owner login so credentials are never filmed), `sandbox/README.md` (honest residual risks), `sandbox/manual_check.py`.
- `lib/sandbox/runtime.py` — `ContainerRuntime` with `AppleContainer`, `Colima`, `Docker`; detection order Apple → Colima → Docker.
- `lib/sandbox/capture_script.py` + `schemas/artifacts/capture_script.schema.json` — unknown actions fail; per-surface action rules; `navigate` host must be in `allow_domains`; IP-literal domains rejected.
- `lib/sandbox/workspace.py` — host-side copy excluding `.git`, secret filenames (`.env*`, keys, credentials, `.npmrc`…), symlinks, `node_modules`; redacts secret-looking text.
- `lib/heavy_lock.py` — host-wide lock so captures never overlap lip-sync/Remotion.
- `tools/capture/sandbox_capture.py` (`capability="screen_capture"`): operations `run`, `build_image`, `start`/`status`/`confirm_login`/`collect` (owner login via noVNC on 127.0.0.1:6080; owner confirms in chat), mounts only a workspace COPY + scratch dir, `--cpus 4 --memory 4G`, wall-clock timeout, container removed after each capture, scratch/workspace copy deleted; manifest `assets.tools_available` now lists it.
- Not covered by a run: the owner-login (noVNC) flow and Colima/Docker runtimes were not exercised. Residual risk: see `sandbox/README.md`.

Acceptance:
- Fast tests: capture-script validator, workspace prep exclusions, runtime adapter selection (mocked), heavy-lock, tool input rejection → `tests/contracts/test_topic_tutorial.py`; `.venv/bin/pytest tests/contracts -q` → 1609 passed, 9 skipped.
- Manual checks (real containers, final image, `sandbox/manual_check.py`):
  1. code-server capture of `python3 -c "print('hello')"`: success, 10.6 s, 1920×1080, 30 fps, h264; terminal output `hello` visible; clean full-frame (no browser chrome, neutral prompt).
  2. Browser capture of `https://example.com/` with `allow_domains: [example.com]`: success, 6.1 s, 1920×1080 @ 30 fps; proxy log: allowed `example.com`; Chromium background traffic to `accounts.google.com`, `www.google.com` denied.
  3. Network probe from the in-sandbox terminal (`allow_domains: [example.com]`): `https://example.com/` → `ALLOWED:200`; `https://example.org/` via proxy → `CONNECT tunnel failed, response 403`; `curl --noproxy '*' https://example.org/` → `Could not resolve host` (iptables owner-match blocks direct/DNS egress). `network.iptables == true` in the guest kernel.
  4. After runs: no capture containers left (`container ls -a` shows only the builder, since stopped); `.sandbox/` scratch deleted.

## Phase 4 — Presenter onboarding (identity + voice) — code complete; owner steps NOT done

Status: **blocked on 🛑 owner touchpoints** (recording session → identity pick → voice pick). No real profile exists yet; nothing here counts as a real presenter or voice.

Done (code, fast-tested):
- `schemas/artifacts/presenter_profile.schema.json` (locked profile requires identity + voice + hashes); `lib/presenter_profile.py` (`~/.openmontage/presenter_profiles/<id>/`, `OPENMONTAGE_PROFILE_ROOT` override, dirs mode 700 / files 600, create / lock with sha256 of every file / verify incl. permissions and tamper detection / `mint_presenter_asset` / raw-path detection).
- Guard (D3) `lib/presenter_guard.py` extended: rejects anything not `identity_transform == "beautified"` + `profile_id`, test-only paths, `source_type` owner_raw/user_supplied, and any path inside a profile's `raw/` — even if the asset claims to be beautified. `mint_presenter_asset` refuses raw paths and unlocked profiles.
- `tools/presenters/presenter_profile.py` tool (`init/status/verify/lock/validate_recording/record_raw/mint_asset/check_asset`); `lib/recording_validation.py` (ffprobe: ≥1080p, fps, duration windows, ≥44.1 kHz, noise floor ≤ −45 dBFS, no clipping).
- `tools/presenters/twin_identity.py` + `lib/twin_prompts.py`: still extraction (MediaPipe when installed — **not installed here; the tool says so and falls back to sharpness-only**), Gemini-image beautify / wardrobe / pick_canonical via `google_imagen`. Paid calls are refused unless `paid_call_approved: true` AND `ALLOW_PAID_APIS=true`. **No Gemini call has been made.** The tool cannot price Gemini image models (needs a quote) — to be itemized at the 🛑.
- `lib/voice_lab.py` + `tools/audio/voice_lab.py`: 8-candidate plan (4 Kokoro blends + 4 Chatterbox blends), fixed polish chain, local candidate page (`voice/candidates/index.html`), `lock_voice` → `voice_profile.json`; `mlx_tts` accepts `voice_profile` (seeded Kokoro synthesis + polish; refuses non-Kokoro engines, no silent fallback).
- `pipeline_defs/presenter-onboarding.yaml` + 6 skills in `skills/pipelines/presenter-onboarding/` (capture_session 🛑, identity_build, identity_lock 🛑, voice_lab, voice_lock 🛑). `test_runtime_presentation_contract.py` excludes it (no compose stage).

Verified with real runs: Kokoro blend synthesis works (4 candidates built in ~6–8 s, polish chain applied); two syntheses of the same text from a locked profile differ by max abs 9e-5 (seeded; **not byte-identical** — spec said "deterministic", corrected to "reproducible to float jitter" in the profile note and skills).

Not verified / not run:
- **Chatterbox:** `chatterbox` package is not installed; the four Chatterbox candidates are listed as `unavailable` on the page, and the embedding-interpolation API was **not** verified. Per spec the owner must be told before any engine switch; weights would be a ≥ 500 MB download needing OK.
- Face detection (MediaPipe) not installed; stills extraction exercised only on a synthetic clip.
- Real beautify / wardrobe (Gemini): not run (🛑 first paid call).
- Owner recording validation tested on synthetic clips only.

Acceptance (fast): guard rejects a raw recording passed as presenter (tiny generated clip), profile lock/verify/tamper, recording validation, voice recipes/page/profile, paid-call refusal, mocked Gemini flow → `tests/contracts/test_topic_tutorial.py` 77 passed; `tests/contracts` all green.
Pending 🛑: owner recording session → identity pick → voice pick; first paid Gemini image call.

## Phase 5 — Twin bake-off — tooling only; bake-off NOT RUN (blocked on 🛑)

See `reports/twin_bakeoff.md` (status NOT RUN, with the blocker table and protocol). No clip was produced, no Gemini call made, no weights downloaded.

Done (code, fast-tested): `twin_idle_loop` (plan / guarded generate / Flow import / seam check / motion source), `twin_lipsync` (looping + ping-pong, resumable per-segment outputs, raw-source refusal; MuseTalk-MLX and LatentSync adapters that fail loudly — pre/post-processing not integrated), `twin_performance_transfer` (LivePortrait; contract and honest status only), `presenter_matte` (ProRes 4444 alpha via injectable segmenter; real BiRefNet unavailable — `rembg` not installed), `lib/twin_media.py`, `lib/twin_backends.py`, `lib/bakeoff.py`. The tools are listed in the manifest's assets stage.

Acceptance (fast): loop seam check, loop/ping-pong durations, resumable segments, raw-source refusal, alpha output, paid-call guard → `tests/contracts/test_topic_tutorial.py` 87 passed; `tests/contracts` 1644 passed, 9 skipped.
Pending 🛑: first paid idle-loop call (and Flow fallback if the API fails), model downloads ≥ 500 MB, owner's default-engine pick.

## Phase 6 — Productionize twin + assets stage (code complete; no real twin run)

Done:
- **Alignment (D22):** `lib/script_alignment.py` + tool `script_aligner`: faster-whisper word times (through `transcriber`) anchored onto the known script tokens (numbers/punctuation map back via the gap between neighbouring anchors); falls back to the energy heuristic with `alignment_method: heuristic` + `fallback_reason`. **Deviation from spec, stated plainly:** whisperX is not installed in this repo (the "existing transcriber" is faster-whisper), so the primary method is named `asr_anchored`, not `forced`; manifest enum is `forced | asr_anchored | heuristic`. Log it as an `alignment_method` decision.
- `tools/analysis/transcriber.py`: pre-decodes audio with ffmpeg because faster-whisper 1.2.1 needs a newer PyAV than this venv has (`open() got an unexpected keyword argument 'metadata_errors'`). I `pip install`ed `faster-whisper` into `.venv` (small; models were already in the HF cache; not added to requirements files).
- **Scene cache hash** (`lib/scene_cache.py`): now includes sha256 of every referenced input asset, renderer version (hash of `remotion-composer/src` + package version), TTS model, voice-profile hash, aspect (`collect_input_hashes`, `renderer_version`). Backward compatible defaults.
- **Presenter QA** (`lib/presenter_qa.py`): face-presence ≥ 98 %, mouth–audio offset ±2 frames (cross-correlation), no frame identical to `raw/` (16×16 dHash, distance ≤ 6/256), identity guard. Providers for face detection / mouth landmarks are injectable; with none installed (MediaPipe missing) those checks report `not_run`, and `not_run` never counts as a pass (`verdict: incomplete`).
- **No-presenter fallback** (`lib/presenter_fallback.py`): presenter beats re-planned to diagram beats, policy disabled, `presenter_status: skipped_failed` + reason; result is schema-valid and compiles with 0 % presenter.
- Resumable segments: `twin_lipsync` writes per-segment outputs + `progress.json` keyed by (motion hash, audio hash, backend); the asset skill tells the agent to refresh checkpoint `partial_progress` per unit.
- Skills updated (`asset-director`).

Real run evidence: Kokoro narration (10 s) → `script_aligner` with faster-whisper `base` on CPU: `asr_anchored`, 91.3 % of 23 script tokens matched, 1.2 s.

Not run: any real twin segment, real face/mouth QA (no MediaPipe), real overnight resume with a backend.

Acceptance (fast): alignment (numbers/punctuation, fallback flags), cache invalidation per field, QA math + raw-frame detection + not_run semantics, fallback re-plan, aligner tool → `tests/contracts/test_topic_tutorial.py` 99 passed; `tests/contracts` all green.

## Phase 7 — Edit/compose, legibility, aspect seam (code complete; no real render yet)

Done:
- **Normalized layout + aspect seam (§5.9):** `remotion-composer/src/layouts/{types,landscape,portrait,index,diagramMetrics}.ts` (16:9 implemented; `portrait.ts` is the deliberately trivial 9:16 slot) and a Python mirror `lib/layout.py`. `Root.tsx` `calculateMetadata` reads `props.canvas` for width/height. `PresenterPip` / `PresenterScreenSplit` / `PresenterFullScreen` now take their rectangles from the layout and support `alpha` (OffthreadVideo `transparent`, backdrop → presenter → captions layer stack); `DiagramScene` rewritten on the layout grid with legibility metrics. `tsc --noEmit` passes.
- **Scene plan / adapter:** `focus_region` (normalized, validated) on beats; new beat types `sandbox_capture`, `sourced_image`, `sourced_clip` (adapter requires matching assets); `compile(..., canvas=)` → `canvas`, per-cut `layoutPx`, `focusRegion`, `presenterAlpha` (matte preferred), PIP corner chosen so it never covers the focus region; oversized diagrams (> 7 nodes) split into progressive-reveal beats; `visual_analytics.legibility_problems`.
- **Diagram legibility validator** `lib/diagram_legibility.py`: at 1080p labels ≥ 28 px, titles ≥ 44 px (scales with canvas height), contrast ≥ 4.5:1, ≤ 7 nodes/beat, label length; constants kept in sync with the TS file by a test. The old diagrams (22 px labels, 14 px sublabels) failed this; the rewritten component uses 28/44/22/22 px at 1080p.
- **R128:** `lib/loudness.py` (measure + two-pass `master_two_pass`; −14 LUFS ±1, TP ≤ −1 dBTP). Real check on a synthetic −51.9 LUFS tone → −13.95 LUFS after two-pass. `VideoCompose._run_final_review` adds `checks.loudness` (when `metadata.loudness_target_lufs` is set; out-of-target → `revise`) next to the honesty guard from P0 (TEST_ONLY asset → `fail`); `final_review` schema updated.
- Skills updated (`edit-director`, `compose-director`).

Not run: a real Remotion render of the new components with a real alpha presenter (needs a real twin clip) — the P8 smoke test renders a diagram + `TEST_ONLY_` layer clip.

Acceptance (fast): 16:9 and 9:16 compile of the same plan, matte/alpha, focus-region PIP move, beat types, focus validation, legibility validator + TS sync, diagram splitting, two-pass mastering, final-review loudness + honesty fail/pass, schema → `tests/contracts/test_topic_tutorial.py` 111 passed; `tests/contracts` 1669 passed, 9 skipped. Whole `tests/` (excluding `tests/tools/test_gemini_omni_video.py`): 3051 passed, 14 skipped.

Pre-existing, not caused by this branch: `tests/tools/test_gemini_omni_video.py` has 25 failures on `main` too (schema `model` enum no longer matches what the test expects); files untouched here. Follow-up for the owner.

## Phase 8 — Tests consolidation

Done:
- `tests/contracts/test_topic_tutorial.py` split into `test_topic_tutorial_fast.py` (112 tests, ~11 s — under the 30 s budget; no models, no network, no sandbox) and `test_topic_tutorial_smoke.py` (1 test, opt-in).
- `smoke` marker registered in `tests/conftest.py`; smoke is **skipped unless `-m smoke`** (so `pytest tests/contracts/test_topic_tutorial*.py` runs only the fast layer).
- Smoke test (real local run, no paid APIs): Kokoro narration (~10 s) → `script_aligner` → R128 two-pass mastering → real Remotion render, 1280×720, diagram beat + a `TEST_ONLY_` presenter layer → ffprobe (1280×720, 30 fps, video+audio, duration = narration + 1 s tail), loudness within target, caption timings monotonic and inside the audio, `fixture_presenter_percentage > 0` while `presenter_percentage == 0` → `final_review.status == "fail"` because of the `TEST_ONLY_` asset; a diagram-only variant passes. It sets `HF_HUB_OFFLINE=1` (tests block the network) and skips cleanly when ffmpeg / Remotion / Kokoro narration are unavailable.
- Obsolete tests: the v2 tests tied to behaviour removed in earlier phases were rewritten in place during P0–P7 (fixture presenter counted as real, raw presenter registered by the resolver, assets gate off); no tests for still-existing tools (e.g. `local_talking_head`, which remains in the registry but is no longer in the topic-tutorial manifest) were deleted.
- One extra fix found while rendering: the bottom PIP overlapped the caption bar; bottom PIPs now sit above the caption-safe zone (TS + Python layouts, tested).

Acceptance (actual runs):
- Fast: `.venv/bin/pytest tests/contracts/test_topic_tutorial*.py -q` → 112 passed, 1 skipped (smoke opt-in), ~11 s.
- Smoke: `.venv/bin/pytest -m smoke tests/contracts/test_topic_tutorial_smoke.py -q` → 1 passed in ~56 s.
- Full contracts: `.venv/bin/pytest tests/contracts -q` → 1670 passed, 10 skipped.
- Whole repo `tests/` excluding `tests/tools/test_gemini_omni_video.py` (25 failures that exist on `main`, untouched by this branch): 3051 passed, 14 skipped (run before the last small layout change; contracts re-run after).

---

## Fix round 1

Source: `docs/topic-tutorial-v3-fixes.md` (Opus audit). Commits are per group: `fix(topic-tutorial-v3): <group> — <summary>`. Not pushed. §4 (owner recordings) is skipped by design.

### Group A — Hygiene (F6, F7, F8, F9, F12, F13)

**F6 — stock Gemini Omni tool restored.** Our earlier commit `b4d5baf` had changed `tools/video/gemini_omni_video.py` (env-driven default model, `GEMINI_VIDEO_ENABLED` gate, budget ceiling). Restored it to its pre-`b4d5baf` contents with `git checkout b4d5baf^ -- tools/video/gemini_omni_video.py` (default model `gemini-omni-1.1-flash` again; no env gates).
- Paid-call gate now lives only in our own layer: `tools/presenters/twin_idle_loop.py` requires `paid_call_approved`, `ALLOW_PAID_APIS=true`, an optional `budget_cap_usd` (spent + estimate must stay ≤ cap) and `lib/paid_call_guard`. The stock-tool tests I had added for the removed gates were replaced by `TestStockGeminiOmniUntouched`.
- `gemini-omni-1.2-flash` is **not** enabled: the pricing page lists it (`$12/1M` video output, ≈ $0.07/s) and says `1.1` requests route to `1.2` from 2026-12-03. If B6 needs `1.2`, extend the stock enum upstream-compatibly then; nothing needs it yet.
- `.venv/bin/pytest tests/tools/test_gemini_omni_video.py -q` → **33 passed** (was 25 failed / 8 passed).

**F7 — legibility in compose QA.** `VideoCompose._run_final_review` now computes `checks.diagram_legibility` from `edit_decisions.metadata.diagram_cuts` (published by `ScenePlanAdapter`) at the **rendered** resolution (from ffprobe); any violation → issue `Diagram illegible: …` → `status: revise`. `lib/diagram_legibility.validate_diagram_spec` also honours explicit `label_font_px` / `title_font_px` overrides. Schema `final_review` gained `checks.diagram_legibility`. Tests: `test_final_review_diagram_legibility` (20 px label at 1080p → revise; compliant → pass) and `test_adapter_publishes_diagram_cuts_for_compose_qa`.

**F8 — heavy lock everywhere heavy.** `lib/heavy_lock.py` rewritten on `fcntl.flock` (atomic, kernel releases it when the holder dies — no stale-pid logic), re-entrant per process (the old version's inner `finally` released the outer lock), `wait=` queues instead of failing (`wait=0` keeps fail-fast). Taken in: `VideoCompose` `render`/`remotion_render`, `HyperFramesCompose` `render`/`render_existing`, `mlx_tts` for text > 450 chars (~30 s of speech), plus the existing `sandbox_capture` and `twin_lipsync` (now queue up to 1 h). LatentSync/LivePortrait run inside `twin_lipsync`, so they are covered. Tests: nested no-deadlock; two real processes serialize (start/end never interleave) while a fail-fast probe is refused.

**F9 — playbook verification.** The playbook schema allows extra top-level keys, but `styles/playbook_loader.list_playbooks` globs `styles/topic-tutorial/*.yaml` and would list a sidecar as a playbook, so the sidecar is `config/topic-tutorial/playbook_verification.yaml` (deviation from the doc's `styles/topic-tutorial/verification.yaml`; recorded here). All five playbooks `verified: false`; `lib/playbook_verification.py` loader; `proposal-director.md` reads it. Tests: every playbook has an entry; loader doesn't list the sidecar. `software-technical` flips to `true` only after the owner approves Group E's compose gate.

**F12 — dependencies.** New `requirements-topic-tutorial.txt` (the repo has no extras mechanism; it follows the existing `requirements-gpu.txt` / `-dev.txt` pattern) with `faster-whisper>=1.2` and a comment on the ffmpeg pre-decode workaround for the PyAV `metadata_errors` bug; documents `alignment_method = asr_anchored` as the default. Groups B/C add their deps there.

**F13 — Gemini image pricing.** `lib/gemini_image_pricing.py` (our own table; the stock `google_imagen` tool intentionally raises `PriceQuoteRequired` for these models and is untouched). Source `https://aistudio.google.com/docs/pricing` (fetched 2026-11-14): `gemini-3.1-flash-image` 1K $0.067/image, `gemini-nano-banana-2.1` 1K $0.0336, `gemini-3-pro-image` 1K $0.134, etc., plus a $0.01 input/thinking pad per call. `TwinIdentity.estimate_cost` now returns a number (6 beautify calls = $0.462 on the default model).

**Also pulled forward (needed for the tree to stay green):** committing the fixes doc makes `test_skill_reference_paths` demand `docs/presenter-onboarding-recording-guide.md`, so the F14 deliverables `docs/presenter-onboarding-recording-guide.md` and `config/presenter-onboarding/voice_read_script.md` (442 words, original) were written now; the skill-failure-handling part of F14 stays in Group D.

Commands and results:
- `.venv/bin/pytest tests/contracts/test_topic_tutorial_fast.py -q` → 119 passed
- `.venv/bin/pytest tests/ -q -p no:cacheprovider` (**no exclusions**) → **3093 passed, 15 skipped** in 120 s (skips: optional playwright, footage/golden fixtures, live-doc checks, smoke opt-in).

### Group C — Smoke flakiness (F5)

Command: `.venv/bin/pytest -m smoke tests/contracts/test_topic_tutorial_smoke.py --tb=long -p no:cacheprovider -q` under `/usr/bin/time -l`, logs in the scratchpad (`run1..5.log`).

| run | conditions | result | wall | peak RSS |
|---|---|---|---|---|
| 1 | **cold**: fresh process, `remotion-composer/node_modules/.cache` and `$TMPDIR/remotion*` removed first | passed | 55.8 s | 1.07 GB |
| 2–5 | sequential, fresh process each | 4 × passed | 54.9–55.8 s | 1.22 GB |
| load | 14 busy-loop processes competing for CPU | passed | 68.7 s | – |

So **5/5 pass and the audit's failure (1 in 4, output not captured) did not reproduce** — including a cold run and a CPU-starved run. What I checked and ruled out:
- Alignment/caption assertions: 8 fresh Kokoro narrations → `script_aligner`, all `asr_anchored`, 32 tokens, monotonic and inside the audio every time; narration length is a stable 12.93 s (assertion window 7–16 s).
- Duration/loudness assertions have margin (mastered through the render within the ±1.5 LU window in every run).

Most plausible remaining causes (not proven), and what I changed:
1. Remotion's default 30 s headless-browser setup timeout on a cold Chrome launch → the smoke render now passes `remotion_timeout_ms=180000`.
2. Two heavy jobs at once (a second pytest session or a real render fighting for CPU/RAM) → the smoke render now takes the host-wide heavy lock (`wait=900`) so it queues instead of racing. Verified in practice: the first hardened run started while a sandbox capture held the lock, queued behind it (80.7 s) and passed.
No assertion was loosened. Re-run after hardening: 5 × passed (80.7 s incl. queueing, then 68.0 / 68.2 / 67.9 / 67.8 s). The ~12 s increase over the 55 s baseline appeared with the hardening (the `--timeout` flag and/or the lock wrapper) and was not investigated further. If the flake ever recurs, the test failure message now carries the Remotion error tail (`res.error`) — capture it.

### Group D — Research & capture readiness (F10, F14; F15 not run)

**F10.**
- `pipeline_defs/topic-tutorial.yaml`: research stage gained `sandbox_capture`, `pexels_image`, `pixabay_image`, `direct_clip_search`; assets stage gained `pexels_image`, `pixabay_image`. Registry check: image/stock tools found by capability are `pexels_image`/`pixabay_image` (stills; currently *unavailable* — no API keys), `direct_clip_search` (available), `clip_search`, `corpus_builder`; no Wikimedia/Openverse tool exists, so open-licensed Commons/NASA images come from web search. A fast test asserts every tool the manifest lists is registered.
- `video_downloader`/`transcript_fetcher` stay for reference-video analysis only. Hard rule added to `research-director.md`; `lib/research_contract.py` (`asset_rights_problems`, `brief_problems`) now flags any `sourced_clip` / clip candidate whose `source_tool`/`provider`/`source_type` is one of them. Fast test: `TestFixRound1ResearchReadiness`.
- Manifest review line corrected from "forced alignment" to script-anchored (`asr_anchored`).
- **Dry run** (topic "How Apple Silicon unified memory speeds up local AI inference"), under `projects/dev-research-dryrun/` (gitignored): `artifacts/research_brief.json` and `artifacts/fact_sheet.json`, both schema-valid; `brief_problems() == []`; `script_claim_problems() == []`; 4 data points, 7 sources, 3 angles, 3 media candidates with rights fields (a CC0 Wikimedia image whose file-page licence I read, an own-capture of the MLX docs page, an attributed screenshot of Apple's article). Honest limits: I ran the planner/worker pattern inline with search and fetch tools, not as separate sub-agents; only 4 pages were actually fetched and read (Apple ML Research article dated 2026-10-15, WWDC25 session 315, MLX docs, two Commons file pages); the blog-sourced facts come from search summaries, so they carry `verified: false` and medium/low confidence; the MLX docs-site licence is inferred from the repo's MIT licence; the first Commons M1 file has a conflicting EXIF copyright and was not used.
- **Sandbox screenshot of an allowed public page**: `SandboxCapture` `run`, surface `browser`, `allow_domains: [ml-explore.github.io]` → `assets/captures/mlx_unified_memory_page/` (`capture.mp4` 1920×1080 30 fps 5.5 s, `screenshots/mlx_unified_memory_doc.png` showing the MLX "Unified Memory" page, `network.json`: only `ml-explore.github.io` allowed; Chromium's background calls to `accounts.google.com`/`www.google.com` were **denied**; `iptables: true`).

**F14 (remaining part).** The reading script and owner guide were written in Group A. This group expanded all six `presenter-onboarding` skills with failure handling (validator failure → re-record request, max 3 attempts; identity drift → regenerate within the approved budget with `paid_call_guard`; rejected voices → round 2 with new ratios; locking/verify failures) and pointed `capture-session-director.md` to both files.

**F15.** Not run: no planned capture needs an owner login yet; to be exercised in Group E only if one does.

Commands and results:
- `.venv/bin/pytest tests/contracts -q -p no:cacheprovider` → 1681 passed, 10 skipped.

### Group B — Local engine integration with a STAND-IN presenter (F1–F4)

B0 was approved by the owner ("Approve b0": all rows as sent, $3 dev cap). Weights/code live in the model store `~/Models` (shared, machine-wide) (`lib/model_store.py`; pointer file `~/.openmontage/models_dir`; they were first downloaded to an external SSD and the store was later moved to internal storage — nothing references the SSD any more); presenter profiles stay in `~/.openmontage/presenter_profiles`. Check free space with `df -h /`.

**Downloads** (all licences read upstream before download; no InsightFace weights anywhere):

| Item | Size | Licence | Where / note |
|---|---|---|---|
| mlx-community/MuseTalk-1.5-fp16 | 1.9 GB | MIT (HF tag) + `musetalk-mlx` code (pyproject MIT, **no LICENSE file**, 0 stars; pinned commit c6eb30e, `pip install --no-deps`) | `musetalk/MuseTalk-1.5-fp16` |
| KwaiVGI/LivePortrait `liveportrait/*` (base models, stitching, landmark.onnx) | 0.68 GB | MIT (repo LICENSE read: **InsightFace models are non-commercial → not used**) | `liveportrait/weights`, code clone `liveportrait/src` @ 9b294b3 |
| ZhengPeng7/BiRefNet `model.safetensors` | 0.44 GB | MIT | `birefnet/weights`, code clone @ f707963. (rembg's own `birefnet-general-lite` ONNX, 224 MB, was also fetched first; its `birefnet-portrait` is 973 MB, not fetched) |
| ResembleAI/chatterbox (ve, t3_cfg, s3gen, tokenizer, conds) | ≈ 3.3 GB | MIT | `hf/` (the 13.9 GB repo's multilingual/v3 files were not fetched); `chatterbox-mlx` 1.3.1 in its own venv |
| ByteDance/LatentSync-1.6 (`latentsync_unet.pt` + `whisper/tiny.pt`) | 5.2 GB | code Apache-2.0, weights OpenRAIL++ | **deleted — LatentSync deferred, see B4** |
| MediaPipe `blaze_face_short_range.tflite`, `face_landmarker.task` | 4 MB | Apache-2.0 | `mediapipe/` |

**B1 — stand-in profile and guards.** `standin-dev` created with `standin: true` (schema `presenter_profile` + `standin_note`). Fictional portrait from `gemini-3.1-flash-image` (prompt: "FICTIONAL adult person … not resembling any real individual"; new `twin_identity` operation `standin_portrait`, refuses non-stand-in profiles, paid-guarded, dev cap). Voice: Kokoro `k3_steady_presenter` locked; a 30.3 s Kokoro clip as `raw/voice_read.wav`. Guards (`lib/standin.py`): a stand-in asset is detected by its record (`standin: true` or a stand-in `profile_id`), by any path inside the profile dir, or by the `STANDIN_` marker; `honesty_check` → `final_review: fail` / `replace_test_assets` outside test mode; `presenter_guard` rejects it so it counts as `fixture_presenter_percentage`, never `presenter_percentage`; QA's identity check fails it. Fast tests: `TestFixRound1StandinGuard` (3).

**B2 — MediaPipe + matte.** `mediapipe` 1.2.3 (Tasks API: `mp.solutions` no longer exists) via `lib/face_tools.py` (detector, 478-pt landmarks, mouth openness) wired into `lib/presenter_qa.py` (face presence, mouth series) and `twin_identity` still picking. `presenter_matte` now uses BiRefNet on **MPS fp16: 0.47 s/frame** (`lib/birefnet_mps.py`); the rembg ONNX route measured **6.7 s/frame on CPU** (502 s for 75 frames, 10.8 GB RSS) and its CoreML provider hung, so it stays only as a slow fallback. Real QA values on the stand-in clips: face presence 1.0 (115 frames), `no_raw_frames` correctly `not_run` (no raw recordings for a stand-in). **Mouth sync**: the lip-gap vs audio-envelope proxy proved unreliable (it did not follow audio shifted by ±5/10 frames; unrelated audio hit |lag| ≤ 2 in 13 % of trials), so `check_mouth_sync` now runs a null test and reports `inconclusive` (never a pass) unless the peak correlation beats the unrelated-audio 95th percentile. Both stand-in clips are `inconclusive` — judge sync by eye.

**B3 — MuseTalk.** The pairing code is the `musetalk_mlx` package (xocialize, MVS Collective) — it owns the neural core only. `lib/musetalk_runner.py` implements the rest with MediaPipe: crop box by the upstream rule (symmetric about the nose bridge down to the chin + 10 px), 256² crop → masked⊕ref latent → UNet per whisper chunk → resize → feathered paste-back (mask = face oval below the crop mid-line, eroded + Gaussian), output at source resolution, 25 fps, per-segment resume kept in `twin_lipsync`. 22.9 s of narration on the 10 s idle loop: **235 s wall, 5.3 GB RSS (20 GB peak footprint)**; output 1280×720 H.264 + AAC. Visually: clear mouth shapes, no visible seam. `musetalk_mlx_available()` now checks the package, the weights and MediaPipe.

**B5 — LivePortrait.** `lib/liveportrait_runner.py` + `lib/_liveportrait_worker.py` run the MIT code in an isolated subprocess on MPS with a MediaPipe-backed replacement for `FaceAnalysisDIY` injected before import (InsightFace is never imported). `twin_performance_transfer` takes an explicit `driving_video` (+ `driving_license` outside the profile). Test: stand-in portrait driven by the Omni idle clip (licence: own generation) → **375 s, 3.6 GB RSS** for 10 s (1280×714), blinks/head motion transfer cleanly.

**B6 — idle loop.** `twin_idle_loop generate` on the stand-in portrait: `gemini-omni-1.1-flash`, **10.03 s, 1280×720, 24 fps, 46.8 s, seam score 0.0083 (seamless)**; **actual cost $1.0217** (usage-based) vs estimate $1.0136. Dev spend total ≈ **$1.10 of the $3.00 cap** (portrait $0.077 estimated — the image tool does not report usage — + clip $1.0217). The Google Flow fallback was not needed.

**B7 — Chatterbox.** chatterbox-mlx pins torch 2.8 / transformers 5, so it runs from its own venv (`lib/chatterbox_runner.py`, `lib/_chatterbox_worker.py`). **Verified API:** `ChatterboxTTSMLX.conds.t3.speaker_emb` (1×256) and `conds.gen["embedding"]` (1×192) can be read and interpolated; the acoustic prompt (`cond_prompt_speech_tokens`, `gen.prompt_token`, `gen.prompt_feat`) comes from the owner reference clip and is *not* interpolated — a blend is "owner prompt + blended speaker embeddings". All 4 Chatterbox candidates were built on the stand-in voice (owner ref = stand-in Kokoro clip, donors = Kokoro `am_michael/am_adam/af_heart/am_fenrir`), plus the 4 Kokoro ones; the page `voice/candidates/index.html` lists 8/8. Defect found: Chatterbox sometimes stops early and drops sentence endings (first run: c1/c2 truncated), so each candidate is now ASR-checked (`lib/voice_lab.asr_coverage`, ≥ 0.92) and re-synthesized up to 3 times with new seeds; after that **c3 and c4 are complete (1.0), c1 (0.79) and c2 (0.83) stay truncated and are labelled with a warning on the page.** Locking a Chatterbox candidate is not wired into `mlx_tts` (audition only; `lock_voice` says so).

**B8 — dev bake-off**: `scripts/twin_bakeoff_dev.py all` + `report` → `reports/twin_bakeoff_dev.md` (STAND-IN header, per-stage wall clock and peak memory, real QA numbers, contact sheet in `reports/twin_bakeoff_dev_clips/`). Both MuseTalk routes ran lipsync → matte → QA → two Remotion renders (PIP over a diagram, full-screen) with the real alpha presenter layer, 16:9, 1920×1080: 10/10 stages ok; every render's `final_review` = **fail** with the stand-in asset flagged (required). Finding: without a `focus_region` the PIP covered the "GPU" node (scene-director follow-up). No default engine picked.

**B4 — LatentSync: DEFERRED by owner decision.** Not run; no third-party MLX port code was executed. The weights and venv (`~/Models/latentsync`, ~6.4 GB) are deleted (see Fix round 1 / LatentSync drop below). `twin_backends.latentsync_available()` now reports the deferral reason; MuseTalk-MLX handles the full-screen route.

Commands and results:
- `.venv/bin/pytest tests/ -q -p no:cacheprovider` (no exclusions) → **3105 passed, 15 skipped** (237 s).
- Real runs: see the per-stage timings above and in `reports/twin_bakeoff_dev.md`.

### Sandbox image/container cleanup (`docs/sandbox-image-cleanup.md`)

Done as asked: the image is tagged `openmontage-capture:<12-hex sha256 of sandbox/>` (`sandbox_hash` / `current_image_tag`, sorted path + bytes, `__pycache__`/`.DS_Store` ignored) and built with `--label org.openmontage.role=capture` on both runtimes; `ContainerRuntime` gained `list_capture_images`, `list_capture_containers`, `remove_image`, `prune_dangling_images`, `stop_builder` (Apple, Docker, Colima); `cleanup_stale(rt, keep_tag, active_name)` runs containers → old images (incl. legacy `:1`) → dangling → builder stop, best-effort, scoped by `ScopeError` assertions (`openmontage-capture` repo / `om-capture-` prefix / role label; no `--all`, no system prune). It runs after every successful `build_image` (also when the image is already current), at the start of `run`/`start` (only once the current image exists), and as the new `cleanup` operation; never after a failed build, and image removal is skipped if the current image is missing. In-progress captures are protected (active name, heavy lock held by another `sandbox_capture`, or a running container younger than 29 min). Docs: `sandbox/README.md`, `docs/topic-tutorial-v3-handoff.md` §5.7.

Facts learned from the real runtime (Apple `container` 1.7.1), now encoded in the parsers and tests: `image list --format json` entries are `{"configuration": {"name": "docker.io/library/<repo>:<tag>"}, "id": "<digest>"}` (local images get the `docker.io/library/` prefix); `list --all --format json` entries have `status` as an object (`{"state": "running"|"stopped"}`); two tags of identical content share one digest, so deleting one tag leaves the other usable; `container builder stop` works but leaves a stopped `buildkit` container (not ours; never touched).

Tests: 10 fast tests `TestSandboxCleanup` (hash stable/changes; build removes old tags and `:1` but not the new tag, `ubuntu`, `postgres`; current image short-circuits and still cleans; failed build removes nothing; stopped containers removed, active/in-progress/foreign (`postgres`, `buildkit`) untouched; no `--all`/`-a`/system prune in any argv and `ScopeError` on out-of-scope names; a raising step still returns build success; old images kept when the current one is missing; Docker JSON parsing) with subprocess mocked, plus one real smoke test `test_smoke_sandbox_image_cleanup_real` (`-m smoke`).

Real smoke run (this machine): build 1 → `openmontage-capture:303552a23d28` (already current, nothing built); a stopped orphan `om-capture-smoke-stale-1` was created; README touched → build 2 → `openmontage-capture:754165a82015`, **removed `docker.io/library/openmontage-capture:303552a23d28` and container `om-capture-smoke-stale-1`**, pruned dangling, stopped the builder, `errors: []`; then exactly one `openmontage-capture` image remained and no `om-capture-*` container; README reverted. A manual `cleanup` earlier removed a leftover `…:754165a82015` the same way. After editing `sandbox/README.md` for the docs the image was rebuilt as `openmontage-capture:0a8a0dfd1f76` and `…:303552a23d28` was removed — final state: one capture image, `ubuntu:24.04` untouched, only the Apple `buildkit` container left. Whole suite: `.venv/bin/pytest tests/ -q -p no:cacheprovider` → **3116 passed, 16 skipped** (257 s). No load tests were run in this task (and none will leak processes: macOS has no `timeout`; any future load test must trap/kill its own PIDs).

### LatentSync dropped (owner decision, relayed 2026-11-14)

Owner answer: drop LatentSync; MuseTalk-MLX handles the full-screen route. Done:
- `rm -rf ~/Models/latentsync` — 6.4 GB (checkpoints 5.2 GB, mlx/ + upstream/ clones, venv; the venv's `bin/python*` were symlinks into Homebrew Python, so only the links were removed). `ls ~/Models` afterwards: birefnet, chatterbox, hf, liveportrait, mediapipe, musetalk, u2net.
- `lib/twin_backends.latentsync_available()` now always returns unavailable with the deferral reason; `reports/twin_bakeoff_dev.md` (+ `scripts/twin_bakeoff_dev.py` text) and B4 above say "deferred", `presenter-director.md` no longer recommends it.
- `sb1992/latentsync-mlx` was never executed. `pytest tests/contracts/test_topic_tutorial_fast.py` → 137 passed.

## Fix round 1 — Group E (no-presenter validation run, project `topic-tutorial-validation`)

Owner input (via parent session, 2026-11-14): this repo (`pipeline_defs/topic-tutorial.yaml` + `skills/pipelines/topic-tutorial/`) + `https://www.remotion.dev/docs/the-fundamentals` + a topic line. Presenter policy `none` (`presenter_status: skipped_unavailable`, "presenter profile not yet created"). Paid calls: none (`ALLOW_PAID_APIS=false`).

Defects found so far and fixed (with tests in `TestFixRound1GroupEIngestion` / `TestFixRound1GroupEDecisionLog`):
- `universal_ingestor`: repo `focus` was applied after the 100-file cap, so a focused repo ingested 0 files → focus now applied while walking (and cannot escape the repo root); `.gitignore` directory entries ending in `/` (e.g. `projects/`) were ignored → fixed; URL fetch refused every redirect (`HTTP 308` on the Remotion docs URL) → follows ≤ 5 redirects, SSRF-validating each hop. Result: 13/13 sources ingested.
- `decision_log` schema enum lacked the categories the topic-tutorial skills mandate (`model_routing`, `presenter_engine`, `presenter_wardrobe`, `voice_profile`, `music`, `playbook`, `capture_plan`, `alignment_method`) → added.
- Manifest: the `assets` stage was a gate (`human_approval_default: true`) with `checkpoint_required: false` → set to `true`; test asserts every gated stage requires a checkpoint.
- `asset-director.md` sent diagrams to `diagram_gen`, whose output cannot meet the legibility floor on this machine → now points to spec-driven `diagram` cuts.
- Noted, not changed: `proposal_packet.schema` requires ≥ 3 concepts while skill/manifest say "2–3"/"at least 2"; `mlx_tts` defaults to `allow_fallback=true` (to an unavailable piper); `skipped_unavailable` is a free string.

Stages: research (deep sub-agent, 18 data points, 4 angles, 2 media candidates; `brief_problems` = []) → completed. Proposal (deep sub-agent) → `awaiting_human` at gate 1.

Group E progress (continued): gate 1 (proposal) approved — concept A, Remotion, templated, no music, $0; gate 2 (scene_plan) approved. Both the script and scene plan went through a deep-tier critic (REVISE → applied). Assets stage (standard sub-agent) → gate 3 `awaiting_human`.

More defects found by the run and fixed (tests in `TestFixRound1GroupE*`):
- `lib/honesty_guard`: matched `TEST_ONLY_`/`tests/fixtures` in any string, so a diagram that merely *explains* the guard would fail `final_review` → now checks only asset-reference keys.
- `ScenePlanAdapter`: consecutive capture beats replayed the recording from 0 s (now continue via `source_in_seconds`); `screenshot_callout` took "the first image" (now its own asset, error if missing); `layout.overlays` were dropped (now emitted as `label` overlays; Remotion `Explainer` renders them); consecutive beats on one still became separate cuts that restarted the fade/zoom (merged); diagram beats re-popped their build animation (`diagramContinue`).
- `sandbox/runner.py`: terminal `wait_for_text` could never match (ttyd's default canvas renderer has no DOM text) → `rendererType=dom` + xterm buffer read; `click` now scrolls its target to the centre first (the four-properties list was cut off). Image rebuilt (`openmontage-capture:3ebe9dfab882`; the old image was removed by the automatic cleanup, `errors: []`). cap_01–cap_04 then ran clean and were checked by eye on their output stills.
- New registry tool `sourced_image_import` (allow-listed hosts, per-hop SSRF check, size cap, content-type + PIL verify, rights fields mandatory, optional expected size/sha) — there was no tool that could import an approved URL with its rights record. First Wikimedia request got a transient HTTP 429, the retry succeeded: 664,146 bytes, 1920×1080, CC0.
- Noted, not fixed: `mlx_tts` has no seed input outside `voice_profile` (the run seeds MLX externally); Layer-3 skills for `mlx_tts`, `script_aligner`, `sandbox_capture` point at unrelated vendor docs; `sandbox_capture` discards the recording when a run fails; `test_heavy_job_two_processes_serialize_and_fail_fast` failed once under load and passes alone (timing).
- Narration: 263.8 s vs the script's 296.5 s estimate (−11 %; Kokoro reads 2.7 words/s vs the 2.5 assumed). The edit stage re-times beats to the real audio.
