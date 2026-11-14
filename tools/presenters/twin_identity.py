"""twin_identity — owner stills, beautified canonical candidates and wardrobe variants (spec §5.5).

Wraps the Gemini image API through ``google_imagen`` (reference-image editing). Paid calls are
refused unless the run explicitly carries ``paid_call_approved: true`` (the agent sets this only
after the proposal/owner approval) — see lib/paid_call_guard.py. Face detection uses MediaPipe
(Apache-2.0); InsightFace weights are non-commercial and are NOT used.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from lib import presenter_profile as pp
from lib.twin_prompts import beautify_prompt, wardrobe_prompt
from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image"


def laplacian_variance(path: Path) -> float:
    """Sharpness score (variance of a 3x3 Laplacian) on a 640px-wide grayscale copy."""
    img = Image.open(path).convert("L")
    img.thumbnail((640, 640))
    a = np.asarray(img, dtype=np.float32)
    lap = -4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]
    return float(lap.var())


def _mediapipe_faces():
    try:
        import mediapipe as mp  # noqa: F401
        return mp.solutions.face_detection
    except Exception:  # noqa: BLE001
        return None


def detect_face_score(path: Path) -> float | None:
    """Best face-detection confidence (0..1), or None when MediaPipe is not installed."""
    fd = _mediapipe_faces()
    if fd is None:
        return None
    import mediapipe as mp  # noqa: F401

    with fd.FaceDetection(model_selection=1, min_detection_confidence=0.5) as det:
        res = det.process(np.asarray(Image.open(path).convert("RGB")))
    return max((d.score[0] for d in (res.detections or [])), default=0.0)


class TwinIdentity(BaseTool):
    name = "twin_identity"
    version = "1.0.0"
    tier = ToolTier.GENERATE
    capability = "avatar"
    provider = "gemini_image"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["binary:ffmpeg"]
    agent_skills = ["flux-best-practices"]
    install_instructions = (
        "Requires GEMINI_API_KEY (Gemini image models) for beautify/wardrobe and `pip install mediapipe` "
        "(Apache-2.0) for face detection. Set ALLOW_PAID_APIS=true only for an approved run."
    )
    fallback_tools: list[str] = []
    capabilities = ["extract_stills", "beautify_portrait", "wardrobe_variant", "pick_canonical"]
    supports = {"operations": ["extract_stills", "beautify", "wardrobe", "pick_canonical"], "license_note": "MediaPipe Apache-2.0; no InsightFace weights"}
    best_for = ["building and extending the owner's beautified identity from his own stills"]
    not_good_for = ["rendering raw owner footage (never allowed)"]
    input_schema = {
        "type": "object",
        "required": ["operation", "profile_id"],
        "properties": {
            "operation": {"type": "string", "enum": ["extract_stills", "beautify", "wardrobe", "pick_canonical"]},
            "profile_id": {"type": "string"},
            "count": {"type": "integer", "default": 5},
            "model": {"type": "string", "default": DEFAULT_IMAGE_MODEL},
            "paid_call_approved": {"type": "boolean", "default": False},
            "variant_id": {"type": "string"},
            "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "hair": {"type": "string"},
            "candidate": {"type": "string"},
            "tweaks": {"type": "string"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=100, network_required=True)
    retry_policy = RetryPolicy(max_retries=1, backoff_seconds=2.0)
    side_effects = ["writes identity/ files in the presenter profile", "sends owner reference stills to the Gemini image API (beautify/wardrobe)"]

    def get_status(self) -> ToolStatus:
        if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
            return ToolStatus.DEGRADED  # stills extraction works; image generation does not
        return ToolStatus.AVAILABLE if _mediapipe_faces() else ToolStatus.DEGRADED

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        # Dated per-image table (lib/gemini_image_pricing.py, source + as_of recorded) — itemize in the proposal.
        from lib.gemini_image_pricing import estimate_calls_usd

        op = inputs.get("operation")
        n = int(inputs.get("count", 5)) if op == "beautify" else 1 if op == "wardrobe" else 0
        return estimate_calls_usd(inputs.get("model", DEFAULT_IMAGE_MODEL), n, inputs.get("resolution", "1K"))

    # ------------------------------------------------------------------
    def _imagen(self):
        from tools.graphics.google_imagen import GoogleImagen

        return GoogleImagen()

    def _guard_paid(self, inputs: dict[str, Any]) -> str | None:
        if not inputs.get("paid_call_approved"):
            return "paid Gemini image call not approved: itemize it in the proposal and set paid_call_approved only after the owner OKs it"
        if os.environ.get("ALLOW_PAID_APIS", "").lower() != "true":
            return "ALLOW_PAID_APIS is not 'true' for this run"
        return None

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        op, pid = inputs.get("operation"), inputs.get("profile_id")
        try:
            d = pp.profile_dir(pid)
            if not (d / "profile.json").is_file():
                return ToolResult(success=False, error=f"profile {pid!r} not initialised (run presenter_profile init)")
            if op == "extract_stills":
                return self._extract_stills(d, int(inputs.get("count", 8)))
            if op == "beautify":
                return self._beautify(d, pid, inputs)
            if op == "wardrobe":
                return self._wardrobe(d, pid, inputs)
            if op == "pick_canonical":
                return self._pick(d, pid, inputs)
            return ToolResult(success=False, error=f"unknown operation {op!r}")
        except (pp.ProfileError, KeyError) as exc:
            return ToolResult(success=False, error=str(exc))

    # ---- extract_stills -------------------------------------------------
    def _extract_stills(self, d: Path, count: int) -> ToolResult:
        raw = next(iter(sorted((d / "raw").glob("face_turn.*"))), None)
        if raw is None:
            return ToolResult(success=False, error="raw/face_turn.* not found — run capture_session first")
        refs = d / "identity" / "refs"
        tmp = refs / "_all"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-vf", "fps=4,scale=1280:-2",
                        str(tmp / "f_%04d.png")], check=True, timeout=300)
        frames = sorted(tmp.glob("f_*.png"))
        scored = []
        face_available = _mediapipe_faces() is not None
        for f in frames:
            sharp = laplacian_variance(f)
            face = detect_face_score(f) if face_available else None
            if face_available and (face or 0) < 0.6:
                continue
            scored.append((sharp, f, face))
        if not scored:
            shutil.rmtree(tmp, ignore_errors=True)
            return ToolResult(success=False, error="no usable frames (no face detected)" if face_available else "no frames extracted")
        # Spread the choice across the turn: best-sharpness frame per time bucket.
        buckets = np.array_split(np.arange(len(scored)), min(count, len(scored)))
        chosen = []
        for b in buckets:
            if len(b):
                chosen.append(max((scored[i] for i in b), key=lambda s: s[0]))
        for old in refs.glob("still_*.png"):
            old.unlink()
        out = []
        for i, (sharp, f, face) in enumerate(chosen, 1):
            dest = refs / f"still_{i:02d}.png"
            shutil.copy2(f, dest)
            dest.chmod(0o600)
            out.append({"file": dest.relative_to(d).as_posix(), "sharpness": round(sharp, 1), "face_score": face})
        shutil.rmtree(tmp, ignore_errors=True)
        return ToolResult(success=True, data={
            "stills": out, "face_detection": "mediapipe" if face_available else "unavailable (install mediapipe); frames chosen by sharpness only",
        })

    # ---- paid image calls -----------------------------------------------
    def _call_image(self, d: Path, prompt: str, refs: list[Path], out: Path, model: str) -> ToolResult:
        res = self._imagen().execute({
            "prompt": prompt, "model": model, "image_paths": [str(r) for r in refs], "output_path": str(out),
            "aspect_ratio": "16:9",
        })
        if res.success and out.is_file():
            out.chmod(0o600)
        return res

    def _beautify(self, d: Path, pid: str, inputs: dict[str, Any]) -> ToolResult:
        blocked = self._guard_paid(inputs)
        if blocked:
            return ToolResult(success=False, error=blocked)
        refs = sorted((d / "identity" / "refs").glob("still_*.png"))
        if not refs:
            return ToolResult(success=False, error="no reference stills — run extract_stills first")
        cdir = d / "identity" / "candidates"
        cdir.mkdir(parents=True, exist_ok=True)
        model = inputs.get("model", DEFAULT_IMAGE_MODEL)
        made, errors = [], []
        for i in range(int(inputs.get("count", 5))):
            out = cdir / f"cand_{i + 1:02d}.png"
            res = self._call_image(d, beautify_prompt(i), refs[:4], out, model)
            (made if res.success else errors).append(out.relative_to(d).as_posix() if res.success else res.error)
        prof = pp.read_profile(pid)
        prof.setdefault("identity", {"canonical": ""})
        prof["identity"].update({"candidates": made, "model": model})
        # canonical is required by the schema only when locked; keep a placeholder path until picked.
        prof["identity"]["canonical"] = prof["identity"].get("canonical") or "identity/canonical.png"
        pp.write_profile(d, prof)
        return ToolResult(success=bool(made), data={"candidates": made, "errors": errors, "model": model},
                          error=None if made else "; ".join(map(str, errors)))

    def _wardrobe(self, d: Path, pid: str, inputs: dict[str, Any]) -> ToolResult:
        blocked = self._guard_paid(inputs)
        if blocked:
            return ToolResult(success=False, error=blocked)
        canonical = d / "identity" / "canonical.png"
        if not canonical.is_file():
            return ToolResult(success=False, error="identity/canonical.png not set — pick a canonical first")
        vid = inputs.get("variant_id")
        desc = inputs.get("description")
        if not vid or not desc:
            return ToolResult(success=False, error="variant_id and description are required")
        out = d / "identity" / "wardrobe" / f"{vid}.png"
        res = self._call_image(d, wardrobe_prompt(desc, inputs.get("hair")), [canonical], out, inputs.get("model", DEFAULT_IMAGE_MODEL))
        if not res.success:
            return ToolResult(success=False, error=res.error)
        cat_path = d / "identity" / "wardrobe_catalog.json"
        catalog = json.loads(cat_path.read_text()) if cat_path.is_file() else []
        catalog = [c for c in catalog if c["id"] != vid]
        catalog.append({"id": vid, "description": desc, "tags": inputs.get("tags", []),
                        "prompt": wardrobe_prompt(desc, inputs.get("hair")), "image": out.relative_to(d).as_posix(),
                        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        cat_path.write_text(json.dumps(catalog, indent=2))
        cat_path.chmod(0o600)
        return ToolResult(success=True, data={"variant": vid, "image": str(out), "catalog_size": len(catalog)})

    def _pick(self, d: Path, pid: str, inputs: dict[str, Any]) -> ToolResult:
        cand = d / "identity" / "candidates" / f"{inputs.get('candidate', '')}.png"
        if not cand.is_file():
            return ToolResult(success=False, error=f"candidate not found: {cand.name}")
        canonical = d / "identity" / "canonical.png"
        shutil.copy2(cand, canonical)
        canonical.chmod(0o600)
        prof = pp.read_profile(pid)
        ident = prof.setdefault("identity", {})
        ident.update({"canonical": "identity/canonical.png", "picked_candidate": cand.stem,
                      "wardrobe_catalog": "identity/wardrobe_catalog.json", "identity_transform": "beautified"})
        if inputs.get("tweaks"):
            ident["tweaks"] = inputs["tweaks"]
        pp.write_profile(d, prof)
        return ToolResult(success=True, data={"canonical": str(canonical), "picked": cand.stem})
