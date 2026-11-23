# Twin bake-off (P5) — STATUS: DONE. `engine_default = local`, mouth = C2

Spec: `docs/topic-tutorial-v3-handoff.md` D7, §5.5, §6 P5. Run on the owner's real, private profile (`~/.openmontage/presenter_profiles/ming/`, outside git) on a 24 GB Apple-silicon laptop. Everything below was measured on that profile; raw footage is only ever a driving signal and never appears in a rendered output. Decisions are in `projects/presenter-onboarding-ming/decision_log.json` (d-025 … d-030, gitignored with the project).

## Result

| | Local (LivePortrait + MuseTalk-MLX) | Hybrid (Gemini Omni idle loop + MuseTalk-MLX) |
|---|---|---|
| Cost | **$0** | **$1.0198** (one 10 s idle loop; estimate $1.0136, stop $1.216) |
| Head size variation (limit 3 %) | 1.1 % | 1.2 % |
| Brow repetition (mirror ≤ 0.80, autocorr ≤ 0.75) | 0.66 / 0.39 pass | **autocorr 0.96 fail** (the 10 s loop repeats 2.4× in a 24 s clip) |
| Blinks per minute (6–30) | 15.3 | 17.9 |
| Lip-sync wall time, 23.6 s narration | 204–223 s, peak 20.4 GB | 257 s |
| Matte wall time | 299–310 s | 313 s |
| One-time motion cost | LivePortrait 1142 s for a 24 s driving window (a pool, reused) | one paid call per outfit |

Owner decision (relayed verbatim): "The local is good enough to proceed - Gemini is not noticibly better to justify the cost." The profile's `engine_default` is `local`; the hybrid path stays supported in code but is not used. Total spend on this profile including identity work is $2.9688 (ledger `spend_ledger.json`), of which the engine test is the $1.0198 idle-loop call, approved by the owner in-session.

## What the free fixes were (all local, $0)

Owner feedback in order, each measured before and after:

1. **Eyes looking up, expression too serious.** Eye keypoints locked to the portrait; brow and cheek motion scaled to 0.6 around the clip mean; the sternest frame of the driving clip held as the reference; a 50 % blend of the original and the warm-smile portrait as the base (`expr_soft_smile`).
2. **Repeated eyebrow movement and head resizing.** A 24 s continuous driving window (33–65 s of the recording has no hands) instead of a short ping-pong loop; head pose smoothed (0.35 s) and damped; scale locked to frame 0; the compositor push-in removed for alpha presenters. Head size variation 4.2–5.4 % → 0.9–1.7 %; brow mirror 0.87–0.92 → 0.58–0.66.
3. **Blinks too hard.** The owner's own recording was measured (15 blinks in 68 s; close 33–67 ms, shut 2–3 frames, re-open 200–300 ms, median gap 3.2 s). Blinks now follow resampled real eyelid curves, rendered through LivePortrait's symmetric eye retargeting (`lib/blink_model.py`).
4. **Voice.** Pure owner clone (no donor voice) from the cleaned `voice_read_v2` window, 0.95 pace, per-sentence ASR check; locked (d-021 … d-024).

## Mouth lab (owner: moving mouth and diagonal creases look unnatural)

Measured against 24 s of the owner's real speech (`lib/mouth_metrics.py`): mouth opening is the gap between the lips divided by face width; **crease flicker** is how much the edge energy in the two cheek bands beside the mouth pulses from frame to frame (lower = steadier).

| Variant | What it is | Opening mean / p90 | Crease flicker | Crease level (real 1.72) |
|---|---|---|---|---|
| real speech | the owner | 0.041 / 0.052 | 0.112 | 1.72 |
| current (before) | whole-oval paste mask, LivePortrait lips moving | 0.052 / 0.067 | 0.076 | 1.35 |
| A | 25 % smile, openness 0.5, lips held still, lips+chin mask | 0.041 / 0.051 | 0.022 | 1.59 |
| B | 50 % smile, openness 0.35 | 0.043 / 0.055 | 0.039 | 1.43 |
| C1 | big mouth, LivePortrait lips held still, ellipse mask, colour match | 0.051 / 0.066 | 0.034 | 1.43 |
| **C2 (chosen)** | big mouth, lips held still, **lips-and-chin-only paste mask**, colour match | **0.052 / 0.068** | **0.029** | 1.58 |
| C3 | C2 with a tighter mask | 0.049 / 0.063 | 0.0235 | 1.63 |

The owner preferred the big mouth ("it makes people feel like it is actually speaking") and the small-mouth variants "feel not speaking naturally", so A/B were dropped; the remaining problem was the creases fading in and out. Cause: the smile base plus LivePortrait lip/jaw motion, which is out of sync with MuseTalk's mouth, was hidden by the whole-oval paste mask. C2 keeps MuseTalk openness 1.0, holds LivePortrait's lips still, pastes only lips and chin (the cheeks and the folds come from the stable portrait) and matches skin colour inside the mask. Crease flicker 0.076 → 0.029; opening unchanged. Real speech flickers more than any generated variant, so the aim is "no out-of-sync pulsing", not zero.

C2 is now the default of the natural bake-off script (`NATURAL_LIP_GAIN`, `NATURAL_MOUTH` in `scripts/twin_bakeoff_owner.py`) and of the tutorial batch runner (`lib/twin_segments.DEFAULT_MOUTH`). QA on all variants: face size 0.7–0.9 %, brow mirror 0.63–0.65, 15.3 blinks per minute, `final_review` pass in both layouts.

## Wall time of the local pipeline (23.6 s narration, one segment)

| Stage | Wall | Peak memory |
|---|---|---|
| Narration (Chatterbox, locked voice) | 47 s | 0.6 GB (plus the TTS worker) |
| LivePortrait (24 s driving → a reusable motion clip) | 1142 s — **one time per outfit, not per segment** | 0.1 GB (MPS) |
| MuseTalk-MLX lip-sync | 204 s | **20.4 GB** |
| Matte (BiRefNet) | 299 s | 6.1 GB |
| QA | 22 s | 0.2 GB |
| Remotion render, full screen / PIP | 62 s / 57 s | 0.5 GB |

Heavy stages are serialised by `lib/heavy_lock` and never overlap with renders.

## Known limits (honest)

- **The mouth-sync QA check is inconclusive for generated mouths** (the lip-gap vs audio-envelope correlation is not above its null), so mouth timing needs an ear; every other automated check runs.
- **Pale matte patch above the upper lip** (the portrait's stubble area) and a **faint light patch on the right cheek** after the narrower C2 mask: see the P6 section below for what was tried.
- **Motion variety is limited by the recording**: only ~32 s of the 68 s performance is hands-free, so a long tutorial replays motion from a pool of about 24 s (see P6).
- MuseTalk-MLX peak memory is 20 GB; no concurrent renders.
- GFPGAN-style sharpening is not installed (a ≥ 500 MB download needs the owner's OK); CodeFormer is non-commercial and must not be used.
- `reports/phase4_avatar_feasibility.json` ("MuseTalk infeasible", "LivePortrait 12–16 GB leak") is superseded by the measurements above.

## P6 (full-tutorial batching): see the section appended by the dry run
