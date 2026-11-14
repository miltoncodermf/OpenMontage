"""Honesty guard for the topic-tutorial pipeline.

Test fixtures, placeholders and mocks must never be counted as a real presenter,
capture or visual. Any asset path that points at a ``TEST_ONLY_`` file or into
``tests/fixtures`` makes ``final_review.status`` fail, unless the process
explicitly runs in test mode (``OPENMONTAGE_TEST_MODE=1``) — in which case the
finding is downgraded to an issue note instead of a failure.
"""

from __future__ import annotations

import os
from typing import Any, Iterable

TEST_ONLY_MARKER = "TEST_ONLY_"
FIXTURE_DIR_MARKER = "tests/fixtures"
TEST_MODE_ENV = "OPENMONTAGE_TEST_MODE"


def is_test_only_path(value: str) -> bool:
    """True when a path string looks like a test fixture / placeholder asset."""
    norm = str(value).replace("\\", "/")
    return TEST_ONLY_MARKER in norm or FIXTURE_DIR_MARKER in norm


def is_test_mode() -> bool:
    return os.environ.get(TEST_MODE_ENV, "").strip().lower() in {"1", "true", "yes"}


def _iter_strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_strings(v)


def find_test_only_assets(*artifacts: Any) -> list[str]:
    """Return every string value in the artifacts that references a test-only asset."""
    found: list[str] = []
    for art in artifacts:
        if art is None:
            continue
        for s in _iter_strings(art):
            if len(s) < 4096 and is_test_only_path(s) and s not in found:
                found.append(s)
    return found


def honesty_check(*artifacts: Any) -> dict[str, Any]:
    """Run the guard. ``blocking`` is False in test mode."""
    from lib.standin import find_standin_assets

    offenders = find_test_only_assets(*artifacts)
    standins = [s for s in find_standin_assets(*artifacts) if s not in offenders]
    test_mode = is_test_mode()
    bad = bool(offenders or standins)
    return {
        "test_only_assets": offenders,
        "standin_assets": standins,
        "test_mode": test_mode,
        "blocking": bad and not test_mode,
        "issues": [f"Honesty guard: test-only asset used in output: {o}" for o in offenders]
        + [f"Honesty guard: stand-in presenter asset (fictional dev profile) used in output: {s}" for s in standins],
    }
