"""Path containment guards and filename sanitisation."""

from __future__ import annotations

from pathlib import Path
import re
import unicodedata

from .core import ClipError, _normalize_text
from .urls import _url_hash

MAX_FILENAME_BYTES = 180


DOS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


_FORBIDDEN_FILENAME = set('<>:"/\\|?*')


def _resolve_vault_path(vault: Path, configured: str) -> Path:
    raw = Path(configured).expanduser()
    candidate = raw if raw.is_absolute() else vault / raw
    resolved = candidate.resolve()
    _require_within(resolved, vault, "Configured path must remain inside the vault.")
    return resolved


def _require_within(path: Path, parent: Path, message: str) -> None:
    try:
        path.relative_to(parent)
    except ValueError as exc:
        raise ClipError(message) from exc


def _truncate_utf8(value: str, byte_limit: int) -> str:
    used = 0
    result: list[str] = []
    for char in value:
        encoded_size = len(char.encode("utf-8"))
        if used + encoded_size > byte_limit:
            break
        result.append(char)
        used += encoded_size
    return "".join(result)


def safe_filename(title: str, url: str, max_bytes: int = MAX_FILENAME_BYTES) -> str:
    """Build a portable Unicode Markdown filename capped by encoded byte size."""
    if max_bytes < 16:
        raise ClipError("The configured filename limit is too small.")
    cleaned_chars = []
    for char in _normalize_text(title):
        if char in _FORBIDDEN_FILENAME or unicodedata.category(char).startswith("C"):
            continue
        cleaned_chars.append(char)
    stem = "".join(cleaned_chars)
    stem = re.sub(r"\s+", " ", stem)
    stem = re.sub(r"\.+", ".", stem).strip(" .")
    if not stem:
        stem = _url_hash(url)[:12]
    if stem.split(".", 1)[0].upper() in DOS_RESERVED:
        stem = f"_{stem}"

    extension = ".md"
    stem = _truncate_utf8(stem, max_bytes - len(extension)).rstrip(" .")
    if not stem:
        stem = _truncate_utf8(_url_hash(url)[:12], max_bytes - len(extension))
    return stem + extension


def _filename_with_suffix(title: str, url: str, suffix: str) -> str:
    base = safe_filename(title, url, MAX_FILENAME_BYTES).removesuffix(".md")
    tail = f"-{suffix}.md"
    base = _truncate_utf8(base, MAX_FILENAME_BYTES - len(tail)).rstrip(" .")
    if not base:
        base = _url_hash(url)[:12]
    return base + tail
