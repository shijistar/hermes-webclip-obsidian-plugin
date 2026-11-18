"""Direct HTTP download of a single media file."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from ...core import ClipError
from ...netguard import download_to_file
from ..models import DownloadPlan, DownloadedFile
from .ffmpeg import probe_duration


def download_direct(
    plan: DownloadPlan,
    destination: Path,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 60,
    max_bytes: int = 500 * 1024 * 1024,
) -> DownloadedFile:
    """Try each planned URL in order; a partial file is always cleaned up."""
    merged_headers: dict[str, str] = dict(plan.headers)
    if headers:
        merged_headers.update(headers)
    last_error: ClipError | None = None
    for url in plan.urls:
        try:
            _, written = download_to_file(
                url,
                destination,
                headers=merged_headers,
                timeout=timeout,
                max_bytes=max_bytes,
            )
        except ClipError as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            continue
        if written < 1024:
            # A placeholder kept by a lazy-loading template (a transparent GIF,
            # a redirect body) is a few hundred bytes, not a video.
            destination.unlink(missing_ok=True)
            last_error = ClipError("The video file is too small to be a video.")
            continue
        return DownloadedFile(
            path=destination,
            bytes_written=written,
            duration_s=probe_duration(destination),
        )
    raise ClipError(f"Downloading the video failed: {last_error}")
