"""Netease adapter.

Netease needs its own path for two reasons the generic collector cannot cover:

* a ``/news/v/<ID>.html`` page has no article body, so the extractor's quality
  gate rejects it before any ``videos`` field exists (measured: this is why the
  clip pipeline carries a curl fallback for exactly these URLs);
* the player publishes the stream in ``data-m3u8`` / ``data-mp4`` attributes,
  and the value is frequently protocol-relative (``//flv0...``). ``data-mp4``
  may also be the literal string ``"undefined"`` while ``data-m3u8`` holds the
  real address.

So this adapter fetches the page itself and scans the raw HTML. It is the one
place allowed to use a page-wide regex, and the pattern is narrow: only URLs
that end in a container extension count.
"""

from __future__ import annotations

from typing import Mapping
import html as html_module
import re
from urllib.parse import urljoin, urlsplit

from ..models import VideoCandidate
from ...core import ClipError
from ...sites import _fetch_netease_video_html

_STREAM_ATTRIBUTE_RE = re.compile(
    r'data-(?:m3u8|mp4|hls|video-url)\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE
)
_STREAM_URL_RE = re.compile(
    r'(?:https?:)?//[^\s"\'<>]+\.(?:m3u8|mp4)(?:\?[^\s"\'<>]*)?', re.IGNORECASE
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_FIGURE_ALT_RE = re.compile(
    r'<figure[^>]*\bdata-alt\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE
)
_TITLE_SUFFIXES = ("_网易视频", "-网易视频", "_手机网易网", "_网易新闻", "-网易新闻")

_PLACEHOLDERS = {"", "undefined", "null", "none"}


def _clean_title(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw)
    text = html_module.unescape(text).strip()
    for suffix in _TITLE_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def _absolutize(value: str, page_url: str) -> str | None:
    candidate = html_module.unescape(value.strip())
    if candidate.lower() in _PLACEHOLDERS:
        return None
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    elif candidate.startswith("/"):
        candidate = urljoin(page_url, candidate)
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return candidate


class NeteaseAdapter:
    name = "netease"
    needs_article = False

    def matches(self, url: str) -> bool:
        try:
            hostname = urlsplit(url).hostname or ""
        except ValueError:
            return False
        return hostname == "163.com" or hostname.endswith(".163.com")

    def discover(
        self, url: str, *, article: Mapping[str, object] | None = None
    ) -> list[VideoCandidate]:
        try:
            page = _fetch_netease_video_html(url)
        except ClipError as exc:
            raise ClipError("The Netease page could not be fetched.") from exc

        title_match = _TITLE_RE.search(page)
        page_title = _clean_title(title_match.group(1)) if title_match else ""
        figure_match = _FIGURE_ALT_RE.search(page)
        figure_title = html_module.unescape(figure_match.group(1)).strip() if figure_match else ""
        title = figure_title or page_title

        raw_values: list[str] = []
        raw_values.extend(_STREAM_ATTRIBUTE_RE.findall(page))
        raw_values.extend(_STREAM_URL_RE.findall(page))

        candidates: list[VideoCandidate] = []
        seen: set[str] = set()
        for value in raw_values:
            resolved = _absolutize(value, url)
            if not resolved or resolved in seen:
                continue
            seen.add(resolved)
            candidates.append(
                VideoCandidate(
                    src=resolved,
                    type="application/x-mpegURL" if ".m3u8" in resolved.lower() else "video/mp4",
                    title=title,
                    origin="netease",
                )
            )
        return candidates

    def headers(self, url: str) -> Mapping[str, str]:
        return {"Referer": "https://www.163.com/"}
