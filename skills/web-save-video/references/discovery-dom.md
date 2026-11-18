# How Players Are Found in the DOM

The extractor collects video candidates *before* Defuddle runs, because the
Markdown it produces keeps only an empty `<video>` tag: `absolutizeLinks()`
rewrites anchors and `img`/`source` sources but deliberately leaves
`video[src]` and every `data-*` media attribute untouched.

## Sources, in the order they are read

1. `video[src]`
2. `video[data-m3u8]`, `data-hls`, `data-mp4`, `data-video-url`, `data-video`,
   `data-src`, `data-url`
3. `source[src]` (with its `type`)
4. `meta[property="og:video:secure_url" | "og:video:url" | "og:video"]`,
   `meta[name="twitter:player:stream"]`
5. `script[type="application/ld+json"]` → `VideoObject.contentUrl`

## Rules the collector applies

- **Every value is resolved against the page URL.** Protocol-relative
  `//flv0.example.com/a.m3u8` is common and an `https?://` regex misses those
  pages entirely.
- **Placeholders are rejected**: `""`, `undefined`, `null`, `none`, `false`.
  Article pages really do write `data-mp4="undefined"` while the real address
  sits in `data-m3u8`.
- **The attribute name is not the container.** `data-mp4` can hold an `.m3u8`
  URL; the extension decides the type.
- **Only `http:` / `https:` survive**, and URLs carrying credentials are dropped.
- **Duplicates collapse** on the resolved URL, so the same file offered through
  three attributes yields one candidate.
- **At most 20 candidates per page.**
- **Title preference**: `video[title]` → closest `figure[data-alt]` → page `<title>`.

## What a page with no candidates means

An empty result is a legitimate answer (the page genuinely has no player), and
`/save-video` reports it as "No video was found on this page". A page that
visibly has a player but yields nothing usually means the player is built from
`<div>` elements plus JavaScript, and the address only appears in a network
request. That is a site-specific adapter job, not something to guess at from
the Markdown.
