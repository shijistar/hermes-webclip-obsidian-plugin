"""Note discovery, frontmatter and favourite markers."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Sequence
import re
import yaml

from .core import ClipError, MAX_DESTINATION_SCAN_ENTRIES, _normalize_text
from .fsutil import atomic_write
from .paths import _filename_with_suffix, _require_within, safe_filename
from .urls import _url_hash, normalize_url

def _frontmatter_from_text(text: str) -> dict[str, object] | None:
    normalized = _normalize_text(text)
    if not normalized.startswith("---\n"):
        return None
    end = normalized.find("\n---\n", 4)
    if end < 0:
        return None
    try:
        parsed = yaml.safe_load(normalized[4:end])
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None


def read_skill_frontmatter(skill_md: Path) -> dict[str, object]:
    """Parsed frontmatter of a SKILL.md; ``{}`` when it is missing, unreadable, or empty.

    register() hands this to ``ctx.register_skill()`` so the registry sees the same
    metadata the file declares — description, and the platform/condition gates Hermes
    evaluates for plugin skills — instead of a second hardcoded copy in ``__init__.py``.
    """
    try:
        text = skill_md.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return {}
    return _frontmatter_from_text(text) or {}


def _note_prefix(path: Path, limit: int = 64 * 1024) -> str | None:
    """Read a bounded note prefix for frontmatter lookups.

    The writer puts the frontmatter at the top, so a prefix identifies the
    note even when the article body pushes the file past *limit*. Decoding
    ignores a multibyte character split at the read boundary.
    """
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit)
        return raw.decode("utf-8", errors="ignore")
    except OSError:
        return None


def _sources_from_note(path: Path) -> set[str]:
    """Return every normalized source URL the note records for itself.

    ``fetched_url`` is included so a note clipped through an entry URL whose
    canonical URL differs can still be found by the URL the user requested.
    """
    text = _note_prefix(path)
    if text is None:
        return set()
    metadata = _frontmatter_from_text(text)
    sources: set[str] = set()
    if metadata is None:
        return sources
    for field in ("url", "original_url", "source", "fetched_url"):
        candidate = metadata.get(field)
        if not isinstance(candidate, str) or not candidate:
            continue
        try:
            sources.add(normalize_url(candidate))
        except ClipError:
            continue
    return sources


def _checked_candidate(destination: Path, filename: str) -> Path:
    candidate = destination / filename
    if candidate.is_symlink():
        raise ClipError("Refusing to replace a symbolic-link note.")
    resolved = candidate.resolve()
    _require_within(resolved, destination, "Generated note path escaped its destination.")
    return candidate


def _destination_notes(destination: Path) -> list[Path]:
    """Regular ``.md`` notes in *destination*, refusing symlinks and bounded scans."""
    entries: list[Path] = []
    for index, existing in enumerate(destination.iterdir(), start=1):
        if index > MAX_DESTINATION_SCAN_ENTRIES:
            raise ClipError("The clip destination contains too many entries to scan safely.")
        entries.append(existing)

    notes: list[Path] = []
    for existing in sorted(entries, key=lambda path: path.name):
        if existing.suffix.lower() != ".md":
            continue
        if existing.is_symlink():
            raise ClipError("Refusing to scan a symbolic-link note.")
        if existing.is_file():
            notes.append(existing)
    return notes


def _scan_source_matches(destination: Path, source: str) -> list[Path]:
    """Return notes in *destination* whose recorded source matches *source*."""
    normalized_source = normalize_url(source)
    return [
        note
        for note in _destination_notes(destination)
        if normalized_source in _sources_from_note(note)
    ]


def _note_hashes(path: Path) -> tuple[str | None, str | None]:
    """Return ``(webclip_id, source_content_hash)`` from a note's frontmatter."""
    text = _note_prefix(path)
    if text is None:
        return None, None
    metadata = _frontmatter_from_text(text)
    if not metadata:
        return None, None
    webclip_id = metadata.get("webclip_id")
    content_hash = metadata.get("source_content_hash")
    return (
        webclip_id if isinstance(webclip_id, str) else None,
        content_hash if isinstance(content_hash, str) else None,
    )


def _digest_matches(value: str | None, digest: str) -> bool:
    """Whether a frontmatter hash equals *digest* (bare or ``sha256:`` prefixed)."""
    if not value:
        return False
    normalized = value.strip().lower()
    if normalized.startswith("sha256:"):
        normalized = normalized[len("sha256:") :]
    return normalized == digest


def _scan_hash_matches(destination: Path, digest: str) -> tuple[list[Path], str | None]:
    """Find notes by ``webclip_id`` first, then by ``source_content_hash``.

    Returns every match plus the field that matched (``None`` when nothing did).
    """
    wanted = digest.lower()
    by_id: list[Path] = []
    by_content: list[Path] = []
    for note in _destination_notes(destination):
        webclip_id, content_hash = _note_hashes(note)
        if _digest_matches(webclip_id, wanted):
            by_id.append(note)
        elif _digest_matches(content_hash, wanted):
            by_content.append(note)
    if by_id:
        return by_id, "webclip_id"
    if by_content:
        return by_content, "source_content_hash"
    return [], None


def _write_target_ok(note: Path, webclip_id: str) -> bool:
    """A scan match is a write target only when its webclip_id agrees.

    A note can record a URL under ``fetched_url`` while belonging to a
    different canonical source. Marker lookups may match any recorded URL
    form, but rewriting such a note from a new clip would hijack another
    article's note, so choose_target skips it. Legacy notes without a
    webclip_id keep the pre-existing behavior.
    """
    note_id, _ = _note_hashes(note)
    return note_id is None or note_id == webclip_id


def choose_target(
    destination: Path,
    title: str,
    source: str,
    *,
    capture_date: str | None = None,
) -> Path:
    """Choose an idempotent target without scanning outside the destination."""
    destination = destination.resolve()
    if not destination.is_dir():
        raise ClipError("The configured clip destination is unavailable.")
    digest = _url_hash(source)
    webclip_id = f"sha256:{digest}"
    matches = [
        note
        for note in _scan_source_matches(destination, source)
        if _write_target_ok(note, webclip_id)
    ]
    if len(matches) > 1:
        raise ClipError("The clip destination contains multiple notes for this source.")
    if matches:
        return matches[0]

    if capture_date is None:
        capture_date = datetime.now(timezone.utc).date().isoformat()
    try:
        parsed_date = datetime.strptime(capture_date, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ClipError("The capture date is invalid.") from exc
    if parsed_date != capture_date:
        raise ClipError("The capture date is invalid.")

    normalized_source = normalize_url(source)
    dated_title = f"{capture_date}-{title}"
    base = _checked_candidate(destination, safe_filename(dated_title, source))
    if not base.exists() or (
        normalized_source in _sources_from_note(base)
        and _write_target_ok(base, webclip_id)
    ):
        return base

    for length in range(8, len(digest) + 1, 4):
        candidate = _checked_candidate(
            destination, _filename_with_suffix(dated_title, source, digest[:length])
        )
        if not candidate.exists() or (
            normalized_source in _sources_from_note(candidate)
            and _write_target_ok(candidate, webclip_id)
        ):
            return candidate
    raise ClipError("Unable to choose a unique filename for the clip.")


def _manual_section(text: str) -> str:
    start_marker = "<!-- webclip:manual:start -->\n"
    end_marker = "<!-- webclip:manual:end -->"
    start = text.find(start_marker)
    if start < 0:
        return ""
    start += len(start_marker)
    end = text.find(end_marker, start)
    return text[start:end] if end >= 0 else ""


def _managed_section(text: str) -> str | None:
    start_marker = "<!-- webclip:managed:start -->\n"
    end_marker = "<!-- webclip:managed:end -->"
    start = text.find(start_marker)
    if start < 0:
        return None
    start += len(start_marker)
    end = text.find(end_marker, start)
    return text[start:end] if end >= 0 else None


# Fields that describe the source page rather than the rendering of it. Only these
# decide whether a body difference came from the site or from the renderer:
# `status`, `category` and `tags` are the reader's own edits, `word_count` is filled
# in by the caller, and `content_hash` is the renderer's own fingerprint.
_SOURCE_FIELDS = (
    "title",
    "url",
    "original_url",
    "original_host",
    "author",
    "site",
    "published",
    "description",
    "keywords",
    "extraction_method",
    "webclip_id",
)

_HASH_FIELDS = ("source_content_hash", "content_hash")


def _source_fields(metadata: dict[str, object]) -> dict[str, object]:
    return {key: metadata.get(key) for key in _SOURCE_FIELDS}


def _valid_hashes(metadata: dict[str, object]) -> bool:
    """True only when both fingerprints are well-formed sha256 digests."""
    for key in _HASH_FIELDS:
        value = metadata.get(key)
        if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
            return False
    return True


def _note_semantic_state(text: str) -> tuple[dict[str, object], str] | None:
    metadata = _frontmatter_from_text(text)
    managed = _managed_section(text)
    if metadata is None or managed is None:
        return None
    comparable_metadata = dict(metadata)
    comparable_metadata.pop("created", None)
    return comparable_metadata, managed


def _with_manual_section(note: str, manual: str) -> str:
    marker = "<!-- webclip:manual:start -->\n"
    start = note.find(marker)
    end_marker = "<!-- webclip:manual:end -->"
    end = note.find(end_marker, start + len(marker)) if start >= 0 else -1
    if start < 0 or end < 0:
        raise ClipError("The generated note is missing managed boundaries.")
    return note[: start + len(marker)] + manual + note[end:]


_FAVORITE_LINE = re.compile(r"^favorite[ \t]*:")


def _find_original_host_index(lines: Sequence[str]) -> int | None:
    """Return the index of the top-level ``original_host`` key, if present.

    YAML top-level keys start at column zero. Matching without stripping
    leading whitespace keeps indented continuation lines inside multi-line
    values from being mistaken for the real key.
    """
    for i, line in enumerate(lines):
        if line.startswith("original_host:"):
            return i
    return None


def _favorite_insert_index(lines: Sequence[str]) -> int:
    """Return the index where ``favorite: true`` belongs.

    Immediately after the top-level ``original_host`` key, or at the end of
    the frontmatter when that key is absent.
    """
    host_index = _find_original_host_index(lines)
    return len(lines) if host_index is None else host_index + 1


def _favorite_position_ok(lines: Sequence[str], index: int) -> bool:
    """Return whether the favorite line at *index* sits in its canonical spot."""
    host_index = _find_original_host_index(lines)
    if host_index is not None:
        return index == host_index + 1
    return index == len(lines) - 1


def _remove_existing_favorite(lines: list[str]) -> list[str]:
    """Remove any existing favorite lines from the list, return the filtered list."""
    return [line for line in lines if not _FAVORITE_LINE.match(line)]


def _insert_favorite(lines: list[str]) -> list[str]:
    """Insert exactly one canonical favorite line at its canonical position."""
    remaining = _remove_existing_favorite(lines)
    remaining.insert(_favorite_insert_index(remaining), "favorite: true")
    return remaining


def _set_favorite_marker(text: str, favorite: bool) -> tuple[str, bool]:
    """Add or remove the favorite key in a managed note's frontmatter.

    Only the favorite line is touched, so the remaining frontmatter and the
    body (including the manual section) stay byte-for-byte unchanged.

    The favorite marker is inserted after the ``original_host`` field
    when adding, to keep the frontmatter well-organized.
    """
    normalized = _normalize_text(text)
    if not normalized.startswith("---\n"):
        raise ClipError("The clipped note has no YAML frontmatter to update.")
    end = normalized.find("\n---\n", 4)
    if end < 0:
        raise ClipError("The clipped note has invalid frontmatter boundaries.")
    try:
        metadata = yaml.safe_load(normalized[4:end])
    except yaml.YAMLError as exc:
        raise ClipError("The clipped note has invalid YAML frontmatter.") from exc
    if not isinstance(metadata, dict):
        raise ClipError("The clipped note has invalid YAML frontmatter.")
    if not metadata.get("webclip_id"):
        raise ClipError("Refusing to modify a note that is not webclip-managed.")
    if (
        _managed_section(normalized) is None
        or "<!-- webclip:manual:start -->" not in normalized
        or "<!-- webclip:manual:end -->" not in normalized
    ):
        raise ClipError("The existing note is not a valid webclip note.")

    lines = normalized[4:end].split("\n")
    indexes = [index for index, line in enumerate(lines) if _FAVORITE_LINE.match(line)]

    if favorite:
        if metadata.get("favorite") is True and len(indexes) == 1:
            if lines[indexes[0]].strip() in {"favorite: true", "favorite: True"}:
                if _favorite_position_ok(lines, indexes[0]):
                    return text, False
        # Drop any existing marker and re-insert one at its canonical position,
        # so an out-of-place marker is repositioned instead of left behind.
        lines = _insert_favorite(lines)
    else:
        if not indexes:
            if "favorite" in metadata:
                raise ClipError(
                    "The favorite marker is not stored as a simple frontmatter field."
                )
            return text, False
        for index in reversed(indexes):
            del lines[index]
    return "---\n" + "\n".join(lines) + normalized[end:], True


def _read_note_for_marker(target: Path) -> str:
    """Read a note for a marker update, refusing symlinks and missing files."""
    if target.is_symlink():
        raise ClipError("Refusing to modify a symbolic-link note.")
    if not target.exists():
        raise ClipError("The clipped note does not exist.")
    try:
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ClipError("Could not read the existing clipped note.") from exc


def set_frontmatter_flag(target: Path, *, favorite: bool) -> str:
    """Set or clear the favorite marker without touching the article body."""
    existing = _read_note_for_marker(target)
    updated, changed = _set_favorite_marker(existing, favorite)
    if not changed:
        return "unchanged"
    atomic_write(target, updated)
    return "written"


def _has_favorite_flag(target: Path) -> bool:
    """Return whether the note already carries ``favorite: true``."""
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    metadata = _frontmatter_from_text(text)
    return bool(metadata and metadata.get("favorite") is True)


def _note_title(target: Path) -> str:
    """Return the note title for commit messages, falling back to its stem."""
    try:
        metadata = _frontmatter_from_text(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        metadata = None
    title = metadata.get("title") if metadata else None
    if not isinstance(title, str) or not title.strip():
        return target.stem
    return title.strip()


def _marker_commit_message(action: str, targets: Sequence[Path]) -> str:
    """One title for a single note, a count when several notes share the marker."""
    if len(targets) == 1:
        return f"{action}: {_note_title(targets[0])[:60]}"
    return f"{action}: {len(targets)} notes"


def write_managed_note(target: Path, content: str, *, refresh: bool) -> str:
    """Write a new managed note, no-op identical content, or require refresh."""
    if not target.exists():
        atomic_write(target, content)
        return "written"
    if target.is_symlink():
        raise ClipError("Refusing to replace a symbolic-link note.")
    try:
        existing = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ClipError("Could not read the existing clipped note.") from exc
    old_state = _note_semantic_state(existing)
    new_state = _note_semantic_state(content)
    if old_state is None or new_state is None:
        raise ClipError("The existing clipped note has invalid managed metadata.")
    old_meta, old_managed = old_state
    new_meta, new_managed = new_state
    if old_meta.get("webclip_id") != new_meta.get("webclip_id"):
        raise ClipError("Refusing to replace a note managed for a different URL.")
    if old_state == new_state:
        return "unchanged"
    if (
        old_managed == new_managed
        and {key: value for key, value in old_meta.items() if key != "favorite"}
        == {key: value for key, value in new_meta.items() if key != "favorite"}
    ):
        # The marker is user intent, not article content: apply it without
        # requiring --refresh while preserving the manual section.
        atomic_write(target, _with_manual_section(content, _manual_section(existing)))
        return "written"
    if (
        _valid_hashes(old_meta)
        and _valid_hashes(new_meta)
        and old_meta["source_content_hash"] == new_meta["source_content_hash"]
        and old_meta["content_hash"] != old_meta["source_content_hash"]
        and new_meta["content_hash"] != new_meta["source_content_hash"]
        and _source_fields(old_meta) == _source_fields(new_meta)
    ):
        # Same source, same source-derived metadata, both bodies already rendered
        # rather than raw: the managed body differs only because the renderer
        # changed (a new trim rule, link-shaped headings flattened). Rewrite
        # without demanding --refresh; the manual section survives and an existing
        # favorite marker is carried over.
        #
        # Everything else keeps the gate: a moved source, a still-raw note
        # (content_hash == source_content_hash, where the first render change
        # really does alter what the reader sees), or metadata missing a
        # fingerprint — where nothing can prove the source is unchanged.
        rewritten = content
        if old_meta.get("favorite") is True and new_meta.get("favorite") is not True:
            rewritten, _ = _set_favorite_marker(rewritten, True)
        atomic_write(target, _with_manual_section(rewritten, _manual_section(existing)))
        return "written"
    if not refresh:
        raise ClipError("The saved page changed; rerun with --refresh to update it.")
    atomic_write(target, _with_manual_section(content, _manual_section(existing)))
    return "written"
