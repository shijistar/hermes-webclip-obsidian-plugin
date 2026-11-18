# Changelog

All notable changes to the hermes-webclip-obsidian-plugin will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## 2026-11-18

### Added

- `PLUGIN.md#compatibility`: the published contract surface for 1.0.0 — command
  flags, configuration keys, the frontmatter fields you can query, extractor
  output fields, and the note-body boundaries, each assigned to a promise tier
  (L1 needs a major version to break, L2 best-effort, L3 not a contract, Frozen).
- `README.md`: `/save-video` usage, a video quick start, and Documentation map
  entries for the video command and its skill.
- `extractor/README.md`: the `videos` array and the `--with-videos` flag, neither
  of which was documented.

### Changed

- **Plugin 1.0.0, extractor 1.0.0.** No part of the public API breaks: 1.0.0
  freezes the contract described above and carries no migration steps. The
  built-in defaults did move, though — see the next two entries — so an
  installation without a `config.toml` should confirm or create its vault
  before upgrading. The skills move to `web-clip-to-obsidian` 1.14.0 and
  `web-save-video` 1.0.4.
- `config.example.toml` is a neutral template now: it targets a `~/Obsidian`
  vault and an `inbox` destination, carries a comment on every key, and no
  longer documents `ytdlp` (the key is still accepted for existing configs).
- Built-in defaults follow the template — `~/Obsidian` and `inbox` instead of one
  machine's `~/obsidian/shijistar` and `Inbox`.
- The configuration precedence is stated explicitly, in `PLUGIN.md` and in the
  README: while `config.toml` exists the `WEB_TO_OBSIDIAN_*` environment
  variables take no part, for any key; when it is absent they are read.
- Skill tags carry the skill name, `skill@<name>@<version>`. Historical flat
  `skill@<version>` tags stay as they are; their owner is decided by the commit
  they sit on.
- `README.md` is 25 lines shorter despite gaining the video sections: the
  favorite-marker rules and the configuration table now point at
  `PLUGIN.md` and `config.example.toml` instead of repeating them.

### Fixed

- `netguard`: a chunked response that stops mid-body raises `http.client.IncompleteRead`,
  which is neither an `OSError` nor a `ClipError`. It escaped the per-candidate handler and
  aborted the whole `/save-video` batch instead of failing one candidate; both readers now
  convert it, and a truncated download removes its partial file.
- `probe`: the HLS encryption check searched the raw attribute list for `METHOD=`, so
  `#EXT-X-KEY:KEYFORMAT="METHOD=NONE",METHOD=AES-128,…` reported an AES-128 stream as plain
  and downloaded it into an unplayable file. The attribute list is parsed now, so quoted
  values cannot impersonate a key.
- `service`: `/save-video` read `[clip]` leniently while `/webclip` used
  `ClipConfig.from_file`, so a table without `lock_file` (or `vault`) sent the two commands
  to different locks and vaults. Both resolve through the same entry point.
- `report`: the `MEDIA:` neutraliser required a word boundary, so a page-supplied
  `https://…/xMEDIA:/tmp/report.pdf` survived as a live directive. It is neutralised at any
  offset now, which also lets the path-separator rewrite cover it.
- `download/hls`: ffmpeg opens its output with `fopen()` and `-y`, which follows a symlink
  and truncates its target. The merge output is claimed with `O_EXCL` first, so a pre-placed
  symlink fails the candidate instead of redirecting the write.

### Docs

- `skills/web-save-video/references/storage-policy.md`: a relative destination that escapes
  the vault through a symlink is rejected, not treated as "outside".
- `/save-video` security regressions moved into `tests/test_security_regressions.py`, where
  `AGENTS.md` requires them.

## 2026-11-17

### Added

- `/save-video <url> [<url> ...] [--name <name>] [--to <dir>] [--overwrite] [--no-browser]`:
  downloads the video(s) on a page to local disk. Generic HTML5 pages use the extractor's new
  `videos` field; Netease pages are fetched by a site adapter because a `/news/v/` stub has no
  article body. HLS playlists are pre-flighted (encryption, liveness, segment count) and their
  segments are downloaded by the plugin's own SSRF-guarded client before ffmpeg remuxes **local**
  files; direct media is streamed with a byte ceiling enforced while writing. Every candidate is
  reported, and a failure never aborts the rest of the batch.
- `[video]` table in `config.toml`: `destination` (absolute = outside the vault, relative =
  inside), `gitignore`, `max_size_mb`, `max_per_run`, `download_timeout_s`, `ytdlp`. Parsed
  independently of `[clip]`, so a typo here degrades to defaults with a warning instead of
  breaking `/webclip`.
- `skills/web-save-video/`: new skill (main file under 80 lines) with seven references —
  platform matrix, DOM discovery, HLS, direct download, naming, storage policy, Netease.
- `_webclip/netguard.py`: resolves a page-supplied URL once, rejects private / link-local /
  non-default-port answers, pins the connection to the approved address and revalidates every
  redirect. This is what stops a playlist from pointing the downloader at `127.0.0.1` or a cloud
  metadata endpoint.
- `skill/references/zhihu-article-extraction.md`: the Zhihu per-article procedure that until now
  lived only in a local profile skill — the four-layer ladder, how to read a `40362` refusal
  (request-layer throttling, not a cookie problem, plus the three-probe check that proves it),
  why a login is not an extraction lever, the body-trim boundaries, and the fallback fingerprint
  caveat: on the fallback path `source_content_hash` is the constant hash of an empty string, so
  no refresh, dedupe or "page changed" decision may rest on it. `SKILL.md` now points at it
  beside the existing diagnostics reference. Skill version 1.11.1 → 1.12.0.

### Changed

- Repository layout: `skill/` became `skills/<name>/`, so a second skill can ship from the same
  package. Registration paths in `__init__.py`, `post-install.sh`, `AGENTS.md`, `PLUGIN.md`,
  `README.md` and the skill's own references were updated; the registered names are unchanged.
  Skill version 1.12.0 → 1.13.0.
- Extractor 0.4.1 → 0.5.0. `extractHtml()` now returns a `videos` array (collected from the DOM
  before Defuddle runs), `--with-videos` lets a video-stub page clear the quality gate, and asking
  an older extractor for videos is a loud error instead of an empty list. `/webclip` never asks
  for `videos`, so its behaviour is unchanged.
- `_webclip/article.py` validates the new `videos` field (http(s) sources only, at most 20
  entries) and distinguishes "the extractor cannot report videos" from "this page has none".
- The fallback contract now puts the fetched page text in `article["markdown"]`, with the trimmed
  or re-rendered body only in `content_markdown`. `render_note()` refuses a payload that supplies
  a rendered body with an empty `markdown`, because that combination made `source_content_hash`
  the constant `sha256("\n")` — under which a rewritten article looked unchanged and was saved
  without the `--refresh` gate. Notes clipped before this change keep the constant fingerprint
  until their next `--refresh`.
- `write_managed_note()` rewrites the managed section without `--refresh` when the source
  fingerprint is unchanged, both bodies are already rendered, and every source-derived field
  matches. The comparison is a whitelist (`title`, `url`, `original_url`, `original_host`,
  `author`, `site`, `published`, `description`, `keywords`, `extraction_method`, `webclip_id`),
  so the reader's own edits to `status`, `category` or `tags` no longer block a rule-driven
  rewrite. Four guards keep the exemption from widening: a note missing either fingerprint is not
  exempt; a source fingerprint equal to the empty-body hash `sha256("\n")` is not exempt (it
  carries no source identity); a body of pure whitespace is rejected rather than treated as
  content; and an existing `favorite` marker is carried over only on the implicit path, so an
  explicit `--refresh` with `favorite=False` still clears it. Plugin version bumped
  0.22.1 → 0.22.2.
- `AGENTS.md` no longer mirrors the current module versions in its versioning table. The values
  live in `plugin.yaml`, `extractor/package.json` and the `version` frontmatter of
  `skill/SKILL.md`, and copying them into a document that must be edited by hand only added a
  second place to forget. The table now records where each version lives.

### Fixed

- A vault destination's `.gitignore` commit reported only "A Git command failed while tidying the
  vault" when the repository had no author identity. Git 2.56 no longer invents `user@hostname`,
  so this surfaced as an unexplained failure on CI and on fresh vaults. The plugin now says
  "Git has no author identity in this vault. Set user.name and user.email", and other Git
  failures carry the stderr detail instead of being discarded. The video test fixtures pin a
  local identity for the same reason: the plugin commits without `-c`.
- The `/save-video` receipt no longer renders page-controlled text. A title could carry a newline
  and forge a `MEDIA:` line (or a bare existing path), which the gateway turns into an uploaded
  attachment; the success line now shows the saved filename and every page-supplied field is
  flattened and de-fanged.
- A response shorter than its declared `Content-Length` was accepted as complete — `read(amt)`
  returns `b""` instead of raising `IncompleteRead` when the peer closes early — so a truncated
  video could be published, and could replace a good file under `--overwrite`. Both readers now
  verify the received count, and the temporary file is created with `O_EXCL` under a randomised
  name so a pre-placed symlink fails the write instead of redirecting it.
- One bad candidate can no longer abort the batch: a malformed `#EXTINF` duration, a page-declared
  `width="100001"` that made the payload validator raise (which also broke `/webclip`), and an
  `http.client.HTTPException` from a broken status line are all reported per candidate.
- Playlists this downloader cannot honour are refused at pre-flight instead of being downloaded
  incorrectly: `EXT-X-BYTERANGE` (the whole resource once per range) and `EXT-X-MAP` (the fMP4
  initialisation section would be dropped).
- Smaller fixes: the declared MIME subtype is mapped through a fixed set (`video/md` no longer
  saves a `.md` file inside the vault), gitignore entries escape glob characters, the managed
  block is built with a literal replacement, a relative destination that escapes the vault
  through a symlink is refused, variant parsing is a single pass, `METHOD` is read as an
  attribute, the vault and lock fall back to `WEB_TO_OBSIDIAN_*` like `/webclip`, and
  `<picture>`/`<audio>` sources no longer consume the video candidate limit.

### Docs

- `skills/web-save-video/references/netease.md` records the `/news/sv/` URL prefix (same player
  markup, same adapter — `matches()` only checks the hostname, so no path check was added), four
  end-to-end samples spanning 16:9, 4:3 and 9:16 from 720×1280 to 1920×1080, and the measured
  behaviour of `data-mp4`: it held the same `.m3u8` address as `data-m3u8` in 3/3 pages, so the
  container must be derived from the URL rather than the attribute name.
- `skills/web-save-video/references/download-hls.md` now documents how to verify a merged file:
  the residue against the `EXTINF` sum scales with segment count (48–68 ms per segment across
  five measured pages), so an absolute "under 3 seconds" rule fails a long but intact download.
  Includes the packet-timeline check that separates boundary padding from a dropped segment.

## 2026-11-16

### Added

- `ClipResult.summary_markdown()` now leads its table with a **title** row, so a receipt
  identifies the article instead of starting at the author. The value comes from the
  `ClipResult.title` field that `_article_report_fields()` already filled, is capped at 120
  characters so one long `<title>` cannot dominate the receipt, and renders the same em
  dash as the other empty cells when no title is present. Plugin version bumped
  0.21.0 → 0.22.0; skill 1.11.0 → 1.11.1.

### Changed

- Skill docs: `references/zhihu-cookie-and-scraper-diagnostics.md` now records the measured
  four-layer outcome of a cookie-less Zhihu clip — protocol `403`, Playwright `403`, local
  logged-in browser `40362` throttling with a placeholder title, and `web_extract` as the
  layer that returns the body — plus the rule that rung 4 succeeding does not validate
  rung 3, the edit-metadata line that bounds the article body, and the `image_count`
  parameter that keeps a retained image from being reported as none.
- Skill docs: `SKILL.md` records that the WSL-era `GODEBUG=http2client=0` prefix is not
  needed on macOS, so `gh` and `git` commands run unprefixed.

### Fixed

- Receipt cells no longer render page text as Markdown. Titles like
  `[Claim prize](https://evil.example)`, `![x](https://evil/track.gif)`, `https://example.com`,
  `@shijistar`, `**Important**` or `~~strike~~` used to become real links, remote images,
  account mentions or styled text inside the summary table, and a raw `<img>` tag survived as an
  element. Values carrying any of those markers are now wrapped in a code span, which GFM
  renders literally — backslash escaping and HTML entities were both measured against GitHub's
  renderer and do not stop the parse. Only page-derived cells are wrapped, so the plugin's own
  image and size cells keep their emphasis.
- `_summary_cell()` doubles backslashes before escaping pipes, so a value containing `\|`
  keeps its backslash instead of rendering as `|`. Plugin version bumped 0.22.0 → 0.22.1.

## 2026-11-15

### Changed

- `web_to_obsidian.py` is now a 72-line façade: the 3629-line module is split into
  sixteen layered modules under `_webclip/` (core → proc / urls / report →
  article / paths → config / extract / fsutil / git_sync / markdown →
  images / notes / pending / sites → service). Symbol names, signatures and
  behaviour are unchanged, and `dir(web_to_obsidian)` still exposes the same 199
  names, so callers and tests that reach for `clip.os` or `clip.subprocess` are
  unaffected. Both loading modes (top-level module for tests, package submodule
  for Hermes) share one `_webclip` instance. No version bump: pure refactor.

### Fixed

- A timeout after a successful `git commit` no longer discards the commit: a
  push timeout reports `committed` with `push_failed` and a verification timeout
  reports `committed_unverified`, and both keep the sha and subject. Previously
  any `ClipError` in that window returned `verification_failed`, so the receipt
  said the note was never committed while the commit existed locally.
- A `git log` result that is not valid UTF-8 no longer aborts the sequence
  either: `_commit_identity()` decodes inside its guard, so the commit is still
  verified and pushed and only the sha in the receipt is lost.
- Three extractor tests patch `_webclip.extract._run_bounded` and assert the
  mock ran. They had been patching the façade binding, which the module no
  longer consults, so they executed the real extractor and passed on an
  unrelated failure instead of the payload validation they claim to cover.

## 2026-11-14

### Added

- `ClipResult.summary_markdown(lang="zh")` returns a fixed report — author, published date,
  source host, image count annotated with `image_mode`, note size, commit sha, and the
  preview link — so the agent prints plugin-computed figures instead of recomputing them.
  There is no git status row: the commit cell already answers "did it land?" and a sync
  dashboard in a clip receipt is noise. A failed push, commit, stage or verification
  appends one warning line below the table; a clean clip prints nothing extra.
  `lang="en"` renders English labels;
  `favorite` / `unfavorite` keep the existing short message. `user_message()` is unchanged,
  so the `/webclip` boundary and older callers keep working. Plugin 0.20.0 → 0.21.0,
  skill 1.10.0 → 1.11.0.

### Changed

- The plugin registers its skill with `ctx.register_skill()`, so the skill lives inside
  the plugin package and resolves as `webclip-obsidian:web-clip-to-obsidian`. Nothing is
  copied into a profile's `skills/` directory. Editing `skill/SKILL.md` or its references
  takes effect immediately; only the description shown in the skills list refreshes on the
  next gateway restart. Plugin 0.19.3 → 0.20.0, skill 1.9.0 → 1.10.0.
- Browser-extraction docs are split by platform. `references/browser-extraction-ladder.md`
  states which path to take (bundled Playwright extractor first, CDP only for a logged-in
  session); `references/platforms/linux-macos.md` covers local Chrome, and
  `references/platforms/wsl.md` keeps the existing PowerShell flow for borrowing a Windows
  Chrome session.
- `plugin.yaml` now declares `linux` **and** `macos`, and the README requirement says
  "Linux, macOS, or WSL". Nothing branched on the platform at runtime — the manifest and
  the README were simply wrong about it.
- `plugin.yaml` declares `python_dependencies: PyYAML>=6.0,<7` (and `requirements.txt`
  matches). Hermes never auto-installs declared dependencies, but the declaration lets
  `hermes pm repair` / `hermes plugins doctor` name the missing package instead of the
  plugin failing to load with a bare `No module named 'yaml'`. `post-install.sh` no longer
  installs PyYAML itself: it picked `command -v python3`, which is a different interpreter
  from the Hermes runtime that loads the plugin, so a successful run proved nothing.

### Removed

- `skill/references/profile-skill-vs-source-repo-sync.md` — it documented a drift
  problem that can no longer occur. `skill/references/repo-linked-maintenance.md` and
  `skill/README.md` were rewritten to match.

## 2026-11-13

### Added

- `skill/references/input-normalization.md`: per-site rules for turning a share-sheet
  paste into a clean URL before it reaches `service.run()`. Share sheets prepend the
  article title and append tracking parameters. `webclip_id` is derived from the
  extractor's canonical URL, falling back to the final fetched URL when a page has no
  usable canonical — and because lookup keeps every query parameter while writing
  drops the common tracking keys, a parameterised paste fails to find the note its
  clean equivalent wrote. Cleaning at the input stage closes that gap.
  Rules cover Netease News, Juejin, Zhihu, Bilibili and both WeChat URL forms (the new
  `/s/<id>` form carries no query; the legacy `__biz` form must keep `__biz`, `mid`,
  `idx`, `sn`). A host that is not listed is passed through unchanged, since a wrong
  strip can make an article unreachable. Skill 1.8.0 → 1.9.0.

## 2026-11-12

### Changed

- In `ask` image mode the agent now collects the choice with a `clarify` card
  whose labels start with `A.` (远程图片, remote) and `B.` (本地图片, local),
  instead of asking the user to type `yes` / `no`. The mapping is explicit
  (A → `resume_pending('no')`, B → `resume_pending('yes')`) because the plugin
  argument is inverted relative to the destination. Runtimes without `clarify` fall back to the same A/B
  question in one text line. Option labels follow the conversation language
  (Chinese for Chinese input, English otherwise) while the A/B mapping stays
  fixed, and the skill prose is English-only. The no-argument default stays
  `--save-images no`, and `--save-images ask` still returns `PendingClipResult`.

### Fixed

- Downloaded images now take their extension from the served `Content-Type` instead
  of trusting the URL path. Netease (and others) return PNG or WebP payloads from
  `.jpg` paths, so a localized note could reference a file named `.jpg` that was
  actually PNG, which misleads anything that reads the extension. Known image
  subtypes map to a canonical extension (`image/jpeg` → `.jpg`, `image/svg+xml` →
  `.svg`, `image/x-icon` → `.ico`); an unknown subtype still falls back to the URL
  suffix, then to `.img`.

## 2026-11-11

### Changed

- Skill default image mode is now `remote`: the agent passes `--save-images no`
  unless the user asks for local images or explicitly asks to be prompted, so a
  plain clip no longer stops for an image confirmation. The plugin's own default
  is unchanged (`ask`), and `--save-images ask` still returns
  `PendingClipResult` for callers that want the two-step flow.

## 2026-11-06

### Fixed

- `post-install.sh` now prefers the installed plugin directory it runs from
  (`<profile>/plugins/<key>`) when deriving the target profile. Previously,
  running from the default `<HERMES_HOME>/plugins/webclip-obsidian` while
  exactly one named profile existed selected that profile, so `config.toml`,
  dependencies and the skill symlink landed in the wrong profile and the
  default install ended up with no configuration. The single-profile
  heuristic now only applies to source checkouts.

### Changed

- Preview URL parameter validation now counts the 1 KiB limit after the
  optional leading `?` is stripped. `matches_config()` documents that it
  intentionally ignores `preview_url_params`, and edge-case tests cover
  fragment preservation, percent-encoding normalization and call-site
  idempotency.

## 2026-11-05

### Added

- `preview_url_params` in `config.toml` appends custom query parameters to the
  article preview (GitHub blob) URL. It is empty by default, so existing
  installs keep byte-identical URLs. Clients such as Feishu/Lark support
  `lk_jump_to_browser=true` and `lk_mobile_jump_to_browser=true` to open a link
  in the system browser. Invalid values (fragments, control characters,
  values that are not `k=v` pairs, and overlong strings) are rejected when the
  config is loaded.
- `docs/preview-link-params.md`: a per-platform reference for opening preview
  links in a browser, listing which platforms support a URL query parameter and
  which require a client setting or an in-app JSAPI instead.

### Changed

- `ClipConfig` accepts `preview_url_params` and the equivalent
  `WEB_TO_OBSIDIAN_PREVIEW_URL_PARAMS` environment variable. Both the
  single-clip and batch result URLs honour it.
- `config.toml` is no longer tracked: it is listed in `.gitignore` and
  generated from `config.example.toml` on install, so this version and later
  ones do not publish a user's local paths and preview parameters (values
  already committed in earlier history remain visible there).
- **Upgrade note**: pulling this change removes the tracked `config.toml`.
  Back up local edits first (`cp config.toml config.toml.bak`), then recreate
  the file only when absent
  (`[ -f config.toml ] || cp config.example.toml config.toml`, or re-run
  `post-install.sh`) and re-apply local values. To recover the previously
  tracked version instead of the template:
  `git show <commit-before-pull>:config.toml > config.toml`.

## 2026-11-03

### Changed

- **`--favorite` is now idempotent (`ensure-favorited`)**: a new URL is clipped
  and marked; an existing note is marked in place without fetching; `--refresh`
  is the only way to re-fetch. `--unfavorite` clears the marker and, without
  `--refresh`, never fetches. This removes the need to remember which of the two
  favorite flags applies to a given target.
- **A `webclip_id` is a first-class target**: the 64-hex digest from a note's
  frontmatter (with or without the `sha256:` prefix) selects a clipped note.
  Resolution checks `webclip_id` first and falls back to `source_content_hash`.
  A `webclip_id` target requires `--favorite`/`--unfavorite` and rejects
  `--refresh`/`--save-images`.
- **Duplicate notes are all marked**: a selector matching several notes updates
  every match in one commit and reports them as "N notes" instead of failing on
  ambiguity.
- **Batch mode classifies specs before enforcing the image flag**: marker specs
  no longer need `--save-images`, while every spec that extracts a page still
  does.

### Added

- `ClipResult.paths` and `ClipResult.matched_by`, plus multi-note result
  messages that list every marked path.

### Removed

- **`--favorite-only` and `--unfavorite-only`**: use `--favorite`/`--unfavorite`
  instead. With an existing note they keep the old marker-only behaviour, and a
  `webclip_id` target is always marker-only.

### Fixed

- Notes larger than 64 KiB are no longer invisible to URL, `webclip_id`, and
  re-clip lookups: frontmatter is read from a bounded prefix instead of
  rejecting the whole file, so a long article can be marked by any selector
  and re-clipping it no longer writes a duplicate note.
- Marker lookup now also matches the `fetched_url` a note recorded, so
  `--favorite`/`--unfavorite` accept the original entry URL of a page whose
  canonical URL differs. The write path is guarded separately: a clip whose
  canonical URL equals another note's `fetched_url` creates a new note
  instead of rewriting (and failing on) the note that only fetched that URL.
- Git preflight (fetch + rebase) now runs before marker lookups and batch
  classification, so a vault behind its remote no longer misreads a note as
  missing: `--favorite`/`--unfavorite` and marker-only batch specs resolve
  against the rebased state instead of failing or demanding `--save-images`
  for a clip that would not happen.
- `_mark_targets` validates and computes every marker update before writing
  any of them: a malformed duplicate among hash-matched notes now fails with
  zero writes instead of leaving earlier notes modified but uncommitted in a
  dirty worktree.
- A marker-only batch now commits as `favorite: batch (N notes)` or
  `unfavorite: batch (N notes)` instead of `clip: batch`, with the count
  reflecting the notes actually changed; no-op marker specs do not influence
  the subject, and failed sha256 selectors are shortened in the batch
  summary.

## 2026-10-30

### Changed

- **Skill index description fits the 57-character window**: the frontmatter
  description dropped from 638 characters (of which the system prompt showed
  only the first 57) to a 55-character sentence that names all three intents —
  clip, save, favorite — plus the Chinese trigger words the user actually
  types. Routing no longer depends on text the prompt never receives.
- **Pitfalls slimmed by 66%**: the section went from 36 bullets / 14.4k
  characters to 28 bullets / 4,896 bytes. Executable rules stay inline; root causes,
  diagnosis paths and site deep-dives moved to `references/` behind a one-line
  pointer. SKILL.md shrank from 25,611 to 15,131 bytes (40.3%), cutting roughly
  4.5k tokens from every load without dropping a rule.
- **Favorite semantics consolidated**: the marker rules and the intent-to-command
  mapping (favorite / unfavorite, clipped target vs bare URL, target resolution
  order, `bookmarks.json` ban) now live in one section instead of being spread
  across a section and six pitfall bullets.
- **Six unreferenced references are now reachable**: git sync testing, GitHub
  blob/image_mode, profile-vs-source drift, repo-linked maintenance, WSL Chrome
  CDP and pending resume were dead files; the slimmed Pitfalls link them.

### Added

- `references/wechat-curl-extraction.md` — curl fallback, the two `nickname`
  page formats, the CAPTCHA wall and the failure judgement.
- Pending-state table (four states and their exact errors) in
  `references/pending-resume-fallback.md`; SPA "cannot be extracted" section in
  `references/anti-bot-fallback-web-extract.md`; explicit per-spec image policy
  in `references/batch-processing.md`.

## 2026-10-25

### Changed

- **Favorite marker placement**: `favorite: true` now sits immediately after the
  top-level `original_host` field instead of at the end of the frontmatter.
  A marker already present in the wrong position is moved into place by
  `--favorite-only`, so existing notes converge on the new layout. Only a key
  starting at column zero is treated as `original_host`, so indented
  continuation lines inside multi-line values cannot pull the marker into a
  nested block.
- **Batch clipping produces one commit**: `ClipService.run_batch()` clips
  several URLs under a single vault lock and commits/pushes every written note
  once. Per-URL flags stay independent, one failing URL does not abort the
  rest, and `--save-images ask` is rejected for any spec that extracts a page
  (marker-only specs are exempt) because a single pending confirmation cannot
  represent multiple articles. The `/webclip` slash command still accepts
  exactly one URL per invocation.

### Added

- `web_to_obsidian_resume_pending` tool declaration in `plugin.yaml`.

### Changed (install path)

- The profile plugin symlink is now named `webclip-obsidian` instead of
  `web-to-obsidian`, matching the manifest name. Hermes keys plugins by
  `plugin.yaml`'s `name`, but the install directory is expected to carry the same
  name, and a mismatched directory lets a later `hermes plugins install` create a
  second directory for the same key. `plugins.enabled` is unchanged.

### Fixed (docs)

- Corrected `skill/SKILL.md` and its references against the current code:
  - The skill now names the plugin by its registered key `webclip-obsidian`;
    `hermes-webclip-obsidian-plugin` is used only for the source repo path.
  - The installed plugin directory is `plugins/web-to-obsidian`, while the
    registration key is `webclip-obsidian` (from `plugin.yaml`'s `name`). Hermes
    keys plugins by that name, so `plugins.enabled` must list `webclip-obsidian`;
    listing the directory name silently leaves the plugin disabled.
  - The anti-bot fallback example now passes the extracted body into
    `content_markdown` instead of the empty `article["markdown"]`, which produced
    frontmatter-only notes; `markdown` is documented as required but allowed to be
    empty.
  - The pending-state pitfall now describes the `active.json` pointer plus
    `<pending_id>.json` layout; an empty directory is normal, and stale or expired
    entries are cleared automatically.
  - 163 `spss`/`spsnuid`/`spsvid`/`spstoken` params are documented as **not**
    stripped by the plugin; dedup depends on the page's canonical tag, and
    `original_url`/`fetched_url` are normalized too.
  - `config.toml` is documented as a shared, tracked file rather than a per-profile
    copy; `run_batch()` is documented in the batch workflow; `ClipResult.action`
    and the third Python entry point are listed.
  - Minor fixes: the `%2F` blob-URL note now states what `github_blob_url()`
    actually emits, the WSL stop-Chrome snippet is valid bash, the batch script
    uses `cut -f4-`, and `preflight(vault, ...)` is described accurately.

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
- Restructured `README.md` into a scannable landing page: consolidated features
  and requirements, condensed install steps, added a complete flag table, a
  favorite behavior table with Obsidian queries, configuration and safety
  summaries, a contributor/test section, and the MIT license.

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
