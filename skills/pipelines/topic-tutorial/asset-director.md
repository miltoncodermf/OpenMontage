# Asset Director — topic-tutorial v3  🛑 gate

**Read first:** `skills/pipelines/explainer/asset-director.md` and `skills/pipelines/screen-demo/asset-director.md`; for the presenter work also `skills/pipelines/topic-tutorial/presenter-director.md`. Model tier: standard (this stage includes driving sandbox captures). Read each tool's Layer 3 `agent_skills` before calling it.

## topic-tutorial deltas

1. **Narration:** `mlx_tts` with the **locked `voice_profile`** (deterministic for a given text). Pad and condition as before; two-pass R128 mastering happens at compose.
2. **Alignment (D22):** call `script_aligner` (ASR word times from faster-whisper via `transcriber`, anchored onto the **known script tokens** by `lib/script_alignment.py` — numbers/punctuation map back to script tokens). Set the manifest's `alignment_method` to what it returns: `asr_anchored` (primary; honest name — the repo has faster-whisper, not whisperX forced alignment) or `heuristic` (energy fallback, with `fallback_reason`) — surfaced at the gate. Log `alignment_method`. Narration comes from `mlx_tts` with `voice_profile` (seeded, reproducible).
3. **Twin generation** — see `presenter-director.md`; QA with `lib/presenter_qa.presenter_qa_report` (checks that are `not_run` never count as a pass — say so at the gate). On unrecoverable failure or QA `fail` → `lib/presenter_fallback.replan_without_presenter(scene_plan, reason)` (`presenter_status: "skipped_failed"` + reason), never a fixture. Scene cache keys use `lib/scene_cache.compute_scene_hash` with input-asset hashes, renderer version, TTS model, voice-profile hash and aspect.
4. **Captures:** run each beat's capture script with `sandbox_capture` only (never `screen_recorder`/`cap_recorder`, never the owner's desktop). Never run captures concurrently with lip-sync or Remotion renders (24 GB). Keep the recording, step screenshots and the step log.
5. **Other visuals:** diagrams as spec-driven `diagram` cuts with a `diagramSpec` rendered by the composition (Remotion `DiagramScene`) so `lib/diagram_legibility.validate_cuts` can check them — `diagram_gen` raster output (Pillow 18 px labels, tiny fallback font on macOS, Mermaid needs `mmdc`) does not meet the legibility floor and must not be used for tutorial diagrams, screenshots, sourced media — each `sourced_*` asset records `rights_status`, `license`, `source_url`, `attribution`, `retrieved_at`.
6. **Cost:** itemized paid calls only; run `lib/paid_call_guard.check_paid_call` first; track actuals with `tools/cost_tracker.py`.
7. **Manifest:** every asset with SHA-256, provenance (tool, provider, model/version, seed), cost, scene linkage; presenter assets carry `identity_transform: "beautified"` and `profile_id`. Write `partial_progress` in the checkpoint after each unit so long runs resume.
8. **QA before the gate:** ffprobe all media; no `TEST_ONLY_`/fixture asset anywhere; presenter QA results (§5.5 step 5) summarized. Present assets scene-by-scene, then **end your turn**.

## Review focus / success criteria
Mirror the manifest: clean narration, forced word timings (method stated), presenter assets real-or-skipped, every visual beat satisfied.
