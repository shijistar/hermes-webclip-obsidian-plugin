# Netease (163.com)

Two page shapes carry video, and they behave differently. The short-video pages
come under two URL prefixes, `/news/v/` and `/news/sv/`; both serve the same
player markup and both reach the adapter.

## Video page: `c.m.163.com/news/v/<ID>.html` (also `/news/sv/`)

Measured on 2025-11-05 across ten samples:

| Check | Result |
| --- | --- |
| Media address | only HLS (`data-m3u8`), no mp4 anywhere in the page |
| Hotlink protection | none — a plain request without `Referer` returns 200 |
| Encryption | none: 0 `EXT-X-KEY` in 10/10 playlists |
| Bitrate variants | none — the page exposes a single quality |
| `/SD/` in the path | **not** a resolution: the same directory held both 1276×718 and 1920×1080 |

## Measured again on 2026-11-18, end to end

Four pages downloaded through `/save-video` — the whole path, not a bare probe:
page fetch → adapter scan → HLS pre-flight → ffmpeg remux → receipt. Container
duration is compared with the sum of `#EXTINF`; the residue is the remux
boundary.

| Page | Prefix | File | Resolution | DAR | Duration (playlist) | Residue |
| --- | --- | --- | --- | --- | --- | --- |
| `VKAVGKVBP` | `/news/v/` | 3.4 MB | 1280×720 | 16:9 | 44.20s (43.96s) | 0.24s |
| `VX92E7HC1` | `/news/v/` | 6.0 MB | 1440×1080 | 4:3 | 40.24s (40.00s) | 0.24s |
| `VRB0KKUPI` | `/news/v/` | 33.8 MB | 1920×1080 | 16:9 | 251.79s (251.16s) | 0.63s |
| `VX90A5AE9` | `/news/sv/` | 31.8 MB | 720×1280 | 9:16 | 231.99s (231.36s) | 0.63s |

What this settles:

- **Aspect ratio is arbitrary.** 16:9, 4:3 and 9:16 all remux cleanly; do not
  assume landscape or a fixed DAR when reasoning about the output.
- **`/SD/` is still not a resolution.** All four sit under the same `/SD/`
  segment and span 720×1280 to 1920×1080.
- **The URL prefix does not matter.** `/news/sv/` behaves exactly like
  `/news/v/`: `NeteaseAdapter.matches()` only checks the hostname (`163.com` or
  any `*.163.com`) and the stream comes from a `data-(m3u8|mp4|hls|video-url)`
  attribute, so a new prefix needs no adapter change. Do not add a path check.

The player markup:

```html
<video id="player" data-m3u8="http://flv0.bn.netease.com/xxx.m3u8" src=""></video>
```

Two traps: the value is often **protocol-relative** (`//flv0…`), and
`data-mp4` is not a second stream. Measured on three pages on 2026-11-18, it held
the **same `.m3u8` address** as `data-m3u8` in 3/3 cases; an earlier session also
saw the literal string `"undefined"`. So the container must be derived from the
URL (`.m3u8` → `application/x-mpegURL`), never from the attribute name —
otherwise an HLS playlist gets written into a file named `.mp4`. Deduplication
then collapses the two attributes into one candidate.

## Article page: `www.163.com/news/a/<ID>.html` and `dy/article/`

Video appears inside a cover figure:

```html
<figure data-alt="视频标题">
  <video data-m3u8="//flv0.bn.netease.com/…m3u8" src=""></video>
</figure>
```

`figure[data-alt]` is the readable title; the page `<title>` is a fallback and
carries a site suffix (`_网易视频`, `_手机网易网`, …) that is stripped.

Embedded video is **rare**: in a sample of 11 articles only 1 had any. A command
that returns no video for an article is usually telling the truth.

## Sample lifetime

The Netease URLs recorded in the earlier session (`VPAMDR7UL`, `VT9QL19VJ`)
returned 302/404 by 2026-11-17, and none of the three Netease home pages still
linked a `news/v/` page. Two consequences:

1. **Never use a live Netease URL as a test fixture.** Unit tests carry a fixed
   HTML sample; a live URL is only for manual acceptance.
2. Before touching the adapter, re-sample 5–10 current pages and confirm the
   `data-m3u8` shape still holds. If it changed, update the adapter first.

## Why curl instead of the extractor

A `news/v/` (or `news/sv/`) page has no article body, so the extractor's quality
gate rejects it before producing any video field. The adapter therefore fetches
the page itself (desktop UA, byte-capped) and scans the raw HTML. Only URLs
ending in `.m3u8`/`.mp4` count, which keeps recommendation-rail links from being
mistaken for the subject video.
