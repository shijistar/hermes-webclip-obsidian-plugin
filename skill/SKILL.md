---
name: web-clip-to-obsidian
description: Clip, save, favorite web articles to Obsidian; 剪藏 抓取 收藏
version: 1.9.0
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
# Query parameters appended to the article preview (GitHub blob) URL.
# Leave empty to keep the URL unchanged. Feishu/Lark example:
#   "lk_jump_to_browser=true&lk_mobile_jump_to_browser=true"
preview_url_params = ""
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
`--favorite`, `--unfavorite`

## Default image policy

**Always pass `--save-images no` unless the user asks otherwise.** Do not ask
the user which image mode to use: remote images keep the note small, keep the
vault free of binary blobs, and leave the source page's own image CDN in charge.

| User says | Flag |
| --- | --- |
| nothing about images, or "远程图片" / "remote images" | `--save-images no` |
| "本地图片" / "local images" / "download images" / "保存图片" | `--save-images yes` |
| "问我" / "ask me" / "让我选" | `--save-images ask` |

`--save-images ask` is the only mode that returns `PendingClipResult` and needs
a `resume_pending('yes'|'no')` follow-up. Use it only when the user explicitly
asked to be prompted, and never call `resume_pending()` to decide on the user's
behalf.

### Asking in `ask` mode: a `clarify` card, never a typed reply

When the mode is `ask`, collect the decision through a **`clarify` card carrying two
options** — never a text prompt that makes the user type `yes` / `no`.

Write the two labels in the **language of the current conversation**: Chinese when the
user writes Chinese, English when they write English. Keep the order fixed — **A first,
B second** — so the option the card marks as recommended is also the remote default.
The letters and their mapping never change.

| Option | zh-CN label | en label | Call |
| --- | --- | --- | --- |
| **A** | `A. 远程图片（保留原站链接）` | `A. Remote images (keep the source URLs)` | `resume_pending('no')` |
| **B** | `B. 本地图片（下载到 vault 的 images/）` | `B. Local images (download into the vault)` | `resume_pending('yes')` |

Spell the letter **inside the label** (`A. …` / `B. …`). A `clarify` call returns the
text of the selected option, not an index and not a bare letter, so the prefix is the
only thing the agent can match on; never wait for a reply containing just `"A"`.

The labels name the **destination**, while the plugin argument is inverted: `yes`
means "save the images locally". Map deliberately — a user picking the `A.` option must
end in `resume_pending('no')`; never forward the raw label or the leading letter.

If the runtime has no `clarify` tool (one-shot CLI, scripted run), ask the same A/B
question in a single text line, in the user's language, and still call
`resume_pending()` yourself. In every case the agent performs the mapping and never
picks a mode on the user's behalf.

## Favorite Marker

`favorite: true` in the note frontmatter is the single source of truth. It is
plugin-managed, independent of the article body, and never stored by editing
`.obsidian/bookmarks.json` — that file belongs to Obsidian's own Bookmarks
plugin, and the two stores drift apart the moment only one is updated.

`--favorite` is idempotent: a URL that is not clipped yet is clipped and marked;
an existing note is marked in place without fetching; `--refresh` is the only
way to re-fetch. `--unfavorite` clears the marker and, without `--refresh`,
never fetches.

| User intent | Target | Command |
| --- | --- | --- |
| favorite | URL, new or already clipped | `--favorite` |
| favorite | `webclip_id` from the note | `--favorite` |
| unfavorite | URL or `webclip_id` | `--unfavorite` |
| refresh content, keep the marker | URL | `--favorite --refresh` |

Trigger phrases: "收藏", "收藏这篇文章", "收藏一下", "favorite this", "star it".

Resolve the target before running anything, in this order: a URL in the same
message; the clip made earlier in this conversation (its `path`); a `webclip_id`
the user pastes; a title the user names, matched against exactly one note in
`Inbox/`. If that does not identify a single note, ask — never favorite "the
most recent note" on a guess.

Address a clipped note by its recorded source URL: read `url:` from the note
frontmatter and pass it, e.g. `service.run("https://example.com/a --favorite")`.
A `webclip_id` (64 hex characters, `sha256:` prefix optional) also works and is
more robust when the URL form is uncertain; the plugin falls back to
`source_content_hash` when no `webclip_id` matches. Do not rebuild the URL from
the title and do not rewrite the host (`c.m.` and `www.` normalize to different
sources).

Rules:

- A refresh or plain re-clip **without** a favorite option preserves the stored
  marker. Clear it explicitly with `--unfavorite`.
- Marker operations never call the extractor; a `webclip_id` target cannot be
  combined with `--refresh` or `--save-images`. A missing selector fails closed.
  A dirty worktree blocks the run unless `--no-git` is passed, which writes the
  marker locally without a commit.
- Every note matching the selector is marked. Duplicate clips of the same
  article are all updated in one commit and the result lists them as "N notes".
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

## Normalize the input before anything else

Share sheets prepend a title and append tracking parameters, and some apps put
the article identity in the query string. Because `webclip_id` is derived from
whatever URL reaches the service, passing the raw paste makes one article look
like two — it gets clipped twice, and `--favorite` against the existing note
stops matching.

Drop the title, apply that site's rule from `references/input-normalization.md`,
then pass only the cleaned URL to `service.run()`. A host that is not in the
rule table is passed through **unchanged** — guessing is worse than doing
nothing, because a wrong strip can make an article unreachable.

This applies to **URL-shaped input**: `clip`, `--refresh`, and the
`--favorite` / `--unfavorite` calls that address a note by URL. A `webclip_id`
selector (`sha256:…`) is an exact hash and is never rewritten, and in a batch
every spec's URL is cleaned before the list is built
(`references/batch-processing.md`).

## Workflow

1. **Extract**: Call `service.run(url)` with the cleaned URL for structured control flow, or `handler(url)` when a final user-facing string is sufficient.
2. **PendingClipResult** — returned only when the call carried
   `--save-images ask`: ask with a `clarify` card whose two labels start with `A.` / `B.`
   and are written in the user's language
   - **`A.`** (remote images) → `resume_pending('no')` — keep the source image URLs
   - **`B.`** (local images) → `resume_pending('yes')` — download into the vault's `images/`
3. **Resume** — only after an `ask` run: call `service.resume_pending('yes')` or
   `service.resume_pending('no')` (requires `ClipService` + pending state)
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
- **Image confirmation is opt-in**: the agent default is `--save-images no`, so a plain clip writes the note immediately with `image_mode: remote` and never returns `PendingClipResult`. Only `--save-images ask` returns `PendingClipResult`, and in that mode nothing is saved until `resume_pending('yes'|'no')` runs — ask via a `clarify` card with two lettered options (labels in the user's language, A = remote, B = local), then map A→`'no'` and B→`'yes'`.
- **Always return the GitHub URL**: after a save, report `ClipResult.github_url` so the user can preview the note. The URL may already carry the `preview_url_params` query parameters configured in `config.toml`; do not strip or duplicate them (see `docs/preview-link-params.md`).
- **Pre-clip repo hygiene (both repos)**: before clipping, confirm the vault (`~/obsidian/shijistar`) and the plugin source repo are both on a clean `master`; a leftover feature branch would take the clip commit. Run `git switch master && git pull --ff-only` and `git status --short` in each repo.
- **Dry-run preflight**: run `node extractor/src/cli.mjs <url> --no-browser` once and check `ok:true`, a non-empty `author` and a sane markdown length before `service.run()`; this catches 404s and anti-bot walls early.
- **Hash protection on re-clip**: an existing note whose content changed raises `The saved page changed; rerun with --refresh to update it.` Check whether the note already exists and ask keep-vs-refresh instead of overwriting; `--refresh --save-images yes` refreshes and localizes.
- **Image policy**: always pass `--save-images no` unless the user asked for local images (`yes`) or asked to be prompted (`ask`); never ask the user which mode to use. In a batch, every spec that extracts a page must carry an explicit `yes` or `no` — `ask` is rejected because one pending confirmation cannot represent several articles; marker-only specs are exempt. See `references/batch-processing.md`.
- **One-step non-interactive clip**: `service.run('<url> --refresh --save-images yes|no --no-browser')` clips in a single call and returns `ClipResult` with no pending step.
- **Branch semantics**: new clips commit and push straight to the vault's `sync_branch` (the user-approved direct-master exception for the Obsidian vault); manual vault edits and any change to the plugin source repo go through a feature branch and PR. Never force-push.
- **163 embedded metadata**: author/published come from `window.__INITIAL_STATE__`, not meta tags. See `references/netease-embedded-state-author.md`.
- **163 video short links** (`/news/v/<id>.html`): the curl fallback extracts title, author, cover, date and the stream URL. See `references/netease-placeholder-and-video-links.md`.
- **163 `empty.png`**: a 1x1 lazy-load placeholder; the current extractor resolves the real `data-echo` URL. See `references/netease-placeholder-and-video-links.md`.
- **163 tracking params**: `spss`/`spsnuid`/`spsdevid`/`spsvid`/`spsshare`/`spsts`/`spstoken` are removed at the input stage by `references/input-normalization.md`; duplicate detection still depends on the page's canonical tag, which is why cleaning never changes an existing note's identity. See `references/netease-placeholder-and-video-links.md`.
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

1. Show the GitHub vault URL from `ClipResult.github_url` (it already includes any configured `preview_url_params`)
2. Update any tracking (e.g., reading list) if user maintains one
