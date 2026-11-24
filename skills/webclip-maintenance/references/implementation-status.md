# Implementation status

What this plugin actually does, as opposed to what a generic capture pipeline
should do. Update it when behaviour changes; `PLUGIN.md` stays the compatibility
contract and wins where the two disagree.

## Implemented

- SSRF-safe HTTP for extraction and media downloads: redirect revalidation and
  private, link-local and IPv6 rejection in `_webclip/netguard.py`, used by
  `_webclip/images.py`.
- Sanitization of untrusted Markdown and HTML in `_webclip/markdown.py`.
- Remote image detection and localisation behind a yes/no decision, bound to the
  destination context and expiring (`_webclip/pending.py`).
- Idempotency by content hash: identical content is a no-op, changed content
  needs an explicit refresh.
- Single-writer Git transaction under a Vault lock; only the generated note is
  staged; a second lock contender fails closed (`_webclip/git_sync.py`).
- Extractor failure classification: HTTP status and challenge headers cross the
  process boundary, and the message layer maps them to a verdict
  (`extractor/error-payload.mjs`, `_webclip/extract.py`).
- Post-extraction corroboration of body against title
  (`extractor/verify.mjs`).

## Partial

- The localised image extension comes from the response `Content-Type`, not from
  magic-byte sniffing; a URL suffix is only used after validation.
- Verification is fail-open by design: a weak title/body match still writes the
  note, marked `extraction_verified: weak`.

## Not implemented

- Automatic classification. Captures land in `[clip].destination` (default
  `inbox`) with `category: Inbox`; there is no classifier and no
  category-to-folder mapping.
- Obsidian community-plugin integration for classification or file moves.

## Out of scope

Do not build these here:

- Login-gated pages, cookies, credentials, password-manager integration.
- Native Windows support.
- The video download path is not part of the article-capture playbook.

## WSL2

The Vault belongs on the Linux filesystem: `/mnt/c` is slower, and native
Windows is unsupported. Do not apply a Windows-filesystem Vault layout.

## Refresh semantics

`refresh` regenerates the frontmatter and the managed region and preserves the
manual region. Edits inside the managed region are lost on refresh. The
boundaries are the frozen markers documented in `PLUGIN.md`.
