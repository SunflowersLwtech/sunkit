#!/bin/bash
# build.sh — render an A4 brief from its .src.html and PROVE it fits.
#   bash build.sh <brief.src.html> [out.pdf]
# Exit 1 = a page overflows (footer pushed off the 297mm page and clipped) or the
# page count is wrong. Exit 0 prints the PDF path + preview PNG paths to eyeball.
# Run with `bash`, never `./` (copy/sync tools often drop the executable bit).
set -u
SRC="${1:?usage: build.sh <brief.src.html> [out.pdf]}"
SRC="$(cd "$(dirname "$SRC")" && pwd)/$(basename "$SRC")"
OUT="${2:-${SRC%.src.html}.pdf}"

# Chrome discovery: CHROME_BIN wins, then the platform browser, then the newest
# Playwright "Chrome for Testing" in the ms-playwright cache (same engine, same flags).
CH="${CHROME_BIN:-}"
if [ -z "$CH" ]; then
  for c in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/usr/bin/google-chrome" "/usr/bin/google-chrome-stable" \
    "/usr/bin/chromium" "/usr/bin/chromium-browser" "/snap/bin/chromium" \
    "$HOME"/Library/Caches/ms-playwright/chromium-*/chrome-mac-arm64/"Google Chrome for Testing.app"/Contents/MacOS/"Google Chrome for Testing" \
    "$HOME"/Library/Caches/ms-playwright/chromium-*/chrome-mac/"Google Chrome for Testing.app"/Contents/MacOS/"Google Chrome for Testing" \
    "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux/chrome \
    "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux*/chrome
  do
    [ -x "$c" ] && CH="$c" && break
  done
fi
[ -x "$CH" ] || { echo "No Chrome/Chromium found (set CHROME_BIN, or: npx playwright install chromium)"; exit 2; }

# Never let a directly-launched Chromium touch the login keychain: without these two
# flags Chrome for Testing asks for "Chromium Safe Storage" on every launch and pops
# a keychain dialog on the user's screen. Playwright's launch() adds
# --use-mock-keychain itself; a bare binary call does not.
CHFLAGS=(--use-mock-keychain --password-store=basic)
TMP="$(mktemp -d)"

# Chrome caches file:// URLs, so re-rendering the SAME path after an edit can serve the
# PREVIOUS content: exit 0, a fresh file on disk, last build's words inside it. Every
# render below therefore goes through a URL that has never been fetched before. The
# scratch copies live beside the source, not in $TMP, so a relative <img>/<link> in a
# future brief still resolves; both are dot-prefixed, so `*.src.html` never matches them.
DIR="$(dirname "$SRC")"; BASE="$(basename "$SRC")"
PROBE_HTML="$DIR/.probe-$$-$BASE"
REND_HTML="$DIR/.render-$$-$BASE"
trap 'rm -f "$PROBE_HTML" "$REND_HTML"; rm -rf "$TMP"' EXIT

# 1. Overflow probe. Each .page is a fixed 297mm flex column with overflow:hidden,
#    so too much content silently pushes the .ft footer off the page — the PDF
#    still renders and pdfinfo still says N pages. Measure instead of looking.
sed 's#</body>#<script>window.addEventListener("load",()=>{const r=[...document.querySelectorAll(".page")].map((p,i)=>({page:i+1,over:p.scrollHeight-p.clientHeight}));document.title="OVERFLOW:"+JSON.stringify(r)});</script></body>#' \
  "$SRC" > "$PROBE_HTML"
PROBE=$("$CH" "${CHFLAGS[@]}" --headless=new --disable-gpu --window-size=1200,2000 --dump-dom "file://$PROBE_HTML" 2>/dev/null | grep -o 'OVERFLOW:[^<]*' | head -1)
[ -n "$PROBE" ] || { echo "probe produced no output — is the file valid HTML with <body>?"; exit 2; }
BAD=$(printf '%s' "${PROBE#OVERFLOW:}" | python3 -c 'import json,sys; r=json.load(sys.stdin); print(" ".join("page%d:+%dpx" % (p["page"], p["over"]) for p in r if p["over"] > 0))') \
  || { echo "probe parse failed: $PROBE"; exit 2; }
if [ -n "$BAD" ]; then
  echo "OVERFLOW — footer clipped on: $BAD"
  echo "Trim that page (shorter lede / fewer rows / drop a band) and rebuild. Nothing written."
  exit 1
fi

# 2. Render. Header/footer disabled; @page size comes from the source CSS.
#    Rendered from a never-fetched URL (see the cache note above), so what the probe
#    measured and what the PDF contains are the same bytes.
cp "$SRC" "$REND_HTML"
"$CH" "${CHFLAGS[@]}" --headless=new --disable-gpu --no-pdf-header-footer --print-to-pdf="$OUT" "file://$REND_HTML" 2>/dev/null
[ -s "$OUT" ] || { echo "print-to-pdf wrote nothing"; exit 2; }

# 3. Page count must equal the number of .page divs (a stray margin or a
#    missing page-break shows up here as an off-by-one).
WANT=$(grep -o 'class="page' "$SRC" | wc -l | tr -d ' ')
GOT=$(pdfinfo "$OUT" 2>/dev/null | awk '/^Pages:/{print $2}')
[ "$WANT" = "$GOT" ] || { echo "page count mismatch: source has $WANT .page divs, PDF has $GOT pages"; exit 1; }

# 4. Previews for a visual pass (layout, orphan headings, wrapped tokens).
PREV="${PREVIEW_DIR:-$TMP/preview}"; mkdir -p "$PREV"
pdftoppm -r 60 -png "$OUT" "$PREV/p" 2>/dev/null
echo "OK  $OUT  ($GOT pages, $(du -h "$OUT" | cut -f1 | tr -d ' '))"
echo "previews: $PREV/p-*.png  — look at every page before calling it done"
