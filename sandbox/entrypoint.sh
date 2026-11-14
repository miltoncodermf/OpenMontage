#!/bin/bash
# Root-side setup for one capture. Network policy is applied BEFORE anything runs as `capture`.
set -u
OUT=/out
mkdir -p $OUT/network $OUT/screenshots
chmod -R a+rwX $OUT /workspace 2>/dev/null || true
ALLOW_DOMAINS="${ALLOW_DOMAINS:-}"
ENFORCE="$OUT/network/enforcement.json"

fw_ok=false
if iptables -P OUTPUT ACCEPT 2>/dev/null; then
  iptables -F OUTPUT
  iptables -A OUTPUT -o lo -j ACCEPT
  iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
  if [ -n "$ALLOW_DOMAINS" ]; then
    # Only the proxy (uid egress) may leave the VM; `capture` is limited to loopback.
    iptables -A OUTPUT -m owner --uid-owner egress -j ACCEPT
  fi
  iptables -A OUTPUT -j REJECT
  # IPv6: block everything except loopback.
  ip6tables -F OUTPUT 2>/dev/null && ip6tables -A OUTPUT -o lo -j ACCEPT && ip6tables -A OUTPUT -j REJECT 2>/dev/null
  fw_ok=true
fi
echo "{\"iptables\": $fw_ok, \"allow_domains\": \"$ALLOW_DOMAINS\"}" > "$ENFORCE"

if [ -n "$ALLOW_DOMAINS" ]; then
  su -s /bin/bash egress -c "ALLOW_DOMAINS='$ALLOW_DOMAINS' NETWORK_LOG=$OUT/network/network_log.jsonl /usr/bin/python3 /opt/sandbox/egress_proxy.py" &
  for _ in $(seq 1 50); do (echo > /dev/tcp/127.0.0.1/3128) 2>/dev/null && break; sleep 0.1; done
  export HTTP_PROXY=http://127.0.0.1:3128 HTTPS_PROXY=http://127.0.0.1:3128 http_proxy=http://127.0.0.1:3128 https_proxy=http://127.0.0.1:3128
  export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
fi

# Display + window manager (as capture).
RES="${RESOLUTION:-1920x1080}"
su -s /bin/bash capture -c "Xvfb :99 -screen 0 ${RES}x24 -nolisten tcp &" &
for _ in $(seq 1 50); do su -s /bin/bash capture -c "DISPLAY=:99 xdpyinfo >/dev/null 2>&1" && break; sleep 0.1; done
su -s /bin/bash capture -c "DISPLAY=:99 openbox >/dev/null 2>&1 &" &

if [ "${OWNER_LOGIN:-0}" = "1" ]; then
  # Owner-login mode: noVNC for the owner (published on host loopback only).
  su -s /bin/bash capture -c "x11vnc -display :99 -localhost -nopw -forever -quiet -bg" 
  websockify --web /usr/share/novnc 6080 localhost:5900 >/dev/null 2>&1 &
fi

exec su -s /bin/bash capture -c "cd /workspace && DISPLAY=:99 HTTP_PROXY=${HTTP_PROXY:-} HTTPS_PROXY=${HTTPS_PROXY:-} \
  NO_PROXY=${NO_PROXY:-} PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
  CAPTURE_SCRIPT=${CAPTURE_SCRIPT:-/out/script.json} RESOLUTION=$RES FPS=${FPS:-30} MAX_DURATION_S=${MAX_DURATION_S:-120} \
  ALLOW_DOMAINS='$ALLOW_DOMAINS' OWNER_LOGIN=${OWNER_LOGIN:-0} \
  /opt/runner-venv/bin/python /opt/sandbox/runner.py"
