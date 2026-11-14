"""Host-wide lock so memory-heavy jobs never overlap (spec §9, 24 GB unified memory).

Sandbox captures, lip-sync/LivePortrait runs and Remotion renders each take this lock.
Stale locks (dead pid) are reclaimed.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

LOCK_PATH = Path(os.environ.get("OPENMONTAGE_HEAVY_LOCK", Path.home() / ".openmontage" / "heavy_job.lock"))


class HeavyJobBusy(RuntimeError):
    pass


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def current_holder(path: Path | None = None) -> dict | None:
    path = Path(path) if path else LOCK_PATH
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if _alive(int(data.get("pid", 0))) else None


@contextmanager
def heavy_job(label: str, path: Path | None = None):
    """Hold the heavy-job lock; raises HeavyJobBusy if another live job holds it."""
    path = Path(path) if path else LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    holder = current_holder(path)
    if holder and holder["pid"] != os.getpid():
        raise HeavyJobBusy(f"heavy job already running: {holder.get('label')} (pid {holder['pid']})")
    path.write_text(json.dumps({"pid": os.getpid(), "label": label, "since": time.time()}))
    try:
        yield
    finally:
        try:
            path.unlink()
        except OSError:
            pass
