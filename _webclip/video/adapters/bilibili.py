"""Bilibili adapter.

Bilibili never publishes a ``<video src>``: the playable address comes from the
player API. That API has two shapes, and the difference matters here.

* ``fnval=4048`` returns DASH — separate video and audio tracks, 480P at best
  for an anonymous caller, and the preferred CDN entry is frequently a PCDN node
  on a non-default port (``...mcdn.bilivideo.cn:8082``). :mod:`_webclip.netguard`
  refuses non-default ports by policy, so that entry would be rejected outright.
* ``platform=html5&high_quality=1`` returns ``durl``: one muxed mp4 that needs no
  merging, reaches 720P anonymously, and points at a plain ``upos-sz-*`` host.
  Measured 2026-11-18 on seven videos: ``quality=64`` every time, one 51.97 MB
  file for a 3:32 clip, 1280x720 h264 + aac.

So this adapter asks for the second shape and reuses the existing direct
downloader. A video that only ships DASH is reported as an error; returning an
empty list would be indistinguishable from "this page has no video", which is the
failure mode this whole subsystem exists to avoid.
"""

from __future__ import annotations

from typing import Any, Mapping
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from ...core import ClipError
from ...netguard import fetch_bytes
from ..models import VideoCandidate

_API_ROOT = "https://api.bilibili.com"
_REFERER = "https://www.bilibili.com/"
# The CDN endpoints answer this Referer and reject requests without it (403).
_HEADERS = {"Referer": _REFERER}
_MAX_API_BYTES = 1_000_000
_VIDEO_ID_RE = re.compile(r"(BV[0-9A-Za-z]{10}|av\d+)", re.IGNORECASE)
_BARE_HOSTS = {"bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv"}
_LIVE_HOST = "live.bilibili.com"
_UNSUPPORTED_PREFIXES = ("/bangumi/", "/cheese/")


def _page_number(query: str) -> int:
    values = parse_qs(query).get("p") or []
    if not values:
        return 1
    try:
        page = int(values[0])
    except ValueError:
        return 1
    return page if page >= 1 else 1


def _host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _id_params(video_id: str) -> dict[str, object]:
    """``aid`` takes the bare number: ``aid=av80433022`` is rejected with -400."""
    if video_id.lower().startswith("av"):
        return {"aid": video_id[2:]}
    return {"bvid": video_id}


class BilibiliAdapter:
    name = "bilibili"
    #: The video page has no article worth extracting; the API carries the title.
    needs_article = False

    def matches(self, url: str) -> bool:
        host = _host_of(url)
        if host == _LIVE_HOST:
            return True
        if host.endswith(".bilibili.com"):
            return True
        return host in _BARE_HOSTS

    def discover(
        self, url: str, *, article: Mapping[str, object] | None = None
    ) -> list[VideoCandidate]:
        page_url = self._follow_short_link(url)
        parts = urlsplit(page_url)
        host = (parts.hostname or "").lower()

        if host == _LIVE_HOST:
            raise ClipError(
                "Bilibili live streams are not supported: there is no fixed video file to save."
            )
        if parts.path.lower().startswith(_UNSUPPORTED_PREFIXES):
            raise ClipError(
                "Bilibili bangumi and paid courses are not supported: they are DRM-protected."
            )
        match = _VIDEO_ID_RE.search(parts.path)
        if not match:
            raise ClipError(
                "This Bilibili URL has no video id; expected /video/BV... or /video/av...."
            )

        page = _page_number(parts.query)
        info = self._view(match.group(1))
        pages = info.get("pages")
        if not isinstance(pages, list) or not pages:
            raise ClipError("Bilibili returned no video parts for this URL.")
        if page > len(pages):
            raise ClipError(
                f"This video has {len(pages)} parts; ?p={page} is out of range."
            )
        selected = pages[page - 1]
        if not isinstance(selected, dict):
            raise ClipError("Bilibili returned an unreadable part list.")
        cid = selected.get("cid")
        if isinstance(cid, bool) or not isinstance(cid, int):
            raise ClipError("Bilibili returned no cid for this video.")

        title = str(info.get("title") or "").strip()
        if len(pages) > 1:
            # Every part of a multi-part video would otherwise share one filename.
            part_title = str(selected.get("part") or "").strip()
            suffix = f"P{page} {part_title}".strip()
            title = f"{title} - {suffix}" if title else suffix

        src = self._durl(match.group(1), cid)
        return [
            VideoCandidate(
                src=src,
                type="video/mp4",
                title=title,
                origin="bilibili",
            )
        ]

    def headers(self, url: str) -> Mapping[str, str]:
        return dict(_HEADERS)

    def _follow_short_link(self, url: str) -> str:
        """Resolve ``b23.tv`` to the page it redirects to.

        ``fetch_bytes`` follows redirects itself and returns the final URL, so
        one small request is enough: the body is discarded.
        """
        if _host_of(url) != "b23.tv":
            return url
        try:
            final, _body = fetch_bytes(url, headers=_HEADERS, timeout=20, max_bytes=200_000)
        except ClipError as exc:
            raise ClipError("The b23.tv short link could not be resolved.") from exc
        return final

    def _api(self, path: str, params: Mapping[str, object]) -> dict[str, Any]:
        target = f"{_API_ROOT}{path}?{urlencode(params)}"
        try:
            _final, body = fetch_bytes(
                target, headers=_HEADERS, timeout=20, max_bytes=_MAX_API_BYTES
            )
        except ClipError as exc:
            raise ClipError("The Bilibili API could not be reached.") from exc
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ClipError("Bilibili returned an unreadable API response.") from exc
        if not isinstance(payload, dict):
            raise ClipError("Bilibili returned an unreadable API response.")
        code = payload.get("code")
        if code != 0:
            message = str(payload.get("message") or "no message")
            raise ClipError(f"Bilibili refused the request (code {code}: {message}).")
        return payload

    def _view(self, video_id: str) -> dict[str, Any]:
        payload = self._api("/x/web-interface/view", _id_params(video_id))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ClipError("Bilibili returned no metadata for this video.")
        return data

    def _durl(self, video_id: str, cid: int) -> str:
        payload = self._api(
            "/x/player/playurl",
            {
                **_id_params(video_id),
                "cid": cid,
                # The html5 player is served one muxed file instead of DASH.
                "platform": "html5",
                "high_quality": 1,
                "qn": 80,
            },
        )
        data = payload.get("data")
        entries = data.get("durl") if isinstance(data, dict) else None
        if not isinstance(entries, list) or not entries:
            raise ClipError(
                "Bilibili returned no downloadable file for this video; "
                "it may only offer DASH streams."
            )
        first = entries[0]
        src = first.get("url") if isinstance(first, dict) else None
        if not isinstance(src, str):
            raise ClipError("Bilibili returned an unreadable download address.")
        # The address is page-controlled: only http(s) may reach the downloader.
        try:
            parsed = urlsplit(src)
        except ValueError as exc:
            raise ClipError("Bilibili returned an invalid download address.") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ClipError("Bilibili returned an invalid download address.")
        return src
