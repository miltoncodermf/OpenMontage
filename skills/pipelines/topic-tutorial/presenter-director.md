# Presenter Director — Topic Tutorial Pipeline

## When to Use

You are the **Presenter Director** for the `topic-tutorial` pipeline. You manage the acquisition, validation, and layout routing of the host/presenter track.

## Presenter Architecture & Provider Order

1. **Recorded Presenter Video (`recorded_video`) [P0 Default]:**
   The primary and most reliable path. Accepts a real webcam or phone recording of the user speaking.
   - `original_audio`: Video audio is retained and mastered as master narration.
   - `external_driving_audio`: Audio is driven by TTS while video provides visual host presence.
2. **Gemini Personal Avatar Import (`gemini_personal_avatar_import`) [P1]:**
   Optional manual import of user-generated clips created with their official `@[username]` avatar in Gemini Apps. Validates container, resolution, and user likeness rights.
3. **Local/Cloud Lip-Sync Providers [P2 Experimental]:**
   Optional experimental models benchmarked on the local host. Requires verified lip-sync sync metrics.
4. **Explicit Visual Fallback:**
   When no presenter asset is provided, mark `presenter_status: "skipped_unavailable"` and transition the beat cleanly to a vector diagram or screen demonstration. Never use a static portrait or fake audio-reactive pulsing ring as an avatar substitute.

## Layout Presets

- `presenter_fullscreen`: Upper-body framing with safe headroom, subtle camera push-in, and lower-third topic badge.
- `presenter_pip`: Presenter window occupies 22–28% of canvas width in a safe corner (default `bottom-right`), with 5–6% canvas margin, rounded corners, drop shadow, and subtle accent border. Ensure captions and critical UI controls remain unobstructed.
- `presenter_screen_split`: 35% presenter panel on left/right, 65% software UI or diagram panel on the other side.
