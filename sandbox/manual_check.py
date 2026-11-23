#!/usr/bin/env python3
"""Manual P3 acceptance checks for the capture sandbox (needs a ready container runtime + built image).

Usage: .venv/bin/python sandbox/manual_check.py <scratch_project_dir>
Runs: (1) code-server capture of `python -c "print('hello')"`, (2) browser capture of an allowed
public page, (3) network enforcement probe (allowed host reachable, other host blocked via proxy,
proxy bypass blocked by iptables). Prints one JSON summary. Not part of the fast suite.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.capture.sandbox_capture import SandboxCapture  # noqa: E402

proj = Path(sys.argv[1]).resolve()
only = set(sys.argv[2:])
proj.mkdir(parents=True, exist_ok=True)
ws = proj / "src_repo"
ws.mkdir(exist_ok=True)
(ws / "hello.py").write_text("print('hello from the sandbox')\n")
tool = SandboxCapture()
summary = {}

def run(script, **kw):
    res = tool.execute({"project_dir": str(proj), "workspace": str(ws), "script": script, "max_duration_s": 60, **kw})
    return {"success": res.success, "error": res.error,
            "asset": {k: (res.data.get("asset") or {}).get(k) for k in ("path", "duration_seconds", "width", "height", "fps", "codec")},
            "network": res.data.get("network"), "result": res.data.get("result")}

summary["code_server_hello"] = (not only or "code_server_hello" in only) and run({
    "capture_id": "m1_hello", "surface": "code_server", "allow_domains": [],
    "steps": [{"action": "open_file", "path": "hello.py"},
              {"action": "type_in_terminal", "text": "python3 -c \"print('hello')\"", "wpm": 200},
              {"action": "wait_for_text", "text": "hello", "timeout_s": 30},
              {"action": "screenshot", "label": "hello_out"}, {"action": "pause", "seconds": 2}]})
summary["browser_allowed_page"] = (not only or "browser_allowed_page" in only) and run({
    "capture_id": "m2_browser", "surface": "browser", "allow_domains": ["example.com"],
    "steps": [{"action": "navigate", "url": "https://example.com/"},
              {"action": "wait_for_text", "text": "documentation examples", "timeout_s": 30},
              {"action": "screenshot", "label": "example"}, {"action": "pause", "seconds": 3}]})
summary["network_probe"] = (not only or "network_probe" in only) and run({
    "capture_id": "m3_probe", "surface": "code_server", "allow_domains": ["example.com"],
    "steps": [{"action": "type_in_terminal", "text": "curl -sS -m 8 -o /dev/null -w 'ALLOWED:%{http_code}\\n' https://example.com/ ; "
                                                     "curl -sS -m 8 -o /dev/null https://example.org/ 2>&1 | sed 's/^/BLOCKED_PROXY:/' ; "
                                                     "curl -sS -m 8 --noproxy '*' -o /dev/null https://example.org/ 2>&1 | sed 's/^/BYPASS:/' ; echo PROBE_DONE", "wpm": 400},
              {"action": "wait_for_text", "text": "PROBE_DONE", "timeout_s": 60},
              {"action": "screenshot", "label": "probe"}, {"action": "pause", "seconds": 2}]})
print(json.dumps(summary, indent=2, default=str))
