#!/usr/bin/env python3
"""
Browser-based scraper that gets past Cloudflare's "managed challenge".

Plain curl only ever sees the "Just a moment..." interstitial because the
challenge requires a real browser to execute JavaScript (and sometimes click a
Turnstile checkbox). We drive a real Chrome via nodriver, wait for the
challenge to clear, and then save the resulting HTML.

Usage: scrape.py URL [OUTPUT_FILE]
If OUTPUT_FILE is omitted it is derived from the URL the same way download.sh
did (host without www, slashes -> hyphens, .html suffix).
"""

import asyncio
import re
import sys
import time

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
    # Try clicking the turnstile iframe area directly.
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
    print(f"Launching browser for {url}", flush=True)
    browser = await uc.start(
        headless=False,
        browser_args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--window-size=1920,1080",
        ],
    )

    try:
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

            # Still challenged - give the JS a chance, then try clicking.
            await try_click_turnstile(tab)

        if not cleared:
            print(
                "WARNING: challenge did not clear within timeout; saving whatever "
                "we have for diagnosis.",
                flush=True,
            )

        # One final content grab.
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


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: scrape.py URL [OUTPUT_FILE]", file=sys.stderr)
        return 1
    url = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else derive_filename(url)
    return uc.loop().run_until_complete(scrape(url, output))


if __name__ == "__main__":
    sys.exit(main())
