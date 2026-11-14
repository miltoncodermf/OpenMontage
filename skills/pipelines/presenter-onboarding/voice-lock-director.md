# Voice Lock Director — presenter-onboarding  🛑

1. Ask the owner to pick a candidate id from `voice/candidates/index.html`.
2. `voice_lab` `lock_voice` → `voice/voice_profile.json` (engine, model version, recipe, polish chain, seed) and `voice/sample.wav`. Narration with this profile is seeded and reproducible (identical up to float32 jitter, not byte-identical).
3. `presenter_profile` `lock`: writes sha256 of **every** profile file and sets `locked: true`; then `verify` must return no problems (directory mode 700, hashes match).
4. Log a `voice_profile` decision. Present the locked profile summary (never raw paths of owner recordings in any shareable artifact) and **end your turn**. From now on every topic-tutorial video uses this identity and voice.
