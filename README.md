# hermes-webclip-obsidian-plugin

A **web clipping pipeline for Obsidian**: extract a public web article as clean
Markdown, save it as a dated note in your vault, and — when the vault is a Git
repository — commit and push it with guarded automatic synchronization. The
repository is the Hermes plugin package, with a bundled Node.js extractor and an
agent skill in the same tree.

## Features

- **Clean extraction** — Defuddle static parsing with an isolated Playwright
  Chromium fallback for weak static pages.
- **Image control** — keep remote image URLs, download them into the vault, or
  decide per clip.
- **Favorite marker** — mark a note with `favorite: true` while clipping or
  later; refreshing keeps the stored marker.
- **Guarded Git sync** — clean-worktree checks, path-scoped commits, normal
  pushes, and a GitHub preview link when available.
- **WeChat fallback** — curl-based extraction when the Node extractor is
  blocked by the article page.
- **Idempotent notes** — notes are matched by normalized source URL; unchanged
  content is a no-op instead of a duplicate.

## Requirements

- Linux, macOS, or WSL (the implementation uses `fcntl` locks and POSIX process groups;
  Windows is not supported).
- Hermes Agent with standalone plugin support.
- Python 3.11+ and PyYAML (declared in `plugin.yaml`; `hermes plugins install` installs it
  into the Hermes runtime environment).
- Node.js 18+ with the bundled extractor; Playwright Chromium is installed by
  its `prepare` hook.
- Git for the default synchronization flow.

Not supported: login-gated pages, cookies, credentials, and password-manager
integration.

## Quick start

### Install

The bundled installer wires up the Node dependencies (Playwright Chromium) and
`config.toml`:

```bash
cd /path/to/hermes-webclip-obsidian-plugin
./post-install.sh --install-plugin   # install, then wire up dependencies
./post-install.sh                    # later refresh
```

It detects `HERMES_HOME` and the active profile automatically
(`--hermes-home DIR` overrides) and preserves an existing `config.toml`. Manual
steps are in [`PLUGIN.md`](PLUGIN.md#install).

### Configure

Review `config.toml` in the plugin directory before the first clip. The
installer generates it from `config.example.toml` (defaults target
`~/obsidian/shijistar`, write to `Inbox`, and sync `master`); the
[Configuration](#configuration) section lists every key. `config.toml` is
gitignored, so this version and later ones do not publish a machine's local
values (values committed before this change remain visible in git history).
Restart your Hermes gateway after changing the configuration.

### Clip your first article

```text
/webclip https://example.com/article
/webclip https://example.com/article --save-images yes
/webclip https://example.com/article --favorite
```

The note is written with a dated filename (`YYYY-MM-DD-<title>.md`) in the
destination. With Git enabled, the plugin commits it as `clip: <title>`, pushes,
and reports a GitHub preview link. If remote Markdown images remain and
`--save-images` is omitted, the plugin asks for a `yes`/`no` image decision
before writing.

## Usage

`/webclip <url|webclip_id> [flags]` accepts exactly one public `http://` or
`https://` URL, or one `webclip_id` (64 hex characters, `sha256:` prefix
optional). A `webclip_id` target requires `--favorite` or `--unfavorite`.

### Command and flags

| Flag | Effect |
| --- | --- |
| `--refresh` | Update changed managed content while preserving the manual section. |
| `--no-browser` | Disable the Playwright fallback in the extractor. |
| `--no-git` | Skip Git preflight, commit, and push for this invocation. |
| `--save-images yes\|no\|ask` | Download images, keep remote URLs, or ask (default). Applies only when the page is clipped or refreshed. |
| `--favorite` / `--unfavorite` | Ensure the note carries (or does not carry) the marker (see below). |

### Favorite marker

`favorite` is a plugin-managed boolean property. It is written only when true;
an absent field means the note is not favorited.

`--favorite` is idempotent: it clips a URL that is not in the vault yet, marks
an existing note without fetching it, and only re-fetches when you ask with
`--refresh`. `--unfavorite` clears the marker and, without `--refresh`, never
fetches.

| Target | Command | Fetches page | Changes body | Result |
| --- | --- | --- | --- | --- |
| new URL | `--favorite` | Yes | Yes (first clip) | Clips and writes `favorite: true` |
| clipped URL | `--favorite` | No | No | Writes `favorite: true` |
| clipped URL | `--favorite --refresh` | Yes | Only if the page changed | Refreshes and keeps the marker |
| clipped URL | `--unfavorite` | No | No | Removes the marker |
| `webclip_id` | `--favorite` / `--unfavorite` | No | No | Marks the matching note(s) |

- A target is either an `http(s)` URL or a `webclip_id`: the 64-hex digest from
  the note frontmatter, with or without the `sha256:` prefix. A content hash
  (`source_content_hash`) is accepted as a fallback when no `webclip_id`
  matches.
- Marker operations patch exactly one frontmatter line and leave the article
  body and manual section byte-for-byte unchanged (a marker rewrite normalizes
  line endings to LF). A `webclip_id` target
  cannot be combined with `--refresh` or `--save-images`.
- Every note matching the selector is marked; duplicate clips of the same
  article are reported as "N notes" in the result.
- Refreshing or re-clipping **without** a favorite flag keeps the existing
  marker. Clear it explicitly with `--unfavorite`.
- A change limited to `favorite` does not require `--refresh`; article-body
  changes still do.
- Only notes carrying a `webclip_id` and the managed/manual boundaries can be
  marked. Unknown selectors fail closed.
- Repeating the current state writes nothing and creates no Git commit.

In Obsidian, query the boolean property directly. With the Dataview community
plugin:

```dataview
LIST FROM "Inbox" WHERE favorite = true
```

Without Dataview, search `favorite: true` or filter the Properties view. This is
not a tag, so `#favorite` will not match. Full rules:
[`PLUGIN.md`](PLUGIN.md#favorite-marker).

### Images

- `--save-images ask` (default) stores a pending yes/no confirmation when the
  sanitized Markdown still has remote Markdown images.
- `--save-images yes` downloads them into `images/<article-slug>/`.
- `--save-images no` keeps the remote URLs and saves immediately.

## Configuration

`config.toml` lives in the plugin directory. It is gitignored and generated
from `config.example.toml` on install:

| Key | Default | Purpose |
| --- | --- | --- |
| `vault` | `~/obsidian/shijistar` | Obsidian vault root. |
| `destination` | `Inbox` | Note destination inside the vault. |
| `images` | `images` | Directory for localized images. |
| `sync_branch` | `master` | Branch the vault must be on for Git sync. |
| `lock_file` | `~/.hermes/workspace/cache/webclip-obsidian/vault.lock` | Cross-process lock; must be outside the vault. |
| `pending_root` | `~/.hermes/workspace/cache/webclip-obsidian/pending-state` | Pending image confirmations; one active at a time. |
| `preview_url_params` | `""` (empty) | Query parameters appended to the article preview URL; see [Opening preview links in a browser](docs/preview-link-params.md). |

The equivalent `WEB_TO_OBSIDIAN_VAULT`, `WEB_TO_OBSIDIAN_DEST`,
`WEB_TO_OBSIDIAN_IMAGES`, `WEB_TO_OBSIDIAN_SYNC_BRANCH`,
`WEB_TO_OBSIDIAN_LOCK_FILE`, `WEB_TO_OBSIDIAN_PENDING_ROOT`, and
`WEB_TO_OBSIDIAN_PREVIEW_URL_PARAMS` environment variables are accepted when
`config.toml` is absent. Values are never forwarded to the extractor process.

## Safety

- URLs reject credentials, fragments, unsafe ports, malformed hosts, and
  non-HTTP schemes; redirects are revalidated.
- Remote image downloads block reserved/private IP ranges, pin redirects,
  reject non-default ports, and require `Content-Type: image/*`.
- Vault writes stay inside the configured vault, reject symlinks, and use
  same-directory temporary files with `fsync` and atomic replacement.
- The extractor child receives only an allowlisted environment; credential-like
  markers in extracted content refuse to save.
- Git sync requires the configured branch, a completely clean worktree, an
  `origin` remote, and no in-progress Git operation. It stages only generated
  paths and never force-pushes.

Details: [`PLUGIN.md`](PLUGIN.md#network-and-content-safety),
[`PLUGIN.md`](PLUGIN.md#vault-and-idempotency-safety), and
[`PLUGIN.md`](PLUGIN.md#git-safety).

## Development

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/ -v
cd extractor && npm test && npm run check
```

Tests use fixtures, temporary directories, and temporary Git repositories; they
never write the configured real vault. Contributor rules and the release
workflow live in [`AGENTS.md`](AGENTS.md).

## Documentation map

| Topic | Where |
| --- | --- |
| Install, configuration, usage | [`PLUGIN.md`](PLUGIN.md) |
| Favorite marker rules | [`PLUGIN.md`](PLUGIN.md#favorite-marker) |
| Plugin network, vault, and Git safety | [`PLUGIN.md`](PLUGIN.md#network-and-content-safety) |
| Extractor CLI and error codes | [`extractor/README.md`](extractor/README.md) |
| Agent skill deployment | [`skill/README.md`](skill/README.md) |
| Contributor guide | [`AGENTS.md`](AGENTS.md) |
| Version history | [`CHANGELOG.md`](CHANGELOG.md) |

## License

MIT — see [`LICENSE`](LICENSE).
