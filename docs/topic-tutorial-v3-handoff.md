# `topic-tutorial` v3 — Implementation Handoff Spec

**Audience:** Claude Sonnet 5.5 (implementer), running in Claude Code inside this repo.
**Author:** Claude Opus 5.5, after a grilling session with the project owner (2026-11-13).
**Status:** **This document is the single source of truth.** It supersedes
`~/Downloads/openmontage_topic_tutorial_master_blueprint.md`,
`reports/topic_tutorial_implementation_report.md`, `reports/topic_tutorial_baseline_audit.md`,
and any claim in `reports/phase*` files. Where code, skills, or reports disagree with this
document, this document wins.

---

## 0. How to use this document

1. Read `AGENT_GUIDE.md` and `PROJECT_CONTEXT.md` first (repo rule). Then read this whole spec before writing code.
2. Work on branch `feat/topic-tutorial-v3` (branch from `main`). Commit at the end of each phase with a message `feat(topic-tutorial-v3): phase N — <summary>`. Do not push unless the owner asks.
3. Phases are ordered by dependency (§6). Each phase ends with **acceptance checks** — run them and paste results into `reports/topic_tutorial_v3_progress.md` (append-only, one section per phase).
4. **Stop and ask the owner** at every point marked 🛑. Never work around a 🛑 by substituting another path.
5. Honesty rule: never count a fixture, placeholder, mock, or test asset as a real presenter, real capture, or real visual in any metric, report, or `final_review`. If something was not run, say "not run".
6. The repo already contains `.env` (gitignored, mode 600) with `GEMINI_API_KEY`. Never print, log, commit, or copy it into artifacts, sandboxes, or test fixtures.

---

## 1. What the product is

A **reusable, agent-driven pipeline** (`topic-tutorial`) that turns one input into a polished
16:9 tutorial video, presented by a **beautified digital twin of the owner**, with real
captured footage (code running, websites being used), diagrams, and researched media.

**Acceptance for this project (definition of done):** an agent (Claude Code, following
`AGENT_GUIDE.md` Rule Zero) can take any supported input the owner supplies and run
`topic-tutorial` stage by stage through the director skills and human gates, producing a
finished tutorial using the locked presenter profile — repeatably. The project's deliverable
is the pipeline, not a specific video. One validation run with the owner at the gates (Phase 9)
demonstrates it.

---

## 2. Honest status of the current code (as of `b4d5baf`)

What exists and is reusable:

| Area | Files | Verdict |
|---|---|---|
| Pipeline manifest | `pipeline_defs/topic-tutorial.yaml` | Keep, modify (gates, tools, stages). |
| Director skills (11) | `skills/pipelines/topic-tutorial/*.md` | **Skeletons — 248 lines total** vs ~3,100 for stock `explainer`. Rewrite as deltas (§5.2). |
| Ingestor | `tools/ingestion/universal_ingestor.py` (910 lines) | Keep security core (secret filename filter, symlink containment, SSRF, redaction). **Trim formats** (§5.3). |
| TTS | `tools/audio/mlx_tts_provider.py` (Kokoro MLX + Piper fallback) | Keep; extend for voice profile (§5.6). |
| Word alignment | `tools/audio/alignment_provider.py` | RMS-energy heuristic, **not** forced alignment. Demote to fallback; primary = whisperX via existing `tools/analysis/transcriber.py` (§5.8). |
| Scene cache | `lib/scene_cache.py` | Keep; hash is missing inputs (§5.8). |
| Scene plan v2 + adapter | `schemas/artifacts/scene_plan.schema.json`, `tools/video/scene_plan_adapter.py`, `lib/scene_plan_migration.py`, `lib/asset_resolver.py` | Keep; extend for aspect-agnostic layout (§5.9). |
| Remotion components | `remotion-composer/src/components/{DiagramScene,PresenterFullScreen,PresenterPip,PresenterScreenSplit,ScreenshotScene}.tsx`, `Explainer.tsx` | Keep; fix diagram legibility; make layout aspect-aware (§5.9). |
| Presenter providers | `tools/presenters/recorded_video_provider.py`, `gemini_personal_avatar_import.py` | `recorded_video` becomes an **onboarding source only** (never rendered). Gemini personal-avatar import: keep as dormant optional import, not part of default flow (clips are 3–10 s, prompt-driven audio — impractical). |
| Avatar | `tools/avatar/local_talking_head_provider.py` | Replace semantics with the twin engine (§5.5). |
| Flow import | `tools/video/google_flow_import_provider.py` | Keep; used by the browser-Flow fallback (§5.5). |
| Gemini video | `tools/video/gemini_omni_video.py` (cost guard), `tools/video/veo_video.py` | Reuse for idle-loop generation (§5.5). |
| Gemini image | `tools/graphics/google_imagen.py` (supports `image_paths` reference editing; `gemini-*-image` models) | Reuse for beautify/wardrobe (§5.5). |
| Background removal | `tools/enhancement/bg_remove.py` (rembg) | Reuse with a BiRefNet model for presenter mattes (§5.5). |
| Playbooks | `styles/topic-tutorial/*.yaml` + `styles/custom/*` | Keep. Only `software-technical` is verified in v3 (§5.10). |

What is **false or misleading** today and must be corrected in Phase 0:

1. The rendered "presenter" in `projects/tutorial-pipeline-mastery` is `tests/fixtures/topic_tutorial/presenter_fixture.mp4` — a teal square with a caption. The reported `presenter_percentage = 59%` counts it. Screenshot and screen recording are fixtures too.
2. "8/8 stages production verified" was a single 1,240-line script (`scripts/phase7_tutorial_pipeline_e2e.py`) with a hand-coded scene plan; no agent ran the director skills; no gates were exercised. This violates AGENT_GUIDE Rule Zero.
3. `presenter-director.md` makes a raw webcam recording the P0 presenter — contradicts the owner's rule that his raw face is never shown.
4. `alignment_provider` is described as "genuine word timestamps" — it is an energy heuristic.
5. `reports/phase4_avatar_feasibility.json` conclusions (e.g. LivePortrait "12–16 GB leak", MuseTalk "infeasible") are unverified; MuseTalk 1.5 has a native MLX port. Treat that report as unreliable.

---

## 3. Locked decisions

| ID | Decision |
|---|---|
| D1 | This spec is the source of truth. Old blueprint/reports are superseded; add a `> SUPERSEDED by docs/topic-tutorial-v3-handoff.md` banner to each old report (do not delete them). |
| D2 | **Presenter default = beautified photoreal digital twin of the owner.** If the twin cannot be produced or fails QA, the video is made **with no presenter** (visuals + narration). No stylized/cartoon fallback in v3 (deferred). **No Kling / cloud avatar** (removed entirely from this pipeline). |
| D3 | Owner's raw recordings are **source material only**, stored privately; **never rendered** in any video. Every presenter asset must carry `identity_transform: "beautified"` and originate from the presenter profile; a guard rejects anything else. |
| D4 | One-time **`presenter-onboarding` pipeline** builds a private **presenter profile** (identity pack + voice profile). Stored on the Mac internal drive at `~/.openmontage/presenter_profiles/<profile_id>/` (override: `OPENMONTAGE_PROFILE_ROOT`), dir mode 700, outside git. |
| D5 | Identity is created once and then **fixed**; per-topic variation is **simple wardrobe/hair** chosen by the agent from a catalog it can extend; variants are generated once and cached in the profile. |
| D6 | Beautify/wardrobe via **Gemini image API** (`google_imagen`, `gemini-3.1-flash-image` or `gemini-3-pro-image`), using the owner's stills as references. |
| D7 | Twin engine: build and **bake off two paths, keep both supported**: **(ii) Hybrid** — Gemini API (Omni/Veo) generates a seamless 8–10 s idle loop per outfit (once), then **local MuseTalk-MLX** lip-syncs it to the narration; **(i) Local** — LivePortrait transfers the owner's recorded talking performance onto the beautified portrait, then MuseTalk-MLX lip-syncs. Also test **LatentSync (local MPS)** for full-screen shots. Owner picks the default after seeing both. Long local/overnight runs are acceptable. |
| D8 | If the Gemini API route fails (no access/billing/quota), fallback for the idle loop = the agent drives **Google Flow** in the owner's browser (Claude in Chrome), owner confirms each generation and download in chat, then `google_flow_import`. |
| D9 | Voice: one-time voice design. Owner records ~3 min of his voice; agent builds ~8 candidates — **Chatterbox (MIT, MLX)** clones of the owner blended with other voices at several ratios + pure **Kokoro** voice blends — with a fixed polish chain. Owner picks once; voice is locked in the profile and used for every video. It need not match his real voice; it must be consistent, attractive, distinctive. |
| D10 | Presenter screen time is **content-driven**: full-screen for hook, section intros, outro; PIP on the low side (~30% of remaining runtime). No hard limit. |
| D11 | Supported inputs (combinable): **local code repo**, **website URL(s)**, **local PDF(s)**, **topic only** (agent researches). Remove all other format handlers. |
| D12 | **Per-stage model tiers** (deep / standard / fast) in one editable routing file; the main agent delegates each stage to a sub-agent on that model (§5.1). |
| D13 | Online research is first-class: (a) deep topic research → cited research brief; (b) media sourcing — real images, open-licensed clips, website screenshots/recordings — under a rights policy (§5.4). |
| D14 | **Computer control happens only in a disposable sandbox** (Apple `container`, one lightweight VM per container), started only for capture beats; the pipeline itself runs natively on macOS. Image definition is OCI-portable (Colima fallback, Docker optional). The owner's real desktop is never automated (§5.7). |
| D15 | Captures default to public, no-login pages. If an account is needed, pipeline pauses and the **owner logs in himself** inside the sandbox browser (dedicated test account). |
| D16 | Real sandbox recordings are the default for code execution and website usage; synthetic `TerminalScene` only for short idealized CLI snippets. |
| D17 | Human gates (OpenMontage rules respected): **proposal, scene_plan, assets, compose**. Each gate is a one-line toggle in the manifest so autopilot can be introduced later. No autopilot in v3. |
| D18 | Cost: default $0, low-cost allowed. Proposal itemizes every paid call with estimate; proposal approval covers them up to **estimate + 20%**; anything else pauses and asks. |
| D19 | Delivery: **16:9, 1920×1080, 30 fps**, 4–8 min typical, EBU R128 (−14 LUFS ±1, TP ≤ −1 dBTP). Implementation must make a later **9:16 re-layout of the same video** easy (§5.9). Do not build 9:16 now. |
| D20 | Only the `software-technical` playbook is verified in v3; others stay selectable but labeled `verified: false`. |
| D21 | Tests per pipeline: fast checks + one smoke test, run on every change. No overnight acceptance suite (§7). Delete `scripts/phase7_tutorial_pipeline_e2e.py`. |
| D22 | Word timing primary = whisperX forced alignment against known script text (existing `transcriber`); heuristic = fallback, flagged in the manifest. |

**Assumptions the owner has not explicitly decided (follow stock OpenMontage behavior; mention at proposal):** English only; music via the stock "Music Plan" at proposal (`music_library/` → search → generation → none); Remotion vs HyperFrames and templated vs atelier are presented at proposal per AGENT_GUIDE hard rules (recommend Remotion + templated for repeatable tutorials); publish = local bundle only (no upload).

---

## 4. Target architecture

```
                    ONE-TIME                                      PER VIDEO
┌───────────────────────────────────────┐   ┌──────────────────────────────────────────────────────┐
│ presenter-onboarding pipeline         │   │ topic-tutorial pipeline (runs natively on macOS)     │
│  capture_session  (owner records)     │   │  research   ← repo | URL | PDF | topic               │
│  identity_build   (Gemini image)      │   │     deep research (Opus plan, Sonnet workers)        │
│  identity_lock    🛑 owner picks       │   │     media sourcing + rights                          │
│  voice_lab        (Chatterbox/Kokoro) │   │  proposal   🛑 gate (cost itemized, runtime, music)   │
│  voice_lock       🛑 owner picks       │   │  script     (Opus)                                   │
│  → ~/.openmontage/presenter_profiles/ │──▶│  scene_plan 🛑 gate (beats, capture scripts, layout)  │
└───────────────────────────────────────┘   │  assets     🛑 gate                                   │
                                            │     narration (locked voice) → whisperX alignment    │
                                            │     twin: wardrobe variant → idle loop | perf. xfer  │
                                            │           → MuseTalk/LatentSync → matte (alpha)      │
                                            │     captures ──▶ [disposable Apple container sandbox]│
                                            │     diagrams, screenshots, sourced media             │
                                            │  edit       (frames, captions, layers)               │
                                            │  compose    🛑 gate (Remotion 1080p30, R128, QA)      │
                                            │  publish    (local bundle, attributions)             │
                                            └──────────────────────────────────────────────────────┘
```

---

## 5. Component specifications

### 5.1 Model routing (D12)

`pipeline_manifest.schema.json` forbids extra stage keys — **do not** add fields to the manifest. Create
`config/topic-tutorial/model_routing.yaml`:

```yaml
tiers:
  deep:     { claude_code: opus,   model_id: claude-opus-5-5,   gemini_cli: gemini-3.8-pro }
  standard: { claude_code: sonnet, model_id: claude-sonnet-5-5, gemini_cli: gemini-3.8-flash }
  fast:     { claude_code: haiku,  model_id: claude-haiku-5-5,  gemini_cli: gemini-3.8-flash-lite }
stages:
  research.plan_and_synthesize: deep
  research.search_workers:      standard
  proposal:                     deep
  script:                       deep
  scene_plan:                   deep
  critic.script:                deep
  critic.scene_plan:            deep
  assets:                       standard   # includes driving sandbox captures
  edit:                         standard
  compose:                      standard
  qa.frame_review:              fast
  publish:                      fast
onboarding:
  identity_build: standard
  voice_lab:      standard
```

(Verify Gemini CLI model names at implementation time; they are placeholders.) The
`executive-producer.md` skill must instruct: read this file; for each stage spawn a sub-agent
(Claude Code `Agent` tool, `model:` = tier's `claude_code`) with the stage director skill path,
input artifact paths, and expected output artifact; the **main session** owns checkpoints, gates,
decision_log, and all communication with the owner. Sub-agents never talk to the owner and never
write checkpoints. Record the model used per stage in `decision_log` (`category: "model_routing"`).
Add a fast test that every manifest stage has a routing entry.

### 5.2 Director skills as deltas on stock skills

Rewrite each `skills/pipelines/topic-tutorial/<stage>-director.md` as:

1. **"Read first:"** the stock skill(s) — `explainer/<stage>-director.md`, plus `screen-demo/<stage>-director.md` for scene/asset/edit stages.
2. **"topic-tutorial deltas:"** only what differs (inputs, presenter, captures, rights, gates, model tier).
3. Review focus + success criteria mirroring the manifest.

Required content per skill (minimum):

- `executive-producer`: stage loop, model routing (§5.1), gates (D17), profile loading, failure → no-presenter rule (D2), cost rule (D18), blocker escalation format from AGENT_GUIDE.
- `research-director`: input modes (§5.3), deep research protocol (§5.4a), media sourcing (§5.4b), research_brief requirements (every claim has `source_ref` with URL/file+line/page).
- `proposal-director`: 2–3 concepts; runtime + composition mode presentation (AGENT_GUIDE hard rules); music plan; **itemized paid-call table**; presenter plan (engine, outfit choice, screen-time estimate); capture plan summary; playbook choice with `verified` flag.
- `script-director`: 140–160 WPM; tutorial structure (hook ≤ 15 s → why → steps with proof → recap → CTA); every factual claim linked; mark lines intended for presenter full-screen vs voice-over.
- `scene-director`: visual beats 3–6 s; beat types (presenter_fullscreen, presenter_pip, presenter_screen_split, diagram, screenshot_callout, screen_recording, sandbox_capture, sourced_image, sourced_clip, chart, text_card ≤ 10% runtime); **capture scripts** (§5.7) embedded per capture beat for owner review at the gate; per-beat `focus_region` (§5.9); presenter screen-time target (D10).
- `asset-director` + `presenter-director`: narration with locked voice → alignment; twin generation order (§5.5); capture execution; rights recording; matte generation; manifest provenance; QA before the assets gate.
- `edit-director`: frame math at 30 fps from conditioned audio; captions; layer stack (background visual, presenter layer with alpha, captions, overlays).
- `compose-director` / `review-director`: render, R128 two-pass mastering, QA (black/freeze, caption sync, diagram legibility §5.9, no-fixture check), contact sheet for the gate.
- `publish-director`: local bundle; description with chapter timestamps + **attributions list** from asset rights.

Delete content from the current skills that conflicts with this spec (e.g. "recorded presenter P0").

### 5.3 Inputs & ingestion (D11)

Supported, combinable, declared in `projects/<id>/inputs/inputs.yaml`:

```yaml
topic: "How Apple Silicon unified memory speeds up local AI"   # optional
repos:  [ { path: "/Users/nathan/workspace/some-repo", focus: ["src/", "README.md"] } ]
urls:   [ "https://example.com/docs/getting-started" ]
pdfs:   [ "inputs/whitepaper.pdf" ]
```

- **Repo:** respect `.gitignore`; read code + markdown/text inside the repo; secret filename filter + redaction (existing); record file+line refs.
- **URL:** existing SSRF-safe fetch + readability extraction; also allow the research stage to request a sandbox **screenshot** of the page (§5.7) for visuals.
- **PDF:** `pypdf`; scanned PDFs with no text → `status: unsupported` with reason (no OCR in v3).
- **Topic only:** no ingestion; research stage does deep research (§5.4a).
- **Remove** docx/pptx/xlsx/csv/media/loose-file handlers and their tests from `universal_ingestor.py`; remove now-unused deps from requirements only if nothing else in the repo imports them (grep first).
- Keep prompt-injection posture: ingested content is **data**; facts extracted get `untrusted_source: true` until cross-checked.

### 5.4 Online research (D13)

**(a) Topic research.** Use the Claude `deep-research` skill pattern: deep-tier planner decomposes
the topic into questions; standard-tier workers search/read in parallel; planner synthesizes. Output
`research_brief` + `fact_sheet` where each fact has `claim`, `source_url`, `retrieved_at`,
`confidence`, `corroborated_by[]`. Minimum: every claim used in the script has ≥ 1 source; key
claims have ≥ 2 independent sources. Optional per-project toggle (set at proposal): Gemini Deep
Research via API as a second source — only if the key has access; otherwise log
`rejected_because`.

**(b) Media sourcing.** For each beat needing real-world media, preference order:

1. **Self-captured** in the sandbox: website screenshots/recordings, code running.
2. **Public-domain / open-licensed**: Wikimedia Commons, NASA, Pexels/Pixabay-type stock — reuse the registry's stock/archive search tools from `documentary-montage` (e.g. `direct_clip_search`, `clip_search`, `corpus_builder`; discover via registry, don't hardcode).
3. **Official press/media kits.**
4. **Copyrighted images** only as an attributed "screenshot of the source" with the URL visible on screen. **Never** third-party video clips (no YouTube rips).

Every sourced asset in `asset_manifest` records `rights_status`, `license`, `source_url`,
`attribution`, `retrieved_at`. Publish stage emits the attributions list.

### 5.5 Digital twin (D2–D8)

**Profile layout** (`~/.openmontage/presenter_profiles/<profile_id>/`, mode 700):

```
profile.json                 # schema: schemas/artifacts/presenter_profile.schema.json (new)
raw/                         # owner recordings — NEVER rendered, never copied into projects/
  face_turn.mov  performance.mov  voice_read.wav
identity/
  canonical.png              # locked beautified portrait (front, studio light)
  refs/*.png                 # extracted owner stills used as references
  wardrobe/<variant_id>.png  # outfit/hair variants (cached)
  wardrobe_catalog.json      # id, description, tags (e.g. coding, finance), prompt, created_at
loops/<variant_id>/idle.mp4  # (ii) seamless idle loop per variant
performance/<variant_id>.mp4 # (i) LivePortrait-transferred performance per variant
voice/
  voice_profile.json         # engine, params, embedding paths, polish chain, sample
  embedding.*  sample.wav
```

**Onboarding pipeline** `pipeline_defs/presenter-onboarding.yaml` + skills in
`skills/pipelines/presenter-onboarding/`:

1. `capture_session` 🛑 — print a recording protocol and wait for files: (1) ~30 s face turn, good even light, plain background; (2) ~60 s natural talking performance, head-and-shoulders, any words; (3) ~3 min voice read of a provided phonetically rich script, quiet room, 48 kHz. Validate with ffprobe (resolution ≥ 1080p, fps, duration, audio level/noise floor).
2. `identity_build` — extract sharp frontal/three-quarter stills (face detection via MediaPipe — Apache-2.0; **do not** use InsightFace weights, non-commercial); call Gemini image API with refs to produce 4–6 beautified canonical candidates (subtle: better skin/light/grooming/framing, still clearly the owner, photoreal, studio background, head-and-shoulders, neutral expression, mouth closed). Also produce 2–3 starter wardrobe variants.
3. `identity_lock` 🛑 — owner picks canonical (+ optional tweaks); lock in `profile.json`.
4. `voice_lab` — build candidates (§5.6). 🛑 owner listens and picks → `voice_lock`.
5. Write `profile.json` with hashes of every file; mark `locked: true`.

**Per-video twin generation** (assets stage), in order:

1. **Wardrobe:** agent picks a catalog variant by topic tags or creates a new simple one (Gemini image edit from `canonical.png`, same face/lighting/framing); cache it; log `decision_log` (`category: "presenter_wardrobe"`).
2. **Motion source** (engine chosen at proposal from the bake-off default):
   - **(ii) Hybrid:** if `loops/<variant>/idle.mp4` missing → generate an 8–10 s idle clip (subtle breathing, blinks, slight head motion, mouth closed) from the variant image via `gemini_omni_video` (or `veo_video` with first frame = last frame for a seamless loop if Veo is available). Model check at implementation: the key currently lists `gemini-omni-*-flash` models but **no Veo models**. If the API fails → D8 Flow fallback.
   - **(i) Local:** LivePortrait (MIT code; MPS; swap InsightFace for MediaPipe) retargets `raw/performance.mov` motion onto the variant image → `performance/<variant>.mp4`. Overnight-OK.
3. **Lip-sync** each presenter segment to its narration WAV with **MuseTalk 1.5 MLX** (`mlx-community/MuseTalk-1.5-fp16`) looping/ping-ponging the motion source to the needed length. For full-screen beats, also support **LatentSync 1.5/1.6** (Apache-2.0, MPS fork) if the bake-off shows MuseTalk's 256² mouth is too soft.
4. **Matte:** produce an alpha version (ProRes 4444 `.mov` or VP9 WebM with alpha) using `bg_remove` with a BiRefNet model (verify rembg supports it; else BiRefNet directly, MIT).
5. **QA:** face present in ≥ 98% frames; mouth-audio offset within ±2 frames (cross-correlate mouth-open area vs audio envelope, or SyncNet-style metric if available locally under a commercial-OK license); no frame identical to raw recordings (perceptual hash vs `raw/` frames must not match); `identity_transform == "beautified"`.
6. On any unrecoverable failure → **no-presenter fallback** for the video (D2): re-plan presenter beats into visual beats, log `presenter_status: "skipped_failed"` with reason, surface at the assets gate.

New tools (BaseTool subclasses, registered, `capability="avatar"` or as noted, each with
`install_instructions`, `get_status()` honest about missing weights):
`presenter_profile` (load/validate/guard), `twin_identity` (Gemini image wrapper for beautify/wardrobe;
may be a thin layer over `google_imagen`), `twin_idle_loop` (Omni/Veo wrapper + loop seam check),
`twin_performance_transfer` (LivePortrait), `twin_lipsync` (MuseTalk-MLX, LatentSync backends),
`presenter_matte`. Remove `local_talking_head` from the topic-tutorial manifest.

Model weights: keep the existing rule — any download ≥ 500 MB requires a disk check and 🛑 owner
confirmation; weight caches may stay on the external SSD via existing env vars (only the **profile**
lives on the internal drive).

### 5.6 Voice lab (D9)

Tool `voice_lab` (onboarding) + extend `mlx_tts` to synthesize from a `voice_profile`.

- **Chatterbox (MIT; `chatterbox-mlx`)**: clone from `raw/voice_read.wav`. Build blends by interpolating the speaker-conditioning embedding between the owner and 2–3 donor voices (donor reference clips can be rendered with Kokoro presets) at ratios ~70/30, 50/50, 30/70; vary `exaggeration`/`cfg`/pitch shift slightly. **Verify** the Chatterbox API exposes the speaker embedding for interpolation; if not, report and use the nearest available control (e.g. Qwen3-TTS base cloning in `mlx-audio`) — 🛑 tell the owner before switching engines.
- **Kokoro blends**: weighted averages of 2–3 preset voice style vectors + speed.
- ~8 candidates total, each reading the same ~20 s tutorial-style paragraph. Apply one **polish chain** to all (high-pass ~80 Hz, gentle presence EQ, de-ess, light compression, loudness normalize) so comparison is fair.
- Produce `voice/candidates/index.html` (local file) with an audio player per candidate + its recipe; 🛑 owner picks; lock recipe in `voice_profile.json` (engine, model version, embedding file + sha256, params, polish chain). Synthesis must be deterministic for a given text (fixed seed).
- Chatterbox outputs carry an inaudible Perth watermark — acceptable; note in profile.

### 5.7 Capture sandbox (D14–D16)

**Runtime:** Apple `container` (open source, Apache-2.0, macOS 26+, Apple Silicon; one lightweight
VM per container). Not installed yet — 🛑 owner installs it (needs admin password); provide exact
steps from the official repo. Fallback runtime: Colima (MIT). Implement a small runtime adapter
(`lib/sandbox/runtime.py`: `ContainerRuntime` interface with `AppleContainer`, `Colima`, `Docker`
implementations; detect what's installed).

**Image** (`sandbox/Dockerfile`, arm64 Linux, OCI-portable): Xvfb (1920×1080×24), a light window
manager, Chromium, code-server (VS Code in browser), a terminal (xterm or ttyd), ffmpeg, Playwright
(Python), common runtimes (python3, node). Non-root user `capture`. No secrets baked in.

**Tool `sandbox_capture`** (BaseTool, `capability="screen_capture"`, runtime LOCAL):

- Inputs: `workspace` (path to a **prepared copy**), `script` (capture script, below), `allow_domains[]`, `resolution` (default 1920×1080), `fps` 30, `max_duration_s`, `output_dir` under `projects/<id>/assets/captures/`.
- Workspace prep (host side): copy the repo subset to `projects/<id>/.sandbox/<capture_id>/workspace`, excluding `.git` remotes/credentials, `.env*`, keys, and anything the ingestor's secret filter flags; run redaction over text files.
- Mounts: only that workspace copy (read-write inside, it's a copy) and an output dir. **Never** mount `$HOME`, `~/.ssh`, keychain, the repo root, or `.env`.
- Limits: `--cpus 4 --memory 4G` (configurable), wall-clock timeout, kill on timeout.
- Network: default deny; allow only `allow_domains` (enforce via an in-container egress proxy that Chromium/package managers must use, plus iptables owner-match so the `capture` user cannot bypass it). Document the residual risk honestly.
- Recording: ffmpeg `x11grab` of the Xvfb display at 30 fps → H.264 (CRF ~18). Also save step screenshots (PNG) and a JSON step log with timestamps (used by edit for sync and by callouts).
- Teardown: container deleted after each capture; keep outputs only.
- Never run concurrently with MuseTalk/LatentSync/Remotion renders (memory).

**Capture script format** (authored by the scene director, shown at the scene_plan gate):

```json
{
  "capture_id": "c3_run_tests",
  "surface": "code_server" ,                      // code_server | browser | terminal
  "allow_domains": ["pypi.org", "files.pythonhosted.org"],
  "steps": [
    {"action": "open_file", "path": "src/app.py", "line": 42},
    {"action": "type_in_terminal", "text": "python -m pytest -q", "wpm": 220},
    {"action": "wait_for_text", "text": "passed", "timeout_s": 60},
    {"action": "screenshot", "label": "tests_passed"},
    {"action": "navigate", "url": "https://example.com/docs"},
    {"action": "click", "selector": "text=Get started"},
    {"action": "pause", "seconds": 1.5}
  ]
}
```

Unknown actions fail validation. Typed text is visible and paced for viewers. **Login flow (D15):**
action `await_owner_login` pauses, exposes the sandbox browser to the owner (VNC/noVNC on localhost
only), owner logs in to a dedicated test account, owner confirms in chat, script continues. The
agent never types passwords.

Existing host-capture tools (`screen_recorder`, `cap_recorder`) are **not** used by topic-tutorial.

**Image/container hygiene (added after the owner's request):** the image is tagged `openmontage-capture:<12-hex sha256 of sandbox/>`; every `build_image` (and every `run`/`start`, and the `cleanup` operation) removes all other `openmontage-capture` images, dangling images, stale `om-capture-*` containers (never one in progress) and stops the Apple builder VM — scoped strictly to our repository/name prefix/role label (see `sandbox/README.md`).

### 5.8 Narration, alignment, cache

- Narration per section via `mlx_tts` with the locked `voice_profile`; pad + condition as today; two-pass R128 master at compose.
- **Alignment:** call `transcriber` (whisperX) with the known script text and keep word timings; map recognized words back to script tokens (handle numbers/punctuation); if alignment confidence is low or the tool is unavailable, fall back to `alignment_provider` and set `alignment_method: "heuristic"` in the manifest (surfaced at the assets gate). On Apple Silicon run whisperX on CPU; if too slow, consider `mlx-whisper` word timestamps — document the choice in `decision_log`.
- **Scene cache hash** (`lib/scene_cache.py`) must add: sha256 of every input asset referenced by the scene (presenter clip, capture, screenshot, sourced media, diagram spec), `renderer_version` (hash of `remotion-composer/src` relevant components or package version + git tree hash of that dir), `tts_model` + voice profile hash, `aspect` (`16:9`). Add a fast test: changing any one of these invalidates the cache.

### 5.9 Composition, legibility, 9:16 readiness (D19)

- Presenter is always a **separate layer with alpha** (from §5.5 step 4) composited by Remotion — never baked into a background plate.
- Each visual beat in `scene_plan` carries `focus_region` (normalized `x,y,w,h` of what matters) and layout is expressed in **normalized units relative to canvas**, not pixels. The adapter computes pixel layout from `canvas: {width, height}`.
- Remotion: `Explainer` takes width/height from props via `calculateMetadata` (Root already has a 1080×1920 composition — reuse that pattern). Layout presets (`presenter_pip`, `presenter_screen_split`, fullscreen) are functions of aspect; implement 16:9 only, but structure code as `layouts/landscape.ts` with an obvious `layouts/portrait.ts` slot. Caption safe areas also normalized.
- Add one fast test that compiles the same scene plan to props for **both** 16:9 and 9:16 canvases without error (portrait may use a trivial placeholder layout — it only proves the seam exists).
- **Diagram legibility:** at 1080p, node labels ≥ 28 px, titles ≥ 44 px, min contrast 4.5:1, ≤ 7 nodes per beat (progressive reveal for more). Scale with canvas height. Enforce in a validator (`composition_validator` extension or new check) used at compose QA and in a fast test. Current diagrams (~10 px labels) fail this.

### 5.10 Playbooks (D20)

Add `verified: true|false` to each `styles/topic-tutorial/*.yaml` (only `software-technical: true`
after Phase 9). Check `schemas/styles/playbook.schema.json` allows the key; if not, put the flag in
a sidecar `styles/topic-tutorial/verification.yaml`. Proposal must show the flag.

### 5.11 Gates, cost, decision log (D17–D18)

- Manifest: `human_approval_default: true` for `proposal`, `scene_plan`, `assets`, `compose`; false elsewhere.
- Proposal packet includes `paid_calls[]`: `{tool, provider, model, purpose, units, unit_cost, est_usd}` and `total_est_usd`. Track actuals with `tools/cost_tracker.py`; before any paid call, if `actual + next_est > 1.2 × total_est_usd` or the call is not in the list → pause and ask.
- Set `ALLOW_PAID_APIS=true` only for the approved project run (respect existing guards in `gemini_omni_video`: `GEMINI_VIDEO_ENABLED`, budget ceiling). Keep `ALLOW_PAID_APIS=false` default in `.env`.
- `decision_log` entries (append-only, AGENT_GUIDE re-log rule) for: model_routing, render_runtime_selection, composition_mode, presenter_engine, presenter_wardrobe, voice_profile, music, playbook, capture_plan, alignment_method, any fallback.

---

## 6. Phased plan

Dependencies: P0 → P1 → (P2, P3, P4 in any order) → P5 → P6 → P7 → P8 → P9.

**P0 — Truth reset & cleanup**
- Delete `scripts/phase7_tutorial_pipeline_e2e.py`. Add SUPERSEDED banners to old reports (D1).
- Remove fixture presenter/screens from any metric; move fixtures to `tests/fixtures/topic_tutorial/` only with filenames prefixed `TEST_ONLY_`, and add a guard: assets whose path contains `TEST_ONLY_` or `tests/fixtures` make `final_review.status = "fail"` outside test mode.
- Trim ingestor (§5.3). Remove `local_talking_head`, `recorded_video` (as presenter), Kling tools from the topic-tutorial manifest.
- ✅ Fast tests green; `grep -r "presenter_fixture" tools lib skills pipeline_defs` returns nothing outside tests.

**P1 — Skills, routing, gates**
- `config/topic-tutorial/model_routing.yaml` (§5.1); rewrite 11 skills as deltas (§5.2); manifest gates (§5.11); proposal paid-call table.
- ✅ Manifest validates; routing test passes; each skill references its stock counterpart file and the file exists (fast test).

**P2 — Inputs & research**
- `inputs.yaml` contract; repo/URL/PDF/topic modes; deep-research protocol in skill; fact_sheet schema fields; media sourcing + rights fields; attributions in publish.
- ✅ Fast tests: each input mode produces a schema-valid `input_manifest` (tiny fixtures; URL test mocked); rights fields required for `sourced_*` assets.

**P3 — Capture sandbox**
- 🛑 Owner installs Apple `container`. Build image; `lib/sandbox/runtime.py`; `sandbox_capture` tool; capture-script schema + validator; network allowlist; workspace prep with secret exclusion; teardown.
- ✅ Fast tests: script validator, workspace prep excludes `.env`/keys/.git credentials, runtime adapter selection (mocked). Manual check (record in progress report): a 10 s capture of `python -c "print('hello')"` in code-server and a 10 s browser capture of an allowed public page; a request to a non-allowed domain is blocked.

**P4 — Presenter onboarding (identity + voice)**
- Profile schema + `presenter_profile` tool + guard (D3); onboarding manifest + skills; `twin_identity`; `voice_lab`; candidate HTML page.
- 🛑 Owner recording session → 🛑 identity pick → 🛑 voice pick.
- ✅ Profile locked with hashes; guard rejects a raw recording passed as presenter (fast test with a tiny generated clip).

**P5 — Twin bake-off** 🛑
- Implement minimal versions of `twin_idle_loop` (ii), `twin_performance_transfer` (i), `twin_lipsync` (MuseTalk-MLX; LatentSync for full-screen), `presenter_matte`.
- Produce the **same 20 s narration** (locked voice) with: (ii) PIP + full-screen, (i) PIP + full-screen, and LatentSync full-screen variant. Record wall-clock, peak memory, cost.
- First paid call (Omni/Veo idle loop): announce tool/model/estimated cost and 🛑 get owner OK. If the API fails (access/billing), 🛑 ask before using the Flow browser fallback (D8).
- Write `reports/twin_bakeoff.md` with side-by-side clips and numbers. 🛑 Owner picks default engine (keep both supported).

**P6 — Productionize twin + assets stage**
- Harden chosen tools: looping/ping-pong, segment batching, overnight resumability (per-segment outputs + checkpoint `partial_progress`), QA checks (§5.5 step 5), no-presenter fallback path.
- Narration with voice profile; whisperX alignment (§5.8); cache hash (§5.8).

**P7 — Edit/compose/legibility/aspect seam**
- Layer stack with alpha presenter; normalized layout + `focus_region`; diagram legibility validator; 16:9 + 9:16 props compile test; R128; QA rejects fixtures.

**P8 — Tests consolidation** (§7). Remove obsolete tests tied to deleted code.

**P9 — Validation run (owner at gates)**
- Owner supplies an input (suggest: this repo + one public docs URL). Agent runs the full pipeline per Rule Zero, through all 4 gates. Fix defects found; re-run affected stages only.
- ✅ Done when: owner approves at compose gate; `final_review` passes honestly; no `TEST_ONLY_` assets; progress report updated; `software-technical` marked `verified: true`.

---

## 7. Testing strategy (D21)

Keep it lean. Two layers, both in `tests/contracts/test_topic_tutorial.py` (split into
`test_topic_tutorial_fast.py` and `test_topic_tutorial_smoke.py` if clearer):

**Fast checks** (no models, no network, no sandbox; whole file < 30 s; run on every change):
manifest + routing coverage; skills reference existing stock files; artifact schemas (scene_plan v2
with `focus_region`, asset_manifest rights fields, presenter_profile, capture script);
scene_plan → props for 16:9 and 9:16; cache-key invalidation per field; guards (raw recording as
presenter rejected, `TEST_ONLY_` asset fails final review, paid call blocked when not approved /
over 1.2×, no-presenter fallback re-plans beats); ingestor modes + secret exclusion; sandbox
workspace prep exclusions; diagram legibility validator.

**Smoke test** (opt-in marker `@pytest.mark.smoke`, ≤ ~3 min, local only, no paid APIs): tiny
input → Kokoro narration (2 sentences) → alignment → render a 10 s 1280×720 Remotion clip with a
diagram beat and a `TEST_ONLY_` presenter layer → ffprobe streams/duration, loudness within
target, caption timing monotonic and within audio bounds, and `final_review` correctly **fails**
because of the `TEST_ONLY_` asset (proves the honesty guard) while a variant without it passes.
Skip cleanly (not fail) when Kokoro/Remotion are unavailable, with a clear reason.

Run: `.venv/bin/pytest tests/contracts/test_topic_tutorial*.py -q` (fast) and
`.venv/bin/pytest -m smoke tests/contracts/test_topic_tutorial*.py -q` (smoke). Also keep the full
`tests/contracts/` suite green.

No overnight/manual acceptance suite; human review happens at the gates during real runs.

---

## 8. Out of scope (v3)

9:16 rendering (only the seam); stylized/cartoon presenter; Kling or any cloud talking-avatar; voice
matching the owner exactly; autopilot (no gates); OCR for scanned PDFs; docx/pptx/xlsx/csv/media
inputs; macOS-VM captures of Mac-only apps; automated upload/publishing; non-English.

---

## 9. Risks & things to verify early

| Risk | Mitigation |
|---|---|
| Gemini key: owner confirms **billing is enabled**; but **no Veo models listed** for this key (Omni flash models are) | Use `gemini_omni_video` for the idle loop; confirm with the first (approved) call in P5; fallback D8. |
| MuseTalk 256² face crop looks soft full-screen | LatentSync for full-screen beats; frame full-screen as medium shot; decide in bake-off. |
| LivePortrait on MPS slow / memory-hungry | Overnight OK; run alone; measure in P5; MediaPipe instead of InsightFace (license). |
| Chatterbox may not expose embedding interpolation | Verify in P4; 🛑 before switching engine. |
| Apple `container` networking/allowlist limits | Egress proxy + iptables inside; Colima fallback; document residual risk. |
| 24 GB unified memory contention | Never run captures, lip-sync, and Remotion concurrently; release MLX memory between steps. |
| Licenses | Only commercial-OK components: MuseTalk (MIT; check dependency weights), LatentSync (Apache-2.0), LivePortrait code MIT (no InsightFace weights), Chatterbox (MIT), Kokoro (Apache-2.0), BiRefNet (MIT), Apple container (Apache-2.0), Colima (MIT). Record license per model in tool metadata; verify upstream files before downloading. |
| Rights of sourced media | Policy §5.4b; attributions in publish. |

---

## 10. Owner touchpoints summary (🛑)

1. Install Apple `container` (P3).
2. Recording session (~10 min) → identity pick → voice pick (P4).
3. Approve first paid idle-loop call; approve Flow fallback if needed (P5).
4. Pick twin default after bake-off (P5).
5. Any model download ≥ 500 MB.
6. Pipeline gates on every run: proposal, scene_plan, assets, compose.
7. Sandbox logins, when a capture needs an account (owner types credentials).
