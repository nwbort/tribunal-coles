#!/bin/bash
set -e
URL='https://www.competitiontribunal.gov.au/current-matters/act-1-of-2026'
OUT='competitiontribunal.gov.au-current-matters-act-1-of-2026.html'

# Cloudflare protects this site with a "managed challenge", so a plain curl
# only ever captures the "Just a moment..." interstitial. Drive a real Chrome
# (headful, under Xvfb) via nodriver to solve the challenge and grab the real
# page. xvfb-run gives Chrome a display so it runs headful, which is far less
# likely to be flagged than headless.
xvfb-run -a python scrape.py "$URL" "$OUT"
