"""Markdown sanitation and note rendering."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Mapping
from urllib.parse import urlsplit
import hashlib
import re
import yaml

from .article import _validate_success_payload
from .core import ClipError, _normalize_text
from .urls import _url_hash, normalize_url

_REMOTE_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\((https?://[^\s)]+)(?:\s+\"[^\"]*\")?\)", re.IGNORECASE)


def _content_hash(markdown: str) -> str:
    normalized = _normalize_text(markdown).rstrip("\n") + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


_DANGEROUS_SCHEMES = r"(?:javascript|vbscript|file|obsidian|data)"


_INLINE_CODE_SPAN = re.compile(r"(`+)([^`\n]*?)\1")


_VIDEO_TAG_RE = re.compile(r"(?is)<video\b[^>]*>\s*</video>")


_VIDEO_SRC_ATTR_RE = re.compile(r"""(?i)\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)')""")


_SAFE_VIDEO_SRC_RE = re.compile(r"^https?://[^\s\"'<>]+$", re.IGNORECASE)


_VIDEO_PLACEHOLDER = "\x00webclip-video-{index}\x00"


def _canonical_video_tag(tag: str) -> str | None:
    """Return a rebuilt, safe ``<video>`` tag when *tag* has a safe http(s) src.

    The tag is rebuilt from scratch so no attacker-controlled attributes (event
    handlers, ``srcset``, etc.) survive sanitization; only a validated URL is
    carried over. Returns ``None`` when the src is missing or unsafe, letting
    the normal HTML-escaping path neutralize the tag.
    """
    match = _VIDEO_SRC_ATTR_RE.search(tag)
    if not match:
        return None
    src = match.group(1) if match.group(1) is not None else match.group(2)
    if not _SAFE_VIDEO_SRC_RE.match(src):
        return None
    return f'<video src="{src}" controls preload="metadata" playsinline></video>'


def _protect_video_tags(text: str) -> tuple[str, list[str]]:
    """Swap validated ``<video>`` tags for placeholders so sanitization keeps them."""
    tags: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        canonical = _canonical_video_tag(match.group(0))
        if canonical is None:
            return match.group(0)
        index = len(tags)
        tags.append(canonical)
        return _VIDEO_PLACEHOLDER.format(index=index)

    return _VIDEO_TAG_RE.sub(_replace, text), tags


def _restore_video_tags(text: str, tags: list[str]) -> str:
    for index, tag in enumerate(tags):
        text = text.replace(_VIDEO_PLACEHOLDER.format(index=index), tag)
    return text


def _sanitize_active_markdown_segment(text: str) -> str:
    text, video_tags = _protect_video_tags(text)
    text = re.sub(r"(?s)<!--.*?-->", "", text)
    dangerous_tags = r"script|iframe|object|embed|form|input|button|textarea|select|option|style|link|meta|base|svg|math"
    text = re.sub(
        rf"(?is)<(?P<tag>{dangerous_tags})\b[^>]*>.*?</(?P=tag)\s*>",
        "",
        text,
    )
    text = re.sub(rf"(?is)</?(?:{dangerous_tags})\b[^>]*>", "", text)
    text = re.sub(r"(?i)<(?=/?[A-Za-z][A-Za-z0-9-]*(?:\s|/?>))", "&lt;", text)
    text = re.sub(
        rf"(?i)(\]\(\s*<?){_DANGEROUS_SCHEMES}:",
        r"\1blocked:",
        text,
    )
    text = re.sub(
        rf"(?im)^(\s*\[[^\]\n]+\]:\s*<?){_DANGEROUS_SCHEMES}:",
        r"\1blocked:",
        text,
    )
    text = text.replace("[[", r"\[\[")
    return _restore_video_tags(text, video_tags)


def _sanitize_text_preserving_inline_code(text: str) -> str:
    pieces: list[str] = []
    cursor = 0
    for match in _INLINE_CODE_SPAN.finditer(text):
        pieces.append(_sanitize_active_markdown_segment(text[cursor:match.start()]))
        pieces.append(match.group(0))
        cursor = match.end()
    pieces.append(_sanitize_active_markdown_segment(text[cursor:]))
    return "".join(pieces)


def _scan_remote_images_in_plain_text(text: str, seen: set[str], found: list[str]) -> None:
    cursor = 0
    for inline_code in _INLINE_CODE_SPAN.finditer(text):
        _collect_remote_images(text[cursor:inline_code.start()], seen, found)
        cursor = inline_code.end()
    _collect_remote_images(text[cursor:], seen, found)


def _is_indented_code_line(line: str, leading_spaces: int | None = None) -> bool:
    if line.startswith("\t"):
        return True
    if leading_spaces is None:
        leading_spaces = len(line) - len(line.lstrip(" "))
    return leading_spaces >= 4 and bool(line.strip())


def _collect_remote_images(text: str, seen: set[str], found: list[str]) -> None:
    for match in _REMOTE_MARKDOWN_IMAGE.finditer(text):
        normalized_url = normalize_url(match.group(1))
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        found.append(normalized_url)


def sanitize_markdown(markdown: str) -> str:
    text = _normalize_text(markdown)
    result: list[str] = []
    plain: list[str] = []
    fenced: list[str] = []
    in_fence = False
    fence_char = ""
    fence_length = 0

    for line in text.splitlines(keepends=True):
        leading_spaces = len(line) - len(line.lstrip(" "))
        content = line[leading_spaces:]
        fence_match = None
        if leading_spaces <= 3:
            fence_match = re.match(r"(`{3,}|~{3,})", content)

        if in_fence:
            fenced.append(line)
            if fence_match:
                marker = fence_match.group(1)
                if marker[0] == fence_char and len(marker) >= fence_length:
                    result.append("".join(fenced))
                    fenced = []
                    in_fence = False
                    fence_char = ""
                    fence_length = 0
            continue

        if fence_match:
            if plain:
                result.append(_sanitize_text_preserving_inline_code("".join(plain)))
                plain = []
            marker = fence_match.group(1)
            in_fence = True
            fence_char = marker[0]
            fence_length = len(marker)
            fenced = [line]
            continue

        if _is_indented_code_line(line, leading_spaces):
            if plain:
                result.append(_sanitize_text_preserving_inline_code("".join(plain)))
                plain = []
            result.append(line)
            continue

        plain.append(line)

    if plain:
        result.append(_sanitize_text_preserving_inline_code("".join(plain)))
    if fenced:
        result.append("".join(fenced))
    return "".join(result)


def _contains_markdown_h1(markdown: str) -> bool:
    in_fence = False
    fence_char = ""
    fence_length = 0
    previous_text_line = None
    for raw_line in _normalize_text(markdown).split("\n"):
        if raw_line.startswith("\t"):
            previous_text_line = None
            continue

        leading_spaces = len(raw_line) - len(raw_line.lstrip(" "))
        content = raw_line[leading_spaces:]

        if leading_spaces <= 3:
            fence_match = re.match(r"(`{3,}|~{3,})", content)
            if fence_match:
                marker = fence_match.group(1)
                if not in_fence:
                    in_fence = True
                    fence_char = marker[0]
                    fence_length = len(marker)
                elif marker[0] == fence_char and len(marker) >= fence_length:
                    in_fence = False
                    fence_char = ""
                    fence_length = 0
                previous_text_line = None
                continue

        if in_fence:
            continue

        if leading_spaces >= 4:
            previous_text_line = None
            continue

        if re.match(r"^#(?:\s+\S|\s*$)", content):
            return True
        if re.match(r"^=+\s*$", content) and previous_text_line:
            return True

        previous_text_line = content if content.strip() else None
    return False


def _sanitized_heading_title(title: str) -> str:
    sanitized = sanitize_markdown(title)
    return re.sub(r"\s+", " ", sanitized).strip()


def _managed_markdown(title: str, markdown: str) -> str:
    cleaned_title = _sanitized_heading_title(title)
    cleaned_markdown = _normalize_text(markdown).rstrip("\n")
    if _contains_markdown_h1(cleaned_markdown):
        return cleaned_markdown
    if not cleaned_markdown:
        return f"# {cleaned_title}"
    return f"# {cleaned_title}\n\n{cleaned_markdown}"


def render_note(
    data: Mapping[str, object],
    created: str | None = None,
    *,
    content_markdown: str | None = None,
    image_mode: str | None = None,
    favorite: bool | None = None,
) -> str:
    """Render extractor data as normalized Markdown with YAML frontmatter."""
    if image_mode not in {None, "remote", "local"}:
        raise ClipError("The image save mode is invalid.")
    if favorite is not None and not isinstance(favorite, bool):
        raise ClipError("The favorite marker is invalid.")
    checked = _validate_success_payload(data)
    timestamp = created or datetime.now(timezone.utc).isoformat(timespec="seconds")
    source = normalize_url(str(checked["canonicalUrl"] or checked["url"]))
    fetched_url = normalize_url(str(checked["url"]))
    source_markdown = sanitize_markdown(str(checked["markdown"])).rstrip("\n")
    if content_markdown is not None and content_markdown and not source_markdown.strip():
        # A rendered body with no source text means source_content_hash would
        # fingerprint an empty string: the note would look complete while
        # carrying a fingerprint that describes nothing, and every later refresh
        # or "page changed" decision built on it would be vacuous. A body of pure
        # whitespace counts: stripping it here let " " through and produced a
        # note whose managed section held a heading and a space.
        raise ClipError(
            "The payload has a rendered body but an empty 'markdown' field. Pass the page "
            "text as article['markdown'] so source_content_hash fingerprints the source, and "
            "keep only the trimmed or re-rendered body in content_markdown."
        )
    effective_markdown = (
        _normalize_text(content_markdown).rstrip("\n")
        if content_markdown is not None
        else source_markdown
    )
    managed_markdown = _managed_markdown(str(checked["title"]), effective_markdown)
    metadata = {
        "title": checked["title"],
        "url": source,
        "author": checked["author"],
        "site": checked["site"],
        "description": checked["description"],
        "keywords": checked["keywords"],
        "tags": ["web-clip"],
        "original_url": source,
        "original_host": urlsplit(source).hostname or "",
        **({"favorite": True} if favorite else {}),
        **({"fetched_url": fetched_url} if fetched_url != source else {}),
        "extraction_method": checked["method"],
        "status": "needs-review",
        "category": "Inbox",
        "word_count": checked["wordCount"],
        "webclip_id": "sha256:" + _url_hash(source),
        "source_content_hash": "sha256:" + _content_hash(source_markdown),
        "content_hash": "sha256:" + _content_hash(effective_markdown),
        **({"image_mode": image_mode} if image_mode is not None else {}),
        "published": checked["published"],
        "created": timestamp,
    }
    frontmatter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip("\n")
    return (
        f"---\n{frontmatter}\n---\n\n"
        "<!-- webclip:managed:start -->\n"
        f"{managed_markdown}\n"
        "<!-- webclip:managed:end -->\n\n"
        "<!-- webclip:manual:start -->\n"
        "<!-- webclip:manual:end -->\n"
    )


def find_remote_images(markdown: str) -> list[str]:
    normalized = _normalize_text(markdown)
    found: list[str] = []
    seen: set[str] = set()
    plain: list[str] = []
    in_fence = False
    fence_char = ""
    fence_length = 0

    for line in normalized.splitlines(keepends=True):
        leading_spaces = len(line) - len(line.lstrip(" "))
        content = line[leading_spaces:]
        fence_match = None
        if leading_spaces <= 3:
            fence_match = re.match(r"(`{3,}|~{3,})", content)

        if in_fence:
            if fence_match:
                marker = fence_match.group(1)
                if marker[0] == fence_char and len(marker) >= fence_length:
                    in_fence = False
                    fence_char = ""
                    fence_length = 0
            continue

        if fence_match:
            if plain:
                _scan_remote_images_in_plain_text("".join(plain), seen, found)
                plain = []
            marker = fence_match.group(1)
            in_fence = True
            fence_char = marker[0]
            fence_length = len(marker)
            continue

        if _is_indented_code_line(line, leading_spaces):
            if plain:
                _scan_remote_images_in_plain_text("".join(plain), seen, found)
                plain = []
            continue

        plain.append(line)

    if plain:
        _scan_remote_images_in_plain_text("".join(plain), seen, found)
    return found
