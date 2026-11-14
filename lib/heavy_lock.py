"""Host-wide lock so memory-heavy jobs never overlap (spec §9, 24 GB unified memory).

Sandbox captures, Remotion/HyperFrames renders, lip-sync / LatentSync / LivePortrait runs and
long MLX TTS batches each take this lock.

Implementation: an ``fcntl.flock`` on a lock file. The kernel drops the lock when the holding
process dies, so there are no stale locks and acquisition is atomic (no check-then-write race).
Re-entrant per process (and per thread-group): nested ``heavy_job`` calls in one process only
take the file lock once, so a render that internally calls another heavy step cannot deadlock.

``wait=0`` (default) fails fast with ``HeavyJobBusy``; ``wait=N`` queues for up to N seconds
(``wait=None`` waits forever) — use that for unattended runs so jobs serialize instead of failing.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path


def _default_path() -> Path:
    return Path(os.environ.get("OPENMONTAGE_HEAVY_LOCK", Path.home() / ".openmontage" / "heavy_job.lock"))


LOCK_PATH = _default_path()


class HeavyJobBusy(RuntimeError):
    pass


_state_lock = threading.RLock()
_held: dict[str, dict] = {}  # lock path -> {"fd": int, "depth": int, "label": str}


def _read_holder(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text() or "{}")
    except (OSError, ValueError):
        return None
    return data or None


def current_holder(path: Path | None = None) -> dict | None:
    """The live holder's record, or None if the lock is free."""
    path = Path(path) if path else LOCK_PATH
    if str(path) in _held:
        return {"pid": os.getpid(), "label": _held[str(path)]["label"]}
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return _read_holder(path) or {"pid": 0, "label": "unknown"}
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    finally:
        os.close(fd)


@contextmanager
def heavy_job(label: str, path: Path | None = None, wait: float | None = 0):
    """Hold the heavy-job lock.

    Raises ``HeavyJobBusy`` if another process holds it and ``wait`` seconds elapse (0 = immediately).
    """
    path = Path(path) if path else LOCK_PATH
    key = str(path)
    with _state_lock:
        mine = _held.get(key)
        if mine:  # re-entrant in this process
            mine["depth"] += 1
            reentrant = True
        else:
            reentrant = False
    if reentrant:
        try:
            yield
        finally:
            with _state_lock:
                _held[key]["depth"] -= 1
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = None if wait is None else time.monotonic() + wait
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    # Serialize in-process threads on the state lock while polling the file lock.
    acquired = False
    try:
        while True:
            with _state_lock:
                if key in _held:  # another thread of this process acquired it meanwhile
                    _held[key]["depth"] += 1
                    os.close(fd)
                    fd = -1
                    acquired = True
                    reentrant = True
                    break
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    pass
                else:
                    os.ftruncate(fd, 0)
                    os.write(fd, json.dumps({"pid": os.getpid(), "label": label, "since": time.time()}).encode())
                    _held[key] = {"fd": fd, "depth": 1, "label": label}
                    acquired = True
                    break
            if deadline is not None and time.monotonic() >= deadline:
                holder = _read_holder(path) or {}
                raise HeavyJobBusy(f"heavy job already running: {holder.get('label', 'unknown')} (pid {holder.get('pid', '?')})")
            time.sleep(0.05)
    finally:
        if not acquired and fd >= 0:
            os.close(fd)
    try:
        yield
    finally:
        with _state_lock:
            rec = _held[key]
            rec["depth"] -= 1
            if rec["depth"] <= 0:
                del _held[key]
                try:
                    os.ftruncate(rec["fd"], 0)
                    fcntl.flock(rec["fd"], fcntl.LOCK_UN)
                finally:
                    os.close(rec["fd"])


# Queue (don't fail) for unattended renders: a render waits up to this long for a capture/lip-sync to finish.
DEFAULT_RENDER_WAIT_S = 3600.0


def heavy_if(condition: bool, label: str, wait: float | None = DEFAULT_RENDER_WAIT_S, path: Path | None = None):
    """``heavy_job`` when ``condition`` holds, else a no-op context (e.g. only long TTS batches lock)."""
    from contextlib import nullcontext

    return heavy_job(label, path, wait=wait) if condition else nullcontext()
