---
name: webclip-maintenance
description: 'Maintain the webclip-obsidian plugin: map, tests, state.'
version: 1.0.0
author: Hermes Agent / Fengbao Li
metadata:
  hermes:
    tags: [obsidian, web-clip, maintenance, testing, plugin]
---

# Webclip Maintenance

Maintain the `webclip-obsidian` plugin itself — its code and its release
surface, not the user-facing clipping workflow. Clipping an article is
`webclip-obsidian:web-clip-to-obsidian`; downloading a video is
`webclip-obsidian:web-save-video`.

## When to Use

- Changing, reviewing or debugging code in `hermes-webclip-obsidian-plugin`:
  extraction, sanitization, image localisation, vault writes, Git sync, video.
- A clipping behaviour is wrong and you need to know which module owns it and
  which test proves it.
- Deciding whether something is a bug or documented behaviour.

## Pipeline, in order

```text
command (/webclip, /save-video)
  -> _webclip/config.py     options, config.toml, flag parsing
  -> _webclip/extract.py    node extractor call, JSON contract
  -> _webclip/markdown.py   sanitization, frontmatter, managed markers
  -> _webclip/images.py     remote image fetch and localisation
  -> _webclip/notes.py      note discovery, identity, refresh decisions
  -> _webclip/git_sync.py   vault lock, staging, commit, push
  -> _webclip/report.py     receipt text returned to chat
```

Cross-cutting modules: `_webclip/netguard.py` (SSRF-safe HTTP),
`_webclip/pending.py` (image-confirmation state), `_webclip/paths.py`
(filename and Vault confinement), `_webclip/sites.py` (bounded retry plus
WeChat/Netease site fallbacks), `_webclip/video/` (the `/save-video`
subsystem), `extractor/src/` (Node.js: `network-policy.mjs`, `verify.mjs`,
`error-payload.mjs`, `video-collect.mjs`, and the Playwright fallback inside
`extractor.mjs`).

## Tests you must run

```bash
python3 -m pytest tests/ -v     # all plugin suites
cd extractor && npm test        # only when extractor/src changed
cd extractor && npm run check   # only when extractor/src changed
```

The registration suites count what is registered; they do not settle for "no
exception". A new skill or command must extend `tests/test_plugin.py`
accordingly, including the damaged-file case, where the broken skill is still
registered with empty frontmatter.

## The twelve ingestion checks, mapped here

The class-level rules live in the `web-ingestion-asset-safety` skill (twelve
checks plus pitfalls; a local skill, not bundled with this plugin). This table
says where this plugin implements each one and what proves it;
`references/implementation-status.md` records the gaps.

| # | Check | Where it lives | Proof |
| --- | --- | --- | --- |
| 1 | Remote asset fetch policy | `netguard.py`, `images.py` | `tests/test_netguard.py`, `tests/test_security_regressions.py` |
| 2 | Sanitization and image detection | `markdown.py` | `tests/test_security_regressions.py` |
| 3 | Git transaction path set | `git_sync.py` | `tests/test_integration.py` |
| 4 | Failure cleanup | `images.py`, `service.py` | `tests/test_integration.py`, `tests/test_security_regressions.py` |
| 5 | Pending identity binding | `pending.py` | `tests/test_integration.py` |
| 6 | Video quality gate | `_webclip/video/`, `extractor/src/extractor.mjs`, `extractor/src/video-collect.mjs` | `extractor/test/extractor.test.mjs`, `extractor/test/video-collect.test.mjs` |
| 7 | Safe HTML subset survives | `markdown.py` | `tests/test_security_regressions.py` |
| 8 | Plugin-managed frontmatter keys | `notes.py` | `tests/test_web_to_obsidian.py` |
| 9 | Content-addressed identity | `markdown.py`, `notes.py`, `urls.py` | `tests/test_web_to_obsidian.py` |
| 10 | Output is an injection surface | `report.py` | `tests/test_web_to_obsidian.py` |
| 11 | Shared destination config | `config.py` | `tests/test_video_config.py` |
| 12 | A 200 is not success; classify the status | `extract.py`, `extractor/src/error-payload.mjs`, `extractor/src/verify.mjs` | `tests/test_failure_classification.py`, `extractor/test/` |

## Truth hierarchy

1. `PLUGIN.md` — compatibility surface, frozen markers, known limitations.
2. `AGENTS.md` — version, tag and release rules; language rules; test commands.
3. `references/implementation-status.md` — implemented, partial, absent, out of
   scope, and the WSL2 and refresh positions.
4. The tests — the only claim of "it works" that counts.

Do not restate line-level facts (paths, error strings, cache layout) in the
class-level `web-ingestion-asset-safety` skill; point here instead. Version
bumps, tags and the GitHub release follow `AGENTS.md`, not this file.
