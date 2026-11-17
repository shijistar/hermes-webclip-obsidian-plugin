"""File naming for downloaded videos.

The rules are deliberately boring because they are user-visible:

* an explicit ``--name`` wins over everything;
* otherwise the video's title, cleaned of characters that break filesystems;
* otherwise a short URL hash, because Netease and most CDNs use opaque ids;
* when a command yields more than one file, every name gets a ``-1``/``-2``
  suffix so the set stays ordered and nothing is overwritten.

``paths.safe_filename()`` is not reused: it is hard-wired to ``.md`` and the
clip pipeline's fallback semantics, and half-generalising it would leave both
callers with a function that fits neither.
"""

from __future__ import annotations

from pathlib import Path
import re
import unicodedata

from ..paths import DOS_RESERVED, MAX_FILENAME_BYTES, _FORBIDDEN_FILENAME, _truncate_utf8
from ..urls import _url_hash

DEFAULT_EXTENSION = ".mp4"


def clean_stem(value: str) -> str:
    """Strip characters a filesystem rejects and collapse whitespace."""
    kept = [
        char
        for char in value
        if char not in _FORBIDDEN_FILENAME and not unicodedata.category(char).startswith("C")
    ]
    stem = "".join(kept)
    stem = re.sub(r"\s+", " ", stem)
    stem = re.sub(r"\.+", ".", stem).strip(" .")
    return stem


def _truncate_stem(stem: str, suffix: str) -> str:
    budget = MAX_FILENAME_BYTES - len(suffix.encode("utf-8"))
    return _truncate_utf8(stem, budget).rstrip(" .")


def extension_for(candidate_type: str, src: str) -> str:
    """Pick the container extension from the declared MIME type, then the URL."""
    declared = (candidate_type or "").lower()
    if "mpegurl" in declared:
        return ".mp4"  # HLS is remuxed into mp4
    if declared.startswith("video/"):
        subtype = declared.split("/", 1)[1].split(";", 1)[0].strip()
        alias = {"quicktime": "mov", "x-matroska": "mkv", "x-msvideo": "avi"}
        subtype = alias.get(subtype, subtype)
        if subtype.isalnum():
            return f".{subtype}"
    path = src.split("?", 1)[0].split("#", 1)[0]
    tail = Path(path).suffix.lower()
    if tail in {".mp4", ".webm", ".mov", ".mkv", ".avi", ".flv", ".m4v", ".ts"}:
        return ".mp4" if tail in {".ts", ".m4v"} else tail
    return DEFAULT_EXTENSION


def build_filename(
    *,
    title: str,
    src: str,
    candidate_type: str = "",
    name: str | None = None,
    index: int | None = None,
    extension: str | None = None,
) -> str:
    """Return a single path component, never containing a directory separator."""
    ext = extension or extension_for(candidate_type, src)
    if name:
        stem = clean_stem(name)
        if not stem:
            raise ValueError("The requested filename is empty after cleaning.")
    else:
        stem = clean_stem(title)
        if not stem:
            stem = _url_hash(src)[:12]
    if stem.split(".", 1)[0].upper() in DOS_RESERVED:
        stem = f"_{stem}"
    suffix = f"-{index}" if index is not None else ""
    stem = _truncate_stem(stem, f"{suffix}{ext}")
    if not stem:
        stem = _truncate_stem(_url_hash(src)[:12], f"{suffix}{ext}")
    return f"{stem}{suffix}{ext}"


def unique_path(directory: Path, filename: str, *, overwrite: bool = False) -> Path:
    """Resolve a free path in *directory*.

    The caller still has to create the file; this only picks a name, and it
    refuses to reuse an existing file unless the user asked to overwrite.
    """
    target = directory / filename
    if overwrite or not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    for counter in range(1, 1000):
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
    raise ValueError("Could not find a free filename in the destination directory.")
