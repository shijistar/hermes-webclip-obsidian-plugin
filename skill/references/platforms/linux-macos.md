# Local Chrome + CDP on Linux and macOS

Use this when a page needs a logged-in browser and the session lives in the local Chrome.
For the WSL equivalent — borrowing a Windows Chrome session — see `wsl.md`.

## Try the extractor first

`web_to_obsidian.py` runs the bundled extractor, which launches Playwright Chromium by
default. `--no-browser` disables it. Only a login wall justifies the manual path below.

## Launch a throwaway Chrome profile

```bash
# macOS
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# Linux
# CHROME="$(command -v google-chrome || command -v chromium)"

PROFILE="${TMPDIR:-/tmp}/webclip-chrome-debug"
"$CHROME" \
  --remote-debugging-port=9222 \
  --user-data-dir="$PROFILE" \
  --no-first-run --no-default-browser-check \
  "<TARGET_URL>" &
echo $! > /tmp/webclip_chrome.pid
```

Using a separate `--user-data-dir` avoids the singleton lock that makes a second launch
attach to the already-running instance instead of opening a debug port.

## List tabs, then evaluate in the target tab

Discover the target over plain HTTP — from Python, not `curl | python` (the plugin's
install scan flags a shell pipeline into an interpreter as a supply-chain risk):

```bash
python3 - <<'PY'
import json, urllib.request

tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json"))
for tab in tabs:
    print(tab["id"], tab["url"], tab["title"], sep=" | ")
PY
```

Evaluate inside the target tab with Playwright, which the plugin already installs in
`extractor/node_modules`. `connectOverCDP` attaches to the browser launched above, so no
extra package is needed — run this from the plugin root:

```bash
node --input-type=module -e "
import { chromium } from 'playwright';
const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
const page = browser.contexts().flatMap(c => c.pages()).find(p => p.url().includes('<URL_FRAGMENT>'));
if (!page) { console.error('no tab matching <URL_FRAGMENT>'); process.exit(1); }
console.log(await page.evaluate(() => document.body.innerText));
process.exit(0);
"
```

`process.exit(0)` detaches without touching the browser. Do **not** call `browser.close()`:
with `connectOverCDP` that shuts down the Chrome instance you are borrowing — including the
login session you need.

`Runtime.evaluate` exists only on the DevTools WebSocket; the HTTP endpoints (`/json`,
`/json/version`) list targets and cannot run JavaScript. If you need the full DOM instead of
the text, use `await page.content()` and hand the HTML to the extractor.

## Shut down only your instance

```bash
pid=$(cat /tmp/webclip_chrome.pid)
kill "$pid" 2>/dev/null || true
rm -rf "${TMPDIR:-/tmp}/webclip-chrome-debug"
```

Never `pkill -f chrome` — that closes the user's own browser.

## Pitfalls

- **Port already bound**: Chrome exits silently. Check `lsof -i tcp:9222` first.
- **Same profile, no debug port**: launching with the default profile just focuses the
  running instance. Always pass a dedicated `--user-data-dir`.
- **Login walls**: if `document.body.innerText` returns a sign-in screen, the session is
  not in this profile — log in once in the debug profile, then retry.
- **Large payloads**: chunk the WebSocket read; a single `recv()` may truncate.
