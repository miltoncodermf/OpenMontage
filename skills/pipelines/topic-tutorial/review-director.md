# Review Director — topic-tutorial v3

**Read first:** `skills/meta/reviewer.md` and `skills/pipelines/explainer/compose-director.md` (final self-review). Model tier: `qa.frame_review` = fast for frame inspection; verdict by the main session.

## topic-tutorial deltas

1. Probe the master with `ffprobe`: 1920×1080, 30 fps, h264 + aac.
2. Loudness: **−14 LUFS ±1**, true peak **≤ −1 dBTP**.
3. Black/frozen frames: none unexplained.
4. Caption sync: timestamps monotonic, inside audio bounds, matching speech.
5. Diagram legibility via the validator (≥ 28 px labels, ≥ 44 px titles, ≥ 4.5:1, ≤ 7 nodes).
6. **No-fixture check:** no asset path with `TEST_ONLY_` or `tests/fixtures`; presenter assets are beautified-twin assets or the presenter is honestly absent.
7. Write `artifacts/final_review.json` honestly. If a check was not run, say "not run". Never override a failing status.
