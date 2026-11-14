"""BiRefNet (MIT) portrait/general matting on Apple-silicon MPS — fix round 1, B2.

The rembg ONNX route runs on CPU at ≈ 6.7 s/frame (1280×720) here; the same family of model on MPS in fp16 takes
≈ 0.47 s/frame, so a 23 s clip mattes in ~5 minutes. Code: github.com/ZhengPeng7/BiRefNet (MIT, cloned into the model
store); weights: HF ``ZhengPeng7/BiRefNet`` ``model.safetensors`` (444 MB, MIT). No remote code is executed from the Hub.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from lib.model_store import model_path

INPUT_SIZE = 1024
_state: dict = {}


def src_dir() -> Path:
    return Path(os.environ.get("BIREFNET_DIR") or model_path("birefnet", "src"))


def weights_file() -> Path:
    return Path(os.environ.get("BIREFNET_WEIGHTS") or model_path("birefnet", "weights", "BiRefNet", "model.safetensors"))


def available() -> tuple[bool, str]:
    try:
        import timm, einops, kornia, torch  # noqa: F401, E401
    except Exception as exc:  # noqa: BLE001
        return False, f"BiRefNet needs torch+timm+einops+kornia: {exc}"
    if not (src_dir() / "models" / "birefnet.py").is_file():
        return False, f"BiRefNet code not found in {src_dir()} (git clone https://github.com/ZhengPeng7/BiRefNet, MIT)"
    if not weights_file().is_file():
        return False, f"BiRefNet weights not found: {weights_file()} (HF ZhengPeng7/BiRefNet model.safetensors, 444 MB)"
    return True, "ok"


def _device() -> str:
    import torch

    return "mps" if torch.backends.mps.is_available() else "cpu"


def segmenter() -> Callable[[Image.Image], Image.Image]:
    """RGB frame -> RGBA frame (alpha = BiRefNet foreground probability)."""
    import torch
    from safetensors.torch import load_file

    ok, why = available()
    if not ok:
        raise RuntimeError(why)
    if "model" not in _state:
        sys.path.insert(0, str(src_dir()))
        from models.birefnet import BiRefNet
        from utils import check_state_dict

        dev = _device()
        model = BiRefNet(bb_pretrained=False)
        model.load_state_dict(check_state_dict(load_file(str(weights_file()))))
        model.eval().to(dev).to(torch.float16 if dev == "mps" else torch.float32)
        _state.update(model=model, dev=dev)
    model, dev = _state["model"], _state["dev"]
    dtype = torch.float16 if dev == "mps" else torch.float32
    mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)

    def run(im: Image.Image) -> Image.Image:
        rgb = im.convert("RGB")
        x = torch.from_numpy(np.asarray(rgb.resize((INPUT_SIZE, INPUT_SIZE), Image.BILINEAR), dtype=np.float32) / 255.0).permute(2, 0, 1)[None]
        x = ((x - mean) / std).to(dev).to(dtype)
        with torch.no_grad():
            pred = model(x)[-1].sigmoid().float().cpu()[0, 0].numpy()
        alpha = Image.fromarray((np.clip(pred, 0, 1) * 255).astype(np.uint8)).resize(rgb.size, Image.BILINEAR)
        out = rgb.convert("RGBA")
        out.putalpha(alpha)
        return out

    return run
