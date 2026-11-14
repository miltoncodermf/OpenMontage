# Compose Director — topic-tutorial v3  🛑 gate

**Read first:** `skills/pipelines/explainer/compose-director.md`; then `skills/pipelines/topic-tutorial/review-director.md` for QA. Model tier: standard (frame review: fast).

## topic-tutorial deltas

- Route by `edit_decisions.render_runtime` as locked at proposal (`remotion` recommended for tutorials; `hyperframes` only if the owner chose it) at **1920×1080, 30 fps**. Blockers follow AGENT_GUIDE ("Escalate Blockers Explicitly"); no silent runtime swap.
- **Mastering:** EBU R128 two-pass to **−14 LUFS ±1, true peak ≤ −1 dBTP**.
- **QA** (see review-director): black/freeze frames, caption sync, **diagram legibility** (labels ≥ 28 px, titles ≥ 44 px at 1080p, contrast ≥ 4.5:1, ≤ 7 nodes per beat), and the **no-fixture check** — `video_compose` runs the honesty guard; a `TEST_ONLY_`/`tests/fixtures` asset forces `final_review.status = "fail"`.
- Produce a **contact sheet** and the render report for the gate. Never present a `revise`/`fail` review as complete. Checkpoint `awaiting_human` and **end your turn**.
- Never run Remotion concurrently with lip-sync or captures.

## Review focus / success criteria
Mirror the manifest: render at target resolution/fps, A/V in sync, no frozen/black frames; schema-valid `render_report`, final MP4 passes ffprobe.
