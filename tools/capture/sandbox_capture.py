"""Sandbox capture — real screen recordings inside a disposable container (spec §5.7, D14–D16).

The agent never automates the owner's real desktop. Each capture runs a validated capture
script in a throw-away Apple ``container`` VM (Colima/Docker fallback) with a *copy* of the
workspace, default-deny networking (allow-list proxy + iptables owner-match), CPU/memory
caps and a wall-clock timeout; the container is deleted afterwards and only the outputs
(recording, step screenshots, step log, network log) are kept.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from lib.heavy_lock import DEFAULT_RENDER_WAIT_S, HeavyJobBusy, heavy_job
from lib.sandbox.capture_script import needs_owner_login, validate_capture_script
from lib.sandbox.runtime import ContainerRuntime, Mount, RunSpec, cleanup_stale, current_image_tag, detect_runtime
from lib.sandbox.workspace import prepare_workspace
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

REPO_ROOT = Path(__file__).resolve().parents[2]
SANDBOX_DIR = REPO_ROOT / "sandbox"
BOOT_GRACE_S = 240  # container boot + code-server/Chromium startup on top of max_duration_s
NOVNC_PORT = 6080


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _probe(path: Path) -> dict[str, Any]:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
        info = json.loads(out)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        num, _, den = v.get("r_frame_rate", "0/1").partition("/")
        return {
            "duration_seconds": round(float(info["format"]["duration"]), 2),
            "width": int(v["width"]), "height": int(v["height"]),
            "fps": round(int(num) / max(int(den or 1), 1), 2), "codec": v.get("codec_name"),
        }
    except Exception:  # noqa: BLE001
        return {}


def summarize_network(out_dir: Path) -> dict[str, Any]:
    """Allowed/denied request summary + whether kernel-level enforcement was active."""
    summary: dict[str, Any] = {"allowed": [], "denied": [], "iptables": None}
    enf = out_dir / "network" / "enforcement.json"
    if enf.is_file():
        try:
            summary["iptables"] = bool(json.loads(enf.read_text()).get("iptables"))
        except ValueError:
            pass
    log = out_dir / "network" / "network_log.jsonl"
    if log.is_file():
        for line in log.read_text().splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("decision") == "allow":
                summary["allowed"].append(ev.get("host"))
            elif ev.get("decision") == "deny":
                summary["denied"].append({"host": ev.get("host"), "reason": ev.get("reason")})
    summary["allowed"] = sorted(set(summary["allowed"]))
    return summary


class SandboxCapture(BaseTool):
    name = "sandbox_capture"
    version = "1.0.0"
    tier = ToolTier.SOURCE
    capability = "screen_capture"
    provider = "sandbox"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["binary:ffmpeg", "binary:ffprobe"]
    agent_skills = ["playwright-recording", "ffmpeg"]
    fallback_tools: list[str] = []
    install_instructions = (
        "Install Apple `container` (macOS 26+, Apple Silicon): download the signed .pkg from "
        "https://github.com/apple/container/releases, install it, then run `container system start`. "
        "Build the capture image: operation `build_image` (tags it openmontage-capture:<hash of sandbox/>, then removes every older "
        "capture image and stale om-capture-* container). Colima or Docker also work as OCI runtimes."
    )

    capabilities = ["sandboxed_screen_recording", "code_server_capture", "browser_capture", "terminal_capture", "owner_login_pause"]
    supports = {"surfaces": ["code_server", "browser", "terminal"], "network_default": "deny", "owner_login": True}
    best_for = [
        "real code-running and website-usage footage for tutorials without touching the owner's desktop",
        "reproducible, scripted captures with a step log for callout timing",
    ]
    not_good_for = [
        "Mac-only apps (the sandbox is a Linux VM)",
        "anything needing the owner's real accounts (owner logs into a dedicated test account himself)",
    ]

    input_schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["run", "build_image", "start", "status", "confirm_login", "collect", "cleanup"], "default": "run"},
            "project_dir": {"type": "string", "description": "projects/<id> directory; outputs go to assets/captures/<capture_id>/"},
            "workspace": {"type": "string", "description": "Source directory to COPY into the sandbox (never mounted directly)"},
            "focus": {"type": "array", "items": {"type": "string"}, "description": "Sub-paths of workspace to include"},
            "script": {"type": "object", "description": "Capture script (schemas/artifacts/capture_script.schema.json)"},
            "capture_id": {"type": "string", "description": "For status/confirm_login/collect"},
            "resolution": {"type": "string", "default": "1920x1080"},
            "fps": {"type": "integer", "default": 30},
            "max_duration_s": {"type": "integer", "default": 120, "maximum": 900},
            "cpus": {"type": "integer", "default": 4},
            "memory": {"type": "string", "default": "4G"},
            "runtime": {"type": "string", "enum": ["apple_container", "colima", "docker"]},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=4096, vram_mb=0, disk_mb=3000, network_required=False)
    retry_policy = RetryPolicy(max_retries=0)
    side_effects = [
        "starts and deletes a container per capture",
        "writes projects/<id>/assets/captures/<capture_id>/",
        "takes the host heavy-job lock while recording",
    ]
    user_visible_verification = [
        "Watch capture.mp4 and the step screenshots",
        "Check network.denied / network.iptables in the result to see what the sandbox blocked",
    ]

    # ---- status -----------------------------------------------------------
    def _runtime(self, preferred: str | None = None) -> Optional[ContainerRuntime]:
        return detect_runtime(preferred)

    def get_status(self) -> ToolStatus:
        rt = self._runtime()
        if rt is None:
            return ToolStatus.UNAVAILABLE
        return ToolStatus.AVAILABLE if rt.image_exists() else ToolStatus.DEGRADED

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    # ---- execute ----------------------------------------------------------
    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        op = inputs.get("operation", "run")
        started = time.time()
        rt = self._runtime(inputs.get("runtime"))
        if rt is None:
            return ToolResult(success=False, error="No ready container runtime. " + self.install_instructions)
        try:
            if op == "build_image":
                return self._build_image(rt)
            if op == "cleanup":
                return ToolResult(success=True, data={"cleanup": self._cleanup(rt)})
            if op == "run":
                res = self._start(rt, inputs, blocking=True)
            elif op == "start":
                res = self._start(rt, inputs, blocking=False)
            elif op == "status":
                res = self._status(inputs)
            elif op == "confirm_login":
                res = self._confirm_login(inputs)
            elif op == "collect":
                res = self._collect(rt, inputs)
            else:
                return ToolResult(success=False, error=f"unknown operation {op!r}")
        except HeavyJobBusy as exc:
            return ToolResult(success=False, error=f"{exc}. Captures never run alongside lip-sync or Remotion renders (24 GB).")
        res.duration_seconds = round(time.time() - started, 2)
        return res

    # ---- operations ---------------------------------------------------------
    def _cleanup(self, rt: ContainerRuntime, active_name: str | None = None) -> dict[str, Any]:
        """Best-effort cleanup; a failure here must never fail the build/capture that triggered it."""
        try:
            return cleanup_stale(rt, current_image_tag(), active_name=active_name)
        except Exception as exc:  # noqa: BLE001
            return {"errors": [f"cleanup failed: {type(exc).__name__}: {exc}"]}

    def _build_image(self, rt: ContainerRuntime) -> ToolResult:
        tag = current_image_tag()
        if rt.image_exists(tag):
            return ToolResult(success=True, data={"image": tag, "runtime": rt.name, "rebuilt": False, "cleanup": self._cleanup(rt)})
        proc = subprocess.run(rt.build_argv(tag, str(SANDBOX_DIR), str(SANDBOX_DIR / "Dockerfile")), capture_output=True, text=True)
        if proc.returncode != 0:  # never clean up after a failed build: the old image is still the only one that works
            return ToolResult(success=False, error=f"image build failed: {proc.stderr[-2000:]}")
        return ToolResult(success=True, data={"image": tag, "runtime": rt.name, "rebuilt": True, "cleanup": self._cleanup(rt)})

    def _paths(self, project_dir: Path, capture_id: str) -> dict[str, Path]:
        scratch = project_dir / ".sandbox" / capture_id
        return {
            "scratch": scratch, "workspace": scratch / "workspace", "out": scratch / "out",
            "final": project_dir / "assets" / "captures" / capture_id,
        }

    def _start(self, rt: ContainerRuntime, inputs: dict[str, Any], blocking: bool) -> ToolResult:
        script = inputs.get("script") or {}
        problems = validate_capture_script(script) if script else ["script is required"]
        if problems:
            return ToolResult(success=False, error="invalid capture script: " + "; ".join(problems))
        login = needs_owner_login(script)
        if login and blocking:
            return ToolResult(success=False, error="script has await_owner_login: use operation start → confirm_login → collect")
        if not inputs.get("project_dir"):
            return ToolResult(success=False, error="project_dir is required (outputs go under projects/<id>/assets/captures/)")
        image = current_image_tag()
        if not rt.image_exists(image):
            return ToolResult(success=False, error=f"capture image {image} not built (sandbox/ changed or never built). Run operation build_image first.")
        cleanup = self._cleanup(rt)  # sweep leftovers from crashed runs before creating the new container
        project_dir = Path(inputs["project_dir"]).resolve()
        cid = script["capture_id"]
        paths = self._paths(project_dir, cid)
        shutil.rmtree(paths["scratch"], ignore_errors=True)
        paths["out"].mkdir(parents=True)

        if inputs.get("workspace"):
            report = prepare_workspace(Path(inputs["workspace"]), paths["workspace"], inputs.get("focus"))
        else:
            paths["workspace"].mkdir(parents=True)
            report = {"copied": [], "excluded": {}, "redacted": []}
        (paths["out"] / "script.json").write_text(json.dumps(script, indent=2))

        max_s = int(inputs.get("max_duration_s", 120))
        name = f"om-capture-{cid}-{int(time.time())}"
        allow = script.get("allow_domains", [])
        spec = RunSpec(
            image=image, name=name, cpus=int(inputs.get("cpus", 4)), memory=str(inputs.get("memory", "4G")),
            mounts=[Mount(str(paths["workspace"]), "/workspace"), Mount(str(paths["out"]), "/out")],
            env={"ALLOW_DOMAINS": ",".join(allow), "RESOLUTION": inputs.get("resolution", "1920x1080"),
                 "FPS": str(inputs.get("fps", 30)), "MAX_DURATION_S": str(max_s), "OWNER_LOGIN": "1" if login else "0"},
            publish=[f"127.0.0.1:{NOVNC_PORT}:6080"] if login else [],
            cap_add=["CAP_NET_ADMIN"], detach=not blocking,
        )
        state = {"name": name, "capture_id": cid, "project_dir": str(project_dir), "max_duration_s": max_s,
                 "started": time.time(), "runtime": rt.name, "workspace_report": {
                     "copied": len(report["copied"]), "excluded": report["excluded"], "redacted": report["redacted"]},
                 "script": script}
        (paths["scratch"] / "state.json").write_text(json.dumps(state))

        if not blocking:
            proc = subprocess.run(rt.run_argv(spec), capture_output=True, text=True)
            if proc.returncode != 0:
                rt.teardown(name)
                return ToolResult(success=False, error=f"container failed to start: {proc.stderr[-1500:]}")
            return ToolResult(success=True, data={
                "capture_id": cid, "status": "started", "container": name, "cleanup": cleanup,
                "novnc_url": f"http://127.0.0.1:{NOVNC_PORT}/vnc.html?autoconnect=1&resize=scale" if login else None,
                "next": "status → confirm_login (after the owner has logged in himself) → collect",
            })

        with heavy_job(f"sandbox_capture:{cid}", wait=DEFAULT_RENDER_WAIT_S):
            try:
                subprocess.run(rt.run_argv(spec), capture_output=True, text=True, timeout=max_s + BOOT_GRACE_S)
            except subprocess.TimeoutExpired:
                pass  # result.json absent -> reported as timeout below
            finally:
                rt.teardown(name)
        res = self._finish(project_dir, cid)
        if isinstance(res.data, dict):
            res.data["cleanup"] = cleanup
        return res

    def _load_state(self, inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Path]] | None:
        cid, pd = inputs.get("capture_id"), inputs.get("project_dir")
        if not cid or not pd:
            return None
        paths = self._paths(Path(pd).resolve(), cid)
        sf = paths["scratch"] / "state.json"
        if not sf.is_file():
            return None
        return json.loads(sf.read_text()), paths

    def _status(self, inputs: dict[str, Any]) -> ToolResult:
        loaded = self._load_state(inputs)
        if not loaded:
            return ToolResult(success=False, error="unknown capture (need project_dir + capture_id)")
        _, paths = loaded
        out = paths["out"]
        phase = ("finished" if (out / "result.json").is_file()
                 else "awaiting_owner_login" if (out / "awaiting_owner_login").is_file() else "running")
        return ToolResult(success=True, data={"capture_id": inputs["capture_id"], "phase": phase})

    def _confirm_login(self, inputs: dict[str, Any]) -> ToolResult:
        loaded = self._load_state(inputs)
        if not loaded:
            return ToolResult(success=False, error="unknown capture (need project_dir + capture_id)")
        _, paths = loaded
        if not (paths["out"] / "awaiting_owner_login").is_file():
            return ToolResult(success=False, error="capture is not waiting for owner login")
        (paths["out"] / "owner_login_done").write_text("confirmed by owner in chat")
        return ToolResult(success=True, data={"capture_id": inputs["capture_id"], "phase": "login_confirmed"})

    def _collect(self, rt: ContainerRuntime, inputs: dict[str, Any]) -> ToolResult:
        loaded = self._load_state(inputs)
        if not loaded:
            return ToolResult(success=False, error="unknown capture (need project_dir + capture_id)")
        state, paths = loaded
        end = time.time() + state["max_duration_s"] + BOOT_GRACE_S + 600
        while not (paths["out"] / "result.json").is_file() and time.time() < end:
            time.sleep(2)
        rt.teardown(state["name"])
        return self._finish(Path(state["project_dir"]), state["capture_id"])

    def _finish(self, project_dir: Path, cid: str) -> ToolResult:
        """Copy outputs to assets/captures/<id>/, build the asset record, delete the scratch copy."""
        paths = self._paths(project_dir, cid)
        out = paths["out"]
        state = json.loads((paths["scratch"] / "state.json").read_text())
        result_file = out / "result.json"
        network = summarize_network(out)
        if not result_file.is_file():
            shutil.rmtree(paths["scratch"], ignore_errors=True)
            return ToolResult(success=False, error=f"capture {cid} produced no result (timeout or container failure)",
                              data={"network": network})
        result = json.loads(result_file.read_text())
        final = paths["final"]
        shutil.rmtree(final, ignore_errors=True)
        final.mkdir(parents=True)
        video_src = out / "capture.mp4"
        artifacts: list[str] = []
        for name in ("steps.json", "result.json"):
            if (out / name).is_file():
                shutil.copy2(out / name, final / name)
        if (out / "screenshots").is_dir():
            shutil.copytree(out / "screenshots", final / "screenshots")
        (final / "network.json").write_text(json.dumps(network, indent=2))
        asset: dict[str, Any] | None = None
        if result.get("status") == "ok" and video_src.is_file():
            shutil.copy2(video_src, final / "capture.mp4")
            probe = _probe(final / "capture.mp4")
            first_nav = next((s["url"] for s in state["script"]["steps"] if s["action"] == "navigate"), None)
            asset = {
                "asset_id": f"capture_{cid}", "id": f"capture_{cid}", "asset_type": "sandbox_capture", "type": "sandbox_capture",
                "path": str((final / "capture.mp4").relative_to(project_dir)),
                "source_tool": "sandbox_capture", "provider_id": "sandbox_capture", "runtime": "local",
                "source_type": "sandbox_capture", "sha256": _sha256(final / "capture.mp4"),
                "rights_status": "self_captured", "license": "self-captured",
                "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "status": "validated",
                "cost_estimate_usd": 0.0, "actual_cost_usd": 0.0,
                "steps_log": str((final / "steps.json").relative_to(project_dir)),
                **probe,
            }
            if first_nav:
                asset["source_url"] = first_nav
            artifacts.append(str(final / "capture.mp4"))
        shutil.rmtree(paths["scratch"], ignore_errors=True)  # workspace copy + scratch never outlive the capture
        ok = asset is not None
        return ToolResult(
            success=ok,
            error=None if ok else f"capture {cid} failed: {result.get('error')}",
            data={"capture_id": cid, "status": result.get("status"), "asset": asset, "output_dir": str(final),
                  "network": network, "workspace_report": state["workspace_report"], "result": result},
            artifacts=artifacts,
        )
