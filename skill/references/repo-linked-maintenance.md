# Repo-linked maintenance rule for hermes-webclip-obsidian-plugin

Use this note when working on the `web-clip-to-obsidian` skill or the `webclip-obsidian` plugin.

## Durable rule

Both are symlinked from the same source repo:

- source repo: `~/.hermes/workspace/repository/hermes-webclip-obsidian-plugin`
- plugin symlink target: that repo root
- skill symlink target: `that repo/skill/`

Therefore, do **not** treat the installed profile-local skill/plugin as an isolated place for ad-hoc fixes after a one-off failure.

## What to do instead

1. Decide whether the lesson is truly class-level and durable, not just a one-session failure.
2. If yes, make the change in the source repo (`~/.hermes/workspace/repository/hermes-webclip-obsidian-plugin`).
3. Keep the repo and remote aligned by submitting the change upstream via PR.
4. Avoid leaving local-only behavior/documentation drift between the installed symlinked skill/plugin and the remote source of truth.

## Why this matters

A local edit to the symlinked skill/plugin changes the source repo immediately. If that change is not reviewed and pushed upstream, the local Hermes behavior diverges from the remote repo and becomes hard to reason about later.

## Install and deploy by symlink

```bash
ln -s ~/.hermes/workspace/repository/hermes-webclip-obsidian-plugin \
      ~/.hermes/profiles/<profile>/plugins/webclip-obsidian
ln -s ~/.hermes/workspace/repository/hermes-webclip-obsidian-plugin/skill \
      ~/.hermes/profiles/<profile>/skills/productivity/web-clip-to-obsidian
```

`config.toml` lives at the plugin package root and is tracked in git. Because the
installed path is a symlink to the repo, editing
`<profile>/plugins/webclip-obsidian/config.toml` edits the tracked file — there
is no per-profile copy. Machine-specific values therefore show up in the source
repo's `git status`; commit them deliberately or keep them out of Git.
