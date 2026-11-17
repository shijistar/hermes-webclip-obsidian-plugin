# Netease (163.com)

Two page shapes carry video, and they behave differently.

## Video page: `c.m.163.com/news/v/<ID>.html`

Measured on 2025-11-05 across ten samples:

| Check | Result |
| --- | --- |
| Media address | only HLS (`data-m3u8`), no mp4 anywhere in the page |
| Hotlink protection | none — a plain request without `Referer` returns 200 |
| Encryption | none: 0 `EXT-X-KEY` in 10/10 playlists |
| Bitrate variants | none — the page exposes a single quality |
| `/SD/` in the path | **not** a resolution: the same directory held both 1276×718 and 1920×1080 |

The player markup:

```html
<video id="player" data-m3u8="http://flv0.bn.netease.com/xxx.m3u8" src=""></video>
```

Two traps: the value is often **protocol-relative** (`//flv0…`), and
`data-mp4` may exist with the literal value `"undefined"` while `data-m3u8`
holds the real address.

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

A `news/v/` page has no article body, so the extractor's quality gate rejects it
before producing any video field. The adapter therefore fetches the page itself
(desktop UA, byte-capped) and scans the raw HTML. Only URLs ending in
`.m3u8`/`.mp4` count, which keeps recommendation-rail links from being mistaken
for the subject video.
