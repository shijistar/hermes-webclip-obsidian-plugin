# Repo-linked maintenance rule for hermes-webclip-obsidian-plugin

Use this note when working on the `web-clip-to-obsidian` skill or the `webclip-obsidian` plugin.

## Durable rule

The source repo is the only copy of both the plugin and its skill:

- source repo: `~/.hermes/workspace/repository/hermes-webclip-obsidian-plugin`
- plugin: symlinked into `<profile>/plugins/webclip-obsidian` while developing, or copied
  by `hermes plugins install` on a normal install
- skill: `<repo>/skill/`, registered by the plugin's `register()`

Therefore, do **not** treat the installed plugin directory as an isolated place for
ad-hoc fixes after a one-off failure.

## What to do instead

1. Decide whether the lesson is truly class-level and durable, not just a one-session failure.
2. If yes, make the change in the source repo (`~/.hermes/workspace/repository/hermes-webclip-obsidian-plugin`).
3. Keep the repo and remote aligned by submitting the change upstream via PR.
4. Avoid leaving local-only behavior/documentation drift between the installed plugin
   and the remote source of truth.

## Why this matters

With the symlink deployment, a local edit to the plugin (its bundled `skill/` included)
changes the source repo immediately. After `hermes plugins install`, the installed tree
is an independent copy, so editing that copy leaves the repo untouched — which is why
fixes belong in the source repo either way. A change that is never reviewed and pushed
upstream makes local Hermes behavior diverge from the remote repo and become hard to
reason about later.

## Install and deploy

```bash
# plugin only — the skill ships inside the package
ln -s ~/.hermes/workspace/repository/hermes-webclip-obsidian-plugin \
      ~/.hermes/profiles/<profile>/plugins/webclip-obsidian
```

`config.toml` lives at the plugin package root but is **gitignored**. Because the
installed path is a symlink to the repo, editing
`<profile>/plugins/webclip-obsidian/config.toml` edits that local file — there
is no per-profile copy and no tracked file to dirty. Machine-specific values
therefore never appear in the source repo's `git status`, and the pre-clip
clean-worktree check stays satisfied.

The installer bootstraps `config.toml` from `config.example.toml` when it is
absent (`post-install.sh`, step 4). A plain symlink deployment that never ran
the installer needs the same step once:
`cp config.example.toml config.toml`, then set `vault` and the other local
values before the first clip.

On upgrade from a version that tracked `config.toml`, pulling the
tracking-removal commit deletes the file when the worktree is clean. If the
file has local edits, `git pull` refuses instead, so handle it explicitly:

```bash
cp config.toml /tmp/config.toml.bak                  # keep local values
git update-index --no-skip-worktree config.toml 2>/dev/null || true
git checkout -- config.toml                          # drop tracked modifications
git pull --ff-only
[ -f config.toml ] || cp config.example.toml config.toml
cp /tmp/config.toml.bak config.toml                  # restore local values
```

To recover the previously tracked version from history instead of the template:
`git show <commit-before-pull>:config.toml > config.toml`.
