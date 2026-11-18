# AGENTS.md

Working guide for humans and AI agents contributing to **hermes-webclip-obsidian-plugin** — a
web clipping pipeline that extracts public articles as clean Markdown, saves
dated notes into an Obsidian vault, and synchronizes them via guarded Git.

## Modules

| Path         | What it is                                                                 | Key files                                                                                                         |
| ------------ | -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| repo root    | Hermes plugin package: config, safe vault writes, image handling, Git sync | `__init__.py`, `web_to_obsidian.py`, `plugin.yaml`, `config.example.toml`                          |
| `extractor/` | Hardened Node.js extraction engine (Defuddle static + Playwright fallback) | `src/cli.mjs`, `src/extractor.mjs`, `src/network-policy.mjs`, `package.json`                                      |
| `skills/`    | Hermes agent skills registered by the plugin (clip + video)                | `web-clip-to-obsidian/SKILL.md`, `web-save-video/SKILL.md`                                                        |
| `tests/`     | Python plugin test suites                                                  | `conftest.py`, `test_web_to_obsidian.py`, `test_integration.py`, `test_plugin.py`, `test_security_regressions.py` |

The repo root **is** the plugin package: `plugin.yaml`, `__init__.py`, and
`web_to_obsidian.py` live at the root, and the extractor is a bundled
subdirectory `extractor/`. `hermes plugins install` clones the whole repository,
so the installed copy keeps the extractor and skill. At runtime the plugin
locates the extractor via `plugin_root / "extractor"` (with legacy fallbacks
for previously npm-installed copies).

## Directory layout

```
hermes-webclip-obsidian-plugin/
├── AGENTS.md
├── CHANGELOG.md                # Version history
├── README.md                   # project overview
├── PLUGIN.md                   # plugin install / config / usage / safety
├── __init__.py                 # entry point: /webclip + resume tool
├── web_to_obsidian.py          # façade: registers `_webclip` and re-exports the public surface
├── _webclip/                   # implementation modules, layered (no import cycles)
│   ├── core.py                 # errors, limits, shared constants, text helpers
│   ├── proc.py                 # bounded subprocess execution
│   ├── urls.py                 # URL validation, normalisation, preview links
│   ├── report.py               # ClipResult family and the summary receipt
│   ├── article.py              # extractor payload validation
│   ├── paths.py                # path containment guards, filename sanitising
│   ├── fsutil.py               # atomic file replacement
│   ├── config.py               # options, config loading, argument parsing
│   ├── extract.py              # Node extractor wrapper
│   ├── git_sync.py             # VaultLock and GitSync
│   ├── markdown.py             # markdown sanitation and note rendering
│   ├── images.py               # SSRF guards, image downloads, localisation
│   ├── notes.py                # note discovery, frontmatter, favourite markers
│   ├── pending.py              # image-confirmation state
│   ├── netguard.py             # SSRF-safe pinned HTTP for media downloads
│   ├── sites.py                # WeChat / Netease fallbacks
│   ├── video/                  # /save-video: adapters, probe, downloads, naming, store
│   └── service.py              # ClipService, build_handler, build_resume_tool
├── plugin.yaml                 # plugin metadata + version
├── post-install.sh                  # one-shot installer (ships with hermes plugins install)
├── config.toml                 # local config (gitignored; generated from config.example.toml)
├── config.example.toml         # Configuration template
├── docs/                       # user-facing reference docs
│   └── preview-link-params.md  # opening preview links in a browser
├── after-install.md            # Follow-up steps shown by `hermes plugins install`
├── tests/                      # python plugin test suites (pytest)
├── extractor/                  # node.js content extraction engine
│   ├── src/cli.mjs             # CLI entry point
│   ├── src/extractor.mjs       # static + Playwright extraction
│   ├── src/network-policy.mjs
│   ├── test/                   # node --test suites + fixtures
│   ├── README.md               # extractor README
│   └── package.json            # extractor version
└── skills/                     # Hermes agent skills, registered by the plugin
    ├── web-clip-to-obsidian/
    │   ├── SKILL.md            # workflow instructions + version in frontmatter
    │   ├── README.md
    │   └── references/         # site quirks & fallback deep-dives
    └── web-save-video/
        ├── SKILL.md            # /save-video workflow + version in frontmatter
        └── references/         # platform matrix, discovery, HLS, naming, storage
```

## Build & test

### Python plugin

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/ -v
```

- `tests/conftest.py` injects the repository root (its parent) into
  `sys.path` so `import web_to_obsidian` resolves to `web_to_obsidian.py`.
- Test suites: core unit tests (`test_web_to_obsidian.py`), real Git/vault
  integration (`test_integration.py`), plugin registration
  (`test_plugin.py`), and security regressions (`test_security_regressions.py`).

### Node extractor

```bash
cd extractor
npm ci --ignore-scripts   # first time only (locked deps)
npm test                  # node --test
npm run check             # node --check on each src module
```

The extractor is published to npm as `@tiny-codes/web-clip-extractor`; the
plugin consumes it as a dependency. In a source checkout the bundled
`extractor/` directory doubles as the package (run `npm install` there to
install deps; `npm install` alone also runs the package's `prepare` hook,
`npx playwright install chromium`).

## Versioning rules

The project tracks module versions in **three** places. The CHANGELOG uses
**date headings** (`## YYYY-MM-DD`), not version numbers, so it is not a
version source:

| Place                    | Field                  |
| ------------------------ | ---------------------- |
| `plugin.yaml`            | `version`              |
| `extractor/package.json` | `version`              |
| `skills/*/SKILL.md`      | frontmatter `version`  |

Read the current version from those fields; this table records where a version
lives, not what it is. Mirroring the numbers here would only add a second place
to forget. Module versions are independent of each other and of the CHANGELOG;
there is no requirement that they match a changelog heading.

## Mandatory rules

### 1. Unit tests are required

Every **new feature** or **bug fix** MUST ship with unit tests covering the
changed behavior:

- Python changes → add/update tests under `tests/` (choose the suite by
  concern: core logic, integration, plugin registration, or security
  regression).
- Node extractor changes → add/update tests under `extractor/test/`.
- Security-relevant changes → add a regression test in
  `tests/test_security_regressions.py` or
  `extractor/test/security-regressions.test.mjs`, even if the change looks
  like a pure refactor.

Do not merge a change whose tests do not pass in the local run.

### 2. Version bumps + CHANGELOG updates are required

Any **new feature or behavior change** MUST:

1. bump the `version` of every module the change touches
   (`plugin.yaml`, `extractor/package.json`, `skills/*/SKILL.md` —
   bump only what the change actually touches);
2. add a `## YYYY-MM-DD` entry in `CHANGELOG.md` (use today's date) describing
   the change, under the existing changelog conventions. If an entry for that
   date already exists, append the change to it (multiple changes on the same
   date share one heading).

Pure docs/refactor changes that do not alter behavior do not require a version
bump, but a CHANGELOG entry is encouraged when user-visible.

### 2.1 Git tags for module versions

Every module version bump MUST also create a git tag of the form
`<type>@<version>` — `skill@<name>@<version>` for skills — on the merge commit
in `master`, so each published module version is addressable by tag:

| Module    | Tag format                     | Example                      |
| --------- | ------------------------------ | ---------------------------- |
| plugin    | `plugin@<version>`             | `plugin@1.0.0`               |
| extractor | `web-clip-extractor@<version>` | `web-clip-extractor@1.0.0`   |
| skill     | `skill@<name>@<version>`       | `skill@web-save-video@1.0.4` |

- **Skill tags carry the skill name.** The flat `skill@<version>` form was
  ambiguous once a second skill existed: `skill@1.13.0` and `skill@1.0.3` are
  different skills, and nothing in the tag says which.
- **Historical flat tags stay as they are.** Do not delete or re-point them; their
  owner is decided by the commit they sit on. `git tag -l 'skill@*'` lists both
  forms, so a script matching skill tags must match the new full shape
  (`skill@<name>@<version>`) rather than the prefix alone.

- The version value comes from the module's version field
  (`plugin.yaml`, `extractor/package.json`, `skills/*/SKILL.md` frontmatter).
- Create the tag only for modules whose version actually changed in the
  commit.
- **Tags MUST be created on `master` after the PR is merged**, not on the
  feature branch. Workflow: push feature branch → create PR → wait for merge
  → checkout `master` → pull latest → create tag on the merge commit → push
  tag to remote.
- If a tag with the same name already exists (e.g. after a rebase or a
  same-version re-publish), replace it: delete the old tag and re-create it
  on the new commit (local rewrite; see also Git workflow below on force
  pushes — tag replacement is allowed, do not force-push branches).

### 2.2 Date tags and their GitHub releases

When a new `## YYYY-MM-DD` entry is added to `CHANGELOG.md`, create a date tag
of the form `vYYYY-MM-DD` on the merge commit in `master` (matching the
changelog heading, e.g. `v2026-09-06`) **and** the GitHub release of the same
name. The tag marks the repository state at the end of that date's release
history; the release is what makes that entry readable without cloning.

- **Both are created on `master` after the PR is merged**, not on the feature
  branch.
- If a tag for that date already exists, **delete the old tag and create the
  new one** pointing at the latest merge commit (a date may have multiple
  version changes; only the newest tag survives). Re-point the release with it
  — see [Re-pointing a date tag](#re-pointing-a-date-tag).
- A date tag without a release is an incomplete release: the entry is invisible
  from the repository's Releases page and cannot be subscribed to.

Release fields:

| Field              | Value                                                                         |
| ------------------ | ----------------------------------------------------------------------------- |
| tag                | `vYYYY-MM-DD`; it must already exist, which `--verify-tag` enforces           |
| name               | the tag itself, e.g. `v2026-11-18`                                            |
| body               | the date's `CHANGELOG.md` section without its heading, plus the compare link  |
| draft / prerelease | `false`                                                                       |

```bash
# notes/vYYYY-MM-DD.md holds the changelog section for that date, heading removed
gh release create "v$DATE" --title "v$DATE" --notes-file "notes/v$DATE.md" --verify-tag
```

The compare link points at the **previous date that has a tag**, not at the
previous line of the changelog: the changelog contains dates with no tag, and a
compare against a missing tag renders as an error.

```
**Full Changelog**: https://github.com/<owner>/<repo>/compare/v<PREV>...v<DATE>
```

The oldest date tag has no predecessor — omit the link there rather than
comparing against the first commit, which would list the entire history.

Verify every release after creating it; a wrong `name` or an accidental draft
is only visible from the API:

```bash
gh release view "v$DATE" --json tagName,name,isDraft,isPrerelease
```

`name` MUST equal the tag, and neither flag may be `true`.

#### Re-pointing a date tag

A re-pointed tag must not leave a stale release behind. Delete the release
first — `--cleanup-tag=false` keeps the tag alive for the re-point — then
recreate both:

```bash
gh release delete "v$DATE" --yes --cleanup-tag=false
git tag -d "v$DATE"
git push origin ":refs/tags/v$DATE"
git tag "v$DATE" <new-commit>
git push origin "v$DATE"
gh release create "v$DATE" --title "v$DATE" --notes-file "notes/v$DATE.md" --verify-tag
```

If only the changelog section changed and the tag still points at the right
commit, skip the tag steps and update the body in place:

```bash
gh release edit "v$DATE" --notes-file "notes/v$DATE.md"
```

#### Backfilling early dates

Early `## YYYY-MM-DD` entries predate this rule, so their tags may be missing
entirely. When backfilling, point the tag at the last `master` commit before
that date's `23:59:59` in the changelog's timezone (`+08:00`). Some of those
sections were written after the fact, so the tagged commit does not contain the
section it is named after — which is why the release body is generated from
`CHANGELOG.md` rather than from the tag's tree.

### 3. Language: English for docs, code comments, and commits

All of the following MUST be written in English:

- **Documentation**: every `.md` file (AGENTS.md, CHANGELOG.md, README.md,
  PLUGIN.md, skill docs, references).
- **Code comments**: inline comments, `#` / `//` line comments, `/* */` block
  comments, and docstrings.
- **Commit messages**: subject and body, including PR titles and bodies.

The only exception is **Chinese text that is part of the code itself** — for
example a regex literal matching a site's Chinese UI string (e.g.
`打开网易新闻`), or a Chinese error message literal. Such literals must stay
as-is; reference them from an English comment when the meaning is not obvious.

## Git workflow

- Branch convention: `feat/<slug>` or `fix/<slug>` from the latest `master`.
  The default branch is `master`; never commit directly to it.
- Commit style: conventional commits — `feat:`, `fix:`, `docs:`,
  `refactor:`, `chore:`, optionally scoped like `fix(plugin):`.
- Push the feature branch and let the maintainer review before opening a PR.
  PR descriptions are written in English.
- Never force-push, never rewrite public history. Prefer `revert` over
  `reset --hard`.

## Safety first

This plugin handles untrusted web content and writes into a user vault. Keep
these invariants on every change:

- **SSRF protection**: remote image fetches must keep blocking reserved/private
  IP ranges, pin redirects, reject non-default ports, and enforce
  `Content-Type: image/*`. Extractor network policy lives in
  `extractor/src/network-policy.mjs`.
- **Path containment**: all writes must resolve inside the configured vault;
  symlink escapes and traversal must be rejected (covered by
  `tests/test_web_to_obsidian.py` TargetAndAtomicWriteTests).
- **Secrets**: never log or forward credentials/tokens to the extractor child;
  the extractor receives only an allowlisted environment. Credential-like
  markers in extracted content must refuse to save.
- **Sandboxing**: the extractor child runs in a new POSIX process group;
  timeout/output-limit cleanup must terminate the whole group.
- **Atomicity**: note writes use same-directory temp file + `fsync` +
  `os.replace`; frontmatter and managed regions are fully plugin-managed.
