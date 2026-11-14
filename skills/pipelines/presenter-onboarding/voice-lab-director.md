# Voice Lab Director — presenter-onboarding

Goal: ~8 candidate voices the owner can compare fairly. Tool: `voice_lab` (`build_candidates`).

- **Kokoro blends:** weighted averages of 2–3 preset style vectors + speed (4 candidates, built locally).
- **Chatterbox (MIT, MLX):** clone the owner from `raw/voice_read.*` and blend with 2–3 donor voices (Kokoro presets) at ~70/30, 50/50, 30/70, varying exaggeration/cfg/pitch slightly (4 candidates). **Verify** the installed Chatterbox backend exposes the speaker embedding for interpolation. If the backend is missing or doesn't expose it, report exactly that and **ask the owner before switching engines** (e.g. Qwen3-TTS base cloning in `mlx-audio`) — never substitute silently. Weights ≥ 500 MB need disk check + owner OK.
- Every candidate reads the **same ~20 s tutorial-style paragraph** through the **same polish chain** (high-pass 80 Hz, presence EQ, de-ess, light compression, loudness normalize) — fair comparison.
- Output `voice/candidates/index.html` (local page: player + recipe per candidate; unavailable candidates are labeled with the reason). Tell the owner to open it and name a candidate id.
- The voice need not match the owner's real voice; it must be consistent, attractive, distinctive. Chatterbox output carries an inaudible Perth watermark (accepted).
