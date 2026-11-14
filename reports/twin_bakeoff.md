# Twin bake-off (P5) — STATUS: NOT RUN

Spec: `docs/topic-tutorial-v3-handoff.md` D7, §5.5, §6 P5. **Nothing below has been measured.** No presenter clip has been produced by any engine, no Gemini call has been made, no weights have been downloaded. Placeholder rows are marked `not run`.

## Why it has not run

| Blocker | Needed from the owner |
|---|---|
| No locked presenter profile (no canonical portrait, no raw performance recording) | 🛑 recording session → identity pick → voice pick (P4) |
| Hybrid engine needs an idle loop → first paid Gemini Omni call | 🛑 OK for tool `twin_idle_loop` → `gemini_omni_video`, model `gemini-omni-*-flash` (key lists Omni flash models, **no Veo**), one 8–10 s clip per outfit; current price quote needed (`twin_idle_loop plan` returns the estimate and prompt) |
| If the API route fails (access/billing/quota) | 🛑 OK to use the Google Flow browser fallback (agent drives Flow in Claude in Chrome; owner confirms each generation/download; then `twin_idle_loop import_flow`) |
| MuseTalk-MLX weights `mlx-community/MuseTalk-1.5-fp16` ≈ 1.88 GB (+ whisper-tiny, sd-vae-ft-mse) | 🛑 model download ≥ 500 MB (disk check first; 65 GB free on internal) |
| LatentSync 1.5/1.6 (MPS fork), LivePortrait, BiRefNet weights | 🛑 each ≥ 500 MB |

## What is implemented (code, fast-tested)

- `twin_idle_loop` — plan/generate/import_flow/check_loop/make_motion_source; paid-call refusal unless approved and within the proposal's paid-call list (≤ 1.2×); loop-seam check.
- `twin_lipsync` — motion-source looping/ping-pong to each segment's narration length (tested), per-segment outputs + `progress.json` resume (tested), heavy-job lock, refuses a profile `raw/` motion source. **Backends `musetalk_mlx` / `latentsync` are adapters that fail loudly**: the MuseTalk-MLX port only exposes a model API (256² face crop + whisper chunks → lip-synced crop; the model card gives no install route for the `musetalk_mlx` package), so face detection/crop, whisper chunking and paste-back still have to be integrated and verified against the real weights during the bake-off.
- `twin_performance_transfer` (LivePortrait) — contract + honest status only; invocation not integrated.
- `presenter_matte` — per-frame matting → ProRes 4444 alpha `.mov` (tested with an injected segmenter); real BiRefNet via rembg `birefnet-portrait` is unavailable here (`rembg` not installed).
- `lib/bakeoff.py` — wall-clock + peak-RSS measurement helper for the runs.

## Protocol to run once unblocked

Same ~20 s narration (locked voice) rendered as: (ii) hybrid PIP + full-screen; (i) local PIP + full-screen; LatentSync full-screen variant. Never concurrent with captures/Remotion (heavy-job lock). Record per variant:

| Variant | Wall clock | Peak memory | Cost (USD) | Mouth sharpness (full-screen) | A/V offset (frames) | Notes |
|---|---|---|---|---|---|---|
| (ii) hybrid + MuseTalk-MLX, PIP | not run | not run | not run | — | not run | |
| (ii) hybrid + MuseTalk-MLX, full-screen | not run | not run | not run | not run | not run | |
| (i) local (LivePortrait) + MuseTalk-MLX, PIP | not run | not run | not run | — | not run | |
| (i) local (LivePortrait) + MuseTalk-MLX, full-screen | not run | not run | not run | not run | not run | |
| LatentSync, full-screen | not run | not run | not run | not run | not run | |

Side-by-side clips go in `reports/twin_bakeoff_clips/` (not committed). The owner then picks the default engine (`profile.engine_default`: `hybrid` | `local`); both stay supported.

## Corrections to the old feasibility report

`reports/phase4_avatar_feasibility.json` ("MuseTalk infeasible", "LivePortrait 12–16 GB leak") is unverified and superseded; MuseTalk 1.5 has an MLX port (MIT) that reports ≈ 34 faces/s at batch 8 and ≈ 7 GB peak on Apple Silicon per its model card — **also unverified here**.
