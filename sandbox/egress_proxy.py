#!/usr/bin/env python3
"""Allow-list HTTP/CONNECT proxy for the capture sandbox.

Runs as the `egress` user; the `capture` user can only reach loopback (iptables owner-match),
so Chromium and package managers must go through this proxy. Only hostnames in
ALLOW_DOMAINS (and their subdomains) pass. Hosts resolving to private/loopback/link-local
addresses are refused (no reaching the VM gateway or the host LAN). Every decision is
appended to /out/network/network_log.jsonl.
"""
import asyncio
import ipaddress
import json
import os
import socket
import sys
import time
import urllib.parse

ALLOW = [d.strip().lower() for d in os.environ.get("ALLOW_DOMAINS", "").split(",") if d.strip()]
LOG = os.environ.get("NETWORK_LOG", "/out/network/network_log.jsonl")
PORT = int(os.environ.get("PROXY_PORT", "3128"))


def log(event: dict) -> None:
    event["ts"] = round(time.time(), 3)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except OSError:
        pass


def host_allowed(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in ALLOW)


def resolves_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return True


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def deny(writer, host, reason):
    log({"decision": "deny", "host": host, "reason": reason})
    writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
    await writer.drain()
    writer.close()


async def handle(reader, writer):
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=15)
    except Exception:
        writer.close()
        return
    lines = head.decode("latin1").split("\r\n")
    method, target, _ = (lines[0].split(" ") + ["", "", ""])[:3]
    if method == "CONNECT":
        host, _, port = target.partition(":")
        port = int(port or 443)
        if not host_allowed(host):
            return await deny(writer, host, "not in allow_domains")
        if not resolves_public(host):
            return await deny(writer, host, "resolves to non-public address")
        try:
            up_r, up_w = await asyncio.open_connection(host, port)
        except OSError as exc:
            return await deny(writer, host, f"connect failed: {exc}")
        log({"decision": "allow", "host": host, "port": port, "method": "CONNECT"})
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await asyncio.gather(pipe(reader, up_w), pipe(up_r, writer))
        return
    parsed = urllib.parse.urlparse(target)
    host = parsed.hostname or ""
    if not host or not host_allowed(host):
        return await deny(writer, host, "not in allow_domains")
    if not resolves_public(host):
        return await deny(writer, host, "resolves to non-public address")
    port = parsed.port or 80
    try:
        up_r, up_w = await asyncio.open_connection(host, port)
    except OSError as exc:
        return await deny(writer, host, f"connect failed: {exc}")
    log({"decision": "allow", "host": host, "port": port, "method": method})
    path = urllib.parse.urlunparse(("", "", parsed.path or "/", parsed.params, parsed.query, ""))
    request_line = f"{method} {path} HTTP/1.1\r\n"
    headers = [l for l in lines[1:] if l and not l.lower().startswith(("proxy-connection", "connection"))]
    up_w.write((request_line + "\r\n".join(headers) + "\r\nConnection: close\r\n\r\n").encode("latin1"))
    await up_w.drain()
    await asyncio.gather(pipe(reader, up_w), pipe(up_r, writer))


async def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    server = await asyncio.start_server(handle, "127.0.0.1", PORT)
    log({"decision": "start", "allow_domains": ALLOW})
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
