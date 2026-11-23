# openmontage-tutorial (Claude Code plugin)

`/tutorial` makes a presenter-led video tutorial from a code repo, a web page, a document or a plain topic, using this repo's **topic-tutorial** pipeline. The plugin is thin: this OpenMontage checkout is the engine.

## Install (once)

```bash
claude plugin marketplace add ~/workspace/OpenMontage
claude plugin install openmontage-tutorial@openmontage-local
```

If your checkout lives elsewhere, set `OPENMONTAGE_HOME` to it (for example in your shell profile). The engine needs its `.venv` set up as described in the main README.

## Use it from any folder

```text
/tutorial .                                        # the repo you are in
/tutorial https://github.com/org/repo              # cloned into the project first
/tutorial https://github.com/org/repo/tree/main/src  # clone + focus on src/
/tutorial ~/docs/spec.pdf                          # PDF
/tutorial notes.md design.docx                     # converted to PDF first
/tutorial https://docs.example.com/guide           # a web page
/tutorial "how unified memory works on Apple silicon"
/tutorial . https://docs.example.com --length 6 --audience "beginners"
```

**Options**

| Option | Values | Default |
|---|---|---|
| `--length` | minutes, 0.5–30 | the proposal picks |
| `--aspect` | `16:9`, `9:16`, `both` | `16:9` |
| `--presenter` | a locked profile id, or `none` | the only locked profile |
| `--audience` | free text | none |
| `--title` | free text | from the first input |

## What happens

1. **Input resolver:** `lib/tutorial_request.py` sorts the inputs and creates `projects/<id>/` with `inputs/inputs.yaml` and `inputs/request.json`.
   - It clones repo URLs and converts Markdown, text, Word, RTF and HTML documents to PDF.
   - It uses folders and PDFs in place and never changes them.
2. **Pipeline:** the topic-tutorial pipeline runs and stops for your OK at four gates: proposal, scene plan, assets and final video.
3. **Cost:** $0 by default. Any paid call is listed in the proposal and needs your approval.
4. **Render time:** about 35 s of Mac time per second of presenter footage. Long tutorials are overnight runs.
