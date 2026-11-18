# Platform Matrix

Which sites the command handles, how each one is recognised, and what is still
missing. The adapter registry tries site adapters in order and the generic
adapter last, because it matches every URL.

| Platform | Status | Detection | Discovery | Download |
| --- | --- | --- | --- | --- |
| Generic HTML5 | shipped | any URL | extractor DOM scan (`<video>`, `<source>`, `og:video`, JSON-LD) | HLS via ffmpeg, or direct GET |
| Netease (163.com) | shipped | hostname `163.com` / `*.163.com` | curl the page, read `data-m3u8` / `data-mp4` | HLS |
| Bilibili | shipped | `*.bilibili.com`, `b23.tv` (live and bangumi refused by name) | `x/web-interface/view` → `x/player/playurl?platform=html5&high_quality=1` | direct GET of the single `durl` mp4 |
| YouTube | shipped | `youtube.com`, `youtu.be`, `m.youtube.com`, `music.youtube.com` | yt-dlp (`kind="ytdlp"`) | yt-dlp, `protocol=https` adaptive streams only |
| WeChat Channels | unsupported | — | — | no public stream URL exists |

## Measured facts (2026-11-18, this machine)

Re-measure before trusting any of these after a site change.

| Fact | Measurement |
| --- | --- |
| Bilibili `view` API without cookies | `code=0`, returns `cid`, `pages[]`, title — 200 in 0.19 s |
| Bilibili `playurl` `fnval=4048` without wbi signature | `code=0`, 6 video + 3 audio DASH streams; anonymous ceiling 480P (`id=32`) |
| Bilibili DASH `baseUrl` | PCDN host `xy…mcdn.bilivideo.cn:8082` — **non-default port, refused by our netguard** |
| Bilibili `platform=html5&high_quality=1` | `quality=64` (720P), `format=mp4720`, **one muxed `durl` mp4**, host `upos-sz-*` with no port |
| Bilibili durl reliability | 7/7 sampled videos returned a durl; one 51.97 MB file for 3:32, 1280x720 h264+aac, duration exactly 213.00 s |
| Bilibili CDN without `Referer` | `403` — the Referer is mandatory, not cosmetic |
| Bilibili URL forms | `b23.tv/<BV>` → 302 to `www.bilibili.com/video/BV…`; `av` ids work but `aid ≠ cid` |
| Bilibili multi-part | `pages[]` carries one `cid` per part; `?p=2` selects `pages[1]` |
| YouTube extraction | works; yt-dlp logs `[jsc:deno] Solving JS challenges using deno` |
| YouTube `m3u8_native` formats | `HTTP 403` on every attempt (the default format order picks these) |
| YouTube `protocol=https` formats | download and merge fine; 1080p avc1 + m4a ≈ 80 MB for 3:33 |
| YouTube throughput | roughly 200 KB/s here, so a 10 minute clip takes minutes, not seconds |
| yt-dlp | `2026.10.26` at `/opt/homebrew/bin/yt-dlp`, installed with `deno` (131 MB) |

## Rules that follow from those facts

1. **Bilibili asks for the html5 shape, not DASH.** `fnval=4048` DASH cannot be
   used as-is: its preferred entry carries port 8082 and `netguard` refuses
   non-default ports by policy. `platform=html5&high_quality=1` returns one muxed
   file that needs no merge step at all.
2. A video with no `durl` is an **error**, not an empty result. Returning `[]`
   would be indistinguishable from "this page has no video".
3. Bilibili's signed URLs carry a `deadline`; discovery and download happen in one
   run. A cached URL from an earlier command fails.
4. Report the resolution actually downloaded. Anonymous Bilibili is 720P at best;
   HD needs cookies, which this plugin does not inject.
5. YouTube's format selector must pin `[protocol=https]`. Without it yt-dlp picks
   an `m3u8_native` variant and every download 403s.
6. Audio stays at yt-dlp's default (Opus in practice). Forcing `[ext=m4a]`
   stalled at 1.8 MB for ten minutes here, while the default stream completed.
   Chromium — and therefore Obsidian — plays Opus inside mp4; QuickTime does not.
7. yt-dlp subprocesses need `HTTPS_PROXY` / `ALL_PROXY` preserved; the extractor's
   environment allowlist drops them. See `ytdlp.md`.
