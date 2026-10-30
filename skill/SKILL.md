---
name: web-clip-to-obsidian
description: Clip, save, favorite web articles to Obsidian; 剪藏 抓取 收藏
version: 1.5.4
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
- User asks to favorite or unfavorite an article already in the vault

## Plugin Location & Config

The **source repo** is the single source of truth. The installed plugin is a
repo-root clone installed by `hermes plugins install` (or a symlink when
developing). Always edit the source repo, never only the installed copy;
the durable rule is in `references/repo-linked-maintenance.md`.

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

Install and config layout (symlinks, no per-profile copy, tracked
`config.toml`): `references/repo-linked-maintenance.md`.

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

`favorite: true` in the note frontmatter is the single source of truth. It is
plugin-managed, independent of the article body, and never stored by editing
`.obsidian/bookmarks.json` — that file belongs to Obsidian's own Bookmarks
plugin, and the two stores drift apart the moment only one is updated.

| User intent | Target already clipped | Only a URL, not clipped |
| --- | --- | --- |
| favorite | `--favorite-only` | `--favorite` |
| unfavorite | `--unfavorite-only` | `--unfavorite` |

Trigger phrases: "收藏", "收藏这篇文章", "收藏一下", "favorite this", "star it".

Resolve the target before running anything, in this order: a URL in the same
message; the clip made earlier in this conversation (its `path`); a title the
user names, matched against exactly one note in `Inbox/`. If that does not
identify a single note, ask — never favorite "the most recent note" on a guess.

Address a clipped note by its recorded source URL: read `url:` from the note
frontmatter and pass it, e.g. `service.run("https://example.com/a --favorite-only")`.
Do not rebuild the URL from the title and do not rewrite the host (`c.m.` and
`www.` normalize to different sources). If the plugin answers that no clipped
note exists for the URL, retry once with `original_url`, then report and ask.

Rules:

- A refresh or plain re-clip **without** a favorite option preserves the stored
  marker. Clear it explicitly with `--unfavorite` or `--unfavorite-only`.
- Marker-only flags never call the extractor, cannot be combined with
  `--refresh` or `--save-images`, and fail closed when no note exists for the
  URL or the match is ambiguous. A dirty worktree blocks the run unless
  `--no-git` is passed, which writes the marker locally without a commit.
- Only notes carrying `webclip_id` plus the managed/manual boundaries can be
  modified; arbitrary vault notes are refused.
- A change limited to `favorite` does not require `--refresh`; any body change
  still does.
- `favorite: false` is meaningless: absence and `false` both mean "not
  favorited", and a refresh drops an explicit `false`.
- Position: the marker sits immediately after the top-level `original_host`
  field, or on the last frontmatter line when that field is absent. A marker in
  the wrong position is moved into place.
- Repeating the current state writes nothing and creates no commit
  (`commit_state == "unchanged"`); report "already in the requested state" instead of
  claiming a new commit; keep a distinct "already favorited" only for the
  `favorite` action so `unfavorite` does not claim it was already favorited. The result's `action` is `favorite` or `unfavorite`.
- Pending image confirmations store the chosen marker state and apply it on
  `resume_pending()`; the pending state itself expires after one hour.
- In Obsidian the marker is a boolean property, not a tag: query it with
  `LIST FROM "Inbox" WHERE favorite = true` (Dataview) or search
  `favorite: true`; `#favorite` will not match.

## Workflow

1. **Extract**: Call `service.run(url)` for structured control flow, or `handler(url)` when a final user-facing string is sufficient.
2. **PendingClipResult** (has remote images): Prompt user `yes`/`no`
   - `yes` → download and localize images into vault `images/` dir
   - `no` → keep remote image URLs
3. **Resume**: Call `service.resume_pending('yes')` or `service.resume_pending('no')` (requires `ClipService` + pending state)
4. **ClipResult**: Contains `path`, `commit_state`, `push_state`, `github_url`, and `action` (`clip` / `favorite` / `unfavorite`)
5. **Return**: Show the GitHub vault URL to user for preview

## Multiple URLs (sequential writes, one commit)

`/webclip` accepts **exactly one URL** — `parse_clip_args()` rejects more. Two
supported paths:

1. **Programmatic (preferred):** a single `ClipService.run_batch()` call writes
   every article and commits them together in one commit.
2. **Slash command:** one `/webclip` per URL, so N URLs produce N commits.

```python
service = ClipService(Path('.'))
result = service.run_batch(['https://example.com/a --save-images yes --favorite',
                            'https://example.com/b --save-images no'])
```

Each spec is `<url> [flags]` and flags bind to the URL they follow;
`--save-images ask` is rejected for any spec that extracts a page (marker-only
specs are exempt); `--no-git` must be consistent across the batch; one failing
article does not abort the rest. Full workflow and rate-limit guidance:
`references/batch-processing.md`.

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

Operational rules stay here; diagnosis notes, root causes and site deep-dives
live in `references/` and are linked from the rule they belong to.

- **CWD matters**: run from the plugin root (repo root, or the installed plugin dir).
- **Node.js required**: the extractor shells out to `node`.
- **Vault lock**: writes take a file lock; a concurrent clip blocks until it is released.
- **Image confirmation is two-step**: `service.run(url)` returns `PendingClipResult` and saves nothing; the note is written only by `resume_pending('yes'|'no')`. Pass `--save-images yes|no` to skip the prompt.
- **Always return the GitHub URL**: after a save, report `ClipResult.github_url` so the user can preview the note.
- **Pre-clip repo hygiene (both repos)**: before clipping, confirm the vault (`~/obsidian/shijistar`) and the plugin source repo are both on a clean `master`; a leftover feature branch would take the clip commit. Run `git switch master && git pull --ff-only` and `git status --short` in each repo.
- **Dry-run preflight**: run `node extractor/src/cli.mjs <url> --no-browser` once and check `ok:true`, a non-empty `author` and a sane markdown length before `service.run()`; this catches 404s and anti-bot walls early.
- **Hash protection on re-clip**: an existing note whose content changed raises `The saved page changed; rerun with --refresh to update it.` Check whether the note already exists and ask keep-vs-refresh instead of overwriting; `--refresh --save-images yes` refreshes and localizes.
- **Image policy**: a single URL always asks the user (never pre-empt `--save-images no` from a general preference); a batch of 10+ passes an explicit `--save-images yes|no` per spec.
- **One-step non-interactive clip**: `service.run('<url> --refresh --save-images yes|no --no-browser')` clips in a single call and returns `ClipResult` with no pending step.
- **Batch image policy**: every spec that extracts a page must state `--save-images yes|no`; marker-only specs are exempt. See `references/batch-processing.md`.
- **Branch semantics**: new clips commit and push straight to the vault's `sync_branch` (the user-approved direct-master exception for the Obsidian vault); manual vault edits and any change to the plugin source repo go through a feature branch and PR. Never force-push.
- **163 embedded metadata**: author/published come from `window.__INITIAL_STATE__`, not meta tags. See `references/netease-embedded-state-author.md`.
- **163 video short links** (`/news/v/<id>.html`): the curl fallback extracts title, author, cover, date and the stream URL. See `references/netease-placeholder-and-video-links.md`.
- **163 `empty.png`**: a 1x1 lazy-load placeholder; the current extractor resolves the real `data-echo` URL. See `references/netease-placeholder-and-video-links.md`.
- **163 tracking params**: `spss`/`spsnuid`/`spsvid`/`spstoken` are not stripped, so dedup depends on the page's canonical tag. See `references/netease-placeholder-and-video-links.md`.
- **Stale `pending-state`**: four distinct states (no `active.json`, dangling pointer, older than one hour, already outstanding) raise different errors; an empty directory is normal. See `references/pending-resume-fallback.md`.
- **Favorite marker**: `## Favorite Marker` above is the only place its semantics are defined.
- **Profile vs source-repo drift**: the loaded profile skill and the repo file may be different files, so patching one leaves no diff in the other. See `references/profile-skill-vs-source-repo-sync.md`.
- **`image_mode` semantics** and private GitHub blob URLs: see `references/github-private-blob-url-and-image-mode.md`.
- **HTML `<img>` tags** do not trigger the `image_mode` confirmation flow.
- **WeChat**: curl fallback, author field format and the CAPTCHA wall. See `references/wechat-curl-extraction.md`.
- **Zhihu**: cookie completeness, login validity and fetch success are three separate checks. See `references/zhihu-cookie-and-scraper-diagnostics.md`.
- **Anti-bot fallback**: when the extractor fails but `web_extract` succeeds, build the article dict and call `_persist_article()`; it must carry both `content_markdown` and `markdown`. See `references/anti-bot-fallback-web-extract.md`.
- **SPA pages**: JS-only pages cannot be extracted by the extractor, `web_extract` or curl; report them instead of saving an empty shell. See `references/anti-bot-fallback-web-extract.md`.
- **Real-browser extraction**: when a page needs a logged-in or JS-executing browser, drive Windows Chrome over CDP from WSL. See `references/wsl-chrome-cdp-extraction.md`.
- **Git sync tests**: `GitSync.preflight()` needs a branch with an upstream. See `references/git-sync-testing-pattern.md`.
- **Dirty vault between batch clips**: never `git checkout -- .`; clean only generated residue under `Inbox/`/`images/` and keep a 2-second delay between 163 requests. See `references/batch-processing.md`.

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
