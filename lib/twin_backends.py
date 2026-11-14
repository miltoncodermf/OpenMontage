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
    from lib import musetalk_runner

    return musetalk_runner.available()


def latentsync_available() -> tuple[bool, str]:
    """LatentSync (Apache-2.0 code, OpenRAIL++ weights) via the MLX port. NOT integrated: see reports/twin_bakeoff_dev.md."""
    d = os.environ.get("LATENTSYNC_DIR")
    if not d:
        from lib.model_store import model_path

        d = str(model_path("latentsync"))
    if not (Path(d) / "checkpoints" / "latentsync_unet_mlx.safetensors").is_file():
        return False, (f"no converted MLX weights in {d}/checkpoints (weights downloaded: latentsync_unet.pt 5 GB + whisper/tiny.pt; "
                       "conversion/inference needs the third-party sb1992/latentsync-mlx code run in its own venv — blocked pending the owner's OK, see reports/twin_bakeoff_dev.md)")
    return False, "converted weights present but the MediaPipe-based LatentSync face pre/post-processing worker is not integrated yet"


def liveportrait_available() -> tuple[bool, str]:
    from lib import liveportrait_runner

    return liveportrait_runner.available()


BIREFNET_MODEL = os.environ.get("OPENMONTAGE_MATTE_MODEL", "birefnet-general-lite")  # rembg fallback session (CPU, slow)


def birefnet_available() -> tuple[bool, str]:
    """Preferred: BiRefNet on MPS (lib/birefnet_mps). Fallback: rembg ONNX session (CPU, ~15x slower)."""
    from lib import birefnet_mps

    ok, why = birefnet_mps.available()
    if ok:
        return True, "ok (BiRefNet on MPS)"
    if importlib.util.find_spec("rembg") is None:
        return False, f"{why}; and python package `rembg` not installed"
    try:
        from rembg.sessions import sessions_names

        if BIREFNET_MODEL not in sessions_names:
            return False, f"{why}; installed rembg has no `{BIREFNET_MODEL}` session"
    except Exception as exc:  # noqa: BLE001
        return False, f"rembg session check failed: {exc}"
    return True, "ok (rembg ONNX fallback, CPU — slow)"
