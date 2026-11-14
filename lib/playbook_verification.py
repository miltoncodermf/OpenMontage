"""Loader for config/topic-tutorial/playbook_verification.yaml (decision D20).

The spec suggests styles/topic-tutorial/verification.yaml, but ``styles/playbook_loader`` lists every
``*.yaml`` in that folder as a playbook, so the sidecar lives under config/ instead.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STYLES_DIR = ROOT / "styles" / "topic-tutorial"
VERIFICATION_FILE = ROOT / "config" / "topic-tutorial" / "playbook_verification.yaml"


def load_verification(path: Path | None = None) -> dict[str, dict]:
    data = yaml.safe_load((path or VERIFICATION_FILE).read_text()) or {}
    return {k: dict(v or {}) for k, v in data.items()}


def is_verified(playbook: str, path: Path | None = None) -> bool:
    return bool(load_verification(path).get(playbook, {}).get("verified", False))


def playbook_ids() -> list[str]:
    return sorted(p.stem for p in STYLES_DIR.glob("*.yaml"))


def label(playbook: str, path: Path | None = None) -> str:
    return f"{playbook} (verified: {str(is_verified(playbook, path)).lower()})"
