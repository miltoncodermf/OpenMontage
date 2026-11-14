# Recording guide — presenter onboarding (one page)

You record **three short takes** once. They are the private source for your digital twin; raw footage
is never rendered in any video and never leaves `~/.openmontage/presenter_profiles/<your-id>/raw/`.
Total time: about 15 minutes including re-takes.

## Setup
- **Camera:** phone on a tripod or a webcam, landscape, **≥ 1080p, ≥ 24 fps** (30 is ideal). Lens at eye height, 1–1.5 m away, head-and-shoulders framing with a little headroom.
- **Light:** a window or soft lamp **in front** of you. No strong backlight, no mixed warm/cool light, no hard shadows across the face.
- **Background:** plain wall or tidy shelf, no screens or moving things behind you.
- **Look:** dress the way you normally present; your twin's outfits are generated later, so don't worry about wardrobe.
- **Audio:** a quiet room (fridge off, windows shut). A lapel or desk mic **20–30 cm** from your mouth beats the phone's built-in mic; if you use the phone, put it on the desk, mic towards you.

## The three takes
| # | Take | Length | What to do | File |
|---|---|---|---|---|
| 1 | **Face turn** | ~30 s | Look at the camera, slowly turn left, back to centre, slowly right, back to centre, a gentle nod up and down. Mouth relaxed, no talking. | `face_turn.mp4` (or `.mov`) |
| 2 | **Natural performance** | ~60 s | Talk naturally to the camera about anything (your day, a tool you like) with ordinary gestures and expressions. Face always in frame. | `performance.mp4` (or `.mov`) |
| 3 | **Voice read** | ~3 min | Read `config/presenter-onboarding/voice_read_script.md` out loud at your normal pace. Audio-only is fine. | `voice_read.wav` (48 kHz) or `.m4a` / `.mp4` |

Formats: H.264/HEVC `.mp4`/`.mov` for video, WAV (preferred) or M4A/MP4 for the voice read. Don't edit,
filter or beautify in the camera app; keep "beauty" modes off.

## Where to put the files
Anywhere convenient (for example `~/Desktop/recordings/`). Tell the agent the three paths; it validates each file
and copies it into your private profile (mode 600, sha256 recorded). Delete the originals afterwards if you like.

## What the validator checks (and how to fix a failure)
| Check | Limit | If it fails |
|---|---|---|
| Resolution / fps | short side ≥ 1080 px, ≥ 24 fps | switch the camera to 1080p/30 or 4K |
| Duration | face 20–90 s, performance 45–180 s, voice 150–420 s | re-record to the target length |
| Sample rate | ≥ 44.1 kHz (48 kHz recommended) | set the recorder to 48 kHz |
| Noise floor | ≤ −45 dBFS | quieter room / mic closer |
| Peak level | ≤ −1 dBFS (no clipping) | lower the input gain or move back a little |

The agent will ask for a re-record rather than accepting a weak file. Likeness consent (that you are the person
in the recordings and agree to the twin) is recorded in the profile at the start; you can revoke it by deleting the profile folder.

## After the recording
1. The agent builds beautified portrait candidates from stills of take 1 (paid Gemini image calls — itemised and approved by you first). **You pick the identity.**
2. It builds 8 voice candidates from take 3. **You listen and pick the voice** (the page also lets you blend ratios for a second round).
3. A short engine bake-off on your identity lets **you pick the default twin engine**.
