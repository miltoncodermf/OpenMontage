"""Presenter guard (spec D3).

A presenter asset may only be counted/rendered as a *real* presenter when it
originates from a locked presenter profile and carries
``identity_transform == "beautified"``. The owner's raw recordings, fixtures and
placeholders are rejected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.honesty_guard import is_test_only_path

PRESENTER_ASSET_TYPES = {"presenter_video", "presenter", "presenter_matte", "presenter_loop"}
RAW_DIR_NAMES = {"raw"}


class PresenterGuardError(ValueError):
    """Raised when an asset is not an acceptable presenter asset."""


def presenter_asset_problems(asset: dict[str, Any]) -> list[str]:
    """Return the reasons ``asset`` is NOT an acceptable real presenter asset (empty = ok)."""
    problems: list[str] = []
    path = str(asset.get("path") or "")
    if asset.get("identity_transform") != "beautified":
        problems.append("identity_transform must be 'beautified'")
    if not asset.get("profile_id"):
        problems.append("asset must originate from a presenter profile (profile_id missing)")
    if is_test_only_path(path):
        problems.append("test-only fixture path cannot be a real presenter")
    from lib.standin import find_standin_assets

    if find_standin_assets(asset):
        problems.append("stand-in profile asset (fictional dev presenter) can never be a real presenter")
    parts = {p.lower() for p in Path(path.replace("\\", "/")).parts}
    if parts & RAW_DIR_NAMES and ("presenter_profiles" in parts or asset.get("source_type") == "owner_raw"):
        problems.append("raw owner recording cannot be rendered (onboarding source only)")
    if path:
        from lib.presenter_profile import is_inside_profile_raw

        if is_inside_profile_raw(path):
            problems.append("path is inside a presenter profile raw/ directory (owner recording, never rendered)")
    if asset.get("source_type") in {"user_supplied", "owner_raw", "onboarding_source"}:
        problems.append(f"source_type {asset.get('source_type')!r} is an onboarding source, never rendered")
    return problems


def is_real_presenter_asset(asset: dict[str, Any]) -> bool:
    return not presenter_asset_problems(asset)


def assert_real_presenter_asset(asset: dict[str, Any]) -> None:
    problems = presenter_asset_problems(asset)
    if problems:
        raise PresenterGuardError("; ".join(problems))
