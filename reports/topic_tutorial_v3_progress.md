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
