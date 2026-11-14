# web-clip-to-obsidian skill

The `skill/` directory is a Hermes agent skill that teaches an agent how to
use the webclip-obsidian plugin: extract an article, apply the default image
policy (remote unless the user asks otherwise), save a dated Markdown note, and
commit & push it to the Obsidian vault Git.

- `SKILL.md` — frontmatter (name, description, version) plus the full workflow:
  plugin location/config, invocation patterns, pending-state flow, commit
  message, filename date prefix, and a large pitfalls section.
- `references/` — deep-dive documents for site quirks and fallback workflows
  (see index below).

## Version

`SKILL.md` frontmatter `version` is the skill version (currently `1.10.0`).
The plugin version is tracked separately in `../plugin.yaml` and
`../CHANGELOG.md`.

## Deploy to a Hermes profile

The plugin registers the skill from its own `register()`, so it resolves as
`webclip-obsidian:web-clip-to-obsidian` as soon as the plugin is enabled. The plugin
directory itself is still linked from the repo during development
(`~/.hermes/profiles/<profile>/plugins/webclip-obsidian -> <repo>`), and its name must
match `plugins.enabled` in `config.yaml`.

## Reference index

| File                                                   | Covers                                                                                                |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| `references/anti-bot-fallback-web-extract.md`          | When the Node extractor is blocked (Zhihu, Doubao), fall back to `web_extract` + `_persist_article()` |
| `references/batch-processing.md`                       | Proven workflow for clipping 10+ articles sequentially                                                |
| `references/browser-extraction-ladder.md`              | Which extraction path to take, and the platform split for CDP                                          |
| `references/git-sync-testing-pattern.md`               | Git safety tests require an upstream branch                                                           |
| `references/github-private-blob-url-and-image-mode.md` | GitHub blob preview URLs and `image_mode` metadata semantics                                          |
| `references/input-normalization.md`                    | Share-sheet pastes to clean URLs, per site; `webclip_id` canonicalization rules                        |
| `references/netease-embedded-state-author.md`          | Netease author/published extraction from embedded JSON state                                          |
| `references/netease-placeholder-and-video-links.md`    | Netease `empty.png` placeholder images and anti-scrape video short links                              |
| `references/pending-resume-fallback.md`                | Outstanding/stale pending-state entries and fallbacks                                                 |
| `references/platforms/linux-macos.md`                  | Local Chrome + CDP on Linux and macOS                                                                  |
| `references/platforms/wsl.md`                          | Borrowing a Windows Chrome session from WSL                                                            |
| `references/repo-linked-maintenance.md`                | Maintenance rules for working on this plugin from its source repo                                      |
| `references/wechat-curl-extraction.md`                 | WeChat curl fallback, author field format and the CAPTCHA wall                                        |
| `references/zhihu-cookie-and-scraper-diagnostics.md`   | Layered Zhihu cookie/fetch/browser diagnostics                                                        |

## Trigger phrases

The skill activates on intent like "clip to obsidian" /
"save to vault" / "web clip" / "抓取到obsidian" / "剪藏" / "抓取<url>" (Chinese phrases are user-input
triggers), or when a URL is shared with the
intent to archive it.
