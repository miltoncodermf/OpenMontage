# Script Director — topic-tutorial v3

**Read first:** `skills/pipelines/explainer/script-director.md` (script structure, timestamps, enhancement cues). Model tier: deep (plus `critic.script` = deep review pass).

## topic-tutorial deltas

- **Pace:** 140–160 WPM (≈ 2.4–2.6 words/s) for 4–8 minutes typical.
- **Structure:** hook ≤ 15 s → why it matters → steps with proof → recap → CTA. Every step that makes a technical claim has a planned proof (diagram, capture, screenshot).
- **Fact linking:** every factual claim carries a `fact_id` into `fact_sheet.json`; claims with `untrusted_source: true` must be cross-checked or reworded.
- **Presenter marks:** mark each section's lines as intended for **presenter full-screen** (hook, section intros, outro) or **voice-over** (everything else — presenter PIP is a scene-director decision). Presenter lines should be conversational and short; the twin lip-syncs them.
- Write narration for the **locked voice** (`voice_profile`): no unpronounceable tokens; spell out symbols and code identifiers as they should be spoken; avoid literal punctuation the TTS would read aloud.
- Output `artifacts/script.json` with scene IDs (`s1`, `s2`, …), narration text, estimated durations, presenter marks.
- Run the `critic.script` pass (deep tier) before checkpointing: pacing, claim sourcing, hook strength.

## Review focus / success criteria
Mirror the manifest: logical flow, 140–160 WPM, claims linked to sources, every scene has narration and an estimated duration.
