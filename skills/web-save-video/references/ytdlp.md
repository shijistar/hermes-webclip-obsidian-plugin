# The yt-dlp backend

Only YouTube uses it. `VideoCandidate.kind == "ytdlp"` is the single switch; a
generic or Netease candidate can never fall back to it, because a page-controlled
URL must not reach a tool that speaks to 1800 sites by itself.

## Why a subprocess

YouTube media URLs are signed by player JavaScript. Reproducing that means running
a JS runtime, which is exactly what yt-dlp already does. The plugin therefore keeps
its own SSRF-guarded downloader for everything else and delegates only this site.

## Non-negotiable flags

| Flag | What breaks without it |
| --- | --- |
| `--ignore-config` | yt-dlp reads `~/.config/yt-dlp/config`, which may contain `--exec` — a config file would be running commands inside the plugin |
| `--no-playlist` | a `watch?v=…&list=…` URL would download the whole playlist. On its own it does **not** stop a bare `/playlist`, `/@handle` or `/channel/` URL (measured: 249 entries), which is why the adapter also rejects those shapes |
| `--playlist-items 1` | second line of defence behind the adapter's URL-shape check |
| `-f "…[protocol=https]…"` | default order selects `m3u8_native`, which answers `HTTP 403` here |
| `ba[ext=m4a]` preference | **not used**: that variant stalled at 1.8 MB for ten minutes here, while the default audio completed. Opus inside mp4 plays in Chromium/Obsidian, not in QuickTime |
| `--socket-timeout 20` + `--retries 2` | a throttled track would otherwise hang until the 1800 s budget expires |
| `--max-filesize` + post-hoc size check | `max_size_mb` must hold even when the size was an estimate |
| `--no-progress` | progress output floods the bounded subprocess buffers |
| `--ffmpeg-location <found ffmpeg>` | the gateway PATH is not the shell PATH; the merge step would fail |
| 1800 s timeout | `download_timeout_s` is a per-request ceiling and kills long videos |

## Locating the binary

Order: `[video].ytdlp` → `PATH` → `/opt/homebrew/bin/yt-dlp` → `/usr/local/bin/yt-dlp`.
A missing binary is reported as "not enabled" with the install command; it is never
a traceback and never a silent zero.

## Failure messages

| Upstream symptom | Message |
| --- | --- |
| `HTTP Error 403` | "YouTube refused the download (HTTP 403); retry later." |
| sign-in / age gate | "YouTube requires a signed-in account for this video." |
| `Requested format is not available` | "YouTube offered no downloadable format for this video." |
| anything else | "yt-dlp could not download this video." — stderr is **not** echoed, it can contain signed URLs |

## Measured behaviour (2026-11-18)

- `-f "bv*[height<=360]+ba"` → selected 396+140 (`m3u8_native`) → `403 Forbidden`.
- `-f "160+140"` → merged `5.3 MB`, both `protocol=https`.
- `-f 18` (progressive 360p) → `11.28 MiB` in 7 s; keep it as the `b` fallback.
- The `ios` player client did not help: `Requested format is not available`.
- Throughput varies a lot between runs here: the same 1080p 3:33 clip took 69 s
  once and 267 s another time (~0.3–1.2 MB/s). Budget for minutes, and do not
  read a slow run as a hang — the socket timeout is what distinguishes the two.
