# Edit Director — topic-tutorial v3

**Read first:** `skills/pipelines/explainer/edit-director.md` and `skills/pipelines/screen-demo/edit-director.md`. Model tier: standard. Schema: `schemas/artifacts/edit_decisions.schema.json`.

## topic-tutorial deltas

- **Frame math at 30 fps** from the *conditioned* narration audio: `frames = round(duration_seconds × 30)`; frame durations sum to total video duration.
- **Captions:** word captions `{word, startMs, endMs}` from the forced alignment; monotonic and inside audio bounds. State `alignment_method`.
- **Layer stack (bottom → top):** background visual (diagram / capture / screenshot / sourced media) → **presenter layer with alpha** (never baked in) → captions → overlays/callouts. Use each beat's normalized layout and `focus_region`; compute pixels from the canvas, not hard-coded values.
- **Capture sync:** use the capture step log (timestamps) to place callouts and zooms on the real action.
- Keep `render_runtime` exactly as locked at proposal; no silent swaps.
- **No fixtures:** edit decisions must not reference `TEST_ONLY_` or `tests/fixtures` paths.

## Review focus / success criteria
Mirror the manifest: exact 30 fps frame counts, caption timing matches word timings, cut/transition durations; frame durations sum to the total.
