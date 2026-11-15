"""Atomic file replacement."""

from __future__ import annotations

from pathlib import Path
import os
import tempfile

from .core import ClipError, _normalize_text
from .paths import _require_within

def atomic_write(target: Path, content: str) -> None:
    """Durably replace a note using a temporary file in the same directory."""
    parent = target.parent.resolve()
    if not parent.is_dir():
        raise ClipError("The configured clip destination is unavailable.")
    if target.is_symlink():
        raise ClipError("Refusing to replace a symbolic-link note.")
    _require_within(target.resolve(), parent, "Generated note path escaped its destination.")

    fd = -1
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".clip-", suffix=".tmp", dir=parent)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            fd = -1
            handle.write(_normalize_text(content))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
        try:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(parent, flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    except ClipError:
        raise
    except OSError as exc:
        raise ClipError("Could not safely write the clipped note.") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            except OSError:
                pass


def atomic_write_bytes(target: Path, content: bytes) -> None:
    """Durably replace a binary asset using a temporary file in the same directory."""
    parent = target.parent.resolve()
    if not parent.is_dir():
        raise ClipError("The configured clip destination is unavailable.")
    if target.is_symlink():
        raise ClipError("Refusing to replace a symbolic-link note.")
    _require_within(target.resolve(), parent, "Generated note path escaped its destination.")

    fd = -1
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".clip-", suffix=".tmp", dir=parent)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
        try:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(parent, flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    except ClipError:
        raise
    except OSError as exc:
        raise ClipError("Could not safely write the clipped asset.") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            except OSError:
                pass
