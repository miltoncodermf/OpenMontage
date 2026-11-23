"""Attributions list for the publish stage (spec §5.4b / publish-director)."""

from __future__ import annotations

from typing import Any

from lib.research_contract import SOURCED_ASSET_TYPES


def build_attributions(asset_manifest: dict[str, Any]) -> list[dict[str, str]]:
    """One entry per sourced asset (image/clip) and per self-captured site URL."""
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for a in asset_manifest.get("assets", []):
        atype = a.get("asset_type") or a.get("type")
        if atype in SOURCED_ASSET_TYPES:
            entry = {
                "asset_id": str(a.get("asset_id") or a.get("id")),
                "attribution": str(a.get("attribution", "")),
                "license": str(a.get("license", "")),
                "source_url": str(a.get("source_url", "")),
            }
        elif atype == "sandbox_capture" and a.get("source_url"):
            entry = {
                "asset_id": str(a.get("asset_id") or a.get("id")),
                "attribution": f"Screen capture of {a['source_url']}",
                "license": str(a.get("license", "self-captured")),
                "source_url": str(a["source_url"]),
            }
        else:
            continue
        key = (entry["source_url"], entry["attribution"])
        if key not in seen:
            seen.add(key)
            out.append(entry)
    return out


def format_attributions(entries: list[dict[str, str]]) -> str:
    if not entries:
        return "Attributions: none (no third-party media used)."
    lines = ["Attributions:"]
    for e in entries:
        lines.append(f"- {e['attribution']} — {e['license']} — {e['source_url']}")
    return "\n".join(lines)
