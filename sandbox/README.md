# Capture sandbox

Real screen recordings for `topic-tutorial`, taken **only** inside a disposable container — never on the owner's desktop.

- Runtime: Apple `container` (default, macOS 26+, Apple Silicon, one lightweight VM per container); Colima or Docker as fallbacks (`lib/sandbox/runtime.py`).
- Build: `sandbox_capture` operation `build_image` (or `container build -t openmontage-capture:<hash> --label org.openmontage.role=capture -f sandbox/Dockerfile sandbox`). The tag is `openmontage-capture:<h>` where `<h>` is the first 12 hex chars of a sha256 over every file under `sandbox/` (sorted path + bytes — editing *any* file here, this README included, makes a new image). If the current tag already exists nothing is built.
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

## Automatic cleanup (images and containers)

Old versions are never used again, so they are removed automatically (`lib/sandbox/runtime.py: cleanup_stale`):

- **After every successful `build_image`** (also when the current image already exists), and at the start of every `run` / `start` (once the current image is known to exist), and on demand with the **`cleanup`** operation (`sandbox_capture {"operation": "cleanup"}`). The result is in `data["cleanup"]` (`containers_removed`, `containers_skipped`, `images_removed`, `pruned_dangling`, `builder_stopped`, `errors`).
- **Order:** stale `om-capture-*` containers → every `openmontage-capture:*` image except the current tag (this includes the legacy `:1`) → dangling images (`container image prune` / `docker image prune -f --filter label=org.openmontage.role=capture`; **never** `--all`, never a system prune) → stop the Apple builder VM (`container builder stop`).
- **Never after a failed build** (the old image is still the only one that works), and image removal is skipped when the current image does not exist.
- **In-progress captures are protected:** a *running* container is left alone if it is the active one, if another `sandbox_capture` holds the heavy-job lock, or if it is younger than 29 minutes (a `start` → `collect` session, e.g. waiting for an owner login). Stopped containers and older orphans (crashed/SIGKILLed runs) are removed.
- **Scope guard (asserted in code, `ScopeError`):** only images whose repository is `openmontage-capture`, containers named `om-capture-*`, and (Docker) the label `org.openmontage.role=capture` can be touched. `ubuntu`, the Apple `buildkit` container and anything else are never removed.
- **Best effort:** every step logs its error in `cleanup.errors` and continues; a cleanup failure never fails a build or capture.
