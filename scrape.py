#!/usr/bin/env python3
"""
Browser-based scraper that gets past Cloudflare's "managed challenge".

Plain curl only ever sees the "Just a moment..." interstitial because the
challenge requires a real browser to execute JavaScript (and sometimes click a
Turnstile checkbox). We drive a real Chrome via nodriver, wait for the
challenge to clear, and then save the resulting HTML.

We launch Chrome ourselves (with a remote-debugging port) and wait until the
DevTools endpoint is actually ready before attaching nodriver. nodriver's own
launcher only waits ~2.5s for the port, which loses a race against Chrome's
~3s cold start on CI runners, so we manage the process and the readiness wait.

Usage: scrape.py URL [OUTPUT_FILE]
If OUTPUT_FILE is omitted it is derived from the URL the same way download.sh
did (host without www, slashes -> hyphens, .html suffix).
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

import nodriver as uc

# Markers that indicate we're still looking at the Cloudflare challenge rather
# than the real page.
CHALLENGE_MARKERS = (
    "Just a moment",
    "challenge-platform",
    "cf_chl_opt",
    "Enable JavaScript and cookies to continue",
    "Verifying you are human",
)

MAX_WAIT_SECONDS = 90

# nodriver's default args, which help the browser look like a normal user
# session rather than an automated one.
CHROME_ARGS = [
    "--remote-allow-origins=*",
    "--no-first-run",
    "--no-service-autorun",
    "--no-default-browser-check",
    "--homepage=about:blank",
    "--no-pings",
    "--password-store=basic",
    "--disable-infobars",
    "--disable-breakpad",
    "--disable-dev-shm-usage",
    "--disable-session-crashed-bubble",
    "--disable-search-engine-choice-screen",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-gpu",
    "--window-size=1920,1080",
    "--no-sandbox",  # CI runs as root
]


def derive_filename(url: str) -> str:
    name = re.sub(r"^https?://", "", url)
    name = re.sub(r"^www\.", "", name)
    name = name.rstrip("/")
    name = name.replace("/", "-")
    if not name:
        name = "index"
    return f"{name}.html"


def looks_like_challenge(html: str) -> bool:
    return any(marker in html for marker in CHALLENGE_MARKERS)


def find_chrome() -> str:
    env = os.environ.get("CHROME_PATH")
    if env and os.path.exists(env):
        return env
    for candidate in (
        "google-chrome",
        "google-chrome-stable",
        "chromium-browser",
        "chromium",
    ):
        from shutil import which

        path = which(candidate)
        if path:
            return path
    raise FileNotFoundError("Could not find a Chrome/Chromium binary")


def free_port() -> int:
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def launch_chrome(chrome_path: str, port: int, user_data_dir: str):
    args = [
        chrome_path,
        *CHROME_ARGS,
        f"--user-data-dir={user_data_dir}",
        f"--remote-debugging-host=127.0.0.1",
        f"--remote-debugging-port={port}",
        "about:blank",
    ]
    print(f"Launching Chrome: {chrome_path} (port {port})", flush=True)
    return subprocess.Popen(
        args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def wait_for_devtools(port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/json/version"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                data = json.load(r)
                print(f"DevTools ready: {data.get('Browser')}", flush=True)
                return True
        except Exception:
            time.sleep(0.5)
    return False


async def try_click_turnstile(tab):
    """Best-effort click of the Cloudflare Turnstile / 'Verify you are human'
    checkbox. Managed challenges often auto-clear, but some render a checkbox
    that must be clicked."""
    for text in ("Verify you are human", "Verify you are a human", "human"):
        try:
            el = await tab.find(text, best_match=True, timeout=3)
            if el:
                await el.mouse_click()
                print(f"  clicked element matching '{text}'", flush=True)
                return True
        except Exception:
            pass
    try:
        iframe = await tab.find("challenges.cloudflare.com", best_match=True, timeout=3)
        if iframe:
            await iframe.mouse_click()
            print("  clicked cloudflare iframe", flush=True)
            return True
    except Exception:
        pass
    return False


async def scrape(url: str, output: str) -> int:
    chrome_path = find_chrome()
    port = free_port()
    user_data_dir = tempfile.mkdtemp(prefix="cf-scrape-")
    proc = launch_chrome(chrome_path, port, user_data_dir)

    if not wait_for_devtools(port):
        print("ERROR: Chrome DevTools endpoint never became ready", flush=True)
        proc.terminate()
        return 3

    browser = await uc.start(
        host="127.0.0.1", port=port, browser_executable_path=chrome_path
    )

    try:
        print(f"Navigating to {url}", flush=True)
        tab = await browser.get(url)

        deadline = time.time() + MAX_WAIT_SECONDS
        html = ""
        cleared = False
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            await tab.sleep(3)
            try:
                html = await tab.get_content()
            except Exception as e:
                print(f"  get_content failed: {e}", flush=True)
                continue

            title = ""
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
            if m:
                title = m.group(1).strip()
            print(
                f"  attempt {attempt}: {len(html)} bytes, title={title!r}",
                flush=True,
            )

            if not looks_like_challenge(html):
                cleared = True
                break

            await try_click_turnstile(tab)

        if not cleared:
            print(
                "WARNING: challenge did not clear within timeout; saving whatever "
                "we have for diagnosis.",
                flush=True,
            )

        try:
            html = await tab.get_content()
        except Exception:
            pass

        with open(output, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved {len(html)} bytes to {output} (cleared={cleared})", flush=True)

        return 0 if cleared else 2
    finally:
        try:
            browser.stop()
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: scrape.py URL [OUTPUT_FILE]", file=sys.stderr)
        return 1
    url = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else derive_filename(url)
    return uc.loop().run_until_complete(scrape(url, output))


if __name__ == "__main__":
    sys.exit(main())
