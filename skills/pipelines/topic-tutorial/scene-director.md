# Scene Director — topic-tutorial v3  🛑 gate

**Read first:** `skills/pipelines/explainer/scene-director.md` and `skills/pipelines/screen-demo/scene-director.md` (scene breakdown, callouts, zoom regions). Model tier: deep (plus `critic.scene_plan` = deep). Schema: `schemas/artifacts/scene_plan.schema.json` (v2).

## topic-tutorial deltas

- **Beats:** visual beats of 3–6 s inside script sections. Allowed beat types: `presenter_fullscreen`, `presenter_pip`, `presenter_screen_split`, `diagram`, `screenshot_callout`, `screen_recording`, `sandbox_capture`, `sourced_image`, `sourced_clip`, `chart`, `text_card` (≤ 10 % of runtime). Don't default to cards; every major claim needs diagram, capture or screenshot proof.
- **Presenter screen time (D10):** content-driven — full-screen for hook, section intros, outro; PIP on the low side (~30 % of remaining runtime). No hard limit. If the profile has no usable twin, plan the video **without presenter beats** (visual beats cover those lines).
- **focus_region:** every visual beat carries `focus_region` = normalized `{x,y,w,h}` (0–1) of what matters. Layout is expressed in **normalized units relative to the canvas**, never pixels — this keeps a later 9:16 re-layout cheap.
- **Capture scripts (§5.7):** every `sandbox_capture` beat embeds its **capture script** (JSON: `capture_id`, `surface` = `code_server|browser|terminal`, `allow_domains[]`, `steps[]` of known actions only). The owner reviews these at this gate. Typed text is visible and paced for viewers. Needing an account → include `await_owner_login`; the agent never types passwords. Default to public, no-login pages (D15). Real sandbox recordings are the default for code execution and website usage (D16); synthetic `TerminalScene` only for short idealized CLI snippets.
- **Diagram legibility:** at 1080p node labels ≥ 28 px, titles ≥ 44 px, contrast ≥ 4.5:1, ≤ 7 nodes per beat (progressive reveal for more). The validator at compose QA enforces this.
- **Rights:** `sourced_image`/`sourced_clip` beats reference a candidate from the research brief with its rights fields.
- Present: beat list, capture scripts, presenter time, card budget. Checkpoint `awaiting_human` and **end your turn**.

## Review focus / success criteria
Mirror the manifest: layout matches content type, presenter beats have a no-presenter plan, hierarchy/readability, every script scene has visual props and layout.
