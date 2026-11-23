"""Loader for config/topic-tutorial/model_routing.yaml (spec §5.1).

Pure data access — no orchestration. The main agent session uses this to pick the
sub-agent model for each stage; tests use it to assert manifest coverage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROUTING_PATH = Path(__file__).resolve().parent.parent / "config" / "topic-tutorial" / "model_routing.yaml"
TIER_KEYS = ("claude_code", "model_id", "gemini_cli")


def load_routing(path: Path | None = None) -> dict[str, Any]:
    data = yaml.safe_load((path or ROUTING_PATH).read_text(encoding="utf-8"))
    validate_routing(data)
    return data


def validate_routing(data: dict[str, Any]) -> None:
    tiers = data.get("tiers") or {}
    if set(tiers) != {"deep", "standard", "fast"}:
        raise ValueError(f"tiers must be exactly deep/standard/fast, got {sorted(tiers)}")
    for name, t in tiers.items():
        missing = [k for k in TIER_KEYS if k not in t]
        if missing:
            raise ValueError(f"tier {name!r} missing {missing}")
    for section in ("stages", "onboarding"):
        for key, tier in (data.get(section) or {}).items():
            if tier not in tiers:
                raise ValueError(f"{section}.{key} uses unknown tier {tier!r}")


def tier_for_stage(stage: str, data: dict[str, Any] | None = None) -> str:
    """Tier for a manifest stage (exact key, else the first `<stage>.*` sub-key)."""
    data = data or load_routing()
    stages = data["stages"]
    if stage in stages:
        return stages[stage]
    for key, tier in stages.items():
        if key.startswith(stage + "."):
            return tier
    raise KeyError(f"no model routing for stage {stage!r}")


def model_for_stage(stage: str, data: dict[str, Any] | None = None) -> dict[str, str]:
    data = data or load_routing()
    return data["tiers"][tier_for_stage(stage, data)]
