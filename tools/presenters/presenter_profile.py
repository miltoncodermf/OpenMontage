"""presenter_profile — load / validate / lock / guard the private presenter profile (spec §5.5).

The profile lives outside git at ``~/.openmontage/presenter_profiles/<id>/`` (mode 700). Raw
owner recordings inside it are onboarding source material only and can never be minted as
presenter assets.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from lib import presenter_profile as pp
from lib.recording_validation import validate_recording
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


class PresenterProfileTool(BaseTool):
    name = "presenter_profile"
    version = "1.0.0"
    tier = ToolTier.SOURCE
    capability = "avatar"
    provider = "local"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["binary:ffmpeg", "binary:ffprobe"]
    agent_skills = ["ffmpeg"]
    install_instructions = "Run the `presenter-onboarding` pipeline once to create and lock a presenter profile."
    capabilities = ["profile_create", "profile_verify", "profile_lock", "recording_validation", "presenter_asset_mint", "raw_guard"]
    supports = {"operations": ["init", "adopt", "status", "verify", "lock", "validate_recording", "record_raw", "register_raw", "normalize_raw", "fix_permissions", "record_consent", "set_defaults", "mint_asset", "check_asset"]}
    best_for = ["loading the locked presenter profile and guarding that only the beautified twin is ever rendered"]
    not_good_for = ["generating anything (use twin_* tools)"]

    input_schema = {
        "type": "object",
        "required": ["operation"],
        "properties": {
            "standin": {"type": "boolean", "default": False, "description": "init only: dev-only fictional stand-in profile; its assets can never pass final_review"},
            "operation": {"type": "string", "enum": ["init", "adopt", "status", "verify", "lock", "validate_recording", "record_raw", "register_raw", "normalize_raw", "fix_permissions", "record_consent", "set_defaults", "mint_asset", "check_asset"]},
            "filename": {"type": "string", "description": "register_raw: file name already inside raw/"},
            "statement": {"type": "string", "description": "record_consent: what the owner agreed to"},
            "hairstyle": {"type": "string", "description": "set_defaults: hair catalog id, or 'current'"},
            "background": {"type": "string", "description": "set_defaults: background catalog id"},
            "likeness_consent": {"type": "boolean", "description": "record_consent: only true when the owner said yes"},
            "profile_id": {"type": "string"},
            "display_name": {"type": "string"},
            "kind": {"type": "string", "enum": ["face_turn", "performance", "voice_read"]},
            "path": {"type": "string"},
            "asset": {"type": "object"},
            "asset_type": {"type": "string"},
            "variant_id": {"type": "string"},
            "project_dir": {"type": "string"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=10, network_required=False)
    retry_policy = RetryPolicy(max_retries=0)
    side_effects = ["creates/updates ~/.openmontage/presenter_profiles/<id>/ (mode 700)"]

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        op = inputs.get("operation")
        try:
            if op == "init":
                d = pp.create_profile(inputs["profile_id"], inputs.get("display_name", ""), standin=bool(inputs.get("standin", False)))
                return ToolResult(success=True, data={"profile_dir": str(d)})
            if op == "adopt":
                return ToolResult(success=True, data=pp.adopt_profile(inputs["profile_id"], inputs.get("display_name", "")))
            if op == "register_raw":
                return ToolResult(success=True, data=pp.register_raw_in_place(inputs["profile_id"], inputs["kind"], inputs["filename"]))
            if op == "normalize_raw":
                return ToolResult(success=True, data=pp.normalize_raw(inputs["profile_id"], inputs["kind"]))
            if op == "fix_permissions":
                return ToolResult(success=True, data={"changed": pp.fix_permissions(pp.profile_dir(inputs["profile_id"]))})
            if op == "record_consent":
                return ToolResult(success=True, data=pp.record_consent(
                    inputs["profile_id"], likeness_consent=bool(inputs.get("likeness_consent")), statement=inputs.get("statement", "")))
            if op == "set_defaults":
                return ToolResult(success=True, data=pp.set_defaults(
                    inputs["profile_id"], hairstyle=inputs.get("hairstyle"), background=inputs.get("background")))
            if op == "status":
                prof = pp.read_profile(inputs["profile_id"])
                return ToolResult(success=True, data={"locked": prof["locked"], "profile": prof,
                                                      "profile_dir": str(pp.profile_dir(inputs["profile_id"]))})
            if op == "verify":
                problems = pp.verify_profile(inputs["profile_id"], require_locked=True)
                return ToolResult(success=not problems, data={"problems": problems},
                                  error="; ".join(problems) if problems else None)
            if op == "lock":
                prof = pp.lock_profile(inputs["profile_id"])
                return ToolResult(success=True, data={"locked_at": prof["locked_at"], "files": len(prof["files"])})
            if op == "validate_recording":
                res = validate_recording(inputs["kind"], Path(inputs["path"]))
                return ToolResult(success=res["ok"], data=res, error="; ".join(res["problems"]) if res["problems"] else None)
            if op == "record_raw":
                return self._record_raw(inputs)
            if op == "mint_asset":
                asset = pp.mint_presenter_asset(
                    inputs["profile_id"], Path(inputs["path"]), asset_type=inputs.get("asset_type", "presenter_video"),
                    variant_id=inputs.get("variant_id", "default"), source_tool="presenter_profile",
                    project_dir=Path(inputs["project_dir"]) if inputs.get("project_dir") else None)
                return ToolResult(success=True, data={"asset": asset})
            if op == "check_asset":
                from lib.presenter_guard import presenter_asset_problems

                problems = presenter_asset_problems(inputs["asset"])
                return ToolResult(success=not problems, data={"problems": problems}, error="; ".join(problems) or None)
            return ToolResult(success=False, error=f"unknown operation {op!r}")
        except (pp.ProfileError, KeyError, ValueError, OSError, subprocess.SubprocessError) as exc:
            return ToolResult(success=False, error=str(exc))

    def _record_raw(self, inputs: dict[str, Any]) -> ToolResult:
        """Copy a validated owner recording into the profile's raw/ and register it in profile.json."""
        import shutil

        pid, kind = inputs["profile_id"], inputs["kind"]
        src = Path(inputs["path"])
        check = validate_recording(kind, src)
        if not check["ok"]:
            return ToolResult(success=False, data=check, error="recording failed validation: " + "; ".join(check["problems"]))
        d = pp.profile_dir(pid)
        prof = pp.read_profile(pid)
        if prof.get("locked"):
            return ToolResult(success=False, error="profile is locked; raw recordings cannot change")
        dest = d / "raw" / f"{kind}{src.suffix.lower()}"
        shutil.copy2(src, dest)
        dest.chmod(0o600)
        raw = prof.setdefault("raw", {})
        raw[kind] = {"file": dest.relative_to(d).as_posix(), "sha256": pp.sha256_file(dest), "probe": check["probe"]}
        pp.write_profile(d, prof)
        return ToolResult(success=True, data={"stored": str(dest), "probe": check["probe"]})
