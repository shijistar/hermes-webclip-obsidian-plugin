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

- Linux or WSL (the implementation uses `fcntl` locks and POSIX process groups).
- Hermes Agent with standalone plugin support.
- Python 3.11+ and PyYAML.
- Node.js 18+ with the bundled extractor; Playwright Chromium is installed by
  its `prepare` hook.
- Git for the default synchronization flow.

Not supported: login-gated pages, cookies, credentials, and password-manager
integration.

## Quick start

### Install

The bundled installer wires up the Python and Node dependencies, Playwright
Chromium, the skill symlink, and `config.toml`:

```bash
cd /path/to/hermes-webclip-obsidian-plugin
./post-install.sh --install-plugin   # install, then wire up dependencies
./post-install.sh                    # later refresh
```

It detects `HERMES_HOME` and the active profile automatically
(`--hermes-home DIR` overrides) and preserves an existing `config.toml`. Manual
steps are in [`PLUGIN.md`](PLUGIN.md#install).

### Configure

Review `config.toml` in the plugin directory before the first clip. The shipped
defaults target `~/obsidian/shijistar`, write to `Inbox`, and sync `master`;
the [Configuration](#configuration) section lists every key. Restart your Hermes
gateway after changing the configuration.

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

`/webclip <url> [flags]` accepts exactly one public `http://` or `https://` URL.

### Command and flags

| Flag | Effect |
| --- | --- |
| `--refresh` | Update changed managed content while preserving the manual section. |
| `--no-browser` | Disable the Playwright fallback in the extractor. |
| `--no-git` | Skip Git preflight, commit, and push for this invocation. |
| `--save-images yes\|no\|ask` | Download images, keep remote URLs, or ask (default). |
| `--favorite` / `--unfavorite` | Set or clear the marker (see below). |
| `--favorite-only` / `--unfavorite-only` | Update an existing note without fetching (see below). |

### Favorite marker

`favorite` is a plugin-managed boolean property. It is written only when true;
an absent field means the note is not favorited.

| Command | Fetches page | Changes body | Result |
| --- | --- | --- | --- |
| `--favorite` | Yes | Only if clipping/refreshing | Writes `favorite: true` |
| `--unfavorite` | Yes | Only if clipping/refreshing | Removes the marker |
| `--favorite-only` | No | No | Writes `favorite: true` |
| `--unfavorite-only` | No | No | Removes the marker |

- Marker-only flags patch exactly one frontmatter line and leave the article
  body and manual section byte-for-byte unchanged. They cannot be combined with
  `--refresh` or `--save-images`, and they fail when the URL has no clipped note.
- Refreshing or re-clipping **without** a favorite flag keeps the existing
  marker. Clear it explicitly with `--unfavorite` or `--unfavorite-only`.
- A change limited to `favorite` does not require `--refresh`; article-body
  changes still do.
- Only notes carrying a `webclip_id` and the managed/manual boundaries can be
  marked. Unknown or ambiguous URLs fail closed.
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

`config.toml` lives in the plugin directory:

| Key | Default | Purpose |
| --- | --- | --- |
| `vault` | `~/obsidian/shijistar` | Obsidian vault root. |
| `destination` | `Inbox` | Note destination inside the vault. |
| `images` | `images` | Directory for localized images. |
| `sync_branch` | `master` | Branch the vault must be on for Git sync. |
| `lock_file` | `~/.hermes/workspace/cache/webclip-obsidian/vault.lock` | Cross-process lock; must be outside the vault. |
| `pending_root` | `~/.hermes/workspace/cache/webclip-obsidian/pending-state` | Pending image confirmations; one active at a time. |

The equivalent `WEB_TO_OBSIDIAN_VAULT`, `WEB_TO_OBSIDIAN_DEST`,
`WEB_TO_OBSIDIAN_IMAGES`, `WEB_TO_OBSIDIAN_SYNC_BRANCH`,
`WEB_TO_OBSIDIAN_LOCK_FILE`, and `WEB_TO_OBSIDIAN_PENDING_ROOT` environment
variables are accepted when `config.toml` is absent. Values are never forwarded
to the extractor process.

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
pip install pytest pyyaml
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
