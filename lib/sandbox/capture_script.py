"""Capture-script validation (spec §5.7). Unknown actions fail; surfaces and domains are cross-checked."""

from __future__ import annotations

import ipaddress
import urllib.parse
from typing import Any

import jsonschema

from schemas.artifacts import validate_artifact

# Which actions each surface supports.
SURFACE_ACTIONS: dict[str, set[str]] = {
    "code_server": {"open_file", "type_in_terminal", "wait_for_text", "screenshot", "navigate", "click", "pause", "await_owner_login"},
    "terminal": {"type_in_terminal", "wait_for_text", "screenshot", "pause"},
    "browser": {"navigate", "click", "wait_for_text", "screenshot", "pause", "await_owner_login"},
}


class CaptureScriptError(ValueError):
    pass


def host_allowed(host: str, allow_domains: list[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in allow_domains)


def validate_capture_script(script: dict[str, Any]) -> list[str]:
    """Return a list of problems (empty = valid). Never raises for content problems."""
    try:
        validate_artifact("capture_script", script)
    except jsonschema.ValidationError as exc:
        # oneOf errors are noisy: surface the best matching sub-error when it names an action.
        return [f"schema: {exc.message}" if not exc.context else _best_error(exc)]
    problems: list[str] = []
    surface = script["surface"]
    allow = script.get("allow_domains", [])
    for d in allow:
        try:
            ipaddress.ip_address(d)
            problems.append(f"allow_domains must be hostnames, not IPs: {d}")
        except ValueError:
            pass
    for i, step in enumerate(script["steps"]):
        action = step["action"]
        if action not in SURFACE_ACTIONS[surface]:
            problems.append(f"steps[{i}]: action {action!r} is not supported on surface {surface!r}")
        if action == "navigate":
            host = urllib.parse.urlparse(step["url"]).hostname or ""
            if not host_allowed(host, allow):
                problems.append(f"steps[{i}]: navigate host {host!r} is not in allow_domains")
    return problems


def _best_error(exc: jsonschema.ValidationError) -> str:
    msgs = sorted({e.message for e in exc.context}, key=len)
    unknown = "unknown action or invalid step"
    return f"schema: {unknown} ({msgs[0] if msgs else exc.message})"


def assert_valid(script: dict[str, Any]) -> None:
    problems = validate_capture_script(script)
    if problems:
        raise CaptureScriptError("; ".join(problems))


def needs_owner_login(script: dict[str, Any]) -> bool:
    return any(s.get("action") == "await_owner_login" for s in script.get("steps", []))
