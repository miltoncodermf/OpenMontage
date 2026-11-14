# Publish Director — topic-tutorial v3

**Read first:** `skills/pipelines/explainer/publish-director.md`. Model tier: fast.

## topic-tutorial deltas

- Publish = **local bundle only** (no upload): master MP4, subtitles (SRT/VTT), thumbnail, metadata.
- Build the list with `lib/attributions.build_attributions(asset_manifest)` / `format_attributions`.
- Description includes **chapter timestamps** from the scene plan and an **attributions list** built from every asset's `rights_status`/`license`/`source_url`/`attribution` (required for `sourced_*` assets; also credit self-captured sites by URL).
- Include no private data: never bundle anything from the presenter profile `raw/` folder.
- Write `artifacts/publish_log.json`.

## Review focus / success criteria
Deliverables bundled; attributions complete for every sourced asset.
