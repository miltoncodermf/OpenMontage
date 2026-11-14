"""Stand-in presenter profiles (fix round 1, B1).

A stand-in is a dev-only, clearly fictional presenter used to validate the twin engines before the
owner's recordings exist. It is treated exactly like a ``TEST_ONLY_`` fixture: ``final_review`` fails
for any video containing its assets (outside test mode) and it never counts toward ``presenter_percentage``.

Detection is layered so a stand-in cannot slip through by renaming a file:
  1. the asset record carries ``standin: true`` or a ``profile_id`` whose profile.json says ``standin: true``;
  2. any path string inside that profile's directory;
  3. any path containing the ``STANDIN_`` marker (twin tools prefix every stand-in output with it).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

STANDIN_MARKER = "STANDIN_"


def _profile_root() -> Path:
    env = os.environ.get("OPENMONTAGE_PROFILE_ROOT")
    return Path(env).expanduser() if env else Path.home() / ".openmontage" / "presenter_profiles"


def standin_profile_ids() -> set[str]:
    root = _profile_root()
    out: set[str] = set()
    if not root.is_dir():
        return out
    for d in root.iterdir():
        f = d / "profile.json"
        try:
            if f.is_file() and json.loads(f.read_text(encoding="utf-8")).get("standin") is True:
                out.add(d.name)
        except (OSError, ValueError):
            continue
    return out


def is_standin_profile(profile_id: str) -> bool:
    return profile_id in standin_profile_ids()


def _walk(obj: Any) -> Iterable[Any]:
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk(v)


def find_standin_assets(*artifacts: Any) -> list[str]:
    """Every reference to a stand-in asset (record, path, or marker) found anywhere in the artifacts."""
    ids = standin_profile_ids()
    root = str(_profile_root()).replace("\\", "/")
    found: list[str] = []

    def add(label: str) -> None:
        if label not in found:
            found.append(label)

    for art in artifacts:
        if art is None:
            continue
        for node in _walk(art):
            if isinstance(node, dict):
                if node.get("standin") is True or (node.get("profile_id") in ids and node.get("profile_id")):
                    add(str(node.get("path") or node.get("asset_id") or node.get("profile_id")))
            elif isinstance(node, str) and len(node) < 4096:
                norm = node.replace("\\", "/")
                if STANDIN_MARKER in norm or any(f"{root}/{i}/" in norm for i in ids):
                    add(node)
    return found
