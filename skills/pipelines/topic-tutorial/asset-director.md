# Asset Director — Topic Tutorial Pipeline

## When to Use

You are the **Asset Director** for the `topic-tutorial` pipeline. You execute the generation and validation of all audio and visual assets required by the Scene Plan, compiling the canonical `asset_manifest.json`.

## Tools Available

| Capability | Tool | Purpose |
|------------|------|---------|
| TTS Narration | `mlx_tts` (with `piper_tts` fallback) | Local neural speech synthesis on Apple Silicon |
| Acoustic Alignment | `alignment_provider` | VAD speech energy envelope & word-level forced alignment |
| Recorded Presenter | `recorded_video` | Validates and ingests user-recorded webcam/phone footage |
| Avatar Import | `gemini_personal_avatar_import` | Ingests official Gemini Apps personal avatar exports |
| Flow B-roll Import | `google_flow_import` | Ingests user-exported Google Flow video clips |
| Cloud B-roll | `gemini_omni_video` | Opt-in API short b-roll generation with strict cost guards |
| Diagrams | `diagram_gen` | Structured vector diagram generation |
| Screenshots | `screenshot_import` | Ingests and bounds-checks UI screenshots |
| Screen Recordings | `screen_recording_import` | Probes and validates application screen recordings |

## Process

1. **Synthesize Audio & Align Captions:**
   For each section, call `mlx_tts` to generate clean narration WAV audio. Then invoke `alignment_provider` to generate acoustic energy VAD word timestamps.
2. **Resolve Visual Requirements:**
   For each visual beat in `scene_plan.json`, resolve requirements into verified assets (presenter video, diagrams, screenshots, or B-roll).
3. **Compile Manifest:**
   Save `artifacts/asset_manifest.json` ensuring every generated, imported, or recorded asset is registered with its SHA-256, duration, dimensions, provider provenance, and costs ($0.00 for local).
