"""Container runtime adapter for the capture sandbox (spec §5.7, D14).

``ContainerRuntime`` hides the CLI differences between Apple ``container`` (default),
Colima and Docker so the image (``sandbox/Dockerfile``, OCI-portable) and the
``sandbox_capture`` tool never branch on the runtime. Command builders return argv
lists so they can be unit-tested without a runtime installed.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional

IMAGE_TAG = "openmontage-capture:1"


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
    def image_exists(self, tag: str = IMAGE_TAG) -> bool:
        return self._ok(self.image_exists_argv(tag))

    def teardown(self, name: str) -> None:
        """Best-effort stop + remove (the container must never outlive a capture)."""
        self._ok(self.stop_argv(name), timeout=30)
        self._ok(self.remove_argv(name), timeout=30)


class AppleContainer(ContainerRuntime):
    name = "apple_container"
    binary = "container"

    def is_ready(self) -> bool:
        return self.is_installed() and self._ok([self.binary, "system", "status"])

    def build_argv(self, tag, context_dir, dockerfile):
        return [self.binary, "build", "-t", tag, "-f", dockerfile, context_dir]

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


class _DockerCompatible(ContainerRuntime):
    binary = "docker"

    def build_argv(self, tag, context_dir, dockerfile):
        return [self.binary, "build", "-t", tag, "-f", dockerfile, context_dir]

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
