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
from urllib.parse import urlencode, urlsplit

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
