# Netease (163.com) Placeholder & Video-Link Quirks

## `news/v/` video short links → curl fallback with metadata extraction
- URL form: `https://c.m.163.com/news/v/<ID>.html` (often with `?spss/spsnuid/spsvid/spstoken` trackers)
- Node.js extractor (`cli.mjs --no-browser`, static) returns `QUALITY_GATE` because the page has no article body (only a video stub + recommendation list).
- **Python curl fallback** (`run_extractor_with_fallback` → `_fetch_netease_video_html` → `_parse_netease_video_html`) handles these URLs automatically:
  - Fetches the raw HTML via curl with a browser User-Agent
  - Extracts title from `<title>`
  - Extracts author from `<div class="s-name">` (video pages don't have the JSON `"nickname"` field used by article pages)
  - Extracts cover image URL from `.poster[data-bg]`
  - Parses publish date from the date segment in the cover URL (e.g. `20261008` → `2026-10-08`)
  - Extracts video stream URL (m3u8/mp4) from the HTML
  - Generates a markdown note with: metadata table, cover image, `<video>` embed, original link
- Contrast: `news/a/<ID>.html` article links are handled by the Node.js extractor directly (author/date/1500+ words).

## `empty.png` placeholder image — root cause & extractor fix
- **Where the placeholder comes from (root cause)**: Netease lazy-loads images. The raw DOM is
  `<img class="js-preview-img" src="https://static.ws.126.net/163/frontend/images/2022/empty.png" data-echo="http://dingyue.ws.126.net/2026/.../REAL.jpg">`.
  `src` is a 1×1 transparent pixel shown immediately; the real URL lives in `data-echo` (also `data-src`/`data-original` on other sites). Front-end JS swaps `data-echo`→`src` only when the image scrolls into view.
- **Bug (pre-fix extractor)**: `extractor/src/extractor.mjs` `absolutizeLinks()` only read `img[src]`, so clipped markdown always contained `empty.png` and the REAL figure URL was lost.
- **Fix (shipped in `fix/extractor-lazy-image`, commit `a327697`)**: added `extractLazyImageSrc()` that, for each `img`, prefers `data-echo`/`data-src`/`data-original`/`data-lazy-src`, resolves it to an absolute http(s) URL, and overwrites `src` before Defuddle runs. Now clipped `news/a/` articles emit the REAL `dingyue.ws.126.net/...` URL, not `empty.png`. Covered by `extractor/test/fixtures/netease-lazy-image.html` + unit test (23/23 pass).
- **Operational consequence**: After this fix, a netease `news/a/` clip that previously showed `empty.png` will now show a REAL remote image URL. That real URL is still a remote link unless `--save-images yes` localizes it.
- **When `empty.png` STILL appears**: only if the source page genuinely has no lazy-load real URL (rare). It remains a 1×1 pixel, NOT a real figure — multiple copies per article.
- **Localizing decision**: stores N identical transparent pixels under `Inbox/images/` and rewrites links. No informational value. When the user asks to "save images locally" but ALL detected remote images are `empty.png`, confirm before localizing; recommend keep-remote / abandon. If real `dingyue.ws.126.net` URLs are present, localizing them is meaningful.

## "打开网易新闻 查看更多图片" app tip — DOM-layer cleanup (extractor 0.4.0)
- **Symptom**: clipped netease `news/a/` articles carry a stray line
  `打开网易新闻 查看更多图片` between the figure image and the body text.
- **Source DOM**: each `<figure>` wraps the image and an app deep-link tip:
  `<figure><img …><div class="u-tip js-media-invoke"><div class="js-open-newsapp">打开网易新闻 查看更多图片 <i class="icon-arrow"></i></div></div></figure>`.
  The trailing `特别声明：本文为网易自媒体平台…` disclaimer lives in a separate
  `<div class="s-statement">` and is INTENTIONALLY KEPT (user requirement).
- **Fix (shipped, `fix/netease-image-prompt-cleanup`)**: `removeNeteaseImagePrompts()`
  in `extractor/src/extractor.mjs`, called from `extractHtml()` before Defuddle,
  guarded to `163.com` / `*.163.com` hostnames only.
- **CRITICAL pitfall — innermost-only removal**: a naive
  `querySelectorAll('p,span,div,a')` + `textContent.includes(prompt)` + `remove()`
  matches THREE nested nodes (`div.m-photo` outer container, `div.u-tip`,
  `div.js-open-newsapp`). Removing `m-photo` deletes the figure image too. Always
  keep only the innermost match: skip any candidate that `.contains()` another
  candidate. Also cap matched text length (≤60) so a long body paragraph that
  merely quotes the phrase is never removed.
- **Verification**: real URL `c.m.163.com/news/a/L5BC6R9V0553K5ZV.html` — after fix
  markdown has no `打开网易新闻`, keeps `特别声明` and the real
  `dingyue.ws.126.net/…` image. Node tests 25 pass (2 new), Python 94 pass.

## Note on tracking params
- `canonicalUrl` strips tracking params; `webclip_id` keys off it → no duplicate-note risk from `?spss=...`.
