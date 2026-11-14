"""Availability checks for the heavy twin backends (honest: none are bundled).

Each check returns ``(available, reason)``. Weights are large (MuseTalk-MLX fp16 ≈ 1.9 GB), so a
download needs a disk check and the owner's OK (spec §5.5, 500 MB rule). Nothing here downloads.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def _dir_env(var: str, marker: str) -> tuple[bool, str]:
    d = os.environ.get(var)
    if not d:
        return False, f"{var} not set"
    if not (Path(d) / marker).exists():
        return False, f"{var}={d} has no {marker}"
    return True, "ok"


def musetalk_mlx_available() -> tuple[bool, str]:
    if importlib.util.find_spec("musetalk_mlx") is None:
        return False, "python package `musetalk_mlx` not installed (MuseTalk-MLX port; MIT)"
    return _dir_env("MUSETALK_MLX_DIR", "config.json")


def latentsync_available() -> tuple[bool, str]:
    return _dir_env("LATENTSYNC_DIR", "scripts")


def liveportrait_available() -> tuple[bool, str]:
    return _dir_env("LIVEPORTRAIT_DIR", "inference.py")


def birefnet_available() -> tuple[bool, str]:
    if importlib.util.find_spec("rembg") is None:
        return False, "python package `rembg` not installed"
    try:
        from rembg.sessions import sessions_names

        if "birefnet-portrait" not in sessions_names:
            return False, "installed rembg has no `birefnet-portrait` session"
    except Exception as exc:  # noqa: BLE001
        return False, f"rembg session check failed: {exc}"
    return True, "ok"
