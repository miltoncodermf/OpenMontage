"""Measurement helpers for the twin bake-off (spec P5): wall-clock, peak memory, cost."""

from __future__ import annotations

import resource
import subprocess
import sys
import time
from typing import Any, Sequence


def peak_rss_mb(children: bool = True) -> float:
    """Peak resident set size of this process or its waited-for children, in MB (macOS reports bytes)."""
    who = resource.RUSAGE_CHILDREN if children else resource.RUSAGE_SELF
    rss = resource.getrusage(who).ru_maxrss
    return round(rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024, 1)


def measure_command(argv: Sequence[str], **kw: Any) -> dict[str, Any]:
    """Run a command and report wall-clock seconds and the child's peak RSS (MB)."""
    before = peak_rss_mb()
    t0 = time.perf_counter()
    proc = subprocess.run(list(argv), capture_output=True, text=True, **kw)
    return {"returncode": proc.returncode, "wall_seconds": round(time.perf_counter() - t0, 2),
            "peak_rss_mb": max(peak_rss_mb(), before)}
