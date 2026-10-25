---
name: web-clip-to-obsidian
description: Clip web articles to the Obsidian vault via the webclip-obsidian plugin — extract, confirm images, save as dated markdown, commit & push to Git. Use when the user shares one or more URLs wanting to save/read-later in Obsidian, or says "web clip"/"clip to obsidian"/"save to vault"/"clip<url>"/"抓取到obsidian"/"剪藏"/"剪藏<url>"/"抓取<url>" (Chinese/English trigger phrases are matched). The slash command accepts exactly one URL per invocation; to clip several URLs, invoke it once per URL, or call `ClipService.run_batch()` so all notes land in a single commit. Each URL keeps its own flags.
version: 1.5.3
author: Hermes Agent / Fengbao Li
metadata:
  hermes:
    tags: [obsidian, web-clip, productivity, content-management, reading]
---

# Web Clip to Obsidian

Clip web articles to the user's Obsidian vault using the `webclip-obsidian` plugin
(source repo: `hermes-webclip-obsidian-plugin`).

## When to Use

- User shares a URL with intent to save it to Obsidian
- Keywords: "clip to obsidian", "save to vault", "web clip", "抓取到obsidian", "抓取<url>", "剪藏" (Chinese phrases are user-input triggers, not documentation prose)
- User pastes a link from Juejin, WeChat, Zhihu, or any web source wanting to archive it

## Plugin Location & Config

The **source repo** is the single source of truth. The installed plugin is a
repo-root clone installed by `hermes plugins install` (or a symlink when
developing):

```
Source repo:     ~/.hermes/workspace/repository/hermes-webclip-obsidian-plugin/
Plugin symlink:  ~/.hermes/profiles/<profile>/plugins/webclip-obsidian/ → source repo (root)
Skill symlink:   ~/.hermes/profiles/<profile>/skills/productivity/web-clip-to-obsidian/ → source repo/skill/
Config:          <source repo>/config.toml
```

The symlink directory name matches the plugin's registration key
(`webclip-obsidian`, from `plugin.yaml`'s `name`). Hermes keys plugins by that
manifest name, and the install directory is expected to carry the same name, so
`plugins.enabled` in `config.yaml` must list `webclip-obsidian`. A different name
there silently leaves the plugin disabled — confirm with
`hermes plugins info webclip-obsidian` (`Status: enabled`).

Deploy via symlink (not copies):

```bash
ln -s ~/.hermes/workspace/repository/hermes-webclip-obsidian-plugin \
      ~/.hermes/profiles/<profile>/plugins/webclip-obsidian
ln -s ~/.hermes/workspace/repository/hermes-webclip-obsidian-plugin/skill \
      ~/.hermes/profiles/<profile>/skills/productivity/web-clip-to-obsidian
```

`config.toml` lives at the plugin package root (`config.toml` in the repo) and is
tracked in git with sensible defaults. Because the installed path is a symlink to
the repo, editing `<profile>/plugins/webclip-obsidian/config.toml` edits the
tracked file — there is no per-profile copy. Machine-specific values therefore
appear in the source repo's `git status`; commit them deliberately or keep them
out of Git.

Default config:

```toml
[clip]
vault = "~/obsidian/shijistar"
destination = "Inbox"
images = "images"
sync_branch = "master"
lock_file = "~/.hermes/workspace/cache/webclip-obsidian/vault.lock"
pending_root = "~/.hermes/workspace/cache/webclip-obsidian/pending-state"
```

## Invocation Pattern

There are **three** Python entry points, all invoked from the plugin root (repo root in a source checkout, or the installed plugin dir):

1. **Hermes command boundary** via `build_handler()` — returns a formatted `str` safe to show directly to the user.
2. **Structured API** via `ClipService.run()` — returns `ClipResult` or `PendingClipResult` for programmatic branching.
3. **Batch API** via `ClipService.run_batch(specs)` — returns `BatchClipResult` (see *Multiple URLs* below); one vault lock and one commit for the whole list.

Hermes-style string handler:

```python
import sys
sys.path.insert(0, '.')
from web_to_obsidian import build_handler
from pathlib import Path

plugin_root = Path('.')
handler = build_handler(plugin_root)
message = handler('<URL>')
print(message)
```

Structured API for automation:

```python
import sys
sys.path.insert(0, '.')
from pathlib import Path
from web_to_obsidian import ClipService

plugin_root = Path('.')
service = ClipService(plugin_root)
result = service.run('<URL>')
print(type(result).__name__)
print(result.user_message())
```

CLI shortcut (string handler):

```bash
cd ~/.hermes/profiles/<profile>/plugins/webclip-obsidian && \
python3 -c "
import sys; sys.path.insert(0, '.')
from web_to_obsidian import build_handler; from pathlib import Path
print(build_handler(Path('.'))('<URL>'))
"
```

Flags: `--no-browser`, `--no-git`, `--refresh`, `--save-images yes|no|ask`,
`--favorite`, `--unfavorite`, `--favorite-only`, `--unfavorite-only`

## Favorite Marker

Clipped notes can carry a `favorite: true` frontmatter marker. It is
plugin-managed and independent of the article body.

| Command | Effect |
| --- | --- |
| `/webclip <url> --favorite` | Clip or refresh, then write `favorite: true` |
| `/webclip <url> --unfavorite` | Clip or refresh, then remove the marker |
| `/webclip <url> --favorite-only` | Mark an existing note without re-fetching |
| `/webclip <url> --unfavorite-only` | Clear an existing note without re-fetching |

Rules:

- A refresh or plain re-clip **without** a favorite option preserves the
  marker already stored on the note. Clear it explicitly with `--unfavorite`
  or `--unfavorite-only`.
- `--favorite-only` / `--unfavorite-only` never call the extractor. They locate
  the note by normalized source URL, patch only the `favorite` frontmatter
  line, and leave the managed body and manual section byte-for-byte unchanged.
  Add `--no-git` to skip Git preflight/commit/push and keep the change local.
- Marker-only flags cannot be combined with `--refresh` or `--save-images`.
  They fail when no clipped note exists for the URL.
- Only notes with `webclip_id` plus the managed/manual boundaries can be
  modified; arbitrary vault notes are refused.
- A change limited to `favorite` does not require `--refresh`; body changes
  still do.
- Repeating the current state writes nothing and creates no Git commit. The
  command is idempotent.
- Pending image confirmations store the chosen marker state and apply it on
  `resume_pending()`; the pending state itself expires after one hour.
- In Obsidian the marker is a boolean property, not a tag: query it with
  `LIST FROM "Inbox" WHERE favorite = true` (Dataview) or search
  `favorite: true`; `#favorite` will not match.
- Programmatic equivalent: `service.run("<url> --favorite-only")` returns a
  `ClipResult` whose `action` is `favorite` or `unfavorite`.

## Workflow

1. **Extract**: Call `service.run(url)` for structured control flow, or `handler(url)` when a final user-facing string is sufficient.
2. **PendingClipResult** (has remote images): Prompt user `yes`/`no`
   - `yes` → download and localize images into vault `images/` dir
   - `no` → keep remote image URLs
3. **Resume**: Call `service.resume_pending('yes')` or `service.resume_pending('no')` (requires `ClipService` + pending state)
4. **ClipResult**: Contains `path`, `commit_state`, `push_state`, `github_url`, and `action` (`clip` / `favorite` / `unfavorite`)
5. **Return**: Show the GitHub vault URL to user for preview

## Multiple URLs (sequential writes, one commit)

The `/webclip` slash command accepts **exactly one URL** per invocation —
`parse_clip_args()` rejects anything else. Never pass two URLs to one command.
To clip several articles there are two supported paths:

1. **Programmatic (preferred for batches):** call `ClipService.run_batch()`
   once. Articles are extracted and written one at a time, then every written
   path is committed and pushed **together in a single commit**.
2. **Slash command:** invoke `/webclip` once per URL. Each call commits on its
   own, so a 5-URL batch produces 5 commits.

```python
from pathlib import Path
from web_to_obsidian import ClipService

service = ClipService(Path('.'))
result = service.run_batch([
    'https://example.com/a --save-images yes --favorite',
    'https://example.com/b --save-images no',
])
print(result.user_message())
```

`run_batch()` contract:

- Every spec is `<url> [flags]`; flags bind to the URL they follow.
- `--save-images ask` is **rejected for any spec that extracts a page**.
  Decide the image policy once before the batch (localize or keep remote) and
  pass `yes` or `no` on every clipping spec; a single pending confirmation
  cannot represent more than one article. `--favorite-only` and
  `--unfavorite-only` specs are exempt because they never fetch the page.
- `--no-git` must be consistent across the whole batch.
- One article failing does **not** abort the rest. The result carries one
  `BatchClipItem` per URL with `ok` / `path` / `error`, and the Git state
  reflects only the successfully written subset.
- Same-site rate limits still apply: keep the 2-second delay guidance from the
  batch pitfall below.

## Pending State

When images need confirmation, pending state is stored under
`config.pending_root` (default
`~/.hermes/workspace/cache/webclip-obsidian/pending-state`). The layout is a
pointer plus one state file:

```
pending-root/
  active.json          # {"pending_id": "..."} — at most one active confirmation
  <pending_id>.json    # stored article + the options chosen at clip time
```

An empty `pending-root/` is normal. Only a present `active.json` means a
confirmation is outstanding; a pointer whose state file disappeared is cleared
automatically on the next read. Never point `pending_root` at a system/state
directory.

## Result Handling

```python
# For PendingClipResult
from web_to_obsidian import ClipService
from pathlib import Path
service = ClipService(Path('.'))
result = service.resume_pending('yes')  # or 'no'
print(result.user_message())
```

`ClipResult.user_message()` produces human-readable output with:

- File path relative to vault
- Git state (committed/pushed/unchanged/failed)
- GitHub URL for preview (when available)

## Pitfalls

- **CWD matters**: Must run from the plugin root (repo root / installed plugin dir)
- **Node.js required**: Extractor uses `node` CLI — ensure it's available
- **Vault lock**: Plugin acquires a file lock during writes; concurrent clips will block
- **Image confirmation flow**: `PendingClipResult` requires a second call with `resume_pending()` — the first call does NOT save the article
- **GitHub URL**: After successful save, always return the vault file URL so user can preview
- **Pre-clip repo hygiene (both repos!)**: before clipping, confirm the vault (`~/obsidian/shijistar`) AND the plugin source repo (`~/.hermes/workspace/repository/hermes-webclip-obsidian-plugin`) are both on clean `master` — prior tasks often leave them on feature branches, and the clip commit would land on the wrong branch. Fix: `git switch master && git pull --ff-only` in each. Verify with `git status --short`.
- **Dry-run preflight before the real clip**: run the extractor once with `node extractor/src/cli.mjs <url> --no-browser` and confirm `ok:true`, non-empty `author`, `method:static`, sane markdown length BEFORE `service.run()`. Catches 404s / anti-bot walls early instead of failing mid-clip.
- **Structured API sequence (proven)**: `service = ClipService(Path('.'))` → `result = service.run(url)` → if `PendingClipResult`, ask the user for image handling (localize vs keep remote) → `service.resume_pending('yes'|'no')` → `ClipResult` with `.github_url`. `run()` alone does NOT save the article.
- **Site-specific extraction quirks**: netease (163.com) pages hide author/published in `window.__INITIAL_STATE__` embedded JSON, not in standard meta/JSON-LD. See `references/netease-embedded-state-author.md` for root cause, diagnosis path, fix (v0.4.0), and backfill hash-safety notes.
- **163 `news/v/` video short links are handled by curl fallback**: A `c.m.163.com/news/v/<id>.html` link returns only a video stub + recommendation list (no article body). The Node.js extractor returns `QUALITY_GATE`, but the Python curl fallback (`_parse_netease_video_html`) automatically extracts title, author (from `<div class="s-name">`, video pages lack the JSON `"nickname"` field used by article pages), cover image (from `.poster[data-bg]`), publish date (from the date segment in the cover URL, e.g. `20261008` → `2026-10-08`), and the m3u8/mp4 stream URL. It generates a markdown note with metadata table, cover image, and `<video>` embed. No manual intervention needed. See `references/netease-placeholder-and-video-links.md`.
- **163 `empty.png` is a placeholder, not a figure — BUT the extractor now resolves the real image**: Netease lazy-loads images via `src=empty.png` + `data-echo=<real url>`; the pre-fix extractor only read `src` and clipped `empty.png`. Since the `fix/extractor-lazy-image` fix (`extractLazyImageSrc()` in `extractor/src/extractor.mjs`), clipped `news/a/` articles now emit the REAL `dingyue.ws.126.net/...` URL instead. So a freshly-clipped netease article shows a real remote image, not `empty.png`. `empty.png` only remains if the source has no lazy-load URL (rare) — it is a 1×1 transparent pixel; localizing it only stores identical pixels — confirm before localizing, default keep-remote. See `references/netease-placeholder-and-video-links.md`.
- **Outstanding or stale `pending-state` entry**: pending state is a pointer file
  (`active.json`) plus one `<pending_id>.json`. An **empty directory is normal**
  and must not be cleaned reflexively. Four distinct cases:
  - No `active.json` → `ClipError: No pending image confirmation exists.`
  - `active.json` points at a missing state file → the pointer is cleared
    automatically and the same "No pending" error is raised; just re-run.
  - Entry older than one hour (`PENDING_TTL_SECONDS`) → cleared automatically and
    rejected with `The pending image confirmation expired; please run /webclip again.`
  - Valid entry already outstanding → the next clip raises
    `Another clipped article ('<title>') is already waiting for yes/no confirmation.`
    Resolve it with `resume_pending('yes'|'no')`, or delete the whole pending root
    to abandon it, before clipping again.
  To avoid the two-step entirely, pass `--save-images yes|no`.
- **Hash-protection on re-clip of an existing note**: If the same URL was already clipped, `write_managed_note` compares semantic state and raises `The saved page changed; rerun with --refresh to update it.` unless `refresh=True`. Common trigger: re-clipping with a different `image_mode` (remote vs local). Before re-clipping, check whether the note already exists in the vault; ask the user keep-vs-refresh rather than auto-overwriting. To refresh AND localize images, pass `--refresh --save-images yes`.
- **Favorite marker is user intent, not article content**: `--favorite` / `--unfavorite` may be applied to an existing note without `--refresh`, while any body change still requires it. Do not hand-edit `favorite:` in the vault; use the flags so the Git commit and idempotency checks stay intact.
- **Marker-only flags never fetch**: `--favorite-only` / `--unfavorite-only` require an existing note in the configured destination and fail closed when it is missing or ambiguous. GitSync.preflight runs after a note is found and before its marker is changed; an unknown URL fails without requiring Git preflight or vault cleanup. A dirty worktree still blocks the operation unless `--no-git` is passed.
- **`favorite: false` is normalized away**: only `favorite: true` is meaningful. A refresh rewrites frontmatter and omits an explicit `false`; treat absence and `false` as "not favorited".

- **Favorite position**: `favorite: true` is always the line immediately after the top-level `original_host` field. When a note has no `original_host` field, the marker becomes the last frontmatter line instead. This applies whether marking via `--favorite` during initial clip or `--favorite-only` on an existing note. A marker found in the wrong position is moved into place; a marker already in the canonical position is left untouched. Only a key starting at column zero counts as `original_host`, so indented continuation lines inside multi-line values are never mistaken for it.

- **Rule**: Use `--favorite-only --no-git` to mark existing clipped articles as favorite without re-extraction or Git operations. This is efficient for quickly flagging articles you've already saved and avoids the extractor and preflight steps.

- **Batch mode rejects `--save-images ask`**: every spec that extracts a page must state `--save-images yes|no`. Decide the image policy once before the batch and pass the same decision on every clipping spec. Marker-only specs (`--favorite-only` / `--unfavorite-only`) are exempt because they never fetch the page.
- **User preference on image confirmations**: single-URL clips always prompt the user for local vs remote images via the normal `service.run(url)` flow; do not preemptively pass `--save-images no` just because the user's general preference is remote. For batches of 10+ articles, the user expects explicit per-article `--save-images yes|no` flags instead of per-article prompts.
- **One-step non-interactive clip via flags**: `service.run('<url> --refresh --save-images yes|no --no-browser')` performs the full clip in a single call and returns `ClipResult` directly — no `PendingClipResult`, no second `resume_pending()` step. Use this when the image decision is already known.
- **163 tracking params are not stripped by the plugin**: `?spss=...&spsnuid=...&spsvid=...&spstoken=...` are share-source trackers. `normalize_url` only drops the fragment, and the extractor's `normalizeUrl` filters only `utm_*`, `fbclid`, `gclid`, `share_token`. Dedup therefore relies on the page supplying a clean `<link rel="canonical">` (the normal case for `c.m.163.com`, verified in stored notes). When a page has no canonical tag, `safeCanonical` falls back to the raw URL, so a `?spss=...` variant yields a different `webclip_id` and a duplicate note. `original_url`/`fetched_url` are also written after `normalize_url`, so they do not retain the full tracked URL.
- **Profile skill vs source-repo drift**: before proposing or creating a PR for `hermes-webclip-obsidian-plugin`, verify whether the loaded profile skill file and `~/.hermes/workspace/repository/hermes-webclip-obsidian-plugin/skill/SKILL.md` are actually the same file or symlink. If they are not, patching the loaded profile skill alone will not create a source-repo diff; sync the source repo file explicitly first.
- **`image_mode` is conditional metadata**: treat `image_mode` as metadata for the remote-Markdown-image workflow only. When no remote Markdown images are present, omit the field entirely. Use `image_mode: remote` only when remote Markdown images were detected and intentionally kept remote; use `image_mode: local` only when those images were localized into the vault.
- **HTML `<img>` is outside `image_mode` flow**: plain HTML image tags in article content do not trigger the yes/no remote-image confirmation path and should not be used as evidence that `image_mode` must be present.
- **WeChat articles**: Plugin now auto-falls back to curl-based extraction for `mp.weixin.qq.com` when Node.js extractor fails. The fallback parses HTML via regex (title, author, body from `js_content`), converts to Markdown, and returns the same format. No manual intervention needed.
- **WeChat article author format**: Newer WeChat pages write author as `var nickname = htmlDecode("...")` instead of the old format `var nickname = "..."`. The parser now tries both formats (old plain-text first, then htmlDecode), so the author field is correctly extracted regardless of the page version. Why: WeChat's new page format uses htmlDecode() to encode the author name, which the original regex pattern couldn't match.
- **Browser CAPTCHA wall**: WeChat triggers slider CAPTCHA in headless browser; the curl fallback bypasses this entirely.
- **Zhihu anti-bot / cookie caveat**: A user-supplied `d_c0` cookie alone may still return `403` / `40362` on Zhihu article pages. Do not claim the retry succeeded unless a real request returns article HTML. If direct retry is blocked but the user has already provided or cached the article HTML (for example under `~/.hermes/profiles/<profile>/cache/documents/`), rebuild the Markdown from that HTML as a fallback and report that the live retry remained blocked.
- **Zhihu login-valid ≠ fetch-success**: even after the user later supplies `z_c0` and an auxiliary scraper reports that `z_c0`/`d_c0` are configured and the Zhihu login status is valid, protocol fetch can still return `HTTP 403`, and browser fallback can fail separately (for example by not finding `articles:<id>` in page state). For Zhihu, verify and report these layers separately: cookie completeness from the actual text received, login validity, protocol fetch result, and browser fallback result. See `references/zhihu-cookie-and-scraper-diagnostics.md`.
- **Anti-bot fallback via web_extract**: For sites with strong anti-bot (Zhihu, Doubao, some paywalled content), the Node.js extractor may fail with `QUALITY_GATE` / `HTTP_STATUS` / 403 even when `web_extract` succeeds. Workflow: run `web_extract` on the URL → if it returns clean Markdown/HTML, manually construct the `article` dict (including `ok: true`, `title`, `author`, `published`, `description`, `site`, `canonicalUrl`, `keywords`, `url`, `wordCount`, `method: web_extract_fallback`, `markdown`) and call `ClipService._persist_article()` directly with the extracted `content_markdown`. Use `ClipConfig.from_file()` (reads `config.toml`, no hardcoded paths) and `GitSync(vault, repo_root, branch)` constructor. This bypasses the extractor entirely and avoids the PendingClipResult flow when no Markdown images are present (HTML `<img>` tags don't trigger it). See `references/anti-bot-fallback-web-extract.md`.
- **`_persist_article()` requires `markdown` field in article dict**: The article dict passed to `_persist_article()` must include a `"markdown"` key (string) in addition to `content_markdown`. Without it, `_validate_success_payload()` raises `ClipError: The extractor returned incomplete or invalid article data.` The `markdown` field is part of the extractor's output schema and is validated even though `content_markdown` is the parameter used by `render_note()`. Always include both.
- **Branch semantics (vault vs source repo)**: NEW article clips auto-commit + push directly to the vault's `sync_branch` (master by default) via the plugin's `finalize()` — that is the expected flow (user-confirmed direct-master exception for the Obsidian vault). Only MANUAL vault edits/backfills and changes to the `hermes-webclip-obsidian-plugin` source repo use feature branch + PR (backfill example: `backfill/netease-author` branch, user manually merged). Never force-push or rewrite history; if a repo rejects direct push due to branch protection, fall back to feature branch + PR.
- **Git sync tests need upstream**: `GitSync.preflight()` requires the branch to have an upstream. In unit tests, always call `git push -u origin <branch>` after the initial commit, before calling `preflight()`.
- **Batch processing pitfalls**: When clipping 10+ articles sequentially, the vault worktree can get dirty between clips (especially after failed local-images clips that leave deleted images on disk). Never run a blanket `git checkout -- .` — it discards uncommitted manual note edits too. Inspect `git status --short` first: if it only shows generated residue under `Inbox/` and `images/`, clean only those paths (`git checkout -- Inbox/ images/`); if it shows any user edit, commit/stash it manually before continuing. Also, 163.com and other sites rate-limit rapid sequential requests — add a 2-second delay between clips. See `references/batch-processing.md` for the full proven workflow (pre-extract → sequential clip with cleanup → summary table).
- **SPA / client-side rendered pages**: Some sites (e.g., kimi.com, certain modern SPAs) render content entirely via JavaScript — the HTML response contains no article content, only JS bundles. The Node.js extractor, `web_extract`, and curl all return empty/boilerplate. Without a real browser session, these cannot be extracted. Report to user as requiring manual browser access. Do NOT save the empty shell as a note.

## Commit Message

Commits use the article title: `clip: <title>` (truncated to 60 chars). The `finalize()` method accepts an optional `commit_message` parameter; when `None`, falls back to `clip: save web article`. The `_persist_article()` method auto-generates the message from the article title. Marker-only operations commit as `favorite: <title>` or `unfavorite: <title>`, also truncated to 60 chars.

## Filename Date Prefix

New clips use the article's **published date** (from frontmatter `published` field) as the filename date prefix, falling back to the capture date when published date is unavailable or invalid. Implemented in `ClipService._publish_date()` (PR #15 on hermes-webclip-obsidian-plugin).

- `published: '2026-05-20T01:20:46+00:00'` → filename prefix `2026-05-20`
- `published: '2026-05-20'` → filename prefix `2026-05-20`
- Missing/invalid published → falls back to today's date

## Post-Clip

After article is saved and pushed:

1. Show the GitHub vault URL from `ClipResult.github_url`
2. Update any tracking (e.g., reading list) if user maintains one
