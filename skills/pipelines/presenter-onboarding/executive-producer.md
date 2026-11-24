# Executive Producer — presenter-onboarding

One-time pipeline that builds the owner's **private presenter profile** used by every `topic-tutorial` video. Spec: `docs/topic-tutorial-v3-handoff.md` §5.5–5.6. Also read `skills/meta/checkpoint-protocol.md`.

## Rules
- Run each stage's director skill in order: `capture_session` 🛑 → `identity_build` → `identity_lock` 🛑 → `voice_lab` → `voice_lock` 🛑. Checkpoint per stage; end your turn at each 🛑.
- Model tiers: `onboarding.identity_build` and `onboarding.voice_lab` = standard, effort medium (`config/topic-tutorial/model_routing.yaml`; pass `model_for_stage(<key>, section="onboarding")` model and effort to the `Agent` tool). The main session owns checkpoints and all owner communication; sub-agents never talk to the owner.
- The profile lives at `~/.openmontage/presenter_profiles/<profile_id>/` (`OPENMONTAGE_PROFILE_ROOT` overrides), directory mode 700, **outside git and outside `projects/`**. Use `presenter_profile` (`init` first). Never copy anything from `raw/` anywhere else.
- The owner's raw recordings are **source material only — never rendered** in any video. Only beautified assets (`identity_transform: "beautified"`) leave the profile.
- Paid calls: the Gemini image calls (beautify, wardrobe) are paid. Announce tool/provider/model/estimate, itemize them, and wait for the owner's explicit OK before the **first** call (🛑). Set `ALLOW_PAID_APIS=true` and `paid_call_approved: true` only after that OK. Never print, log or copy the Gemini key.
- Model downloads ≥ 500 MB (e.g. Chatterbox weights): disk check + owner confirmation first.
- Never substitute a different engine or path around a 🛑; blockers follow the AGENT_GUIDE structure.
- Honesty: never describe a fixture or placeholder as a real recording or identity.

## Failure handling (all stages)
Report failures in the AGENT_GUIDE blocker format (what failed, why, options, recommendation). Validator failure → re-record request (capture); identity drift → regenerate within the approved budget (build); rejected voices → round 2 with new ratios (lab). Never lower a threshold, reuse a fixture, or switch engine/path to get past a failure.
