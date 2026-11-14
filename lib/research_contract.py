"""Research contract checks for topic-tutorial (spec §5.4).

Pure validation helpers the research/script reviewers call:
- every research_brief data point has a ``source_ref``;
- every claim used in the script has >= 1 source, key claims >= 2 independent sources;
- sourced media candidates / assets carry their rights fields.
"""

from __future__ import annotations

from typing import Any

RIGHTS_FIELDS = ("rights_status", "license", "source_url", "attribution", "retrieved_at")
SOURCED_ASSET_TYPES = {"sourced_image", "sourced_clip"}


def brief_problems(brief: dict[str, Any]) -> list[str]:
    problems = []
    for i, dp in enumerate(brief.get("data_points", [])):
        if not dp.get("source_ref"):
            problems.append(f"data_points[{i}] has no source_ref (URL, file+line, or PDF page)")
    for i, mc in enumerate(brief.get("media_candidates", [])):
        missing = [f for f in RIGHTS_FIELDS if not mc.get(f)]
        if missing:
            problems.append(f"media_candidates[{i}] missing rights fields {missing}")
    return problems


def _source_keys(fact: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    ref = fact.get("source_ref") or {}
    key = ref.get("url") or ref.get("file")
    if key:
        keys.add(str(key))
    if fact.get("source_url"):
        keys.add(str(fact["source_url"]))
    keys.update(str(c) for c in fact.get("corroborated_by") or [])
    return keys


def script_claim_problems(script_fact_ids: list[str], fact_sheet: dict[str, Any]) -> list[str]:
    """Check that each fact id the script relies on is sourced (>=1, key claims >=2 independent)."""
    facts = {f["fact_id"]: f for f in fact_sheet.get("facts", [])}
    problems = []
    for fid in script_fact_ids:
        fact = facts.get(fid)
        if fact is None:
            problems.append(f"{fid}: not in fact_sheet")
            continue
        sources = _source_keys(fact)
        if not sources:
            problems.append(f"{fid}: no source")
        elif fact.get("key_claim") and len(sources) < 2:
            problems.append(f"{fid}: key claim needs >= 2 independent sources, has {len(sources)}")
    return problems


def asset_rights_problems(asset_manifest: dict[str, Any]) -> list[str]:
    problems = []
    for a in asset_manifest.get("assets", []):
        if (a.get("asset_type") or a.get("type")) in SOURCED_ASSET_TYPES:
            missing = [f for f in RIGHTS_FIELDS if not a.get(f)]
            if missing:
                problems.append(f"{a.get('asset_id') or a.get('id')}: missing rights fields {missing}")
    return problems
