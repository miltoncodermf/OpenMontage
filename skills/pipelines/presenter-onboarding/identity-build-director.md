# Identity Build Director — presenter-onboarding

Goal: 4–6 subtle, photoreal, clearly-the-owner canonical candidates plus 2–3 starter wardrobe variants. Tool: `twin_identity`. Layer 3: read `flux-best-practices` for reference-image editing prompts before calling image tools.

1. `extract_stills`: sharp frontal/three-quarter frames from `raw/face_turn.*`, picked with **MediaPipe** face detection (Apache-2.0). Do **not** use InsightFace weights (non-commercial). If `mediapipe` is missing the tool says so and falls back to sharpness only — tell the owner; installing `mediapipe` is small and fine.
2. **First paid Gemini call 🛑:** before `beautify`, state tool `twin_identity` → `google_imagen`, provider Gemini image API, model (default `gemini-3.1-flash-image` or `gemini-3-pro-image`), why, count (4–6 = a *sample batch* is one call per candidate), and a current price quote (the tool cannot price Gemini image models). Wait for the owner's OK in chat, then pass `paid_call_approved: true`.
3. `beautify` with 4–6 variations. Prompts (lib/twin_prompts.py) ask for *subtle* improvement: skin/light/grooming/framing; recognisably the owner; photoreal; studio background; head-and-shoulders; neutral expression, mouth closed. Reject over-smoothed or unlike results and regenerate within the approved budget.
4. Create 2–3 starter wardrobe variants (`wardrobe`, e.g. casual-tech, smart-casual, dark-hoodie) from the picked/likely canonical — only after step 2's approval covers them.
5. Show the candidates (file paths in the profile) and checkpoint; the owner picks in `identity_lock`.
