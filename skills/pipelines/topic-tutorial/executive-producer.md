# Executive Producer — topic-tutorial v3

**Read first:** `skills/pipelines/explainer/executive-producer.md` (stage loop, decision contract, checkpoints). Spec of record: `docs/topic-tutorial-v3-handoff.md` — where this skill and the spec disagree, the spec wins.

## topic-tutorial deltas

### What this pipeline makes
A 16:9 (1920×1080, 30 fps) tutorial from one input — a **code repo, website URL(s), PDF(s) or a topic** (combinable, declared in `projects/<id>/inputs/inputs.yaml`) — presented by a **beautified digital twin of the owner**, with real sandbox-captured footage, diagrams and rights-cleared media.

### Stage loop
`research → proposal 🛑 → script → scene_plan 🛑 → assets 🛑 → edit → compose 🛑 → publish`.
For every stage: read the stage director skill, produce the canonical artifact, self-review (`skills/meta/reviewer.md`, max 2 rounds), checkpoint (`skills/meta/checkpoint-protocol.md`). Gates are the four 🛑 stages; each is a one-line `human_approval_default` toggle in the manifest. **Approval is per gate** — end your turn at each one. No autopilot in v3.

### Model routing (D12)
Read `config/topic-tutorial/model_routing.yaml` (`lib/model_routing.py`). For each stage, spawn a sub-agent with the Claude Code `Agent` tool, `model:` = the tier's `claude_code` value (`deep`=opus, `standard`=sonnet, `fast`=haiku), passing: the stage director skill path, input artifact paths, the expected output artifact path. Rules:
- The **main session** owns checkpoints, gates, `decision_log`, and all communication with the owner.
- Sub-agents **never** talk to the owner and **never** write checkpoints. They return the artifact and findings.
- Append one `decision_log` entry per stage (`category: "model_routing"`, `subject: "<stage> model"`), recording tier + `model_id`. Re-log with the same subject if the tier is changed.

### Presenter rule (D2, D3)
The presenter is the beautified twin from the locked profile in `~/.openmontage/presenter_profiles/<profile_id>/` (`OPENMONTAGE_PROFILE_ROOT` overrides). Preflight must confirm a **locked** profile exists; if not, stop and tell the owner to run `presenter-onboarding` (or proceed with **no presenter** if they say so). The owner's raw recordings are never rendered. If the twin cannot be produced or fails QA, the video is made **without a presenter** (`presenter_status: "skipped_failed"` + reason, surfaced at the assets gate). No stylized fallback, no Kling, no cloud avatar. A fixture/placeholder is never a presenter.

### Cost rule (D18)
Default $0. The proposal itemizes every paid call in `cost_estimate.paid_calls`; approval covers them up to estimate + 20 %. Before any paid call run `lib/paid_call_guard.check_paid_call(...)`; if it returns `allowed: false` (not itemized, or past 1.2× the approved total) **pause and ask**. Announce tool/provider/model/reason/sample-vs-batch before each paid call (AGENT_GUIDE). Set `ALLOW_PAID_APIS=true` only for the approved run.

### Never
- Run ad-hoc scripts instead of the director skills (Rule Zero). Count a `TEST_ONLY_` or `tests/fixtures` asset as real (the compose-time honesty guard fails `final_review`). Print, copy or commit the Gemini key from `.env`. Automate the owner's real desktop (captures run only in the disposable sandbox).

### Blockers
Use the AGENT_GUIDE structure: what was attempted / what failed / auth|access|tool bug|prompt quality / options / recommendation. Do not take a substitute path (including around any 🛑) without owner approval.

### Decision-log entries to write
`model_routing`, `render_runtime_selection`, `composition_mode`, `presenter_engine`, `presenter_wardrobe`, `voice_profile`, `music`, `playbook`, `capture_plan`, `alignment_method`, and any fallback. Append-only; re-log with identical (category, subject) when a choice changes.

## Review focus / success criteria
Mirror `pipeline_defs/topic-tutorial.yaml`. Success = every gate approved by the owner, `final_review.status == "pass"` honestly, no `TEST_ONLY_` assets, attributions present at publish.
