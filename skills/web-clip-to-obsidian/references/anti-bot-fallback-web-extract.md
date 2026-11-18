# Anti-bot Fallback via web_extract

When the Node.js extractor fails due to anti-bot measures (Zhihu, Doubao, some paywalled sites), but `web_extract` succeeds in retrieving the article content, use this fallback workflow to save the article to the vault.

## When to Use

- `node extractor/src/cli.mjs <url> --no-browser` returns `ok: false` with `code: "QUALITY_GATE"` or `code: "HTTP_STATUS"`
- `web_extract` on the same URL returns clean Markdown/HTML content
- User wants the article saved despite extractor failure
- Common triggers: Zhihu, Doubao (doubao.com), some paywalled SPA sites

## Workflow

1. **Extract via web_extract**
```python
from hermes_tools import web_extract
result = web_extract([url])
page_text = result["results"][0]["content"]   # whole page, untrimmed → article["markdown"]
body = trim_to_article(page_text)             # article only → content_markdown
```
The split matters: `article["markdown"]` is what `source_content_hash` fingerprints, so it
must be the page as fetched. Trimming or flattening it before hashing hides every future
source-side edit behind an unchanged digest.

2. **Build article dict** (must pass `_validate_success_payload`):
```python
article = {
    "ok": True,
    "title": "...",          # required, non-empty
    "author": "...",          # required string (may be empty "")
    "published": "...",       # required string (may be empty ""; ISO 8601 when set)
    "description": "...",     # required string (may be empty "")
    "site": "...",            # required string (may be empty "")
    "canonicalUrl": url,        # required, valid URL
    "keywords": ["..."],       # list of strings, max 128
    "url": url,                 # required, valid URL
    "wordCount": 1000,          # int >= 0
    "method": "web_extract_fallback",  # required, non-empty
    "markdown": page_text        # required: the page as fetched, untrimmed
}
```

3. **Call _persist_article directly** — use `ClipConfig.from_file()` and `GitSync.preflight()`:
```python
from pathlib import Path
from datetime import datetime
from web_to_obsidian import ClipService, ClipConfig, ClipError, GitSync

plugin_root = Path('.')
config = ClipConfig.from_file(plugin_root / 'config.toml')
try:
    git_sync = GitSync.preflight(config.vault, config.sync_branch)
except ClipError as exc:
    raise SystemExit(f"Git preflight refused the clip: {exc}") from None

service = ClipService(plugin_root)
result = service._persist_article(
    config=config,
    article=article,
    captured_at=datetime.now(),
    refresh=False,
    git_sync=git_sync,
    content_markdown=body,      # trimmed/rendered body; article["markdown"] holds the raw page
    image_mode=None,  # HTML <img> tags don't trigger Markdown image flow
    generated_paths=[],
)
print(result.user_message())
```

**⚠️ API notes**:
- `ClipConfig.from_file()` reads from `config.toml` — the single source of truth for all config (vault, destination, images, sync_branch, lock_file, pending_root). No hardcoded paths.
- `ClipConfig.from_env()` reads from env vars with hardcoded defaults — prefer `from_file()` for portability.
- Build `GitSync` with the `GitSync.preflight(vault, branch)` classmethod, not the constructor. Preflight resolves `repo_root` via `git rev-parse`, verifies the vault is on the expected sync branch, refuses an in-progress Git operation and rebases onto upstream. The constructor performs none of those checks, so a direct-API clip through it can commit onto the wrong branch or during a rebase.
- `generated_paths` is optional, defaults to `()`

## Key Points

- `image_mode=None` is correct when the extracted content has no Markdown `![](...)` images (only HTML `<img>`)
- HTML `<img>` tags are NOT processed by the remote-image confirmation flow
- This bypasses the `PendingClipResult` / `resume_pending()` flow entirely
- `markdown` is **required and must carry the fetched page text, untrimmed**. `render_note()`
  derives `source_content_hash` from it; an empty value makes that fingerprint the constant
  `sha256("\n")`, and no refresh, dedupe or "page changed" decision can then tell a rewritten
  page from a re-render. `render_note()` refuses a payload that supplies a rendered body with an
  empty `markdown`, so a note can no longer be saved with a fingerprint that describes nothing.
  Keep the trimmed or flattened body in `content_markdown`.
- Requires: `ok: true`, `method: non-empty`, valid `canonicalUrl` and `url`, non-empty `title`

## Example: Doubao Article

```python
article = {
    "ok": True,
    "title": "古德哈特定律介绍 (Goodhart's Law, introduction)",
    "author": "",
    "published": "2026-05-26",
    "description": "When a metric becomes a target, it stops being a useful measure",
    "site": "doubao.com",
    "canonicalUrl": "https://www.doubao.com/thread/aa1278a169ca5",
    "keywords": [],
    "url": "https://www.doubao.com/thread/aa1278a169ca5",
    "wordCount": 200,
    "method": "web_extract_fallback",
    "markdown": page_text
}
```

## When no fallback can work: SPA pages

Some sites render the article entirely in JavaScript (kimi.com and other modern
SPAs). The HTML response carries only bundles, so the Node.js extractor,
`web_extract` and a plain curl all return empty or boilerplate content.

- There is no automated path without a real browser session.
- Do **not** save the empty shell as a note: an empty body with valid frontmatter
  looks like a successful clip and silently loses the article.
- Report the URL as requiring manual browser access, and say which methods were
  tried.

## Related References

- `zhihu-cookie-and-scraper-diagnostics.md` — layered diagnostics for Zhihu cookie/fetch/browser
- `netease-embedded-state-author.md` — another anti-bot quirk (netease embedded JSON)

## Version History

- 2026-11-17: The direct-API recipe builds `GitSync` with `GitSync.preflight(vault, branch)` instead of the constructor. The constructor skips the sync-branch check, the in-progress-operation guard and the upstream rebase, so a fallback clip could commit onto the wrong branch or into a rebase.
- 2026-11-17: `article["markdown"]` must now carry the fetched page text, untrimmed; the trimmed
  body goes only in `content_markdown`. This makes `source_content_hash` describe the source
  again — with `markdown: ""` it was the constant `sha256("\n")`, so nothing could distinguish a
  rewritten page from a re-render. `render_note()` now refuses a rendered body with an empty
  `markdown`. Notes saved before this change keep the gate until their next `--refresh`.
- 2026-10-25: Corrected the example to pass the extracted body (`content`) into `content_markdown`; it previously passed the empty `article["markdown"]` and produced frontmatter-only notes. Clarified that `markdown` is required but may be empty.
- 2026-09-04: Restored `ClipConfig.from_file()` + `GitSync()` constructor per code review — removes hardcoded vault path, uses config.toml as single source of truth. Rewrote API notes.
- 2026-09-03-v2: Changed to `ClipConfig.from_env()` + `GitSync.preflight()`. Added doubao.com example. (Reverted — see v3.)
- 2026-09-03-v1: Created from session where Zhihu article was clipped via web_extract fallback.
