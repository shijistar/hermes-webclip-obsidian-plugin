# webclip-obsidian plugin

A synchronous Hermes standalone plugin that clips a **public** web article
into an Obsidian Vault and optionally performs guarded Git synchronization.

This repository **is** the Hermes plugin package: `plugin.yaml`, `__init__.py`
(registration entry point), `web_to_obsidian.py` (core logic), and
`config.example.toml` all live at the repo root. The installer generates a
local, gitignored `config.toml` from that template. The Node.js extraction
engine is the bundled `extractor/` subdirectory.

See [`CHANGELOG.md`](CHANGELOG.md) for version history.

## Requirements

- Hermes Agent with standalone plugin support.
- Python 3.11+ and PyYAML (declared in `plugin.yaml`; `hermes plugins install` installs it
  into the Hermes runtime environment).
- Node.js 18+ (the bundled `extractor/` has its dependencies installed via
  `npm install`).
- Git for default synchronization.
- Playwright Chromium (installed by the extractor `prepare` hook) for dynamic
  fallback.

## Install

The recommended way is the one-shot installer bundled in this repository
(it wires up the extractor npm dependencies + Playwright Chromium and
`config.toml`; the plugin itself is assumed
to be already installed via `hermes plugins install` — pass `--install-plugin` to
have the script run that step too; on an existing install this refreshes it with
`hermes plugins install --force` and preserves your `config.toml`). It
auto-detects `HERMES_HOME` and the profile by
walking up from its own location to the nearest `.hermes` directory:

```bash
# Run without flags from the *installed* plugin dir. From a source checkout
# pass --hermes-home (unless thee checkout already sits beneath a .hermes dir,,
# in which case the walk-up finds it automatically):
cd /path/to/hermes-webclip-obsidian-plugin
./post-install.sh                     # auto-detects HERMES_HOME / profile
./post-install.sh --hermes-home /path/to/custom-hermes   # custom Hermes home
```

Manual steps (what `./post-install.sh` automates), for a git checkout using Hermes'
plugin manager:

```bash
REPO=/path/to/hermes-webclip-obsidian-plugin
hermes plugins install "file://$REPO" --enable
cd "$HERMES_HOME/plugins/webclip-obsidian/extractor"
npm install                     # installs Node deps; the prepare hook installs Playwright Chromium
cp "$REPO/config.example.toml" "$HERMES_HOME/plugins/webclip-obsidian/config.toml"
```

The plugin registers its skill in `register()`, so it lives inside the package and
nothing is copied into a profile. It resolves as
`webclip-obsidian:web-clip-to-obsidian`.

For a named profile, set `HERMES_HOME` to that profile before the commands.
Review `config.toml` before restarting the Gateway. `after-install.md` in the
repository root is printed by `hermes plugins install` and contains these
follow-up steps.

> The installed plugin is a clone of the repository. `hermes plugins install`
> clones the repo root (the plugin package), so the bundled `extractor/`
> directory and `skill/` are preserved in the installed copy. At runtime the
> plugin uses the bundled `<plugin_root>/extractor` (dependencies installed by
> `npm install` inside it, which also pulls Playwright Chromium via the
> `prepare` hook); if a published `@tiny-codes/web-clip-extractor` npm package
> is present in `<plugin_root>/node_modules`, it is preferred instead.

## Configuration

`config.toml` is non-secret and lives in the installed plugin directory:

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

- `vault` — the Obsidian vault root.
- `destination` — note destination subdirectory inside the vault.
- `images` — directory inside the vault for localized images.
- `sync_branch` — the Git branch the vault must be on for automatic sync.
- `lock_file` — cross-process lock path; **must be outside the vault**.
- `pending_root` — where pending image confirmations are stored; only one
  active yes/no confirmation is supported at a time.
- `preview_url_params` — query parameters appended to the article preview
  (GitHub blob) URL; empty by default. See
  [`docs/preview-link-params.md`](docs/preview-link-params.md) for per-platform
  parameters and examples.

When `config.toml` is absent, the legacy `WEB_TO_OBSIDIAN_VAULT`,
`WEB_TO_OBSIDIAN_DEST`, `WEB_TO_OBSIDIAN_IMAGES`, `WEB_TO_OBSIDIAN_SYNC_BRANCH`,
`WEB_TO_OBSIDIAN_LOCK_FILE`, `WEB_TO_OBSIDIAN_PENDING_ROOT`, and
`WEB_TO_OBSIDIAN_PREVIEW_URL_PARAMS` environment variables are accepted as a
fallback. These values are never forwarded to the untrusted extractor process.

## Usage

```text
/webclip <url|webclip_id> [--refresh] [--no-browser] [--no-git]
         [--save-images yes|no|ask] [--favorite|--unfavorite]
```

- Exactly one target: a public `http://` or `https://` URL, or a `webclip_id`
  (64 hex characters, with or without the `sha256:` prefix).
- `--refresh` explicitly updates changed managed content while preserving the
  manual section.
- `--no-browser` disables the Playwright fallback in the extractor.
- `--no-git` disables Git preflight, commit, and push for that invocation.
- `--favorite` ensures the note is favorited: a new URL is clipped, an existing
  note is marked in place, and `--refresh` is the only way to re-fetch.
- `--unfavorite` clears the marker; without `--refresh` it never fetches
  (`--refresh --unfavorite` updates the content and clears the marker in one
  run).
- A `webclip_id` target requires `--favorite` or `--unfavorite` and cannot be
  combined with `--refresh` or `--save-images`.
- `--save-images yes` downloads remote Markdown/HTML image references into
  `images/<article-slug>/...` before saving the note. It applies only when the
  page is clipped or refreshed.
- `--save-images no` preserves remote image URLs and saves immediately.
- Omitting `--save-images` behaves as `ask`: if the final sanitized Markdown
  has remote `http/https` image references, `/webclip` stores one pending
  confirmation and waits for a plain `yes` or `no` reply via the registered
  `web_to_obsidian_resume_pending` tool. If no remote images remain, the note
  is saved immediately.

### Favorite marker

`favorite` is a plugin-managed boolean field that marks a clipped note as a
keeper without changing its article content:

```yaml
favorite: true
```

| Command | Effect |
| --- | --- |
| `/webclip <url> --favorite` | Clip a new URL, or mark an existing note; no fetch for an existing note |
| `/webclip <url> --favorite --refresh` | Re-fetch, update the managed content, keep the marker |
| `/webclip <url> --unfavorite` | Clear the marker; no extraction, no body change |
| `/webclip <webclip_id> --favorite` | Mark every matching note; no extraction |
| `/webclip <webclip_id> --unfavorite` | Clear the marker on every match |

Behavior rules:

- **Refresh preserves the marker.** When `--refresh` (or a plain re-clip) does
  not specify `--favorite` or `--unfavorite`, the existing note's marker is
  carried over. Use `--unfavorite` to clear it explicitly.
- **Marker operations never fetch the page.** The note is located by its
  normalized source URL, or by `webclip_id` with a `source_content_hash`
  fallback; only the `favorite` frontmatter line is added or removed, and the
  managed body plus the manual section stay byte-for-byte unchanged (a marker
  rewrite normalizes line endings to LF). A missing
  selector fails closed. Marker operations accept `--no-git`: the marker is
  written locally without Git preflight, commit, or push.
- **Duplicate notes are all marked.** When a selector matches several notes
  (for example the same article clipped twice), every match is updated in one
  commit and the result lists them as "N notes".
- **Only webclip-managed notes are eligible.** The note must carry a
  `webclip_id`, the managed boundaries, and the manual boundaries; arbitrary
  vault notes are refused.
- **No spurious refresh requirement.** A change that only touches `favorite`
  is applied without `--refresh`; any article-body change still requires it.
- **Idempotent.** Re-applying the current state writes nothing and creates no
  Git commit.
- **Pending image confirmations keep the marker intent.** If the clip waits for
  the yes/no image decision, the chosen favorite state is applied on resume
  (the pending state itself expires after one hour).

#### Using the marker in Obsidian

`favorite` is a boolean property, not a tag. Query it directly.

With the Dataview community plugin:

```dataview
LIST FROM "Inbox" WHERE favorite = true
```

Without Dataview:

- Search `favorite: true` in Obsidian search or filter the Properties view.
- Do not use `#favorite`: no tag is written, so a tag search will not match
  these notes and would create a second source of truth.
- A Bases table/view can filter on the `favorite` property the same way as any
  other frontmatter field.

### Programmatic entry points

```python
from web_to_obsidian import ClipService
from pathlib import Path

service = ClipService(Path("."))          # run from the repository root
result = service.run("<url> [flags]")     # ClipResult | PendingClipResult
# If PendingClipResult: service.resume_pending("yes" | "no")
print(result.user_message())
```

`build_handler(root)` returns the Hermes slash-command string handler;
`build_resume_tool(root)` returns the `web_to_obsidian_resume_pending` tool
handler.

## Filename date prefix

New clips use the article's `published` date as the filename date prefix,
falling back to the capture date when the published date is missing or
invalid.

- `published: '2026-05-20T01:20:46+00:00'` → `2026-05-20`
- `published: '2026-05-20'` → `2026-05-20`
- Missing/invalid → today's date

## Extraction fallback

The plugin drives the Node extractor via `run_extractor_with_fallback()`:

1. `run_extractor()` — Node extractor with hardened network policy.
2. On failure for **WeChat URLs** (`mp.weixin.qq.com`), a curl-based fallback
   fetches the raw HTML and parses title, author, publish time, and the
   `js_content` body via regex, converting HTML to Markdown. This bypasses the
   WeChat slider CAPTCHA that headless browsers trigger.
3. Other sites surface the Node extractor error directly.

## Network and content safety

- URLs reject credentials, fragments, unsafe ports, malformed hosts, and
  non-HTTP schemes.
- Every redirect is revalidated; see `extractor/README.md` for the
  extractor-side network policy.
- The extractor child receives only an allowlisted environment and runs in a
  new POSIX process group. Timeout/output-limit cleanup terminates the
  complete group.
- Extracted Markdown removes injected management comments, active HTML,
  dangerous local/custom URL schemes, and Obsidian embeds. Ordinary HTTPS
  links and remote images remain.
- Remote **image** downloads add SSRF protection: full RFC reserved IP range
  blocking, redirect pinning (max 6 hops), non-default port rejection, IDNA
  hostname validation, and `Content-Type: image/*` enforcement.
- Code-aware sanitization: fenced code blocks, inline code spans, and indented
  code lines are skipped when scanning for remote images.
- Credential-like markers in extracted content are detected and refuse to
  save.

## Vault and idempotency safety

- A cross-process external lock covers Git synchronization, extraction, write,
  commit, and push.
- Paths are resolved and required to remain inside the configured Vault.
- Portable filenames use `YYYY-MM-DD-{article-title}.md` in the configured
  destination and reject traversal, control characters, device names, and
  excessive UTF-8 length.
- Writes use a same-directory temporary file, file `fsync`, `os.replace`, and
  parent-directory `fsync` where supported. Symlink targets are rejected.
- Frontmatter is serialized with `title`, `url`, `author`, `site`,
  `description`, `keywords`, `tags`, `original_url`, `original_host`,
  optional `fetched_url` (when the request URL differs from the canonical
  article URL), `extraction_method`, `status`, `category`, `word_count`,
  `webclip_id`, `source_content_hash`, `content_hash`, `image_mode`,
  `published`, `created`, and optional `favorite` (only when `true`).
- Managed note content preserves an extracted Markdown H1 when present and
  injects `# <title>` only when the extracted article has no Markdown H1.
- Existing notes are matched by normalized `url`, `original_url`, or legacy
  `source` frontmatter so older notes remain refreshable without duplication.
  That compatibility is recognition-only; metadata is rewritten to the new
  field names when a note is refreshed, not by a background migration.
- Same managed source + same managed content is a no-op. Changed content is
  rejected unless `--refresh` is explicit. Refresh preserves text inside the
  manual boundary.
- Frontmatter is fully managed output. User-added frontmatter keys are not part
  of the preserved manual region and may trigger a refresh requirement or be
  overwritten on refresh. The `favorite` key is the exception: when no favorite
  option is given, the stored marker is read back and preserved.
- Title collisions from different sources receive a deterministic URL hash.

## Git safety

With Git enabled, `/webclip` requires:

1. the configured sync branch (the shipped default is `master`);
2. no merge/rebase state;
3. a completely clean worktree, including untracked files;
4. an `origin` remote and successful `fetch --prune`;
5. a successful rebase of the current upstream before extraction.

After writing, it verifies the exact changed path, stages only that note,
verifies the staged set, commits with a message derived from the article title
(e.g. `clip: <title>`), then verifies the actual commit path set and clean
worktree before pushing `HEAD` normally. It never force-pushes or rewrites
public history.
If commit fails, the note remains untracked for recovery. If push fails, the
local commit remains for a later manual retry. When the `origin` remote points at
GitHub, successful saves include the `blob/<branch>/...` preview URL in the user
response.

## Tests

Python tests are colocated with the plugin in `tests/` (repo root). Run pytest
from the repository root:

```bash
python3 -m pytest tests/ -v
```

The tests use fixtures, temporary directories, and temporary Git
repositories; they do not write the configured real Vault. A `tests/conftest.py`
injects the repository root (`..`) into `sys.path` so `import web_to_obsidian`
resolves here.
