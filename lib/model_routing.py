"""Loader for config/topic-tutorial/model_routing.yaml (spec §5.1).

Pure data access — no orchestration. The main agent session uses this to pick the
sub-agent model and reasoning effort for each stage; tests use it to assert
manifest coverage.

A stage entry is either a tier name (``script: deep``) or a mapping that
overrides the tier's effort (``script: {tier: deep, effort: max}``). A tier's
``effort`` defaults to deep=high, standard=medium, fast=low.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROUTING_PATH = Path(__file__).resolve().parent.parent / "config" / "topic-tutorial" / "model_routing.yaml"
TIER_KEYS = ("claude_code", "model_id", "gemini_cli")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_EFFORT = {"deep": "high", "standard": "medium", "fast": "low"}


def load_routing(path: Path | None = None) -> dict[str, Any]:
    data = yaml.safe_load((path or ROUTING_PATH).read_text(encoding="utf-8"))
    validate_routing(data)
    return data


def _entry(value: Any) -> tuple[Any, Any]:
    """(tier, effort-override) for a stage entry."""
    if isinstance(value, dict):
        return value.get("tier"), value.get("effort")
    return value, None


def validate_routing(data: dict[str, Any]) -> None:
    tiers = data.get("tiers") or {}
    if set(tiers) != {"deep", "standard", "fast"}:
        raise ValueError(f"tiers must be exactly deep/standard/fast, got {sorted(tiers)}")
    for name, t in tiers.items():
        missing = [k for k in TIER_KEYS if k not in t]
        if missing:
            raise ValueError(f"tier {name!r} missing {missing}")
        if "effort" in t and t["effort"] not in EFFORTS:
            raise ValueError(f"tier {name!r} effort {t['effort']!r} not in {EFFORTS}")
    for section in ("stages", "onboarding"):
        for key, value in (data.get(section) or {}).items():
            tier, effort = _entry(value)
            if tier not in tiers:
                raise ValueError(f"{section}.{key} uses unknown tier {tier!r}")
            if effort is not None and effort not in EFFORTS:
                raise ValueError(f"{section}.{key} effort {effort!r} not in {EFFORTS}")


def _stage_entry(stage: str, data: dict[str, Any], section: str = "stages") -> Any:
    entries = data.get(section) or {}
    if stage in entries:
        return entries[stage]
    for key, value in entries.items():
        if key.startswith(stage + "."):
            return value
    raise KeyError(f"no model routing for {section[:-1]} {stage!r}")


def tier_for_stage(stage: str, data: dict[str, Any] | None = None) -> str:
    """Tier for a manifest stage (exact key, else the first `<stage>.*` sub-key)."""
    data = data or load_routing()
    return _entry(_stage_entry(stage, data))[0]


def effort_for_stage(stage: str, data: dict[str, Any] | None = None, section: str = "stages") -> str:
    """Reasoning effort for a stage: the stage override, else the tier's effort, else the tier default."""
    data = data or load_routing()
    tier, override = _entry(_stage_entry(stage, data, section))
    return override or data["tiers"][tier].get("effort") or DEFAULT_EFFORT[tier]


def model_for_stage(stage: str, data: dict[str, Any] | None = None, section: str = "stages") -> dict[str, str]:
    """The tier's model fields plus ``tier`` and the resolved ``effort`` for the stage."""
    data = data or load_routing()
    tier = _entry(_stage_entry(stage, data, section))[0]
    return {**data["tiers"][tier], "tier": tier, "effort": effort_for_stage(stage, data, section)}
