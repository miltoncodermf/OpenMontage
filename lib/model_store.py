"""Where local model weights live (``~/.openmontage/models`` by default; point it elsewhere with the env var or the pointer file).

Resolution order: ``OPENMONTAGE_MODELS_DIR`` env → the path stored in ``~/.openmontage/models_dir``
(a one-line file outside the repo) → ``~/.openmontage/models``. Private presenter profiles never live here.
"""

from __future__ import annotations

import os
from pathlib import Path


def models_dir() -> Path:
    env = os.environ.get("OPENMONTAGE_MODELS_DIR")
    if env:
        return Path(env).expanduser()
    pointer = Path.home() / ".openmontage" / "models_dir"
    try:
        text = pointer.read_text(encoding="utf-8").strip()
        if text:
            return Path(text).expanduser()
    except OSError:
        pass
    return Path.home() / ".openmontage" / "models"


def model_path(*parts: str) -> Path:
    return models_dir().joinpath(*parts)


def configure_cache_env() -> None:
    """Point rembg's model cache at the model store (does not override an explicit U2NET_HOME)."""
    os.environ.setdefault("U2NET_HOME", str(models_dir() / "u2net"))
