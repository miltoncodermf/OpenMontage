# Proposal Director — topic-tutorial v3  🛑 gate

**Read first:** `skills/pipelines/explainer/proposal-director.md` (concepts, runtime selection, approval gate). Model tier: deep.

## topic-tutorial deltas

Present **2–3 differentiated concepts** and, in one reviewable packet (`proposal_packet` + `decision_log`):

1. **Runtime + composition mode** — AGENT_GUIDE hard rules: present **both** Remotion and HyperFrames — `render_runtime` is `remotion` or `hyperframes`, locked here (one-sentence strength, honest tradeoff, recommendation) and templated vs atelier. For repeatable tutorials recommend **Remotion + templated**; say atelier costs more. Log `render_runtime_selection` and `composition_mode` with full `options_considered`.
2. **Music plan** — stock Music Plan: `music_library/` → search → generation → none; log `music`.
3. **Itemized paid-call table** — `cost_estimate.paid_calls[]`: `{tool, provider, model, purpose, units, unit_cost, est_usd}` plus `total_est_usd` (default $0.00). Typical entries: Gemini image calls (wardrobe variants), `gemini_omni_video` idle loop (hybrid engine only), optional Gemini Deep Research. Approval covers these up to **estimate + 20 %**; anything else pauses and asks (`lib/paid_call_guard.py`).
4. **Presenter plan** — engine (`hybrid` vs `local`, from the owner's bake-off default — log `presenter_engine`), outfit choice (existing catalog variant or new simple one — log `presenter_wardrobe`), screen-time estimate (content-driven: full-screen for hook, section intros, outro; PIP on the low side, ~30 % of the remaining runtime), and the no-presenter fallback statement (D2).
5. **Capture plan summary** — which beats need sandbox captures, target surfaces, domains to allow, whether any login is needed (owner logs in himself — D15). Log `capture_plan`.
6. **Playbook** — choice plus its `verified` flag, read from `lib/playbook_verification.py` (`config/topic-tutorial/playbook_verification.yaml`; `software-technical` becomes verified only after the owner approves a real run at the compose gate — until then every playbook is labelled `verified: false`). Log `playbook`.
7. **Assumptions to state** (not owner-decided): English only; local bundle publish only (no upload); 16:9 first (9:16 re-layout is a later, easy change).
8. Runtime estimate (4–8 min typical) and target loudness.

Do not set `approval.status` yourself. Write the checkpoint `awaiting_human` and **end your turn**.

## Review focus / success criteria
Mirror the manifest: paid calls itemized, presenter/capture/music plans visible, runtime + mode logged, playbook flag shown.
