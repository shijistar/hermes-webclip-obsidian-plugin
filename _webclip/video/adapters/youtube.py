"""YouTube adapter.

YouTube is the one site here whose media the plugin does not fetch itself: the
signature handling needs a JavaScript runtime, so the download goes through
``yt-dlp``. This adapter therefore only answers two questions — does the URL
belong to YouTube, and what is the video called — and produces exactly one
candidate carrying ``kind="ytdlp"``.

That ``kind`` is the only thing that may switch on the subprocess backend. It is
never used as a fallback for "a direct download failed": a page-controlled URL
must not reach a tool that speaks to 1800 sites by itself.
"""

from __future__ import annotations

from typing import Mapping
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from ...core import ClipError
from ...netguard import fetch_bytes
from ..models import VideoCandidate

_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }
)
_OEMBED = "https://www.youtube.com/oembed"
_MAX_OEMBED_BYTES = 64_000
#: A video id is 11 characters of base64url.
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_SHORT_PATH_PREFIXES = ("/shorts/", "/embed/")
#: Path segments that satisfy `_VIDEO_ID_RE` but are playlist embeds, not ids.
#: ``/embed/videoseries?list=…`` is the shape blogs embed; yt-dlp would route it
#: to its playlist extractor and `--playlist-items 1` would save the first entry
#: as if it were the requested video.
_NOT_VIDEO_IDS = frozenset({"videoseries"})
_NOT_A_VIDEO = (
    "This YouTube URL is not a single video; playlists, channels and search "
    "results are not supported."
)


def _as_video_id(candidate: str) -> str:
    """*candidate* if it is an 11-character video id, otherwise ``""``."""
    if candidate in _NOT_VIDEO_IDS:
        return ""
    return candidate if _VIDEO_ID_RE.match(candidate) else ""


def _video_id(url: str) -> str:
    """The id of the single video behind *url*, or ``""``.

    ``--no-playlist`` only constrains URLs that carry a video *and* a list. A
    bare ``/playlist``, ``/@handle`` or ``/channel/`` URL is a pure list, so
    yt-dlp would happily walk 249 entries (measured) — past ``max_per_run``,
    onto disk one file at a time, holding the vault lock throughout. The shape
    check below is what actually keeps a batch a batch.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    host = (parts.hostname or "").lower()
    path = parts.path.rstrip("/") or "/"

    if host == "youtu.be":
        return _as_video_id(path.lstrip("/"))

    if path == "/watch":
        values = parse_qs(parts.query).get("v") or []
        return _as_video_id(values[0].strip() if values else "")

    for prefix in _SHORT_PATH_PREFIXES:
        if path.startswith(prefix):
            return _as_video_id(path[len(prefix) :])
    return ""


class YoutubeAdapter:
    name = "youtube"
    #: The page is a player, not an article; nothing here needs the extractor.
    needs_article = False

    def matches(self, url: str) -> bool:
        try:
            host = (urlsplit(url).hostname or "").lower()
        except ValueError:
            return False
        return host in _HOSTS

    def discover(
        self, url: str, *, article: Mapping[str, object] | None = None
    ) -> list[VideoCandidate]:
        if not _video_id(url):
            raise ClipError(_NOT_A_VIDEO)
        return [
            VideoCandidate(
                src=url,
                type="video/mp4",
                title=self._title(url),
                origin="youtube",
                kind="ytdlp",
            )
        ]

    def headers(self, url: str) -> Mapping[str, str]:
        # yt-dlp brings its own headers and cookies; adding ours would be noise.
        return {}

    def _title(self, url: str) -> str:
        """Ask the public oEmbed endpoint; an empty title is not an error.

        A missing title only costs a less readable filename (the URL hash takes
        over), so every failure here degrades instead of aborting.
        """
        target = f"{_OEMBED}?{urlencode({'url': url, 'format': 'json'})}"
        try:
            _final, body = fetch_bytes(target, timeout=15, max_bytes=_MAX_OEMBED_BYTES)
            payload = json.loads(body.decode("utf-8"))
        except (ClipError, UnicodeDecodeError, json.JSONDecodeError):
            return ""
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("title") or "").strip()
