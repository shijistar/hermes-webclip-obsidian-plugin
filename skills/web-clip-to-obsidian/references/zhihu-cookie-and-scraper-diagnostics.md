# Zhihu cookie completeness vs. successful fetch

Use this note when a Zhihu article clip/retry task involves user-supplied cookies or an auxiliary scraper such as `zhihu-scraper`.

## Durable lessons

1. Judge cookie completeness from the **actual cookie text received in chat**, not from assumptions about the user's browser state.
2. `z_c0` missing from the received text is a valid reason for a first failure report, but that conclusion must be **retracted/updated immediately** if the user later supplies `z_c0`.
3. `zhihu-scraper check` reporting:
   - `Cookie fields z_c0, d_c0 are both configured`
   - `Zhihu login state is valid`
   does **not** prove article fetch will succeed.
4. Treat these as separate checkpoints:
   - cookie completeness
   - login/session validity
   - protocol fetch success
   - browser fallback success
5. On Zhihu, protocol fetch may still return `HTTP 403` even after `z_c0 + d_c0 (+ q_c1)` are present and login check passes.
6. Browser fallback may fail differently from protocol mode, e.g. page initial state missing the expected `articles:<id>` payload.
7. Therefore, when reporting status to the user, explicitly distinguish:
   - “login state valid”
   - “article body fetched successfully / failed”

## Recommended verification sequence

1. Parse the user-provided cookie text and enumerate cookie names.
2. If using `zhihu-scraper`, run `zhihu check` first.
3. Run protocol mode fetch (`--browser never`).
4. If needed, run browser fallback (`--browser always`).
5. Only claim success if one of the fetch paths returns article content.
6. If all live fetches fail but cached HTML/Markdown exists, use the cache as fallback and clearly label it as a fallback.

## Session-derived example outcomes

- Missing `z_c0` in the received text -> login invalid / fetch blocked.
- Later supplying `z_c0` -> login valid.
- Despite valid login:
  - direct HTTP request still `403`
  - `zhihu-scraper --browser never` still `403`
  - `zhihu-scraper --browser always` may still fail to locate `articles:<id>` in page state.

## Reporting rule

Never collapse these into one statement like “cookies are fine so the scraper should work.”
Instead say exactly which layer passed and which layer failed.

## Measured layer results on a cookie-less clip

A clip of `https://zhuanlan.zhihu.com/p/2025254072844922928` with no user-supplied cookies
produced four distinct outcomes. This is the expected shape of a Zhihu clip, not an incident:

| Layer | Command | Outcome |
| --- | --- | --- |
| 1 | `node extractor/src/cli.mjs <url> --no-browser` | `ok:false`, `code: "HTTP_STATUS"` (the server answered `403`) |
| 2 | `node extractor/src/cli.mjs <url>` (Playwright) | `ok:false`, `code: "HTTP_STATUS"` |
| 3 | Local logged-in browser | body was `{"error":{"message":"您当前请求存在异常，暂时限制本次访问…","code":40362}}` and `document.title` was a single placeholder character |
| 4 | `web_extract` | success — full rendered page (~52 KB), article body 44 KB after trimming |

Lessons that carry over to later runs:

- Rungs 1 and 2 fail at the request layer, so the Playwright render never gets a chance to
  run. Repeating them does not clear the refusal; move to the next rung instead.
- A `40362` JSON body plus a placeholder `document.title` is **IP/device throttling**, not
  an expired session. It does not justify asking the user to log in again, and it says
  nothing about cookie completeness — keep the checkpoints separate.
- Success at rung 4 does not validate rung 3: `web_extract` uses its own fetch path and can
  return the body while the local browser stays throttled.
- When rung 4 wins, save through `_persist_article()` with the page chrome trimmed: cut the
  tail at the `编辑于 <date> <time>・<region>` metadata line, keep the leading blockquote, and
  count Markdown images **after** trimming, then pass that count as `image_count`. A Zhihu
  body usually ends at zero images, which is when `image_mode=None` is correct; a non-zero
  count keeps the remote image URLs and is reported as such in the receipt.
