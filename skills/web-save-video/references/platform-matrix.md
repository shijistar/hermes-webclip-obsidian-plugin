# Platform Matrix

Which sites the command handles, how each one is recognised, and what is still
missing. The adapter registry tries site adapters in order and the generic
adapter last, because it matches every URL.

| Platform | Status | Detection | Discovery | Download |
| --- | --- | --- | --- | --- |
| Generic HTML5 | shipped | any URL | extractor DOM scan (`<video>`, `<source>`, `og:video`, JSON-LD) | HLS via ffmpeg, or direct GET |
| Netease (163.com) | shipped | hostname `163.com` / `*.163.com` | curl the page, read `data-m3u8` / `data-mp4` | HLS |
| Bilibili | planned (P2) | `bilibili.com`, `b23.tv` | `x/web-interface/view` → `x/player/playurl?fnval=4048` | DASH video + audio, remuxed locally |
| YouTube | planned (P2) | `youtube.com`, `youtu.be` | yt-dlp | yt-dlp |
| WeChat Channels | unsupported | — | — | no public stream URL exists |

## Measured facts (2026-11-17, this machine)

These are the numbers the P2 adapters must be built against; re-measure before
trusting them after a site change.

| Fact | Measurement |
| --- | --- |
| Bilibili `view` API without cookies | `code=0`, returns `cid` |
| Bilibili `playurl` `fnval=4048` without wbi signature | `code=0`, 6 video streams, 3 audio streams |
| Bilibili anonymous ceiling | request `qn=80` → `quality=64`, but `dash.video` only carries 480P (`id=32`) and 360P (`id=16`) |
| Bilibili `baseUrl` (mcdn, port 8082) | one run timed out after 25 s; a later run answered in 0.278 s — PCDN nodes vary per session |
| Bilibili `backupUrl` (upos-sz-mirror) | `206`, 1 KB in 0.048 s — the reliable path |
| YouTube reachability | `https://www.youtube.com/` → 200 in 9.27 s through sing-box |
| yt-dlp | not installed; `brew info yt-dlp` → 2026.10.26 |

## Rules that follow from those facts

1. Bilibili plans must list `backupUrl` entries as fallbacks, and the downloader
   must try them in order with a short per-URL timeout. Do not hard-code
   "backup always wins": reachability changes per session.
2. Bilibili's signed stream URLs carry an expiry. Probe and download must happen
   in the same run; a cached URL from an earlier command will fail.
3. Anonymous Bilibili gives 480P at best. Report the resolution that was
   actually downloaded instead of promising "HD".
4. yt-dlp subprocesses need `HTTPS_PROXY` / `ALL_PROXY` preserved; the extractor's
   environment allowlist drops them, and YouTube is unreachable without them here.
