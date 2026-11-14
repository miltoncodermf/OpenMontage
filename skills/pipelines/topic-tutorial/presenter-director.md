# Presenter Director — topic-tutorial v3

**Read first:** `skills/pipelines/avatar-spokesperson/asset-director.md` (presenter asset handling, lip-sync QA). Spec: `docs/topic-tutorial-v3-handoff.md` §5.5. Model tier: standard.

## topic-tutorial deltas

**The presenter is a beautified photoreal digital twin of the owner (D2).** Raw recordings are source material only — stored privately, never rendered, never copied under `projects/`. Every presenter asset must carry `identity_transform: "beautified"` and a `profile_id`; `lib/presenter_guard.py` rejects anything else. No Kling, no cloud avatars, no cartoon fallback.

### Per-video generation order
1. **Load the profile** (`presenter_profile`): locked, hashes verify. Not locked → stop; no-presenter or run onboarding.
2. **Wardrobe:** pick a catalog variant by topic tags or create a new simple one (Gemini image edit from `identity/canonical.png`, same face/lighting/framing); cache it in the profile. Log `presenter_wardrobe`.
3. **Motion source** (engine from the owner's bake-off default, announced at proposal; both stay supported):
   - **Hybrid:** if `loops/<variant>/idle.mp4` is missing, generate an 8–10 s idle loop (breathing, blinks, slight head motion, mouth closed) via `gemini_omni_video` (or `veo_video` with first=last frame if available). Paid call → must be itemized; announce first. API failure → ask the owner before using the Google Flow browser fallback (D8).
   - **Local:** LivePortrait retargets `raw/performance.mov` motion onto the variant image → `performance/<variant>.mp4` (overnight OK; run alone).
4. **Lip-sync** each presenter segment to its narration WAV with `twin_lipsync` (MuseTalk-MLX; LatentSync for full-screen if mouths look soft), looping/ping-ponging the motion source to length. Per-segment outputs so a long run resumes.
5. **Matte:** `presenter_matte` → alpha version (ProRes 4444 or VP9 alpha). The presenter is always a **separate alpha layer**, never baked into a plate.
6. **QA:** face present in ≥ 98 % of frames; mouth–audio offset within ±2 frames; no frame perceptually identical to `raw/` frames; `identity_transform == "beautified"`.
7. **Failure → no presenter:** re-plan presenter beats into visual beats, log `presenter_status: "skipped_failed"` with reason, surface at the assets gate.

### Layout presets (normalized, aspect-aware)
`presenter_fullscreen` (medium shot, safe headroom, lower-third badge), `presenter_pip` (≈ 22–28 % of width, safe corner, margins in normalized units, captions unobstructed), `presenter_screen_split` (≈ 35 % presenter / 65 % content).

### Memory
Never run lip-sync/LivePortrait concurrently with captures or Remotion renders; release MLX memory between steps. Any model download ≥ 500 MB: disk check + owner confirmation first.
