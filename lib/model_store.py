"""Where local model weights live: a machine-wide store shared by every project (``~/Models`` by default).

Resolution order: ``OPENMONTAGE_MODELS_DIR`` env (OpenMontage-only override) → ``MODELS_DIR`` env (shared,
project-neutral) → the path stored in ``~/.openmontage/models_dir`` (legacy pointer file) → ``~/Models``.
Other projects should use the same ``MODELS_DIR`` / ``~/Models`` convention. Private presenter profiles never live here.
"""

from __future__ import annotations

import os
from pathlib import Path

def models_dir() -> Path:
    for var in ("OPENMONTAGE_MODELS_DIR", "MODELS_DIR"):
        env = os.environ.get(var)
        if env:
            return Path(env).expanduser()
    pointer = Path.home() / ".openmontage" / "models_dir"
    try:
        text = pointer.read_text(encoding="utf-8").strip()
        if text:
            return Path(text).expanduser()
    except OSError:
        pass
    return Path.home() / "Models"


def model_path(*parts: str) -> Path:
    return models_dir().joinpath(*parts)


def configure_cache_env() -> None:
    """Point rembg's model cache at the model store (does not override an explicit U2NET_HOME)."""
    os.environ.setdefault("U2NET_HOME", str(models_dir() / "u2net"))
