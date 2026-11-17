"""Destination resolution and Git hygiene for downloaded videos.

Two rules drive this module:

* "inside the vault" is decided by resolving the path and comparing it with the
  vault root — **not** by whether the user wrote ``~`` or a relative path. An
  absolute path can point inside the vault, and a relative one can escape it via
  a symlink.
* A video dropped inside a Git-tracked vault must not leave the worktree dirty,
  because ``/webclip`` refuses to run unless the tree is completely clean. So
  the ignore entry is written *and committed* in one step, and if the tree holds
  anything else the write is refused instead of leaving the vault in a state
  that silently breaks the next clip.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from ..core import ClipError, GIT_TIMEOUT, MAX_GIT_OUTPUT_BYTES, MAX_STDERR_BYTES
from ..fsutil import atomic_write
from ..proc import _run_bounded

BLOCK_START = "# >>> webclip-video >>>"
BLOCK_END = "# <<< webclip-video <<<"
COMMIT_MESSAGE = "chore(webclip): ignore downloaded videos"
_BLOCK_RE = re.compile(
    re.escape(BLOCK_START) + r".*?" + re.escape(BLOCK_END), re.DOTALL
)


def _block_entries(existing: str) -> list[str]:
    match = _BLOCK_RE.search(existing)
    if not match:
        return []
    lines = match.group(0).splitlines()
    return [
        line.strip()
        for line in lines[1:-1]
        if line.strip() and not line.strip().startswith("#")
    ]


@dataclass(frozen=True)
class VideoDestination:
    directory: Path
    inside_vault: bool


def resolve_destination(vault: Path, configured: str) -> VideoDestination:
    raw = Path(configured).expanduser()
    candidate = raw if raw.is_absolute() else vault / raw
    resolved = candidate.resolve()
    try:
        resolved.relative_to(vault.resolve())
        inside = True
    except ValueError:
        inside = False
    return VideoDestination(resolved, inside)


def _ignore_entry(vault: Path, directory: Path) -> str:
    relative = directory.resolve().relative_to(vault.resolve())
    if str(relative) in {"", "."}:
        raise ClipError(
            "The vault itself cannot be the video destination; choose a subdirectory."
        )
    return f"/{relative.as_posix().rstrip('/')}/"


def ensure_gitignore(vault: Path, directory: Path) -> bool:
    """Add or refresh the managed ignore block. Returns True when the file changed."""
    entry = _ignore_entry(vault, directory)
    path = vault / ".gitignore"
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    except (OSError, UnicodeError) as exc:
        raise ClipError("Could not read the vault .gitignore.") from exc

    # Keep every destination that was ever ignored. Replacing the block with a
    # single entry would make videos in the previous directory untracked again,
    # and the next /webclip would then refuse to run on a dirty tree.
    entries = sorted({*_block_entries(existing), entry})
    block = BLOCK_START + "\n" + "".join(f"{item}\n" for item in entries) + BLOCK_END
    if _BLOCK_RE.search(existing):
        updated = _BLOCK_RE.sub(block, existing, count=1)
    else:
        separator = "" if (not existing or existing.endswith("\n")) else "\n"
        updated = f"{existing}{separator}{block}\n"
    if updated == existing:
        return False
    atomic_write(path, updated)
    return True


def _git(vault: Path, *args: str) -> str:
    result = _run_bounded(
        ["git", "-C", str(vault), *args],
        timeout=GIT_TIMEOUT,
        stdout_limit=MAX_GIT_OUTPUT_BYTES,
        stderr_limit=MAX_STDERR_BYTES,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        # Older git invented `user@hostname` when no identity was configured;
        # newer releases refuse instead. The wording differs by version, so match
        # any of the messages that mean "there is no author identity":
        #   fatal: unable to auto-detect email address (got '…')
        #   fatal: no email was given and auto-detection is disabled
        #   *** Please tell me who you are.  … user.email
        identity_markers = (
            "user.email",
            "auto-detect email",
            "auto-detection is disabled",
            "tell me who you are",
        )
        if any(marker in detail.lower() for marker in identity_markers):
            raise ClipError(
                "Git has no author identity in this vault. Set user.name and "
                "user.email, then run the command again."
            )
        message = "A Git command failed while tidying the vault."
        if detail:
            message = f"{message} {detail[:300]}"
        raise ClipError(message)
    return result.stdout.decode("utf-8", errors="replace")


def _status_paths(raw: str) -> list[str]:
    paths: list[str] = []
    for entry in raw.split("\0"):
        if len(entry) <= 3:
            continue
        paths.append(entry[3:])
    return paths


def commit_gitignore(vault: Path, *, message: str = COMMIT_MESSAGE) -> bool:
    """Commit a pending ``.gitignore`` change, refusing to touch anything else.

    Returns False when there was nothing to commit. Raises when the worktree
    holds changes other than ``.gitignore``: committing them would sweep the
    user's unrelated work into a plugin commit, and leaving them uncommitted
    breaks the next clip's clean-tree preflight.
    """
    raw = _git(vault, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    changed = _status_paths(raw)
    if not changed:
        return False
    if changed != [".gitignore"]:
        raise ClipError(
            "The vault has uncommitted changes, so the video ignore rule was not "
            "committed; commit or stash them and run the command again."
        )
    _git(vault, "add", "--", ".gitignore")
    # Pathspec-limited commit: even if something slipped into the index between
    # the status check and here, only `.gitignore` lands in this commit.
    _git(vault, "commit", "-m", message, "--", ".gitignore")
    return True
