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

```bash
curl -s http://127.0.0.1:9222/json | python3 -c '
import json,sys
for t in json.load(sys.stdin):
    print(t["id"], t["url"], t["title"], sep=" | ")
'
```

```bash
python3 - <<'PY'
import json
from websocket import create_connection   # pip install websocket-client

tab = "<TAB_ID>"
ws = create_connection(f"ws://127.0.0.1:9222/devtools/page/{tab}", timeout=30)
ws.send(json.dumps({
    "id": 1, "method": "Runtime.evaluate",
    "params": {"expression": "document.body.innerText", "returnByValue": True},
}))
while True:
    msg = json.loads(ws.recv())
    if msg.get("id") == 1:
        print(msg["result"]["result"]["value"])
        break
ws.close()
PY
```

If `websocket-client` is unavailable, `websockets` or a raw `curl` against the HTTP
endpoint works for short responses; prefer saving the value to a file and decoding it in
Python, the same rule the WSL document follows.

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
