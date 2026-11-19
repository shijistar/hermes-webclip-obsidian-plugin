# hermes-webclip-obsidian-plugin

A **web clipping pipeline for Obsidian**: extract a public web article as clean
Markdown, save it as a dated note in your vault, and — when the vault is a Git
repository — commit and push it with guarded automatic synchronization. A second
command, `/save-video`, downloads the videos on a page to local disk.

The repository is the Hermes plugin package, with a bundled Node.js extractor
and two agent skills in the same tree.

## Features

- **Clean extraction** — Defuddle static parsing, with an isolated Playwright
  Chromium fallback for weak static pages.
- **Image control** — keep remote URLs, localize them, or decide per clip.
- **Video download** — HLS playlists and direct media, fetched through the
  plugin's own SSRF guard and remuxed locally.
- **Favorite marker** — flag a note as a keeper while clipping or later.
- **Guarded Git sync** — clean-worktree checks, path-scoped commits, and a
  preview link when available.
- **Idempotent notes** — matched by normalized source URL; unchanged content is
  a no-op instead of a duplicate.

## Requirements

- Linux, macOS, or WSL2. Native Windows is not supported: `fcntl` is imported at
  module load, so the plugin fails to import rather than degrading gracefully.
- On WSL2, keep the vault on the Linux filesystem (e.g. `~/vault`), not under
  `/mnt/c/...`, where Git sync and file locking are slower.
- Hermes Agent with standalone plugin support.
- Python 3.11+ and PyYAML (declared in `plugin.yaml`).
- Node.js 18+ and Git; Playwright Chromium is installed by the extractor's
  `prepare` hook.

**The vault must already be a Git repository on `sync_branch`** — otherwise every
`/webclip` needs `--no-git`. Not supported: login-gated pages, cookies,
credentials, password-manager integration.

## Quick start

### Install

```bash
hermes plugins install <repo-url>
cd "${HERMES_HOME:-$HOME/.hermes}/plugins/webclip-obsidian"
./post-install.sh
```

`hermes plugins install` clones the package; `post-install.sh` installs the
extractor's Node dependencies and Playwright Chromium, then writes `config.toml`
from `config.example.toml` — preserving an existing one. Restart the gateway
after changing the configuration.

### Clip your first article

```text
/webclip https://example.com/article
/webclip https://example.com/article --save-images yes
/webclip https://example.com/article --favorite
```

The note is written as `YYYY-MM-DD-<title>.md` in the destination. With Git
enabled, the plugin commits it as `clip: <title>`, pushes, and reports a preview
link. If remote Markdown images remain and `--save-images` is omitted, the plugin
asks for a `yes`/`no` decision before writing.

### Download your first video

```text
/save-video https://example.com/post-with-video
/save-video https://example.com/a https://example.com/b --to ~/Movies/clips
```

## Usage

`/webclip <url|webclip_id> [flags]` accepts exactly one public `http://` or
`https://` URL, or one `webclip_id` (64 hex characters, `sha256:` prefix
optional). A `webclip_id` target requires `--favorite` or `--unfavorite`.

### Command and flags

| Command | Flag | Effect |
| --- | --- | --- |
| both&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; | `--no-browser` | Disable the Playwright fallback in the extractor. |
| `/webclip` | `--refresh` | Update changed managed content, preserving the manual section. |
| `/webclip` | `--no-git` | Skip Git preflight, commit, and push for this run. |
| `/webclip` | `--save-images yes\|no\|ask` | Download images, keep remote URLs, or ask (default). |
| `/webclip` | `--favorite` / `--unfavorite` | Ensure the note carries (or does not carry) the marker. |
| `/save-video` | `--name <name>` | Override the filename stem (page title by default). |
| `/save-video` | `--to <dir>` | Override the destination; inside-vs-outside is decided by resolving it. |
| `/save-video` | `--overwrite` | Replace an existing file instead of adding a `-1` suffix. |

### Favorite marker

`favorite` is a plugin-managed boolean, written only when true. It is a
property, not a tag, so `#favorite` will not match.

`--favorite` clips a new URL, marks an existing note without fetching it, and
re-fetches only with `--refresh`. `--unfavorite` clears the marker. Refreshing or
re-clipping without a favorite flag keeps the existing marker.

```dataview
LIST FROM "inbox" WHERE favorite = true
```

Full rules, including `webclip_id` targeting: [`PLUGIN.md`](PLUGIN.md#favorite-marker).

### Images

- `--save-images ask` (default) stores a pending yes/no confirmation when the
  sanitized Markdown still has remote images.
- `--save-images yes` downloads them into `images/<article-slug>/`.
- `--save-images no` keeps the remote URLs and saves immediately.

### Save video

`/save-video <url> [<url> ...] [flags]` downloads the video(s) on a page. It
never writes a note — the two commands are independent.

HLS playlists are pre-flighted: encrypted streams (including a master-level
`EXT-X-SESSION-KEY`) and live streams are refused rather than half-downloaded.
Segments are fetched by the plugin's own SSRF-guarded client, so ffmpeg only ever
reads local files. Direct media is streamed with a byte ceiling enforced while
writing.

Every candidate is reported, and one failure never aborts the rest of the batch.
Limits: 500 MB per file, 10 URLs per run, 20 candidates per page. The default
destination is `[video].destination` (`~/Movies/Videos/webclip`); a destination
inside the vault gets a managed `.gitignore` block that is written **and
committed**, so the next `/webclip` still passes its clean-worktree preflight.

Supported in this release: generic HTML5 pages, Netease, Bilibili and YouTube.
Bilibili is capped at 720P anonymously. YouTube needs `yt-dlp`, which
`./post-install.sh` fetches for you (the official standalone binary, ~36 MB,
checksum-verified, into `~/.hermes/tools/yt-dlp/`); no Homebrew or deno needed.
It updates in place with `~/.hermes/tools/yt-dlp/yt-dlp -U`, and the command
says what to do when the binary is missing. Platform matrix, HLS
details and the storage policy:
[`skills/web-save-video/SKILL.md`](skills/web-save-video/SKILL.md).

## Configuration

`config.toml` lives in the installed plugin directory, is gitignored, and is
generated from `config.example.toml` on install. The keys worth changing first:

| Key | Default | Purpose |
| --- | --- | --- |
| `[clip].vault` | `~/Obsidian` | Vault root. Must already exist. |
| `[clip].destination` | `inbox` | Note folder inside the vault. |
| `[video].destination` | `~/Movies/Videos/webclip` | Video output; an absolute path may live anywhere, a relative one must stay in the vault. |
| `[video].max_size_mb` | `500` | Refuse a single larger file. |
| `[clip].preview_url_params` | `""` | Query parameters for the preview link; see [Opening preview links in a browser](docs/preview-link-params.md). |

Every key, with a comment on what changing it does, is in
[`config.example.toml`](config.example.toml). `lock_file` **must stay outside the
vault**, or holding it dirties the worktree. When `config.toml` is absent the
`WEB_TO_OBSIDIAN_*` environment variables are read instead; when it exists, the
environment takes no part. Values are never forwarded to the extractor process.

## Safety

- URLs reject credentials, fragments, unsafe ports, malformed hosts, and
  non-HTTP schemes; redirects are revalidated.
- Image downloads, and direct or HLS video downloads, block reserved and private
  IP ranges, pin the connection to the approved address, and reject non-default
  ports. YouTube is the exception: `yt-dlp` does its own networking, so the URL
  shape is checked before it runs and `--ignore-config`, `--no-playlist`,
  `--playlist-items 1`, `--max-filesize` plus the plugin's size and timeout
  limits apply — but address filtering and connection pinning do not.
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

## Documentation map

| Topic | Where |
| --- | --- |
| Install, configuration, usage | [`PLUGIN.md`](PLUGIN.md) |
| Compatibility surface and known limitations | [`PLUGIN.md`](PLUGIN.md#compatibility) |
| Favorite marker rules | [`PLUGIN.md`](PLUGIN.md#favorite-marker) |
| Video download rules | [`PLUGIN.md`](PLUGIN.md#save-video) |
| Network, vault, and Git safety | [`PLUGIN.md`](PLUGIN.md#network-and-content-safety) |
| Every configuration key | [`config.example.toml`](config.example.toml) |
| Extractor CLI and error codes | [`extractor/README.md`](extractor/README.md) |
| Article-clipping skill | [`skills/web-clip-to-obsidian/README.md`](skills/web-clip-to-obsidian/README.md) |
| Video skill: platforms, HLS, storage | [`skills/web-save-video/SKILL.md`](skills/web-save-video/SKILL.md) |
| Contributor guide and release workflow | [`AGENTS.md`](AGENTS.md) |
| Version history | [`CHANGELOG.md`](CHANGELOG.md) |

## License

MIT — see [`LICENSE`](LICENSE).
