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
- **Pale matte patch above the upper lip / right-cheek patch**: see "Open items" below (texture restore added; the cheek patch could not be measured).
- **Motion variety is limited by the recording**: only ~32 s of the 68 s performance is hands-free, so a long tutorial replays motion from a pool of about 24 s (see P6).
- MuseTalk-MLX peak memory is 20 GB; no concurrent renders.
- GFPGAN-style sharpening is not installed (a ≥ 500 MB download needs the owner's OK); CodeFormer is non-commercial and must not be used.
- `reports/phase4_avatar_feasibility.json` ("MuseTalk infeasible", "LivePortrait 12–16 GB leak") is superseded by the measurements above.


## P6 — the local engine for a full tutorial (batched, resumable)

Code: `lib/twin_segments.py` (planner, state, QA gates, summary), `scripts/twin_tutorial_segments.py` (runner), manifest = one JSON (`motion_pool`, `segments[{segment_id, beat_id, title, text}]`; `manifest_from_scene_plan()` builds it from a v2 scene plan: one segment per script section that has a presenter beat). Outputs go to `projects/presenter-onboarding-<profile>/engine_p6/<run_id>/` (gitignored).

```
python scripts/twin_tutorial_segments.py run    <manifest.json>    # resumes where it stopped
python scripts/twin_tutorial_segments.py status <manifest.json>
```

**Per segment, in order:** narration (locked voice, cached by hash of voice-profile + text) → alignment (ASR-anchored, flagged if heuristic) → motion (planned from the pool) → MuseTalk lip-sync (C2 + texture) → **QA** → matte → full-screen preview render + minted `presenter_video`/`presenter_matte` assets. Each stage runs in its own process under `/usr/bin/time -l` (memory returns to the OS; wall time and peak footprint per stage are recorded). `run_state.json` is written atomically after every stage with an input-hash key; a stage is skipped on resume only when its key matches and its output exists. A stage process watches the orchestrator and exits if it is killed (no orphan holding the heavy lock).

**QA on every segment** (before the expensive matte): face presence, face scale (≤ 3 %), brow repetition, blink rate (6–30/min), no raw frames (hash comparison against the recordings), crease flicker (≤ 0.06), mouth opening (mean 0.03–0.08 of face width), mouth sync. Mouth sync is reported as `inconclusive` and shown as a warning (it needs an ear); a check that cannot run blocks the segment. A segment that fails becomes `fallback`: the run continues, `run_report.json` lists the reason per beat, and `fallback_scene_plan()` converts exactly those beats to visual beats (`presenter_status: partial`) so the video is made without the presenter there and says so.

**Motion without visible looping.** The LivePortrait clip is a pool (here one 24 s clip). Per segment, chains of ~6 s pieces are cut from the pool, chosen where the pool has been used least so far, preferring starts whose first frame resembles the previous piece's last frame, and joined with 0.7 s cross-dissolves. The plan is deterministic (seed), so a resume rebuilds the same one. **Honest limit:** only ~32 s of the 68 s recording is hands-free, so the pool is 24 s; a long tutorial replays motion. In the dry run the cumulative replay was 5 % after segment 1, 41 % after 2, 60 % after 3 (any moment used up to 4 times), and brow mirror correlation rose 0.63 → 0.67 → 0.70 (limit 0.80). Pieces are 6 s and dissolved, so it does not loop visibly, but a 10-minute tutorial would exceed the limit. **Recommendation:** record 2–3 more minutes of hands-free talking (and run LivePortrait on each window once, ~48 s per driving second); the planner takes any number of pool clips and spreads over them automatically.

### Dry run (3 segments, 52.0 s narrated, `p6_dry`)

Segments 17.8 s, 18.1 s, 16.1 s; all three passed every QA gate, final review passed, nothing paid.

| Segment | Face size var. | Brow mirror | Crease flicker | Mouth opening | Wall | Wall per narrated s |
|---|---|---|---|---|---|---|
| s1 | 1.0 % | 0.63 | 0.024 | 0.043 | 654 s | 36.7 |
| s2 | 1.6 % | 0.67 | 0.024 | 0.046 | 657 s | 36.4 |
| s3 | 1.2 % | 0.70 | 0.027 | 0.041 | 518 s | 32.2 |

**Kill and resume (deliberate):** the orchestrator was killed with `kill -9` 65 s into segment 2's lip-sync (21:41:43). No stage process survived. Restart 12 s later skipped everything finished (segment 1 complete; narration, alignment and motion of segment 2 from cache/state) and redid only the interrupted lip-sync; the final result is identical in structure to an uninterrupted run. The cost of the kill was the 65 s of lost lip-sync plus the restart.

**Wall time per narrated second** (sum of stage wall times over 52.0 s narrated = 1829 s; clock time of the whole run incl. the kill 1908 s, i.e. 36.7):

| Stage | Per narrated second | Notes |
|---|---|---|
| Matte (BiRefNet) | 14.4 s | peak 6.1 GB |
| MuseTalk lip-sync | 10.7 s | peak 20 GB |
| Narration | 4.4 s | includes a ~60 s model load per segment (one process per stage); batching narrations in one process would cut this |
| Preview render (per segment) | 3.0 s | not needed for the final tutorial render, which is one Remotion render; that costs about 2.5–3 s per narrated second |
| QA | 2.4 s | |
| Alignment + motion | 0.2 s | |
| **Total** | **35.2 s** | |

Estimate: **a tutorial with N minutes of presenter narration takes about 35 × 60 × N s ≈ 0.6 h per presenter minute** (a 10-minute presenter share ≈ 6 h, overnight-able; without the per-segment preview and with batched narration ≈ 28 s per narrated second ≈ 0.47 h per minute). One-time: LivePortrait ≈ 48 s per second of driving window per outfit. Matte cost is lower for picture-in-picture segments only if they are rendered smaller (not yet done).

### Open items

- **Pale matte patch above the upper lip.** Cause found: the portrait itself has a grey stubble band there (visible in the unprocessed portrait), with fine stubble texture; the MuseTalk decode is a 256 px face, so inside the paste mask that texture is lost and the band reads as smooth and matte. Fix added: `texture` option in `lib/musetalk_runner.py` (`texture_restore`): in the paste mask, on skin-coloured pixels only (lips, teeth and the mouth opening are gated out), the source frame's fine detail is added back in proportion to the paste weight. On an 8 s excerpt it leaves everything else unchanged (opening 0.057 vs 0.057, crease flicker 0.0255 vs 0.0247, teeth shown 60 % both, sharpness ratio 0.90 vs 0.84) and visibly brings back chin and upper-lip grain (before/after crops are in `engine_p6/texture_lab/`). It does not change the band's grey tone, which is the portrait's own. It is now part of the default mouth (`DEFAULT_MOUTH`, `NATURAL_MOUTH`); `"texture": 0` gives plain C2. The effect is subtle; the dry run above was made without it (it was added after), so a full-tutorial render will include it and the numbers should be re-checked then.
- **Faint right-cheek patch.** Measured in motion on the C2/C3 clips (150 frames, a region beside and below the right mouth corner): brightness 99.4 / 98.7 vs 101.7 for the unprocessed motion source, texture equal (Laplacian variance 13.0 / 12.8 vs 11.7), chroma identical. Crops of three moments show no patch. Not reproduced in measurement, so no fix; if the owner still sees it, point at a timestamp.
- **Mouth sync** stays inconclusive by the automatic check (needs an ear).
