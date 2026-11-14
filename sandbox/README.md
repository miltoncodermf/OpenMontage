# Capture sandbox

Real screen recordings for `topic-tutorial`, taken **only** inside a disposable container — never on the owner's desktop.

- Runtime: Apple `container` (default, macOS 26+, Apple Silicon, one lightweight VM per container); Colima or Docker as fallbacks (`lib/sandbox/runtime.py`).
- Build once: `container build -t openmontage-capture:1 -f sandbox/Dockerfile sandbox` (or `sandbox_capture` operation `build_image`).
- Image: Ubuntu 24.04 arm64, Xvfb 1920×1080, openbox, Chromium (Playwright), code-server (pinned), ttyd, ffmpeg, python3, node. Non-root user `capture`. No secrets baked in.
- Per capture: workspace **copy** (secret filter + redaction; no `.git`, `.env*`, keys) mounted rw at `/workspace`, scratch dir at `/out`; nothing else (never `$HOME`, `~/.ssh`, keychain, the repo root).
- Limits: `--cpus 4 --memory 4G`, wall-clock timeout, container removed afterwards.
- Network: default deny. `allow_domains` go through an in-container allow-list proxy (`egress_proxy.py`, rejects non-public IPs); iptables owner-match lets only the proxy user leave the VM.
- Owner logins: `await_owner_login` pauses recording (credentials are never filmed) and exposes noVNC on `127.0.0.1:6080` only; the owner logs into a dedicated test account himself and confirms in chat.

## Residual risk (honest)

- The capture user is root-less but shares the VM with the proxy; a kernel/VM escape is out of scope.
- If the guest kernel lacks iptables, enforcement falls back to proxy-only (Chromium and package managers honour it; arbitrary binaries could bypass it). `network.iptables` in the capture result says which mode ran.
- Hosts on the allow-list are trusted: content fetched from them can influence what is recorded.
- Apple `container` networking gives the VM a route to the host network; the proxy refuses private/loopback/link-local resolutions, but a raw socket from the `egress` user is not otherwise filtered.
