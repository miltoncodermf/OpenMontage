# OpenMontage capture sandbox — arm64 Linux, OCI-portable (Apple container / Colima / Docker).
# Disposable: one container per capture, deleted afterwards. No secrets are baked in.
# Licenses: code-server (MIT), Playwright (Apache-2.0), ttyd (MIT), Xvfb/openbox/ffmpeg/novnc (OSS).
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG CODE_SERVER_VERSION=4.96.4

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git sudo iptables iproute2 procps \
      xvfb openbox x11vnc novnc websockify xdotool x11-utils \
      ffmpeg ttyd \
      python3 python3-pip python3-venv nodejs npm \
      fonts-dejavu-core fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# code-server (VS Code in the browser), pinned.
RUN set -eux; arch="$(dpkg --print-architecture)"; \
    curl -fsSL -o /tmp/cs.deb "https://github.com/coder/code-server/releases/download/v${CODE_SERVER_VERSION}/code-server_${CODE_SERVER_VERSION}_${arch}.deb"; \
    dpkg -i /tmp/cs.deb; rm -f /tmp/cs.deb

# Playwright + Chromium for the capture runner.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN python3 -m venv /opt/runner-venv \
    && /opt/runner-venv/bin/pip install --no-cache-dir playwright==1.49.1 \
    && /opt/runner-venv/bin/playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# Non-root users: `capture` runs everything visible; `egress` owns the allow-list proxy.
RUN (userdel -r ubuntu 2>/dev/null || true) \
    && useradd -m -u 1000 -s /bin/bash capture \
    && useradd -m -u 1001 -s /usr/sbin/nologin egress \
    && mkdir -p /workspace /out && chown capture:capture /workspace /out

# Neutral prompt so on-screen terminals don't leak container ids.
RUN printf "PS1='\\[\\e[1;32m\\]dev\\[\\e[0m\\]:\\[\\e[1;34m\\]\\W\\[\\e[0m\\]\\$ '\\n" >> /home/capture/.bashrc

COPY egress_proxy.py runner.py entrypoint.sh /opt/sandbox/
RUN chmod +x /opt/sandbox/entrypoint.sh

ENV DISPLAY=:99
WORKDIR /workspace
ENTRYPOINT ["/opt/sandbox/entrypoint.sh"]
