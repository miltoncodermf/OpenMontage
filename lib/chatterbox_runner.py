"""Chatterbox candidate synthesis via the dedicated venv (fix round 1, B7)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from lib.model_store import model_path

WORKER = Path(__file__).resolve().parent / "_chatterbox_worker.py"


def venv_python() -> Path:
    env = os.environ.get("CHATTERBOX_PYTHON")
    return Path(env) if env else model_path("chatterbox", "venv", "bin", "python")


def hf_home() -> Path:
    return Path(os.environ.get("CHATTERBOX_HF_HOME") or model_path("hf"))


def available() -> tuple[bool, str]:
    py = venv_python()
    if not py.is_file():
        return False, f"chatterbox venv not found at {py} (python3.12 -m venv … && pip install chatterbox-mlx soundfile)"
    r = subprocess.run([str(py), "-c", "import chatterbox.tts_mlx"], capture_output=True, text=True)
    if r.returncode != 0:
        return False, f"chatterbox-mlx not importable in {py}: {r.stderr.strip()[-200:]}"
    snap = list((hf_home() / "hub" / "models--ResembleAI--chatterbox" / "snapshots").glob("*/t3_cfg.safetensors"))
    if not snap:
        return False, f"Chatterbox weights not cached in {hf_home()} (ResembleAI/chatterbox: ve, t3_cfg, s3gen, tokenizer, conds ≈ 3.2 GB; needs owner OK ≥ 500 MB)"
    return True, "ok"


def synthesize(owner_ref: Path, donor_refs: dict[str, Path], candidates: list[dict[str, Any]], text: str, out_dir: Path,
               seed: int = 1234, timeout_s: int = 3600) -> dict[str, Any]:
    ok, why = available()
    if not ok:
        raise RuntimeError(why)
    with tempfile.TemporaryDirectory() as td:
        spec = {"owner_ref": str(owner_ref), "donor_refs": {k: str(v) for k, v in donor_refs.items()}, "candidates": candidates,
                "text": text, "out_dir": str(out_dir), "seed": seed, "out_json": str(Path(td) / "report.json")}
        sp = Path(td) / "spec.json"
        sp.write_text(json.dumps(spec))
        env = {**os.environ, "HF_HOME": str(hf_home()), "PYTORCH_ENABLE_MPS_FALLBACK": "1"}
        proc = subprocess.run([str(venv_python()), str(WORKER), str(sp)], capture_output=True, text=True, timeout=timeout_s, env=env)
        if proc.returncode != 0 or not Path(spec["out_json"]).is_file():
            raise RuntimeError(f"chatterbox worker failed (exit {proc.returncode}): {(proc.stderr or proc.stdout)[-1500:]}")
        return json.loads(Path(spec["out_json"]).read_text())
