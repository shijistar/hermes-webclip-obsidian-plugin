# hermes-webclip-obsidian-plugin

A **web clipping pipeline for Obsidian**: extract any public web article as
clean Markdown, save it as a dated note in your Obsidian vault, and — when the
vault is a Git repository — synchronize the note with guarded automatic commit
& push.

The repository **is** the Hermes plugin package (the `plugin.yaml` sits at the
repo root), with two more parts in the same tree:

- [`PLUGIN.md`](PLUGIN.md) — the Hermes plugin (`/webclip` command +
  `web_to_obsidian_resume_pending` tool) implementing config, safe vault
  writes, image handling, and Git synchronization.
- [`extractor/`](extractor/README.md) — a hardened Node.js extraction engine
  (Defuddle static parsing + isolated Playwright fallback) with a CLI and
  strict network policy.
- [`skill/`](skill/README.md) — a Hermes agent skill teaching the full
  clip-to-Obsidian workflow, including anti-bot fallbacks and site quirks.

## Current scope

- Static extraction with Defuddle; Playwright Chromium fallback for weak
  static pages.
- Remote HTTP(S) image references can either stay remote or be downloaded
  into the Vault.
- The default `/webclip <url>` flow asks for a follow-up yes/no decision only
  when the final sanitized Markdown still contains remote images.
- WeChat article URLs automatically fall back to curl-based extraction when
  the Node extractor is blocked.
- Login-gated pages, cookies, credentials, and password-manager integration
  are intentionally unsupported.
- Linux/WSL only: the implementation uses `fcntl` locks and POSIX process
  groups.

See [CHANGELOG.md](CHANGELOG.md) for version history.

## Quick start

Requirements: `Hermes Agent`, `Python` 3.11+, `Node.js` 18+, `Git`, `PyYAML`.

The one-shot installer (at the repo root) wires up the plugin, the extractor
npm dependencies + Playwright Chromium, and the skill symlink. It is normally
run from the *installed* plugin directory; `HERMES_HOME` and the profile are
auto-detected by walking up from the script's location to the nearest
`.hermes` directory, so no flags are needed:

```bash
cd /path/to/hermes-webclip-obsidian-plugin
./post-install.sh                     # auto-detects HERMES_HOME / profile
./post-install.sh --hermes-home /path/to/custom-hermes   # custom Hermes home
# review <profile>/plugins/webclip-obsidian/config.toml (vault, destination, ...)
# restart your Hermes gateway service from a separate shell
```

`post-install.sh` assumes the plugin is **already installed** (via
`hermes plugins install`) and by default only wires up the extractor
dependencies, Playwright Chromium, the skill symlink, and `config.toml` —
it does not re-install the plugin. Re-running it upgrades the extractor
dependencies and refreshes the skill symlink. To also run
`hermes plugins install`, pass `--install-plugin`. `HERMES_HOME` is detected
automatically (nearest `.hermes` directory above the script) or can be set
explicitly with `--hermes-home DIR`. Step-by-step manual
commands are documented in [`PLUGIN.md`](PLUGIN.md#install).

Then clip articles:

```text
/webclip https://example.com/article
/webclip https://example.com/article --save-images yes
/webclip https://example.com/article --refresh
```

Full usage, flags, and safety documentation live in
[`PLUGIN.md`](PLUGIN.md).

## Configuration

All configuration lives in `config.toml` at the repo root (vault, destination,
images directory, sync branch, lock file, pending root). See
[`PLUGIN.md`](PLUGIN.md#configuration) for the full field list, and the legacy
environment-variable fallback.

## Tests

```bash
# Node extractor
cd extractor
npm test
npm run check

# Python plugin (from repo root)
cd ..
python3 -m pytest tests/ -v
```

The automated tests use fixtures, temporary directories, and temporary Git
repositories; they do not write the configured real Vault.

## Documentation map

| Topic                           | Where                                                       |
| ------------------------------- | ----------------------------------------------------------- |
| Install / config / usage        | [`PLUGIN.md`](PLUGIN.md)                                    |
| Plugin network/Vault/Git safety | [`PLUGIN.md`](PLUGIN.md)                                    |
| Extractor CLI & error codes     | [`extractor/README.md`](extractor/README.md)                |
| Extractor network policy        | [`extractor/README.md`](extractor/README.md#network-safety) |
| Agent skill deployment          | [`skill/README.md`](skill/README.md)                        |
| Anti-bot fallbacks              | `skill/references/` (index in skill/README.md)              |
| Version history                 | [`CHANGELOG.md`](CHANGELOG.md)                              |
