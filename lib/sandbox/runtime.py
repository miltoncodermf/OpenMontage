"""Container runtime adapter for the capture sandbox (spec §5.7, D14).

``ContainerRuntime`` hides the CLI differences between Apple ``container`` (default),
Colima and Docker so the image (``sandbox/Dockerfile``, OCI-portable) and the
``sandbox_capture`` tool never branch on the runtime. Command builders return argv
lists so they can be unit-tested without a runtime installed.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

IMAGE_REPO = "openmontage-capture"
CONTAINER_PREFIX = "om-capture-"
ROLE_LABEL_KEY = "org.openmontage.role"
ROLE_LABEL = f"{ROLE_LABEL_KEY}=capture"
SANDBOX_DIR = Path(__file__).resolve().parents[2] / "sandbox"
# A running capture container younger than this is treated as in progress (max_duration 900 s + boot grace 240 s + collect wait 600 s).
ACTIVE_WINDOW_S = 900 + 240 + 600
_NAME_TS = re.compile(r"-(\d{9,11})$")


class ScopeError(RuntimeError):
    """A cleanup step tried to touch something that is not an OpenMontage capture image/container."""


def sandbox_hash(sandbox_dir: Path | None = None) -> str:
    """First 12 hex chars of a sha256 over every file under ``sandbox/`` (sorted relative path + bytes)."""
    root = Path(sandbox_dir or SANDBOX_DIR)
    h = hashlib.sha256()
    for p in sorted(q for q in root.rglob("*") if q.is_file() and "__pycache__" not in q.parts and q.name != ".DS_Store"):
        rel = p.relative_to(root).as_posix().encode()
        h.update(len(rel).to_bytes(4, "big") + rel)
        data = p.read_bytes()
        h.update(len(data).to_bytes(8, "big") + data)
    return h.hexdigest()[:12]


def current_image_tag(sandbox_dir: Path | None = None) -> str:
    return f"{IMAGE_REPO}:{sandbox_hash(sandbox_dir)}"


def image_repo_and_tag(ref: str) -> tuple[str, str]:
    """('openmontage-capture', 'abc') from 'openmontage-capture:abc' or 'docker.io/library/openmontage-capture:abc'."""
    name = ref.rsplit("/", 1)[-1]
    repo, _, tag = name.partition(":")
    return repo, tag


def assert_capture_image(ref: str) -> None:
    if image_repo_and_tag(ref)[0] != IMAGE_REPO:
        raise ScopeError(f"refusing to touch image {ref!r}: not an {IMAGE_REPO} image")


def assert_capture_container(name: str) -> None:
    if not name.startswith(CONTAINER_PREFIX):
        raise ScopeError(f"refusing to touch container {name!r}: name does not start with {CONTAINER_PREFIX!r}")


def _json_records(text: str) -> list[dict[str, Any]]:
    """A JSON array, a single object, or newline-delimited JSON (docker) -> list of dicts."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        data = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    data.append(json.loads(line))
                except ValueError:
                    continue
    if isinstance(data, dict):
        data = [data]
    return [d for d in data if isinstance(d, dict)]


@dataclass
class Mount:
    host: str
    container: str
    read_only: bool = False


@dataclass
class RunSpec:
    image: str
    name: str
    command: list[str] = field(default_factory=list)
    cpus: int = 4
    memory: str = "4G"
    mounts: list[Mount] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    publish: list[str] = field(default_factory=list)  # "127.0.0.1:6080:6080"
    cap_add: list[str] = field(default_factory=list)
    detach: bool = False


class ContainerRuntime:
    name = "base"
    binary = ""

    def __init__(self, which: Callable[[str], Optional[str]] = shutil.which,
                 runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
        self._which = which
        self._run = runner

    # --- detection -------------------------------------------------------
    def is_installed(self) -> bool:
        return self._which(self.binary) is not None

    def _ok(self, argv: list[str], timeout: int = 20) -> bool:
        try:
            return self._run(argv, capture_output=True, text=True, timeout=timeout).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def is_ready(self) -> bool:
        raise NotImplementedError

    # --- command builders ------------------------------------------------
    def build_argv(self, tag: str, context_dir: str, dockerfile: str) -> list[str]:
        raise NotImplementedError

    def run_argv(self, spec: RunSpec) -> list[str]:
        raise NotImplementedError

    def stop_argv(self, name: str) -> list[str]:
        raise NotImplementedError

    def remove_argv(self, name: str) -> list[str]:
        raise NotImplementedError

    def image_exists_argv(self, tag: str) -> list[str]:
        raise NotImplementedError

    # --- actions ---------------------------------------------------------
    def image_exists(self, tag: str | None = None) -> bool:
        return self._ok(self.image_exists_argv(tag or current_image_tag()))

    def teardown(self, name: str) -> None:
        """Best-effort stop + remove (the container must never outlive a capture)."""
        assert_capture_container(name)
        self._ok(self.stop_argv(name), timeout=30)
        self._ok(self.remove_argv(name), timeout=30)

    # --- cleanup (scoped to OpenMontage capture images/containers only) -----
    def _out(self, argv: list[str], timeout: int = 60) -> str:
        try:
            proc = self._run(argv, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return ""
        return proc.stdout if proc.returncode == 0 else ""

    def list_images_argv(self) -> list[str]:
        raise NotImplementedError

    def list_containers_argv(self) -> list[str]:
        raise NotImplementedError

    def remove_image_argv(self, ref: str) -> list[str]:
        raise NotImplementedError

    def prune_dangling_argv(self) -> list[str]:
        raise NotImplementedError

    def stop_builder_argv(self) -> Optional[list[str]]:
        return None  # only Apple `container` runs a separate builder VM

    def parse_images(self, text: str) -> list[str]:
        raise NotImplementedError

    def parse_containers(self, text: str) -> list[dict[str, str]]:
        raise NotImplementedError

    def list_capture_images(self) -> list[str]:
        """Every image reference whose repository is ``openmontage-capture``."""
        return [r for r in self.parse_images(self._out(self.list_images_argv())) if image_repo_and_tag(r)[0] == IMAGE_REPO]

    def list_capture_containers(self, all: bool = True) -> list[dict[str, str]]:  # noqa: A002
        """Every container named ``om-capture-*`` with its state and image."""
        rows = [c for c in self.parse_containers(self._out(self.list_containers_argv())) if c["name"].startswith(CONTAINER_PREFIX)]
        return rows if all else [c for c in rows if c["state"] == "running"]

    def remove_image(self, ref: str) -> bool:
        assert_capture_image(ref)
        return self._ok(self.remove_image_argv(ref), timeout=120)

    def prune_dangling_images(self) -> bool:
        argv = self.prune_dangling_argv()
        # Only dangling images may be pruned — never "all unused" and never a system prune.
        flat = " ".join(argv)
        if re.search(r"(^|\s)(--all|-a)(\s|$)", flat) or "system" in argv:
            raise ScopeError(f"refusing to run {flat!r}: prune must be dangling-only")
        return self._ok(argv, timeout=120)

    def stop_builder(self) -> bool:
        argv = self.stop_builder_argv()
        return self._ok(argv, timeout=60) if argv else False


class AppleContainer(ContainerRuntime):
    name = "apple_container"
    binary = "container"

    def is_ready(self) -> bool:
        return self.is_installed() and self._ok([self.binary, "system", "status"])

    def build_argv(self, tag, context_dir, dockerfile):
        return [self.binary, "build", "-t", tag, "--label", ROLE_LABEL, "-f", dockerfile, context_dir]

    def run_argv(self, spec):
        argv = [self.binary, "run", "--rm", "--name", spec.name, "--cpus", str(spec.cpus), "--memory", spec.memory]
        if spec.detach:
            argv.append("--detach")
        for m in spec.mounts:
            argv += ["--mount", f"type=bind,source={m.host},target={m.container}" + (",readonly" if m.read_only else "")]
        for k, v in spec.env.items():
            argv += ["-e", f"{k}={v}"]
        for p in spec.publish:
            argv += ["-p", p]
        for c in spec.cap_add:
            argv += ["--cap-add", c]
        argv.append(spec.image)
        argv += spec.command
        return argv

    def stop_argv(self, name):
        return [self.binary, "stop", name]

    def remove_argv(self, name):
        return [self.binary, "rm", "--force", name]

    def image_exists_argv(self, tag):
        return [self.binary, "image", "inspect", tag]

    def list_images_argv(self):
        return [self.binary, "image", "list", "--format", "json"]

    def list_containers_argv(self):
        return [self.binary, "list", "--all", "--format", "json"]

    def remove_image_argv(self, ref):
        return [self.binary, "image", "delete", ref]

    def prune_dangling_argv(self):
        return [self.binary, "image", "prune"]  # dangling only; `--all` would delete unrelated images

    def stop_builder_argv(self):
        return [self.binary, "builder", "stop"]

    def parse_images(self, text):
        refs = []
        for rec in _json_records(text):
            # Apple `container` 1.7.1: {"configuration": {"name": "docker.io/library/openmontage-capture:<tag>", ...}, "id": "<digest>", ...}
            ref = (rec.get("configuration") or {}).get("name") or rec.get("reference") or rec.get("name")
            if isinstance(ref, str):
                refs.append(ref)
        return refs

    def parse_containers(self, text):
        out = []
        for rec in _json_records(text):
            conf = rec.get("configuration") or {}
            name = rec.get("id") or conf.get("id") or rec.get("name")
            image = ((conf.get("image") or {}).get("reference")) or rec.get("image") or ""
            status = rec.get("status")  # 1.7.1: {"state": "running"|"stopped", "networks": [...], ...}
            state = str((status.get("state") if isinstance(status, dict) else status) or rec.get("state") or "").lower()
            if isinstance(name, str):
                out.append({"name": name, "state": state, "image": image if isinstance(image, str) else ""})
        return out


class _DockerCompatible(ContainerRuntime):
    binary = "docker"

    def build_argv(self, tag, context_dir, dockerfile):
        return [self.binary, "build", "-t", tag, "--label", ROLE_LABEL, "-f", dockerfile, context_dir]

    def run_argv(self, spec):
        argv = [self.binary, "run", "--rm", "--name", spec.name, "--cpus", str(spec.cpus), "--memory", spec.memory.lower()]
        if spec.detach:
            argv.append("--detach")
        for m in spec.mounts:
            argv += ["-v", f"{m.host}:{m.container}" + (":ro" if m.read_only else "")]
        for k, v in spec.env.items():
            argv += ["-e", f"{k}={v}"]
        for p in spec.publish:
            argv += ["-p", p]
        for c in spec.cap_add:
            argv += ["--cap-add", c.removeprefix("CAP_")]
        argv.append(spec.image)
        argv += spec.command
        return argv

    def stop_argv(self, name):
        return [self.binary, "stop", name]

    def remove_argv(self, name):
        return [self.binary, "rm", "-f", name]

    def image_exists_argv(self, tag):
        return [self.binary, "image", "inspect", tag]

    def list_images_argv(self):
        return [self.binary, "image", "ls", "--filter", f"reference={IMAGE_REPO}", "--format", "{{json .}}"]

    def list_containers_argv(self):
        return [self.binary, "ps", "-a", "--filter", f"name={CONTAINER_PREFIX}", "--format", "{{json .}}"]

    def remove_image_argv(self, ref):
        return [self.binary, "image", "rm", ref]

    def prune_dangling_argv(self):
        # dangling only, and only images carrying our role label (legacy unlabeled builds are removed by tag instead)
        return [self.binary, "image", "prune", "-f", "--filter", f"label={ROLE_LABEL}"]

    def parse_images(self, text):
        refs = []
        for rec in _json_records(text):
            repo, tag = rec.get("Repository"), rec.get("Tag")
            if isinstance(repo, str) and repo != "<none>":
                refs.append(f"{repo}:{tag}" if tag and tag != "<none>" else repo)
        return refs

    def parse_containers(self, text):
        return [{"name": str(rec.get("Names", "")).split(",")[0], "state": str(rec.get("State", "")).lower(), "image": str(rec.get("Image", ""))}
                for rec in _json_records(text) if rec.get("Names")]


class Colima(_DockerCompatible):
    """Colima (MIT) provides a Docker-compatible socket; commands go through the docker CLI."""

    name = "colima"

    def is_installed(self) -> bool:
        return self._which("colima") is not None and self._which("docker") is not None

    def is_ready(self) -> bool:
        return self.is_installed() and self._ok(["colima", "status"]) and self._ok(["docker", "info"])


class Docker(_DockerCompatible):
    name = "docker"

    def is_ready(self) -> bool:
        return self.is_installed() and self._ok(["docker", "info"])


RUNTIME_ORDER = (AppleContainer, Colima, Docker)


def detect_runtime(
    preferred: str | None = None,
    which: Callable[[str], Optional[str]] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> ContainerRuntime | None:
    """First ready runtime in order Apple container → Colima → Docker (or the ``preferred`` one)."""
    candidates = [cls(which=which, runner=runner) for cls in RUNTIME_ORDER]
    if preferred:
        candidates = [c for c in candidates if c.name == preferred]
    for c in candidates:
        if c.is_ready():
            return c
    return None


def _container_age_s(name: str, now: float | None = None) -> float | None:
    m = _NAME_TS.search(name)
    return (now or time.time()) - int(m.group(1)) if m else None


def cleanup_stale(rt: ContainerRuntime, keep_tag: str | None = None, active_name: str | None = None,
                  now: float | None = None, lock_holder: Callable[[], Optional[dict]] | None = None) -> dict[str, Any]:
    """Remove stale capture containers and every image except ``keep_tag`` (best effort, scoped, never raises).

    Order: containers → old ``openmontage-capture:*`` images (incl. legacy ``:1``) → dangling images → Apple builder VM.
    A *running* ``om-capture-*`` container is left alone when it may belong to a capture in progress: the heavy lock is held by
    another process (a blocking ``run``), it is ``active_name``, or it is younger than ``ACTIVE_WINDOW_S`` (a ``start`` →
    ``collect`` session, e.g. a login handoff). Images are only removed when ``keep_tag`` itself exists — the only working
    image is never deleted. Never touches anything outside the capture repository / ``om-capture-`` prefix / role label.
    """
    keep_tag = keep_tag or current_image_tag()
    report: dict[str, Any] = {"keep_tag": keep_tag, "containers_removed": [], "containers_skipped": [], "images_removed": [],
                              "images_skipped": [], "pruned_dangling": False, "builder_stopped": False, "errors": []}

    def step(label: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — cleanup must never fail the caller
            report["errors"].append(f"{label}: {type(exc).__name__}: {exc}")
            return None

    if lock_holder is None:
        def lock_holder() -> Optional[dict]:
            from lib.heavy_lock import current_holder

            return current_holder()
    holder = step("heavy lock", lock_holder)
    other_capture_running = bool(holder) and "sandbox_capture" in str(holder.get("label", ""))

    for c in step("list containers", rt.list_capture_containers) or []:
        name, state = c["name"], c.get("state", "")
        if name == active_name:
            report["containers_skipped"].append({"name": name, "why": "active"})
            continue
        if state == "running":
            age = _container_age_s(name, now)
            if other_capture_running or age is None or age < ACTIVE_WINDOW_S:
                report["containers_skipped"].append({"name": name, "why": "possibly in progress"})
                continue
        if step(f"teardown {name}", lambda n=name: rt.teardown(n) or True):
            report["containers_removed"].append(name)

    images = step("list images", rt.list_capture_images) or []
    if keep_tag and not any(image_repo_and_tag(r)[1] == image_repo_and_tag(keep_tag)[1] for r in images):
        report["images_skipped"] = list(images)  # the current image does not exist: keep whatever works
        report["errors"].append(f"current image {keep_tag} not present; old images kept")
    else:
        keep = image_repo_and_tag(keep_tag)[1]
        for ref in images:
            if image_repo_and_tag(ref)[1] == keep:
                continue
            if step(f"remove {ref}", lambda r=ref: rt.remove_image(r)):
                report["images_removed"].append(ref)
        report["pruned_dangling"] = bool(step("prune dangling", rt.prune_dangling_images))
    report["builder_stopped"] = bool(step("stop builder", rt.stop_builder))
    return report
