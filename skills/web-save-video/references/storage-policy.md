# Storage Policy

Video belongs outside a Git-tracked vault unless the user says otherwise: a
27 MB clip committed today stays in the repository's history after deletion, so
a few dozen clips turn the vault into gigabytes. `/save-video` therefore defaults
to `~/Movies/Videos/webclip`.

## Configuration

```toml
[video]
# absolute path (~ expanded) = outside the vault; relative = inside, against [clip].vault
destination = "~/Movies/Videos/webclip"
# when the destination resolves inside the vault, keep it out of Git
gitignore = true
max_size_mb = 500
max_per_run = 10
download_timeout_s = 300
```

## "Inside the vault" is decided by resolution, not by syntax

`~/Obsidian/attachments/video` is an **absolute** path that lives
**inside** the vault; `attachments/video` is relative and also inside; a
relative path through a symlink that points outside is **rejected** — only an
absolute destination may leave the vault. The check resolves the path and
compares it with the vault root — never "does it start with `~`".

## The Git interaction that must not be missed

`/webclip` refuses to run unless the worktree is **completely clean**
(`git status --porcelain --untracked-files=all` must be empty). So a video
written into the vault creates two problems: an untracked video file, and a
modified `.gitignore`.

The command handles both before downloading:

1. write the managed block into `<vault>/.gitignore`:

   ```
   # >>> webclip-video >>>
   /attachments/video/
   # <<< webclip-video <<<
   ```

2. commit **only** that file (`chore(webclip): ignore downloaded videos`).

If the worktree holds any other change, step 2 refuses and the command stops
with an explanation: committing unrelated work would be worse, and leaving it
uncommitted would break the next clip.

The block keeps **one entry per destination directory** and is never duplicated:
changing `[video].destination` adds a line rather than replacing the old one, so
files already downloaded into the previous directory stay ignored. If the
worktree is dirty, the commit is refused and the command says so — clean it and
run the command again; the retry commits the pending `.gitignore` even though
its content no longer changes.

## Reporting

The receipt says `(inside the vault, ignored by Git)` only when the ignore rule
was applied; with `[video].gitignore = false` it says `NOT ignored by Git`
instead. Files above 50 MB are not attached to the chat — they stay at the
reported path.
