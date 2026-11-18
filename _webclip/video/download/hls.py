"""HLS download: fetch segments ourselves, then remux locally.

The reason ffmpeg never sees the network here: a page-controlled playlist can
point its segments at a private address, and ffmpeg's HTTP client has no SSRF
guard and follows redirects on its own. So every segment goes through
:func:`_webclip.netguard.download_to_file`, and ffmpeg receives a concat list of
local files with ``-protocol_whitelist file``.
"""

from __future__ import annotations

from pathlib import Path
import os
import tempfile
from urllib.parse import urlsplit

from ...core import ClipError
from ...netguard import download_to_file
from ..models import DownloadPlan, DownloadedFile
from ..probe import probe, read_media_playlist
from .ffmpeg import probe_duration, run_ffmpeg

_SEGMENT_SUFFIXES = {".ts", ".m4s", ".mp4", ".m4v", ".aac", ".mp3", ".cmfv", ".cmfa"}


def _segment_name(index: int, url: str) -> str:
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix not in _SEGMENT_SUFFIXES:
        # The concat demuxer sniffs the container from the extension, so an
        # unknown one falls back to the transport-stream default.
        suffix = ".ts"
    return f"seg-{index:06d}{suffix}"


def _concat_line(path: Path) -> str:
    # ffmpeg's concat parser treats single quotes specially inside `file '...'`.
    escaped = str(path).replace("'", "'\\''")
    return f"file '{escaped}'\n"


def download_hls(
    plan: DownloadPlan,
    destination: Path,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 60,
    max_bytes: int = 500 * 1024 * 1024,
) -> DownloadedFile:
    merged_headers: dict[str, str] = dict(plan.headers)
    if headers:
        merged_headers.update(headers)

    info = probe(plan.urls[0], headers=merged_headers, timeout=timeout)
    if info.encrypted:
        raise ClipError(
            "The video stream is encrypted (DRM or AES-128); refusing to download it."
        )
    if info.live:
        raise ClipError(
            "The video is a live stream; only a partial recording would be captured."
        )
    if info.segments == 0:
        raise ClipError("The video playlist contains no segments.")

    # `info.url` is the media playlist: probing a master follows one level down,
    # and re-reading the original URL here would trip the master guard.
    media, segments = read_media_playlist(info.url, headers=merged_headers, timeout=timeout)
    if len(segments) > 5000:
        raise ClipError("The video playlist has too many segments to download.")

    with tempfile.TemporaryDirectory(prefix="webclip-video-") as tmp:
        parts: list[Path] = []
        downloaded = 0
        remaining = max_bytes
        for index, segment in enumerate(segments):
            if remaining <= 0:
                # Fail the whole download instead of hammering the remaining
                # segments with a one-byte ceiling until each one errors.
                raise ClipError("The video is larger than the configured size limit.")
            part = Path(tmp) / _segment_name(index, segment)
            _, written = download_to_file(
                segment,
                part,
                headers=merged_headers,
                timeout=timeout,
                max_bytes=remaining,
            )
            if written == 0:
                raise ClipError("A video segment came back empty.")
            remaining -= written
            downloaded += written
            parts.append(part)

        list_file = Path(tmp) / "segments.txt"
        list_file.write_text("".join(_concat_line(part) for part in parts), encoding="utf-8")
        # ffmpeg opens its output with fopen() and `-y`: that follows a symlink
        # and truncates its target. Claiming the name exclusively first makes
        # ffmpeg truncate the inode created here instead of whatever a
        # pre-placed symlink pointed at.
        os.close(
            os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        )
        run_ffmpeg(
            [
                "-protocol_whitelist",
                "file",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(destination),
            ]
        )

    if not destination.is_file() or destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise ClipError("Merging the downloaded stream produced an empty file.")

    return DownloadedFile(
        path=destination,
        bytes_written=destination.stat().st_size,
        duration_s=probe_duration(destination) or media.duration_s,
    )
