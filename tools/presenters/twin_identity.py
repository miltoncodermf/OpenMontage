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
from lib.twin_prompts import beautify_prompt, hairstyle_prompt, plate_prompt, wardrobe_prompt
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


def _ensure_real_png(path: Path) -> None:
    """Gemini returns JPEG bytes; the tool writes them to the requested ``.png`` name. Re-encode so the extension is true."""
    with Image.open(path) as im:
        if im.format == "PNG":
            return
        rgb = im.convert("RGB")
    rgb.save(path, format="PNG")


def laplacian_variance(path: Path) -> float:
    """Sharpness score (variance of a 3x3 Laplacian) on a 640px-wide grayscale copy."""
    img = Image.open(path).convert("L")
    img.thumbnail((640, 640))
    a = np.asarray(img, dtype=np.float32)
    lap = -4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]
    return float(lap.var())


def _mediapipe_faces():
    """True when the MediaPipe Tasks face detector is usable (no InsightFace)."""
    from lib import face_tools

    return face_tools.mediapipe_available()[0] or None


def detect_face_score(path: Path) -> float | None:
    """Best face-detection confidence (0..1), or None when MediaPipe is not usable."""
    if not _mediapipe_faces():
        return None
    from lib import face_tools

    faces = face_tools.detect_faces(Image.open(path).convert("RGB"))
    return faces[0]["score"] if faces else 0.0


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
    capabilities = ["extract_stills", "beautify_portrait", "wardrobe_variant", "hairstyle_variant", "background_plate", "pick_canonical", "standin_portrait"]
    supports = {"operations": ["extract_stills", "beautify", "wardrobe", "hairstyle", "background_plate", "pick_canonical", "standin_portrait"], "license_note": "MediaPipe Apache-2.0; no InsightFace weights"}
    best_for = ["building and extending the owner's beautified identity from his own stills"]
    not_good_for = ["rendering raw owner footage (never allowed)"]
    input_schema = {
        "type": "object",
        "required": ["operation", "profile_id"],
        "properties": {
            "operation": {"type": "string", "enum": ["extract_stills", "beautify", "wardrobe", "hairstyle", "background_plate", "pick_canonical", "standin_portrait"]},
            "profile_id": {"type": "string"},
            "count": {"type": "integer", "default": 5},
            "model": {"type": "string", "default": DEFAULT_IMAGE_MODEL},
            "paid_call_approved": {"type": "boolean", "default": False},
            "variant_id": {"type": "string"},
            "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "hair": {"type": "string"},
            "candidate": {"type": "string"},
            "scene": {"type": "string", "description": "background_plate: what the empty plate shows"},
            "resolution": {"type": "string", "enum": ["1K", "2K", "4K"], "description": "background_plate: output size (default 2K)"},
            "strength": {"type": "string", "enum": ["subtle", "strong", "very_strong"], "default": "subtle"},
            "start_index": {"type": "integer", "default": 0, "description": "beautify: first candidate number minus one, so rounds do not overwrite each other"},
            "approved_total_usd": {"type": "number", "description": "Owner-approved total for this paid batch; calls stop at 1.2x (lib/paid_call_guard)"},
            "spend_ledger": {"type": "string", "description": "JSON file recording every paid call; the guard sums it"},
            "ref_stills": {"type": "array", "items": {"type": "string"}, "description": "beautify: still file names to use as references (default: the first four); pick frontal, eyes-to-camera frames"},
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
        n = int(inputs.get("count", 5)) if op == "beautify" else 1 if op in ("wardrobe", "hairstyle", "background_plate") else 0
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
            if op == "hairstyle":
                return self._hairstyle(d, pid, inputs)
            if op == "background_plate":
                return self._background_plate(d, pid, inputs)
            if op == "pick_canonical":
                return self._pick(d, pid, inputs)
            if op == "standin_portrait":
                return self._standin_portrait(d, pid, inputs)
            return ToolResult(success=False, error=f"unknown operation {op!r}")
        except (pp.ProfileError, KeyError) as exc:
            return ToolResult(success=False, error=str(exc))

    # ---- extract_stills -------------------------------------------------
    def _extract_stills(self, d: Path, count: int) -> ToolResult:
        raw = pp.working_video(d, "face_turn", raw_fallback=True)
        if raw is None:
            has_raw = any((d / "raw").glob("face_turn.*"))
            return ToolResult(success=False, error=(
                "raw/face_turn.* is HDR or rotated (phone original) and has no SDR working copy — run presenter_profile normalize_raw first"
                if has_raw else "raw/face_turn.* not found — run capture_session first"))
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
            _ensure_real_png(out)
            out.chmod(0o600)
        return res

    def _consent_problem(self, pid: str) -> str | None:
        """Sending the owner's likeness to a cloud model needs recorded consent (stand-ins are fictional)."""
        if pp.read_profile(pid).get("standin"):
            return None
        try:
            pp.require_consent(pid)
        except pp.ProfileError as exc:
            return str(exc)
        return None

    # ---- budget guard: owner-approved total, hard stop at 1.2x (lib/paid_call_guard) -------------
    def _ledger(self, inputs: dict[str, Any]) -> tuple[Path | None, list[dict[str, Any]]]:
        if not inputs.get("spend_ledger"):
            return None, []
        p = Path(inputs["spend_ledger"])
        return p, (json.loads(p.read_text()) if p.is_file() else [])

    def _budget_problem(self, inputs: dict[str, Any], model: str, n: int, resolution: str = "1K") -> str | None:
        from lib.paid_call_guard import OVERRUN_FACTOR

        approved = inputs.get("approved_total_usd")
        if approved is None:
            return None
        _, entries = self._ledger(inputs)
        spent = sum(float(e.get("usd", 0)) for e in entries)
        nxt = self.estimate_cost({"operation": "wardrobe", "model": model, "resolution": resolution}) * n
        if spent + nxt > float(approved) * OVERRUN_FACTOR + 1e-9:
            return (f"budget guard: spent ${spent:.3f} + next ${nxt:.3f} would exceed 1.2x the approved ${float(approved):.3f} "
                    f"(${float(approved) * OVERRUN_FACTOR:.3f}); stop and ask the owner")
        return None

    def _ledger_add(self, inputs: dict[str, Any], op: str, model: str, label: str, reported: float | None, resolution: str = "1K") -> None:
        p, entries = self._ledger(inputs)
        if p is None:
            return
        est = self.estimate_cost({"operation": "wardrobe", "model": model, "resolution": resolution})
        entries.append({"op": op, "model": model, "label": label, "usd": est, "reported_usd": reported,
                        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        p.write_text(json.dumps(entries, indent=2))

    def _beautify(self, d: Path, pid: str, inputs: dict[str, Any]) -> ToolResult:
        blocked = self._guard_paid(inputs) or self._consent_problem(pid)
        if blocked:
            return ToolResult(success=False, error=blocked)
        refs = sorted((d / "identity" / "refs").glob("still_*.png"))
        if inputs.get("ref_stills"):
            chosen = [d / "identity" / "refs" / Path(n).name for n in inputs["ref_stills"]]
            missing = [c.name for c in chosen if not c.is_file()]
            if missing:
                return ToolResult(success=False, error=f"ref_stills not found: {missing}")
            refs = chosen
        if not refs:
            return ToolResult(success=False, error="no reference stills — run extract_stills first")
        cdir = d / "identity" / "candidates"
        cdir.mkdir(parents=True, exist_ok=True)
        model = inputs.get("model", DEFAULT_IMAGE_MODEL)
        strength = inputs.get("strength", "subtle")
        start = int(inputs.get("start_index", 0))
        made, errors = [], []
        for i in range(start, start + int(inputs.get("count", 5))):
            over = self._budget_problem(inputs, model, 1)
            if over:
                errors.append(over)
                break
            out = cdir / f"cand_{i + 1:02d}.png"
            res = self._call_image(d, beautify_prompt(i, strength), refs[:4], out, model)
            if res.success:
                self._ledger_add(inputs, "beautify", model, out.name, res.cost_usd)
            (made if res.success else errors).append(out.relative_to(d).as_posix() if res.success else res.error)
        prof = pp.read_profile(pid)
        prof.setdefault("identity", {"canonical": ""})
        known = [c for c in prof["identity"].get("candidates", []) if c not in made]
        meta = prof["identity"].get("candidate_meta", {})
        meta.update({m: {"strength": strength, "model": model} for m in made})
        prof["identity"].update({"candidates": known + made, "model": model, "candidate_meta": meta})
        # canonical is required by the schema only when locked; keep a placeholder path until picked.
        prof["identity"]["canonical"] = prof["identity"].get("canonical") or "identity/canonical.png"
        pp.write_profile(d, prof)
        return ToolResult(success=bool(made), data={"candidates": made, "errors": errors, "model": model},
                          error=None if made else "; ".join(map(str, errors)))

    def _wardrobe(self, d: Path, pid: str, inputs: dict[str, Any]) -> ToolResult:
        blocked = self._guard_paid(inputs) or self._consent_problem(pid)
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

    def _hairstyle(self, d: Path, pid: str, inputs: dict[str, Any]) -> ToolResult:
        """Hair-only edit of the LOCKED canonical portrait → identity/hair/<id>.png + hair_catalog.json."""
        blocked = self._guard_paid(inputs) or self._consent_problem(pid)
        canonical = d / "identity" / "canonical.png"
        if not blocked and not canonical.is_file():
            blocked = "identity/canonical.png not set — pick a canonical first"
        vid, desc = inputs.get("variant_id"), inputs.get("description")
        if not blocked and (not vid or not desc):
            blocked = "variant_id and description are required"
        model = inputs.get("model", DEFAULT_IMAGE_MODEL)
        blocked = blocked or self._budget_problem(inputs, model, 1)
        if blocked:
            return ToolResult(success=False, error=blocked)
        out = d / "identity" / "hair" / f"{vid}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        res = self._call_image(d, hairstyle_prompt(desc), [canonical], out, model)
        if not res.success:
            return ToolResult(success=False, error=res.error)
        self._ledger_add(inputs, "hairstyle", model, out.name, res.cost_usd)
        cat_path = d / "identity" / "hair_catalog.json"
        catalog = json.loads(cat_path.read_text()) if cat_path.is_file() else []
        catalog = [c for c in catalog if c["id"] != vid]
        catalog.append({"id": vid, "description": desc, "prompt": hairstyle_prompt(desc), "image": out.relative_to(d).as_posix(),
                        "model": model, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        cat_path.write_text(json.dumps(catalog, indent=2))
        cat_path.chmod(0o600)
        return ToolResult(success=True, data={"variant": vid, "image": str(out), "catalog_size": len(catalog)})

    def _background_plate(self, d: Path, pid: str, inputs: dict[str, Any]) -> ToolResult:
        """Person-free 16:9 plate (no reference photo of the owner is sent) → backgrounds/<id>.png (+ catalog entry)."""
        blocked = self._guard_paid(inputs)
        vid, scene = inputs.get("variant_id"), inputs.get("scene")
        if not blocked and (not vid or not scene):
            blocked = "variant_id and scene are required"
        model = inputs.get("model", DEFAULT_IMAGE_MODEL)
        res_label = inputs.get("resolution", "2K")
        blocked = blocked or self._budget_problem(inputs, model, 1, res_label)
        if blocked:
            return ToolResult(success=False, error=blocked)
        out = d / "backgrounds" / f"{vid}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        res = self._imagen().execute({"prompt": plate_prompt(scene), "model": model, "output_path": str(out),
                                      "aspect_ratio": "16:9", "resolution": res_label})
        if not res.success:
            return ToolResult(success=False, error=res.error)
        _ensure_real_png(out)
        out.chmod(0o600)
        self._ledger_add(inputs, "background_plate", model, out.name, res.cost_usd, res_label)
        from lib import backdrops

        backdrops.upsert(d, {"id": vid, "kind": "plate", "label": inputs.get("label", vid), "image": out.relative_to(d).as_posix(),
                             "scene": scene, "model": model, "safe_region": backdrops.SAFE_REGION, "cost": "generated plate"})
        return ToolResult(success=True, data={"variant": vid, "image": str(out)})

    def _standin_portrait(self, d: Path, pid: str, inputs: dict[str, Any]) -> ToolResult:
        """Generate a FICTIONAL portrait for a stand-in profile (dev only; never a real person's likeness)."""
        from lib.twin_prompts import standin_portrait_prompt

        if not pp.read_profile(pid).get("standin"):
            return ToolResult(success=False, error="standin_portrait only works on profiles created with standin: true")
        blocked = self._guard_paid(inputs)
        if blocked:
            return ToolResult(success=False, error=blocked)
        model = inputs.get("model", DEFAULT_IMAGE_MODEL)
        est = self.estimate_cost({"operation": "wardrobe", "model": model})  # one call
        cap = inputs.get("budget_cap_usd")
        if cap is not None and float(inputs.get("actual_spent_usd", 0)) + est > float(cap):
            return ToolResult(success=False, error=f"dev budget cap ${float(cap):.2f} would be exceeded")
        cdir = d / "identity" / "candidates"
        cdir.mkdir(parents=True, exist_ok=True)
        out = cdir / f"cand_{int(inputs.get('index', 0)) + 1:02d}.png"
        res = self._call_image(d, standin_portrait_prompt(int(inputs.get("index", 0))), [], out, model)
        if not res.success:
            return ToolResult(success=False, error=res.error)
        return ToolResult(success=True, cost_usd=res.cost_usd, data={"candidate": out.stem, "path": str(out), "model": model,
                                                                      "estimated_usd": est, "reported_cost_usd": res.cost_usd})

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
