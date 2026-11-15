#!/usr/bin/env python3
"""In-container capture runner (runs as the unprivileged `capture` user).

Reads /out/script.json (a validated capture script), drives Chromium (headed, inside Xvfb)
over code-server / ttyd / arbitrary allowed pages, and records the display with ffmpeg
x11grab. Writes /out/capture.mp4, /out/steps.json, /out/screenshots/*.png and
/out/result.json. Owner-login steps pause the recording so credentials are never filmed.
"""
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import urllib.parse

from playwright.async_api import async_playwright

OUT = "/out"
SCRIPT = json.load(open(os.environ.get("CAPTURE_SCRIPT", f"{OUT}/script.json"), encoding="utf-8"))
RES = os.environ.get("RESOLUTION", "1920x1080")
FPS = int(os.environ.get("FPS", "30"))
MAX_S = float(os.environ.get("MAX_DURATION_S", "120"))
ALLOW = [d for d in os.environ.get("ALLOW_DOMAINS", "").split(",") if d]
PROXY = os.environ.get("HTTPS_PROXY") or ""
SURFACE = SCRIPT["surface"]
W, H = (int(x) for x in RES.split("x"))

CURSOR_JS = """
(() => {
  if (window.__omCursor) return; window.__omCursor = true;
  const add = () => {
    const d = document.createElement('div');
    d.style.cssText = 'position:fixed;z-index:2147483647;width:22px;height:22px;border-radius:50%;' +
      'background:rgba(255,80,80,.55);border:2px solid #fff;pointer-events:none;left:-50px;top:-50px;' +
      'transform:translate(-50%,-50%);box-shadow:0 0 6px rgba(0,0,0,.5)';
    (document.documentElement || document.body).appendChild(d);
    window.addEventListener('mousemove', e => { d.style.left = e.clientX + 'px'; d.style.top = e.clientY + 'px'; }, true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
})();
"""


class Recorder:
    """ffmpeg x11grab in segments (so owner-login stretches are never recorded)."""

    def __init__(self):
        self.segments = []
        self.proc = None
        self.t0 = None
        self.rec_time = 0.0  # seconds of video recorded so far (for step timestamps)
        self._seg_start = None

    def start(self):
        path = f"{OUT}/seg{len(self.segments):02d}.mp4"
        self.segments.append(path)
        self.proc = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab", "-video_size", RES, "-framerate", str(FPS),
             "-draw_mouse", "0", "-i", os.environ.get("DISPLAY", ":99"), "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "18", "-pix_fmt", "yuv420p", path],
            stdin=subprocess.PIPE,
        )
        self._seg_start = time.monotonic()
        time.sleep(0.4)

    def now(self):
        """Recorded-timeline position in seconds."""
        if self._seg_start is None:
            return self.rec_time
        return self.rec_time + (time.monotonic() - self._seg_start)

    def stop(self):
        if not self.proc:
            return
        self.rec_time += time.monotonic() - self._seg_start
        self._seg_start = None
        try:
            self.proc.stdin.write(b"q")
            self.proc.stdin.flush()
        except Exception:
            self.proc.send_signal(signal.SIGINT)
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc = None

    def finalize(self):
        self.stop()
        segs = [s for s in self.segments if os.path.exists(s) and os.path.getsize(s) > 0]
        final = f"{OUT}/capture.mp4"
        if not segs:
            return None
        if len(segs) == 1:
            os.replace(segs[0], final)
        else:
            lst = f"{OUT}/segments.txt"
            open(lst, "w").write("".join(f"file '{s}'\n" for s in segs))
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                            "-c", "copy", "-movflags", "+faststart", final], check=True)
            for s in segs:
                os.remove(s)
            os.remove(lst)
        return final


def start_surface():
    procs = []
    base_url = "about:blank"
    if SURFACE == "code_server":
        settings_dir = os.path.expanduser("~/.local/share/code-server/User")
        os.makedirs(settings_dir, exist_ok=True)
        json.dump({
            "workbench.startupEditor": "none", "workbench.tips.enabled": False,
            "workbench.welcomePage.walkthroughs.openOnInstall": False, "security.workspace.trust.enabled": False,
            "telemetry.telemetryLevel": "off", "update.mode": "none", "extensions.autoUpdate": False,
            "editor.minimap.enabled": False, "editor.fontSize": 20, "terminal.integrated.fontSize": 20,
            "terminal.integrated.gpuAcceleration": "off", "workbench.colorTheme": "Default Dark Modern",
            "window.commandCenter": False, "breadcrumbs.enabled": False, "editor.wordWrap": "on",
            "terminal.integrated.defaultProfile.linux": "bash", "workbench.layoutControl.enabled": False,
        }, open(f"{settings_dir}/settings.json", "w"))
        procs.append(subprocess.Popen(
            ["code-server", "--bind-addr", "127.0.0.1:8080", "--auth", "none", "--disable-telemetry",
             "--disable-update-check", "--disable-workspace-trust", "/workspace"],
            stdout=open(f"{OUT}/code-server.log", "w"), stderr=subprocess.STDOUT))
        base_url = "http://127.0.0.1:8080/?folder=/workspace"
    elif SURFACE == "terminal":
        procs.append(subprocess.Popen(
            ["ttyd", "-W", "-i", "127.0.0.1", "-p", "7681", "-t", "fontSize=26", "-t", "rendererType=dom",
             "-t", "theme={\"background\":\"#0b1020\"}", "bash"],
            stdout=open(f"{OUT}/ttyd.log", "w"), stderr=subprocess.STDOUT))
        base_url = "http://127.0.0.1:7681/"
    return procs, base_url


for _k in ("GOOGLE_API_KEY", "GOOGLE_DEFAULT_CLIENT_ID", "GOOGLE_DEFAULT_CLIENT_SECRET"):
    os.environ.setdefault(_k, "no")  # silences the "Google API keys are missing" infobar


def wait_port(port, timeout=60):
    import socket
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), 1).close()
            return True
        except OSError:
            time.sleep(0.3)
    return False


async def page_text(page):
    """Visible text for ``wait_for_text``: the page text, the xterm DOM rows, and — because ttyd's default canvas/webgl
    renderer draws no DOM text — the xterm buffer itself (``window.term``), which is what the terminal really shows."""
    return await page.evaluate(
        "() => { let buf = ''; try { const t = window.term; if (t && t.buffer && t.buffer.active) { const b = t.buffer.active; "
        "for (let i = 0; i < b.length; i++) { const l = b.getLine(i); if (l) buf += l.translateToString(true) + '\\n'; } } } catch (e) {} "
        "return (document.body ? document.body.innerText : '') + '\\n' + "
        "Array.from(document.querySelectorAll('.xterm-rows, .xterm-accessibility-tree')).map(e => e.textContent).join('\\n') + '\\n' + buf; }")


async def run():
    log = []
    result = {"status": "ok", "error": None, "surface": SURFACE, "capture_id": SCRIPT["capture_id"]}
    rec = Recorder()
    surf_procs, base_url = start_surface()
    port = {"code_server": 8080, "terminal": 7681}.get(SURFACE)
    if port and not wait_port(port):
        result.update(status="failed", error=f"{SURFACE} did not start")
        json.dump(result, open(f"{OUT}/result.json", "w"))
        return 2

    deadline = time.monotonic() + MAX_S
    terminal_open = False
    async with async_playwright() as pw:
        # App mode (no tab strip / URL bar) in a persistent profile gives clean tutorial frames.
        args = [f"--app={base_url}", f"--window-size={W},{H}", "--window-position=0,0", "--start-fullscreen",
                "--no-first-run", "--disable-infobars", "--noerrdialogs", "--disable-features=Translate",
                "--disable-background-networking", "--disable-component-update", "--disable-sync",
                "--no-default-browser-check", "--disable-breakpad", "--test-type"]
        if PROXY:
            args.append(f"--proxy-server={PROXY}")
        ctx = await pw.chromium.launch_persistent_context(
            "/tmp/chromium-profile", headless=False, no_viewport=True, args=args, ignore_https_errors=False,
            ignore_default_args=["--enable-automation"])
        browser = ctx
        await ctx.add_init_script(CURSOR_JS)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            if base_url != "about:blank" and not page.url.startswith("http"):
                await page.goto(base_url, wait_until="domcontentloaded", timeout=60000)
            if SURFACE == "code_server":
                await page.wait_for_selector(".monaco-workbench", timeout=90000)
            try:
                await page.evaluate(CURSOR_JS)
            except Exception:
                pass
            await asyncio.sleep(2.0)
            rec.start()
            for i, step in enumerate(SCRIPT["steps"]):
                if time.monotonic() > deadline:
                    raise TimeoutError(f"max_duration_s ({MAX_S}) exceeded before step {i}")
                action = step["action"]
                entry = {"index": i, "action": action, "start_s": round(rec.now(), 3)}
                if action == "pause":
                    await asyncio.sleep(step["seconds"])
                elif action == "navigate":
                    await page.goto(step["url"], wait_until="domcontentloaded", timeout=45000)
                    await asyncio.sleep(1.0)
                    entry["url"] = step["url"]
                elif action == "click":
                    loc = page.locator(step["selector"]).first
                    await loc.wait_for(state="visible", timeout=15000)
                    # bring the target to the middle of the screen first, so the cursor glide and the next frames show it
                    await loc.evaluate("e => e.scrollIntoView({block: 'center', behavior: 'instant'})")
                    await asyncio.sleep(0.4)
                    box = await loc.bounding_box()
                    if box:
                        await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=30)
                    await asyncio.sleep(0.3)
                    await loc.click(timeout=10000)
                    await asyncio.sleep(0.8)
                elif action == "open_file":
                    await page.keyboard.press("Control+p")
                    await asyncio.sleep(0.5)
                    await page.keyboard.type(step["path"], delay=45)
                    await asyncio.sleep(0.4)
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(1.5)
                    if step.get("line"):
                        await page.keyboard.press("Control+g")
                        await asyncio.sleep(0.4)
                        await page.keyboard.type(str(step["line"]), delay=45)
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(0.8)
                elif action == "type_in_terminal":
                    if SURFACE == "code_server" and not terminal_open:
                        await page.keyboard.press("Control+Backquote")
                        terminal_open = True
                        await asyncio.sleep(2.0)
                    elif SURFACE == "terminal":
                        await page.mouse.click(W // 2, H // 2)
                    delay_ms = max(5, int(60000 / (step.get("wpm", 220) * 5)))
                    await page.keyboard.type(step["text"], delay=delay_ms)
                    if step.get("enter", True):
                        await asyncio.sleep(0.3)
                        await page.keyboard.press("Enter")
                elif action == "wait_for_text":
                    end = time.monotonic() + step.get("timeout_s", 30)
                    needle = step["text"]
                    found = False
                    while time.monotonic() < end:
                        if needle in await page_text(page):
                            found = True
                            break
                        await asyncio.sleep(0.5)
                    if not found:
                        raise TimeoutError(f"text {needle!r} not seen within {step.get('timeout_s', 30)}s")
                    await asyncio.sleep(0.6)
                elif action == "screenshot":
                    await page.screenshot(path=f"{OUT}/screenshots/{step['label']}.png")
                    entry["label"] = step["label"]
                elif action == "await_owner_login":
                    rec.stop()  # never record credentials
                    open(f"{OUT}/awaiting_owner_login", "w").write(step.get("note", ""))
                    end = time.monotonic() + 600
                    while not os.path.exists(f"{OUT}/owner_login_done"):
                        if time.monotonic() > end:
                            raise TimeoutError("owner login not confirmed within 10 minutes")
                        await asyncio.sleep(1.0)
                    os.remove(f"{OUT}/awaiting_owner_login")
                    deadline += 0  # login time is not counted against the recording budget
                    rec.start()
                entry["end_s"] = round(rec.now(), 3)
                log.append(entry)
            await asyncio.sleep(0.8)
        except Exception as exc:  # noqa: BLE001 — recorded in result.json
            result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            try:
                await page.screenshot(path=f"{OUT}/screenshots/_failure.png")
            except Exception:
                pass
        finally:
            video = rec.finalize()
            await browser.close()
            for p in surf_procs:
                p.terminate()
    result.update(video="capture.mp4" if video else None, steps=len(log), duration_s=round(rec.rec_time, 2))
    json.dump(log, open(f"{OUT}/steps.json", "w"), indent=2)
    json.dump(result, open(f"{OUT}/result.json", "w"), indent=2)
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
