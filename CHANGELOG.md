# Changelog

All notable changes to the hermes-webclip-obsidian-plugin will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## 2026-10-24

### Added

- **Favorite marker**: clipped notes can be marked with a plugin-managed
  `favorite: true` frontmatter field, at clip time or later:
  - `/webclip <url> --favorite` / `--unfavorite` set or clear the marker while
    clipping or refreshing;
  - `/webclip <url> --favorite-only` / `--unfavorite-only` update an existing
    note without calling the extractor or touching the article body.
- Marker-only operations patch only the `favorite` frontmatter line, preserve
  the managed body and manual section byte-for-byte, and fail closed for
  unknown or ambiguous URLs. Only notes with a `webclip_id` plus the
  managed/manual boundaries are eligible. Both marker-only flags accept
  `--no-git` to skip Git preflight/commit/push.
- Refreshing or re-clipping without a favorite option preserves the marker
  already stored on the note; clearing it requires an explicit
  `--unfavorite` / `--unfavorite-only`.
- A change limited to `favorite` is applied without `--refresh`; article-body
  changes still require `--refresh`.
- Pending image confirmations carry the chosen marker state into
  `resume_pending()`.
- Marker-only commits use `favorite: <title>` / `unfavorite: <title>`.
  Plugin version bumped 0.15.4 → 0.16.0, skill version 1.4.5 → 1.5.0.

### Tests

- Added a requested-state × persisted-state matrix regression test (true,
  false, absent) through the real service path, asserting the final marker and
  a byte-identical body for every combination.

### Documentation

- Documented how to use the marker in Obsidian: Dataview
  (`LIST FROM "Inbox" WHERE favorite = true`), property search, and Bases
  filters, with an explicit note that it is a boolean property and not a tag.

## 2026-10-21

### Changed

- **Documentation language policy**: added a mandatory rule (AGENTS.md §3)
  requiring all documentation, code comments, and commit messages to be
  written in English. Chinese literals that are part of the code itself
  (regex literals matching site UI strings, error-message strings) are the
  only exception.
- **Comments and docs translated to English**: the Chinese comments in
  `extractor/src/extractor.mjs` and `web_to_obsidian.py`, plus Chinese prose
  in the skill references and CHANGELOG, were rewritten in English. Chinese
  UI-string literals (e.g. `打开网易新闻`, `特别声明`) and user-input trigger
  phrases (e.g. `剪藏`) are preserved because the code depends on them.
  Plugin version bumped 0.15.3 → 0.15.4, skill version 1.4.4 → 1.4.5.

### Fixed

- **WeChat article author parsing**: Newer WeChat pages write author as
  ``var nickname = htmlDecode("...")`` instead of the old format
  ``var nickname = "..."``. The parser now tries both formats, so the
  author field is correctly extracted regardless of the page version.

## 2026-10-19

### Improved

- **Netease `/news/v/` video extraction now captures author, cover image, and
  publish date** — the curl-based video parser (`_parse_netease_video_html`)
  previously only extracted the title and stream URL. It now also:
  - Reads the author from `<div class="s-name">` (video pages don't have the
    JSON `"nickname"` field used by article pages)
  - Extracts the cover image URL from `.poster[data-bg]`
  - Parses the publish date from the date segment in the cover URL
    (e.g. `20261008` → `2026-10-08`)
  - Embeds the cover image as `![video cover](...)` in the markdown note
  Plugin version bumped 0.15.1 → 0.15.2.

## 2026-10-14

### Added

- **Netease video short links (`news/sv/`) are now supported** — the plugin
  detects `c.m.163.com/news/sv/` URLs, fetches the page via curl, extracts
  the video title and m3u8/mp4 stream URL, and generates a markdown note with
  an embedded `<video>` tag. Falls back gracefully when the stream URL cannot
  be extracted. Plugin version bumped 0.14.1 → 0.15.0.

### Fixed

- **Netease `/news/v/` video short links are now recognized** — the video
  URL detection regex was extended from `/news/sv/` to `/news/(?:sv|v)/` so
  the newer video short link format also falls through to the curl-based
  video extractor. Plugin version bumped 0.15.0 → 0.15.1.

- **Empty `<video>` tags no longer pass the quality gate** — when a page
  contains a `<video>` element but all `src` attributes are empty (e.g.
  Netease `/news/v/` pages where Defuddle renders an empty `<video>` stub),
  `meetsQualityGate()` now returns `false` so the caller falls back to
  browser rendering or curl extraction instead of saving a broken embed.
  Extractor version bumped 0.4.0 → 0.4.1.

## 2026-10-10

### Fixed

- **`post-install.sh` auto-installs PyYAML** — Hermes upgrades may switch the
  Python interpreter (e.g. 3.14.x) without carrying over site-packages, causing
  `ModuleNotFoundError: No module named 'yaml'` on the next clip. The installer
  now installs PyYAML (idempotently) before npm install, and a `requirements.txt`
  is added for version pinning. Plugin version bumped 0.14.0 → 0.14.1.

- **Netease image "打开网易新闻 查看更多图片" (Netease UI string) tip is stripped from clipped articles** —
  every Netease (`163.com`) figure is wrapped with an app deep-link tip
  (`<div class="js-open-newsapp">打开网易新闻 查看更多图片</div>`) that Defuddle
  previously carried into the Markdown. `extractHtml()` now removes the
  innermost element matching that exact tip (on `163.com` hostnames only),
  preserving the surrounding `<figure>`/`<img>` and the trailing
  "特别声明" (Netease disclaimer UI string). Covered by two new extractor tests
  (`extractHtml strips the Netease … app tip but keeps the figure and
  disclaimer`, `extractHtml leaves the Netease tip untouched on non-Netease
  hostnames`). Extractor version bumped 0.3.0 → 0.4.0.

## 2026-09-07

### Added

- **`post-install.sh --install-plugin` refresh preserves user `config.toml`** —
  when the plugin directory already exists, `--install-plugin` now performs a
  forced refresh (`hermes plugins install --force`): the existing `config.toml`
  is backed up first, the plugin dir is replaced, and the backup is restored
  afterwards. Backup / reinstall / restore failures abort with a clear error
  and keep the backup for manual recovery; first-time installs are unchanged.
  Covered by new `tests/test_post_install.py` (first-time bootstrap, refresh
  preservation, refresh without user config, backup-failure abort,
  restore-failure with retained backup). Plugin version bumped 0.13.0 → 0.14.0.

## 2026-09-06

### Changed

- **`post-install.sh` supports a custom Hermes home via `--hermes-home DIR`** —
  when the flag is given it is used verbatim as `HERMES_HOME` (custom home);
  otherwise the nearest `.hermes` directory above the script is used. The
  profile is derived per a fixed rule: the `profiles/<name>/` path segment
  when present and existing, else the single profile under
  `HERMES_HOME/profiles/` if there is exactly one, else `HERMES_HOME` itself
  (default profile). Plugin version bumped 0.12.0 → 0.13.0.
- **`post-install.sh` auto-detects Hermes paths by walking up to `.hermes`** —
  the script no longer needs `--hermes-home` / `--profile`: it walks up from
  its own location to the nearest `.hermes` directory for `HERMES_HOME`, and
  derives the profile from a `profiles/<name>/` path segment when present
  (defaulting to `HERMES_HOME` itself otherwise). `PLUGIN_DIR` and
  `SKILLS_DIR` are then built from those. Plugin version bumped 0.11.0 →
  0.12.0.
- **`install.sh` defaults to not re-installing the plugin** — the plugin is
  installed once via `hermes plugins install`, then `install.sh` wires up the
  extractor npm dependency, Playwright Chromium, the skill symlink, and
  `config.toml`. Running `hermes plugins install` from the script now requires
  the explicit `--install-plugin` flag (replaces `--skip-plugin-install`).
  Plugin version bumped 0.10.0 → 0.11.0.
- **Extractor restored as a published npm package** — reverses the earlier
  "bundled-only" decision: `@tiny-codes/web-clip-extractor` is published again
  (version 0.3.0, metadata updated to the renamed repository) and the plugin
  consumes it via a repo-root `package.json` dependency; the
  `npm-publish.yml` workflow is kept. Runtime resolution is
  npm-installed-first (`plugin_root/node_modules/...`), with the bundled
  `extractor/` subdirectory and the legacy sibling as fallbacks. `install.sh`
  installs the npm dependency and runs `npx playwright install chromium`
  explicitly (an npm dependency's `prepare` hook is skipped under npm's
  default allow-scripts policy). Plugin version bumped 0.9.0 → 0.10.0.
- **Plugin renamed to `webclip-obsidian`** — the manifest name (and thus the
  installed plugin directory `plugins/webclip-obsidian`, replacing
  `plugins/web-to-obsidian`) changed to match the repo's branding; install
  paths in `install.sh`, `after-install.md`, `PLUGIN.md`, READMEs, the skill
  docs, and the extractor User-Agent were updated accordingly. Plugin version
  bumped 0.8.0 → 0.9.0.
- **Plugin package moved to the repository root** — `plugin.yaml`, `__init__.py`,
  `web_to_obsidian.py`, `config.toml`, `config.example.toml`, `install.sh`,
  `after-install.md`, and `tests/` now live at the repo root, which **is** the
  plugin package. `hermes plugins install` clones the whole repository, so the
  installed copy retains `extractor/`, `skill/`, and the config example; the
  one-shot installer resolves the skill and config example from its own
  directory and no longer needs `--repo`/`$REPO_ROOT`. Plugin version bumped
  0.7.0 → 0.8.0; skill 1.4.1 → 1.4.2 for the updated paths/install flow.
- **Plugin README preserved as `PLUGIN.md`** — the former `plugin/README.md`
  was migrated to `PLUGIN.md` at the repo root (not discarded); root
  `README.md`, `extractor/README.md`, `AGENTS.md`, and skill docs now link to
  it.
- **Extractor is bundled, not published** — the `.github/workflows/npm-publish.yml`
  workflow was removed and the root `package.json` npm-dependency was dropped.
  The extractor is resolved at `<plugin_root>/extractor` (bundled subdirectory
  first; legacy npm-installed copy and source sibling remain as fallbacks).
  `extractor/package.json` is marked `private` and publish metadata removed.
- **Playwright Chromium installs via the extractor `prepare` hook** —
  `extractor/package.json` already ran `npx playwright install chromium` in
  `prepare`; `install.sh` now runs `npm install` inside `extractor/` (where the
  hook fires) instead of a separate explicit Playwright step. CI uses
  `npm ci --ignore-scripts` so tests do not download browsers.
- **`__init__.py` deferred-imports `web_to_obsidian` inside `register()`** —
  the repo root doubles as a Python package directory, so top-level relative
  imports broke bare `import` from pytest/REPL; imports moved into
  `register()` where Hermes provides the package context.

## 2026-09-05

### Fixed

- **`pending_root` from config now actually applies** — `ClipConfig` carries `pending_root` (read from `config.toml` via `WEB_TO_OBSIDIAN_PENDING_ROOT`), and `_run_locked()` / `_resume_locked()` use `config.pending_root` instead of the hard-coded default. Removed the now-unused `_pending_root()` helper. Covered by new unit tests (env, TOML, default-outside-vault).

### Changed

- **Skill guidance de-risked for data safety and injection** — removed the blanket `git checkout -- .` batch-cleanup advice in favor of inspect-dirty-worktree + targeted cleanup of generated paths only (`inbox/`, `images/`); batch scripts now pass URL/image flags as arguments instead of interpolating them into Python source; Chrome cleanup stops only the debug instance by PID/`--user-data-dir` instead of all `chrome` processes.
- **Docs aligned with the restructured repo** — `skill/SKILL.md` config path now points at `plugin/config.toml` (tracked, not `.gitignored`) and the deploy symlink targets `plugin/`; `extractor/README.md` documents `npx playwright install chromium`; anti-bot fallback docs mark `author`/`published`/`description`/`site`/`markdown` as required (may be empty).
- **CHANGELOG merged the two `2026-07-26` headings** into one.
- **Plugin slash command renamed `/clip` → `/webclip`** — avoids colliding with the `clip` skill's auto-generated `/clip` command in Hermes (skills scan only skips built-in commands, not plugin commands). Plugin version bumped 0.5.1 → 0.6.0; skill 1.4.0 → 1.4.1; docs, error strings, and the plugin registration test updated. The `[clip]` config section name and `webclip_id` field are unchanged.
- **Plugin-local npm extractor install** — `plugin/` now ships a `package.json` declaring `@tiny-codes/web-clip-extractor` (the published npm package), so a plugin install can pull the matching Node.js extractor into `plugin/node_modules` and upgrade it in lockstep with the plugin. `_extractor_dir()` prefers the plugin-local npm package, falling back to the source-repo sibling and then the legacy subdirectory. `.gitignore` ignores `plugin/node_modules/` and `plugin/package-lock.json`. Plugin version bumped 0.6.0 → 0.7.0; covered by 3 new resolution-order unit tests (npm-preferred / sibling fallback / legacy fallback).
- **One-shot installer + after-install guide** — `plugin/install.sh` (ships with `hermes plugins install`) wires up the extractor npm package (with Playwright Chromium), the skill symlink, and config bootstrap in one idempotent script (`--hermes-home` / `--profile` / `--repo` flags). `plugin/after-install.md` is printed by `hermes plugins install` and tells users to run `./install.sh`. READMEs and AGENTS.md document the new flow.

## 2026-09-04

### Added

- **AGENTS.md project working guide** — repo-level guide for humans and AI agents: module map, directory layout, build/test commands, versioning rules, Git workflow, safety invariants, and two mandatory rules (unit tests required for features/fixes; version bumps + CHANGELOG updates required for behavior changes).
- **`web-clip-to-obsidian` skill descriptions & reference keywords clarified** — `skill/SKILL.md` and `skill/README.md` updated for clarity.
- **`config.toml` `pending_root` support** — `ClipConfig.from_file()` now accepts `pending_root`; `config.toml`/`config.example.toml` enable `lock_file` and add `pending_root`. All 6 env vars (`VAULT`, `DEST`, `IMAGES`, `SYNC_BRANCH`, `LOCK_FILE`, `PENDING_ROOT`) now have `config.toml` equivalents — single source of truth.
- **`markdown` field restored as validated payload input** — `source_markdown` is again taken from the validated `markdown` field (previously extracted separately in `render_note`, which excluded it from frontmatter).

### Changed

- **Plugin files restructured into `plugin/` subdirectory** — `__init__.py`, `web_to_obsidian.py`, `plugin.yaml`, `config.toml`, `config.example.toml` moved from the repo root into `plugin/`. `tests/conftest.py` injects `plugin/` into `sys.path`; `tests/test_plugin.py` points at `plugin/__init__.py`.
- **Extractor located as sibling of the plugin package** — `run_extractor()` now resolves `extractor/` via `plugin_root.parent / "extractor"` (with a legacy fallback for `plugin_root/extractor`), so the Hermes plugin works after the restructure.
- **READMEs split by submodule** — added `plugin/README.md`, `extractor/README.md`, `skill/README.md`; rewrote root `README.md` as a project overview with the new repository layout and quick start.
- **CHANGELOG switched to date headings** — entries now use `## YYYY-MM-DD` instead of `## [<version>] - <date>`; module versions (plugin.yaml, package.json, SKILL.md) are independent of the CHANGELOG.

## 2026-09-03

### Added

- **Web Clip skill fully migrated to repo** — the `web-clip-to-obsidian` skill (SKILL.md v1.2.0 + 10 reference documents) is now version-controlled in `skill/` for git-based history and cross-profile sharing.
- 10 skill reference documents covering: anti-bot fallback (web_extract), batch processing, git sync testing, GitHub private blob URLs & image mode, Netease embedded-state author extraction, Netease placeholder & video links, pending-resume fallback, profile skill vs source-repo sync, repo-linked maintenance, Zhihu cookie & scraper diagnostics.

### Changed

- Skill version bumped from 1.1.0 to 1.2.0.
- Profile skill directory can now be a symlink to `skill/` instead of a standalone copy, ensuring single source of truth.

## 2026-09-02

### Added

- Bumped `web-to-obsidian-extractor` subpackage from `0.1.0` to `0.2.0`.

### Fixed

- **Lazy-loaded image extraction** — Netease (`c.m.163.com`) and similar sites render images with a placeholder `src` (`empty.png`) and the real URL in `data-echo` / `data-src` / `data-original`. The extractor now resolves the real lazy-loaded image URL (preferring `data-echo` → `data-src` → `data-original` → `data-lazy-src`, falling back to the original `src`) so clipped articles reference the actual image instead of the placeholder. Covered by `extractor/test/fixtures/netease-lazy-image.html` and a new unit test (full suite 23/23 passing).

## 2026-08-31

### Fixed

- **Netease author/published fallback** — `c.m.163.com` article pages do not expose author/published in standard meta tags or JSON-LD; the metadata lives only in the embedded `window.__INITIAL_STATE__` JSON (`main.source` / `main.sourceinfo.tname` / `main.ptime`). The extractor now falls back to that embedded state (scoped to `163.com` hostnames) when Defuddle returns no author or published value.

## 2026-07-26

### Added

- **WeChat article curl fallback** — when Node.js extractor fails for `mp.weixin.qq.com` URLs, automatically falls back to curl-based extraction: fetches raw HTML, parses metadata (title, author, publish time) and body (`js_content` div) via regex, converts HTML to Markdown. No manual intervention needed.
- `_is_wechat_url()`, `_fetch_wechat_html()`, `_parse_wechat_html()`, `_wechat_html_to_markdown()`, `_count_words()`, `run_extractor_with_fallback()` functions
- 11 unit tests for WeChat extraction pipeline
- `commit_message` parameter to `GitSync.finalize()` — commit messages now include the article title (e.g. `clip: <title>`) instead of a generic `clip: save web article`
- `skill/` directory with Hermes skill documentation for web-clip-to-obsidian workflow

### Changed

- `_run_locked()` now calls `run_extractor_with_fallback()` instead of `run_extractor()` directly

## 2026-07-25

### Added

- **Two-phase image confirmation workflow** — `/clip` with remote images now prompts user to confirm download via `web_to_obsidian_resume_pending` tool (`--save-images yes|no|ask`, default: `ask`)
- **Pending state management** — stores intermediate state in `~/.hermes/workspace/cache/webclip-obsidian/` with 1-hour TTL, single-active constraint, and vault/config binding
- **SSRF protection** for image downloads — full RFC reserved IP range blocking, redirect pinning (max 6 hops), non-default port rejection, IDNA hostname validation, Content-Type `image/*` enforcement
- **Code-aware markdown sanitization** — `sanitize_markdown` and `find_remote_images` skip fenced code blocks, inline code spans, and indented code lines
- **Managed note rendering** with YAML frontmatter (title, url, author, site, description, keywords, tags, extraction_method, word_count, content_hash, image_mode, etc.)
- **Git synchronization** — auto commit + push with post-commit verification, branch safety checks, and note preservation on Git failures
- **Vault lock** — cross-process non-blocking lock to prevent concurrent writes
- **CLI flags** — `--refresh`, `--no-browser`, `--no-git`, `--save-images`
- **Image localization** — downloads remote images to vault `images/` directory, rewrites markdown references, cleans up on failure
- Secure web clipper extraction pipeline with Node.js extractor, Exa fallback, and browser fallback

### Fixed

- Sanitize injected heading title to prevent XSS via article titles
- Refresh managed note semantics — re-clip updates existing notes correctly
- Allow prevalidated extractor payloads to pass through validation

### Security

- SSRF protection blocks private/internal network addresses on image downloads
- HTML dangerous tag sanitization (script, iframe, object, embed, form, etc.)
- Credential-like marker detection in extracted content
- Dangerous URL scheme blocking (javascript, vbscript, file, obsidian, data)
- Knowledge base content hash verification against known secret patterns
