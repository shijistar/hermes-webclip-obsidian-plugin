"""Vault locking and Git synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
import fcntl
import os

from .core import ClipError, GIT_TIMEOUT, MAX_GIT_OUTPUT_BYTES, MAX_STDERR_BYTES
from .paths import _require_within
from .proc import ProcessResult, _decode_output, _run_bounded

@dataclass(frozen=True)
class GitOutcome:
    commit_state: str
    push_state: str
    detail: str = ""
    # Short sha of the commit this outcome created; empty when no commit exists.
    commit_sha: str = ""
    # Subject Git actually stored (a commit-msg hook may rewrite it); empty when
    # there is no commit or the lookup itself failed.
    commit_subject: str = ""


def _status_paths(raw: bytes) -> set[str]:
    try:
        chunks = raw.decode("utf-8").split("\0")
    except UnicodeDecodeError as exc:
        raise ClipError("Git returned an invalid status response.") from exc
    paths: set[str] = set()
    index = 0
    while index < len(chunks):
        entry = chunks[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4 or entry[2] != " ":
            raise ClipError("Git returned an invalid status response.")
        status = entry[:2]
        paths.add(entry[3:])
        if "R" in status or "C" in status:
            if index >= len(chunks) or not chunks[index]:
                raise ClipError("Git returned an invalid status response.")
            paths.add(chunks[index])
            index += 1
    return paths


class VaultLock:
    """A non-blocking cross-process lock shared by all Vault writers."""

    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self._handle = None

    def __enter__(self) -> "VaultLock":
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._handle = self.path.open("a+", encoding="utf-8")
            os.chmod(self.path, 0o600)
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._handle.seek(0)
            self._handle.truncate()
            self._handle.write(f"pid={os.getpid()}\n")
            self._handle.flush()
        except BlockingIOError as exc:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            raise ClipError("Another Vault write operation is already running.") from exc
        except OSError as exc:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            raise ClipError("Could not acquire the shared Vault write lock.") from exc
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


class GitSync:
    """A preflight-approved Git repository that may receive one clip note."""

    def __init__(self, vault: Path, repo_root: Path, branch: str):
        self.vault = vault
        self.repo_root = repo_root
        self.branch = branch

    @staticmethod
    def _git(repo: Path, *args: str, timeout: int = GIT_TIMEOUT) -> ProcessResult:
        return _run_bounded(
            ["git", "-C", str(repo), *args],
            timeout=timeout,
            stdout_limit=MAX_GIT_OUTPUT_BYTES,
            stderr_limit=MAX_STDERR_BYTES,
        )

    @classmethod
    def preflight(
        cls, vault: Path, expected_branch: str | None = None
    ) -> "GitSync":
        vault = vault.resolve()
        top = cls._git(vault, "rev-parse", "--show-toplevel")
        if top.returncode != 0:
            raise ClipError("Git protection requires the vault to be a Git repository.")
        repo_root = Path(_decode_output(top).strip()).resolve()
        _require_within(vault, repo_root, "The vault Git repository is invalid.")

        branch_result = cls._git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD")
        if branch_result.returncode != 0:
            raise ClipError("Git protection requires an active branch.")
        branch = _decode_output(branch_result).strip()
        if expected_branch is not None and branch != expected_branch:
            raise ClipError("The Vault is not on the configured clip sync branch.")

        for state_name in (
            "MERGE_HEAD",
            "CHERRY_PICK_HEAD",
            "REVERT_HEAD",
            "rebase-merge",
            "rebase-apply",
            "sequencer",
        ):
            state = cls._git(repo_root, "rev-parse", "--git-path", state_name)
            if state.returncode != 0:
                raise ClipError("Could not verify the Git operation state.")
            state_path = Path(_decode_output(state).strip())
            if not state_path.is_absolute():
                state_path = repo_root / state_path
            if state_path.exists():
                raise ClipError("Refusing to clip during an in-progress Git operation.")

        status = cls._git(
            repo_root, "status", "--porcelain=v1", "-z", "--untracked-files=all"
        )
        if status.returncode != 0:
            raise ClipError("Could not verify the Git worktree state.")
        if status.stdout:
            raise ClipError("Git protection requires an entirely clean worktree.")
        if expected_branch is not None:
            remote = cls._git(repo_root, "remote", "get-url", "origin")
            if remote.returncode != 0:
                raise ClipError("Git protection requires an origin remote.")
            fetched = cls._git(repo_root, "fetch", "--prune", "origin")
            if fetched.returncode != 0:
                raise ClipError("Could not fetch the Vault Git remote.")
            upstream = cls._git(
                repo_root,
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{u}",
            )
            if upstream.returncode != 0:
                raise ClipError("The clip sync branch has no upstream.")
            rebased = cls._git(repo_root, "rebase", _decode_output(upstream).strip())
            if rebased.returncode != 0:
                cls._git(repo_root, "rebase", "--abort")
                raise ClipError("Vault Git rebase conflicted; no clip was written.")
        return cls(vault, repo_root, branch)

    def _relative_paths(self, generated_paths: Sequence[Path]) -> set[str]:
        relative: set[str] = set()
        for path in generated_paths:
            resolved = path.resolve()
            _require_within(resolved, self.vault, "Generated note is outside the vault.")
            _require_within(resolved, self.repo_root, "Generated note is outside Git.")
            relative.add(resolved.relative_to(self.repo_root).as_posix())
        if not relative:
            raise ClipError("No generated note was supplied to Git.")
        return relative

    def finalize(
        self, generated_paths: Sequence[Path], *, commit_message: str | None = None
    ) -> GitOutcome:
        """Synchronize generated paths, preserving the note on every Git failure."""
        try:
            return self._finalize(generated_paths, commit_message=commit_message)
        except ClipError:
            return GitOutcome("verification_failed", "not_attempted")

    def _finalize(
        self, generated_paths: Sequence[Path], *, commit_message: str | None = None
    ) -> GitOutcome:
        expected = self._relative_paths(generated_paths)
        status = self._git(
            self.repo_root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        )
        if status.returncode != 0:
            return GitOutcome("verification_failed", "not_attempted")
        try:
            changed = _status_paths(status.stdout)
        except ClipError:
            return GitOutcome("verification_failed", "not_attempted")
        if not changed.issubset(expected):
            return GitOutcome("refused", "not_attempted")
        if not changed:
            return GitOutcome("unchanged", "not_needed")

        add = self._git(self.repo_root, "add", "--", *sorted(changed))
        if add.returncode != 0:
            return GitOutcome("stage_failed", "not_attempted")

        staged = self._git(self.repo_root, "diff", "--cached", "--name-only", "-z")
        unstaged = self._git(self.repo_root, "diff", "--name-only", "-z")
        if staged.returncode != 0 or unstaged.returncode != 0:
            return GitOutcome("verification_failed", "not_attempted")
        staged_paths = {part for part in _decode_output(staged).split("\0") if part}
        unstaged_paths = {part for part in _decode_output(unstaged).split("\0") if part}
        if staged_paths != changed or unstaged_paths:
            return GitOutcome("verification_failed", "not_attempted")

        commit = self._git(
            self.repo_root,
            "commit",
            "-m",
            commit_message or "clip: save web article",
        )
        if commit.returncode != 0:
            return GitOutcome("commit_failed", "not_attempted")
        commit_sha, commit_subject = self._commit_identity()
        identity = {"commit_sha": commit_sha, "commit_subject": commit_subject}
        # The commit exists from here on. A timeout in verification or push must
        # not turn it into a pre-commit failure: the outcome keeps the identity
        # and only downgrades the part that actually failed.
        try:
            committed = self._git(
                self.repo_root,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-z",
                "-r",
                "HEAD",
            )
            post_status = self._git(
                self.repo_root,
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            )
            verified = (
                committed.returncode == 0
                and post_status.returncode == 0
                and {
                    part for part in _decode_output(committed).split("\0") if part
                }
                == changed
                and not post_status.stdout
            )
        except ClipError:
            verified = False
        if not verified:
            return GitOutcome("committed_unverified", "not_attempted", **identity)
        try:
            push = self._git(self.repo_root, "push", "-u", "origin", "HEAD")
        except ClipError:
            return GitOutcome("committed", "push_failed", **identity)
        if push.returncode != 0:
            return GitOutcome("committed", "push_failed", **identity)
        return GitOutcome("committed", "pushed", **identity)

    def _commit_identity(self) -> tuple[str, str]:
        """(short sha, stored subject) of HEAD; ("", "") when the lookup fails.

        This runs after a successful commit, so a timeout or a missing command
        must not turn a finished commit into a clip error: the caller still has
        to verify and push it, and only the report loses its sha.
        """
        try:
            head = self._git(self.repo_root, "log", "-1", "--format=%h%x00%s")
        except ClipError:
            return "", ""
        if head.returncode != 0:
            return "", ""
        sha, _, subject = _decode_output(head).partition("\0")
        return sha.strip(), subject.strip()
