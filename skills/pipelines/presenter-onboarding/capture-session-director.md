# Capture Session Director — presenter-onboarding  🛑

Goal: get three clean owner recordings into the private profile. Tool: `presenter_profile` (`init`, `validate_recording`, `record_raw`).

1. `init` the profile (`profile_id` kebab-case, e.g. the owner's first name). Ask for explicit **likeness consent** (store `owner_consent` in profile.json via the checkpoint note).
2. **Print this recording protocol, then stop and wait for the files** (🛑):
   - **Face turn (~30 s):** good even light (window or soft lamp in front, no strong backlight), plain background, head-and-shoulders, ≥ 1080p. Look at camera, then slowly turn left, back to centre, slowly right, back to centre, a gentle nod up and down.
   - **Natural performance (~60 s):** same setup; talk naturally to camera about anything (your day, a topic you like) with ordinary gestures and expressions. Face always visible. Quiet room.
   - **Voice read (~3 min):** quiet room, phone or mic 20–30 cm away, 48 kHz, no music. Read the phonetically rich script the agent provides (a few pangrams plus a tutorial-style passage; include numbers, code identifiers and questions).
3. For each file run `validate_recording` (kinds `face_turn`, `performance`, `voice_read`): resolution ≥ 1080p, fps ≥ 24, duration windows, sample rate ≥ 44.1 kHz, noise floor ≤ −45 dBFS, no clipping. Report problems plainly and ask for a re-record rather than accepting a weak file.
4. `record_raw` each passing file (copies into `raw/`, mode 600, registers sha256). Raw files never leave the profile.
5. Present a summary (probe values per file) and **end your turn** for owner confirmation.
