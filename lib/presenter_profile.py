"""Private presenter profile storage (spec D3–D5, §5.5).

Layout: ``~/.openmontage/presenter_profiles/<profile_id>/`` (override ``OPENMONTAGE_PROFILE_ROOT``),
directory mode 700, outside git. ``raw/`` holds the owner's recordings — source material only,
never rendered, never copied into ``projects/``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path
from typing import Any

from schemas.artifacts import validate_artifact

SUBDIRS = ("raw", "identity/refs", "identity/wardrobe", "loops", "performance", "voice/candidates")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class ProfileError(ValueError):
    pass


def profile_root() -> Path:
    env = os.environ.get("OPENMONTAGE_PROFILE_ROOT")
    return Path(env).expanduser() if env else Path.home() / ".openmontage" / "presenter_profiles"


def profile_dir(profile_id: str) -> Path:
    if not ID_RE.match(profile_id):
        raise ProfileError(f"invalid profile_id {profile_id!r}")
    return profile_root() / profile_id


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def create_profile(profile_id: str, display_name: str = "", standin: bool = False) -> Path:
    """Create the 700-mode directory tree and an unlocked profile.json skeleton."""
    d = profile_dir(profile_id)
    if (d / "profile.json").exists():
        raise ProfileError(f"profile {profile_id!r} already exists")
    root = profile_root()
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    d.mkdir(exist_ok=True)
    os.chmod(d, 0o700)
    for sub in SUBDIRS:
        (d / sub).mkdir(parents=True, exist_ok=True)
    for p in [d, *[q for q in d.rglob("*") if q.is_dir()]]:
        os.chmod(p, 0o700)
    skeleton = {
        "version": "1.0", "profile_id": profile_id, "display_name": display_name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "locked": False, "files": {},
    }
    if standin:
        skeleton["standin"] = True
        skeleton["standin_note"] = "STAND-IN — fictional person, not the owner; engine validation only. Can never pass final_review."
    write_profile(d, skeleton)
    return d


def fix_permissions(d: Path) -> list[str]:
    """chmod the profile tree to 700 (dirs) / 600 (files); returns what changed. Finder junk is deleted."""
    changed: list[str] = []
    for junk in list(d.rglob(".DS_Store")):
        junk.unlink()
        changed.append(f"removed {junk.relative_to(d).as_posix()}")
    for p in [d, *sorted(d.rglob("*"))]:
        if p.is_symlink():
            continue
        want = 0o700 if p.is_dir() else 0o600
        have = stat.S_IMODE(p.stat().st_mode)
        if have != want:
            os.chmod(p, want)
            changed.append(f"{p.relative_to(d).as_posix() or '.'}: {oct(have)} -> {oct(want)}")
    return changed


def adopt_profile(profile_id: str, display_name: str = "") -> dict[str, Any]:
    """Initialise a profile around a folder the owner created by hand, keeping whatever is in ``raw/``.

    Creates the missing subdirectories and the unlocked profile.json skeleton, fixes permissions to 700/600.
    No consent is recorded here: ``record_consent`` does that only after the owner says yes.
    """
    d = profile_dir(profile_id)
    if (d / "profile.json").exists():
        raise ProfileError(f"profile {profile_id!r} already has a profile.json")
    if not d.is_dir():
        raise ProfileError(f"{d} does not exist; use create_profile for a new profile")
    for sub in SUBDIRS:
        (d / sub).mkdir(parents=True, exist_ok=True)
    skeleton = {"version": "1.0", "profile_id": profile_id, "display_name": display_name,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "locked": False, "files": {}}
    write_profile(d, skeleton)
    changed = fix_permissions(d)
    return {"profile_dir": str(d), "permissions_changed": changed}


def read_profile(profile_id: str) -> dict[str, Any]:
    f = profile_dir(profile_id) / "profile.json"
    if not f.is_file():
        raise ProfileError(f"profile {profile_id!r} not found at {f.parent}")
    return json.loads(f.read_text(encoding="utf-8"))


def write_profile(d: Path, data: dict[str, Any]) -> None:
    validate_artifact("presenter_profile", data)
    f = d / "profile.json"
    f.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(f, 0o600)


def file_hashes(d: Path) -> dict[str, str]:
    out = {}
    for p in sorted(d.rglob("*")):
        if p.is_file() and p.name not in ("profile.json", ".DS_Store") and not p.is_symlink():
            out[p.relative_to(d).as_posix()] = sha256_file(p)
    return out


def lock_profile(profile_id: str) -> dict[str, Any]:
    """Lock: requires canonical identity image + voice profile; records hashes of every file."""
    d = profile_dir(profile_id)
    prof = read_profile(profile_id)
    ident = prof.get("identity") or {}
    voice = prof.get("voice") or {}
    for label, rel in (("identity.canonical", ident.get("canonical")), ("voice.profile", voice.get("profile"))):
        if not rel or not (d / rel).is_file():
            raise ProfileError(f"cannot lock: {label} missing ({rel!r})")
    ident["identity_transform"] = "beautified"
    prof["identity"] = ident
    prof["files"] = file_hashes(d)
    prof["locked"] = True
    prof["locked_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_profile(d, prof)
    return prof


def verify_profile(profile_id: str, require_locked: bool = True) -> list[str]:
    """Return problems (empty = OK): permissions, locked flag, hash mismatches, missing files."""
    problems: list[str] = []
    d = profile_dir(profile_id)
    try:
        prof = read_profile(profile_id)
        validate_artifact("presenter_profile", prof)
    except Exception as exc:  # noqa: BLE001
        return [f"profile.json invalid: {exc}"]
    mode = stat.S_IMODE(d.stat().st_mode)
    if mode & 0o077:
        problems.append(f"profile directory mode is {oct(mode)}, expected 700")
    if require_locked and not prof.get("locked"):
        problems.append("profile is not locked")
    if prof.get("locked"):
        current = file_hashes(d)
        for rel, digest in prof["files"].items():
            if rel not in current:
                problems.append(f"missing file {rel}")
            elif current[rel] != digest:
                problems.append(f"hash mismatch {rel}")
        for rel in current:
            if rel not in prof["files"]:
                problems.append(f"unrecorded file {rel}")
    return problems


def register_raw_in_place(profile_id: str, kind: str, filename: str) -> dict[str, Any]:
    """Register a recording that already sits in ``raw/`` (validated, sha256 + probe stored; file untouched)."""
    from lib.recording_validation import validate_recording

    d = profile_dir(profile_id)
    prof = read_profile(profile_id)
    if prof.get("locked"):
        raise ProfileError("profile is locked; raw recordings cannot change")
    f = (d / "raw" / filename).resolve()
    if f.parent != (d / "raw").resolve() or not f.is_file():
        raise ProfileError(f"raw/{filename} not found")
    check = validate_recording(kind, f)
    if not check["ok"]:
        raise ProfileError("recording failed validation: " + "; ".join(check["problems"]))
    os.chmod(f, 0o600)
    prof.setdefault("raw", {})[kind] = {"file": f"raw/{f.name}", "sha256": sha256_file(f), "probe": check["probe"]}
    write_profile(d, prof)
    return prof["raw"][kind]


def normalize_raw(profile_id: str, kind: str) -> dict[str, Any]:
    """Make the SDR/upright working copy of a raw video and register it; the raw file stays byte-identical."""
    from lib.recording_normalize import WORKING_DIRNAME, normalize_video

    d = profile_dir(profile_id)
    prof = read_profile(profile_id)
    if prof.get("locked"):
        raise ProfileError("profile is locked; working copies cannot change")
    entry = (prof.get("raw") or {}).get(kind)
    if not entry:
        raise ProfileError(f"raw {kind} is not registered")
    src = d / entry["file"]
    if sha256_file(src) != entry["sha256"]:
        raise ProfileError(f"raw {kind} changed since registration (sha256 mismatch); refusing to continue")
    dst = d / "raw" / WORKING_DIRNAME / f"{kind}.sdr.mp4"
    report = normalize_video(src, dst)
    if sha256_file(src) != entry["sha256"]:  # belt and braces: the source must be untouched
        raise ProfileError(f"raw {kind} was modified during normalisation")
    os.chmod(dst.parent, 0o700)
    os.chmod(dst, 0o600)
    entry["working"] = {"file": dst.relative_to(d).as_posix(), "sha256": sha256_file(dst),
                        "normalization": {k: report[k] for k in ("filter", "rotation_baked", "tonemapped", "before", "after")}}
    write_profile(d, prof)
    return entry["working"]


def working_video(d: Path, kind: str, *, raw_fallback: bool = False) -> Path | None:
    """Path of the SDR/upright working copy of a raw video (None when absent).

    Pixel-reading tools (OpenCV, MediaPipe, LivePortrait, MuseTalk) must use this, never the phone original.
    ``raw_fallback`` returns the raw file only when it needs no normalising (SDR, upright, 8-bit).
    """
    from lib.recording_normalize import WORKING_DIRNAME, needs_normalizing

    w = d / "raw" / WORKING_DIRNAME / f"{kind}.sdr.mp4"
    if w.is_file():
        return w
    if raw_fallback:
        raw = next(iter(sorted((d / "raw").glob(f"{kind}.*"))), None)
        if raw is not None and not needs_normalizing(raw):
            return raw
    return None


def record_consent(profile_id: str, *, likeness_consent: bool, statement: str, recorded_on: str | None = None) -> dict[str, Any]:
    """Store the owner's likeness consent. Only call this with the owner's own yes (never assumed)."""
    d = profile_dir(profile_id)
    prof = read_profile(profile_id)
    if not likeness_consent:
        raise ProfileError("consent not given; nothing is written")
    prof["owner_consent"] = {"likeness_consent": True, "recorded_on": recorded_on or time.strftime("%Y-%m-%d"),
                             "statement": statement}
    write_profile(d, prof)
    return prof["owner_consent"]


def set_defaults(profile_id: str, *, hairstyle: str | None = None, background: str | None = None) -> dict[str, Any]:
    """Record the owner's default hairstyle and background (ids must exist in the profile's catalogs).

    ``hairstyle='current'`` means the locked canonical's own hair. The other catalog entries stay selectable.
    """
    import json as _json

    d = profile_dir(profile_id)
    prof = read_profile(profile_id)
    ident = prof.setdefault("identity", {})
    defaults = dict(ident.get("defaults") or {})
    if hairstyle is not None:
        cat = d / "identity" / "hair_catalog.json"
        ids = [h["id"] for h in _json.loads(cat.read_text())] if cat.is_file() else []
        if hairstyle != "current" and hairstyle not in ids:
            raise ProfileError(f"hairstyle {hairstyle!r} is not in identity/hair_catalog.json; have {ids}")
        defaults["hairstyle"] = hairstyle
    if background is not None:
        cat = d / "backgrounds" / "backgrounds_catalog.json"
        ids = [b["id"] for b in _json.loads(cat.read_text())] if cat.is_file() else []
        if background not in ids:
            raise ProfileError(f"background {background!r} is not in backgrounds/backgrounds_catalog.json; have {ids}")
        defaults["background"] = background
    ident["defaults"] = defaults
    write_profile(d, prof)
    return defaults


def default_portrait(profile_id: str) -> Path:
    """Portrait image of the default hairstyle (the canonical itself when the default is 'current')."""
    d = profile_dir(profile_id)
    ident = read_profile(profile_id).get("identity") or {}
    hair = (ident.get("defaults") or {}).get("hairstyle", "current")
    if hair == "current":
        return d / ident["canonical"]
    import json as _json

    for h in _json.loads((d / "identity" / "hair_catalog.json").read_text()):
        if h["id"] == hair:
            return d / h["image"]
    raise ProfileError(f"default hairstyle {hair!r} has no catalog entry")


def require_consent(profile_id: str) -> None:
    c = read_profile(profile_id).get("owner_consent") or {}
    if not c.get("likeness_consent"):
        raise ProfileError(f"profile {profile_id!r} has no recorded likeness consent; ask the owner first")


def is_inside_profile_raw(path: str | Path) -> bool:
    """True when the path (resolved) sits under any profile's ``raw/`` directory."""
    try:
        p = Path(path).expanduser().resolve()
        root = profile_root().resolve()
        rel = p.relative_to(root)
    except (ValueError, OSError):
        return False
    return len(rel.parts) >= 2 and rel.parts[1] == "raw"


def mint_presenter_asset(profile_id: str, path: Path, *, asset_type: str, variant_id: str, source_tool: str,
                         project_dir: Path | None = None, **extra: Any) -> dict[str, Any]:
    """Build a presenter asset record stamped ``identity_transform: beautified`` + profile_id.

    Refuses locked-profile mismatches and anything sourced from raw/. The path must be a
    *generated* twin output (never an owner recording).
    """
    if is_inside_profile_raw(path):
        raise ProfileError("raw owner recordings can never be minted as presenter assets")
    prof = read_profile(profile_id)
    if not prof.get("locked"):
        raise ProfileError("presenter assets may only be minted from a locked profile")
    path = Path(path).resolve()
    shown = str(path.relative_to(project_dir.resolve())) if project_dir and path.is_relative_to(project_dir.resolve()) else str(path)
    aid = f"presenter_{variant_id}_{sha256_file(path)[:8]}"
    standin = {"standin": True} if prof.get("standin") else {}
    return {**standin,
        "asset_id": aid, "id": aid, "asset_type": asset_type, "type": asset_type, "path": shown,
        "source_tool": source_tool, "provider_id": source_tool, "runtime": "local_gpu",
        "source_type": "digital_twin", "sha256": sha256_file(path),
        "identity_transform": "beautified", "profile_id": profile_id,
        "variant_id": variant_id, "status": "validated", "cost_estimate_usd": 0.0, "actual_cost_usd": 0.0, **extra,
    }
