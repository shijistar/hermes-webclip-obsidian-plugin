"""User-facing summary for ``/save-video``.

Every outcome is listed. A batch that quietly omits the failures is worse than
one that fails loudly: the user cannot tell "no video on that page" from "the
download broke".
"""

from __future__ import annotations

import re

from .models import VideoOutcome, VideoReport

# Above this size the file stays on disk only: pushing a multi-hundred-megabyte
# video through a chat upload usually times out, and the user asked for a local
# archive anyway.
MEDIA_ATTACH_LIMIT_BYTES = 50 * 1024 * 1024

STATUS_OK = "OK"
STATUS_FAILED = "FAILED"

_DIRECTIVE_RE = re.compile(r"(?i)\bmedia\s*:")
# An absolute path the platform would treat as a deliverable attachment. The
# guard skips a slash preceded by `:` or another slash so URLs survive intact.
_PATH_LIKE_RE = re.compile(r"(?<![\w:/])/(?:[\w.-]+/)*[\w.-]+")


def _text(value: str, limit: int = 300) -> str:
    """Flatten page-controlled text so it cannot act as a delivery directive.

    Page text reaches the chat verbatim, and the gateway turns both a `MEDIA:`
    tag and a bare existing absolute path into an upload. Collapsing whitespace
    kills the standalone-line shape; the substitution kills the tag and the
    path shape while leaving ordinary prose readable.
    """
    flat = " ".join(str(value).split())
    flat = _DIRECTIVE_RE.sub("media\uFF1A", flat)
    flat = _PATH_LIKE_RE.sub(lambda match: match.group(0).replace("/", "\u2044"), flat)
    return flat[:limit]


def _format_size(value: int) -> str:
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB"
    if value >= 1024:
        return f"{value / 1024:.0f} KB"
    return f"{value} B"


def _format_duration(value: float | None) -> str:
    if value is None:
        return "duration unknown"
    total = int(round(value))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _line(outcome: VideoOutcome) -> str:
    if not outcome.ok:
        return f"- FAILED {_text(outcome.source)}: {_text(outcome.message)}"
    if outcome.path is None:
        return f"- {STATUS_OK} {_text(outcome.title)}"
    # The saved filename, never the page's own text: a title can carry newlines
    # and absolute paths, and the gateway turns both `MEDIA:` tags and bare
    # existing paths into uploaded attachments.
    return (
        f"- {STATUS_OK} {outcome.path.name} → {outcome.path} "
        f"({_format_size(outcome.bytes_written)}, {_format_duration(outcome.duration_s)})"
    )


def render_report(report: VideoReport) -> str:
    if report.ignored:
        location = " (inside the vault, ignored by Git)"
    elif report.inside_vault:
        location = " (inside the vault, NOT ignored by Git)"
    else:
        location = ""
    lines = [
        f"Saved {len(report.succeeded)} of {len(report.outcomes)} video(s) "
        f"to {report.destination}{location}",
        "",
    ]
    lines.extend(_line(outcome) for outcome in report.outcomes)

    if report.warnings:
        lines.append("")
        lines.extend(f"Note: {warning}" for warning in report.warnings)

    attachments = [
        outcome.path
        for outcome in report.succeeded
        if outcome.path is not None and outcome.bytes_written <= MEDIA_ATTACH_LIMIT_BYTES
    ]
    if attachments:
        lines.append("")
        lines.extend(f"MEDIA:{path}" for path in attachments)
    elif report.succeeded:
        lines.append("")
        lines.append("Files are too large to attach; they stay in the destination directory.")
    return "\n".join(lines)
