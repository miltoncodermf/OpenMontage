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
- `.venv/bin/pytest tests/contracts -q` → see commit run (all green).
