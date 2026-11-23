---
description: Make a video tutorial about a code repo, web page, document or topic with the OpenMontage topic-tutorial pipeline (presenter twin, sandbox captures, diagrams). Inputs can be combined.
argument-hint: <folder | repo URL | web URL | document | "topic"> ... [--length MIN] [--aspect 16:9|9:16|both] [--presenter ID|none] [--audience TEXT] [--title TEXT]
---

Make a tutorial from this request:

**Request:** $ARGUMENTS

## 1. Find the engine

The engine is the OpenMontage checkout: `$OPENMONTAGE_HOME` if it is set, otherwise `~/workspace/OpenMontage`. Confirm it with:

```bash
OM="${OPENMONTAGE_HOME:-$HOME/workspace/OpenMontage}"; test -f "$OM/AGENT_GUIDE.md" && test -x "$OM/.venv/bin/python" && echo "engine: $OM"
```

If that fails, stop. Tell the owner to set `OPENMONTAGE_HOME` to their OpenMontage folder, which must have its `.venv` set up.

From here on, `$OM` means that folder. Use absolute paths under it for every file you read or write.

When this session's folder is not `$OM`, the engine's own instructions are not loaded. Read `$OM/AGENT_GUIDE.md` now and follow it like project instructions for the rest of this task.

## 2. Turn the request into a project

1. Split the request into input tokens and options.
   - **Inputs:** a token is any of the following. Keep a quoted multi-word topic as one token.
     - a folder (`.` = the folder this session is in)
     - a GitHub/GitLab/Bitbucket repo URL
     - a web URL
     - a document: PDF, Markdown, text, Word, RTF or HTML
     - topic words
   - **Options:** `--length`, `--aspect`, `--presenter`, `--audience`, `--title`.
2. Run the resolver from the engine folder. Pass this session's folder as `--cwd`, and shell-quote each token separately:

```bash
cd "$OM" && .venv/bin/python -m lib.tutorial_request --cwd "<this session's folder>" <quoted tokens and options>
```

What the resolver does:
- **Repo URLs:** shallow-clones them into the project.
- **Markdown, text, Word, RTF and HTML documents:** converts them to PDF, because the pipeline reads only PDFs.
- **Local folders and PDFs:** references them in place and never modifies them.
- **Presenter:** picks the only locked presenter profile, unless `--presenter` says otherwise.
- **Output:** prints JSON.

If `ok` is false, show the owner the `error` in one line with how to fix it, then stop.

3. Show the owner a short summary:
   - the project id
   - what each input was read as (topic / repo / web page / document)
   - the presenter, or none
   - the target length and aspect
   - the expected render time: about 35 s of Mac time per second of presenter footage, so a long tutorial is an overnight run

   If an input was read as something it isn't (for example a topic word taken as a folder name), fix it and re-run with `--id` unchanged only after deleting the wrong project folder. The resolver refuses an existing id.

## 3. Run the pipeline

Run the **topic-tutorial** pipeline on that project exactly as `$OM/AGENT_GUIDE.md` routes it:
- Executive producer skill: `$OM/skills/pipelines/topic-tutorial/executive-producer.md`.
- Manifest: `$OM/pipeline_defs/topic-tutorial.yaml`.
- Stage loop: research → proposal 🛑 → script → scene_plan 🛑 → assets 🛑 → edit → compose 🛑 → publish.

Rules that matter here:
- **Inputs:** research starts from `projects/<id>/inputs/inputs.yaml`.
- **Preferences:** read `projects/<id>/inputs/request.json` for the owner's preferences (length, aspect, audience, presenter) and honour them in the proposal. The proposal also offers outfit, hairstyle and background choices for the presenter.
  - **Aspect:** 16:9 is the supported default. If the owner asked for 9:16 or both, say in the proposal what the pipeline can deliver.
- **Gates:** stop at every 🛑 gate and wait for the owner. Approval is per gate.
- **Costs:** default $0. Itemize any paid call in the proposal and get approval before making it.
- **Presenter:** only the locked twin from `~/.openmontage/presenter_profiles/<id>/`, never raw recordings. If the twin fails QA, that beat falls back to no presenter and you say so at the assets gate.
- **Captures:** run only in the disposable sandbox, never on the owner's desktop.
- **Commands:** run Python commands from `$OM` with `.venv/bin/python`.

When done, give the owner:
- the path to the final render
- the `final_review` result
- what it cost
