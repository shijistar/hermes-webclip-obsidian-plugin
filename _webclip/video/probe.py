"""Playlist pre-flight.

A playlist costs kilobytes; the media costs gigabytes. So the playlist is read
first and its tags decide whether downloading is even possible:

* ``EXT-X-KEY`` **or** ``EXT-X-SESSION-KEY`` with a method other than ``NONE``
  means the segments are encrypted. The session-key form is how DRM (Widevine,
  FairPlay) is declared on a *master* playlist — the media playlist below it
  often carries no key at all — so both must be recognised or protected streams
  slip through as "unencrypted".
* ``EXT-X-STREAM-INF`` means a master playlist: the real media playlist is one
  level down and has to be read again.
* A missing ``EXT-X-ENDLIST`` means a live stream: downloading captures only
  what elapsed, so the caller refuses instead of writing a truncated file.

Every check runs on the text that was actually parsed. Re-fetching the playlist
later and trusting the earlier verdict would leave a window where a server can
swap in an encrypted playlist between the two requests.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping
from urllib.parse import urljoin

from ..core import ClipError
from ..netguard import fetch_bytes

MAX_PLAYLIST_BYTES = 2 * 1024 * 1024
MAX_MASTER_DEPTH = 1

_EXTINF_RE = re.compile(r"^#EXTINF:\s*([0-9.]+)", re.MULTILINE)
_DURATION_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_KEY_RE = re.compile(r"^#EXT-X-(?:SESSION-)?KEY:(.*)$", re.MULTILINE)
_STREAM_INF_PREFIX = "#EXT-X-STREAM-INF"
# Tags whose semantics this downloader would silently ignore: a byte-range
# playlist would download the whole resource once per entry, and an fMP4
# playlist needs its `EXT-X-MAP` initialisation section to be parseable at all.
_UNSUPPORTED_TAGS = ("#EXT-X-BYTERANGE", "#EXT-X-MAP")


@dataclass(frozen=True)
class PlaylistInfo:
    url: str
    segments: int
    duration_s: float
    encrypted: bool
    live: bool
    variants: tuple[str, ...]
    #: A tag whose semantics this downloader does not implement; the playlist is
    #: refused rather than downloaded incorrectly.
    unsupported: str = ""


def _reject_unsupported(info: PlaylistInfo) -> None:
    if info.unsupported:
        raise ClipError(
            f"The video playlist uses {info.unsupported}, which this downloader "
            "does not support yet."
        )


def _variants(text: str, *, url: str) -> tuple[str, ...]:
    """URIs following each ``#EXT-X-STREAM-INF`` tag.

    Read line by line rather than with one regex: a blank line or an
    ``#EXT-X-MEDIA`` tag between the tag and its URI shows up in the wild, and a
    strict ``\\n(?!\\#)`` pattern then reports "no variants" — which looks like a
    media playlist with zero segments instead of a master we failed to read.

    One forward pass: a previous slice-per-variant version was O(n²), so a
    playlist of 50k ``STREAM-INF`` lines (still under the 2 MB cap) burned
    ~1.25 billion candidate visits while the run held the vault lock.
    """
    found: list[str] = []
    pending = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith(_STREAM_INF_PREFIX):
            pending = True
            continue
        if not pending or not stripped or stripped.startswith("#"):
            continue
        found.append(urljoin(url, stripped))
        pending = False
    return tuple(found)


_URI_ATTR_RE = re.compile(r'URI\s*=\s*"[^"]*"', re.IGNORECASE)
_METHOD_ATTR_RE = re.compile(r'METHOD\s*=\s*"?([A-Za-z0-9-]+)"?', re.IGNORECASE)


def _is_encrypted(text: str) -> bool:
    for match in _KEY_RE.finditer(text):
        # Drop the URI first: it can itself contain `METHOD=NONE`
        # (`…?METHOD=NONE`), which would make an encrypted stream look plain.
        attributes = _URI_ATTR_RE.sub("", match.group(1))
        method = _METHOD_ATTR_RE.search(attributes)
        if method is None or method.group(1).upper() != "NONE":
            return True
    return False


def parse_playlist(text: str, *, url: str) -> PlaylistInfo:
    if not text.lstrip().startswith("#EXTM3U"):
        raise ClipError("The video playlist is not a valid HLS playlist.")
    durations = _EXTINF_RE.findall(text)
    for value in durations:
        # The tag regex is permissive (`[0-9.]+`), so `#EXTINF:1.2.3` and `#EXTINF:.`
        # reach `float()` and raise ValueError — which is not a ClipError and would
        # abort the whole batch instead of failing one candidate.
        if not _DURATION_RE.fullmatch(value):
            raise ClipError("The video playlist contains an invalid segment duration.")
    upper = text.upper()
    unsupported = next((tag for tag in _UNSUPPORTED_TAGS if tag in upper), "")
    return PlaylistInfo(
        url=url,
        segments=len(durations),
        duration_s=round(sum(float(value) for value in durations), 3),
        encrypted=_is_encrypted(text),
        live="#EXT-X-ENDLIST" not in text,
        variants=_variants(text, url=url),
        unsupported=unsupported,
    )


def probe(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30,
) -> PlaylistInfo:
    """Read a media playlist, following one level of master playlist."""
    final_url, body = fetch_bytes(
        url, headers=headers, timeout=timeout, max_bytes=MAX_PLAYLIST_BYTES
    )
    info = parse_playlist(body.decode("utf-8", errors="replace"), url=final_url)
    _reject_unsupported(info)
    if info.encrypted:
        # A session key on the master protects every variant below it. Report it
        # here instead of descending: the media playlist usually carries no key,
        # so a second read would look clean.
        return info

    depth = 0
    while info.variants and depth < MAX_MASTER_DEPTH:
        # Prefer the first variant: pages list them best-first and we have no
        # bandwidth probe to do better.
        final_url, body = fetch_bytes(
            info.variants[0], headers=headers, timeout=timeout, max_bytes=MAX_PLAYLIST_BYTES
        )
        info = parse_playlist(body.decode("utf-8", errors="replace"), url=final_url)
        _reject_unsupported(info)
        depth += 1
        if info.encrypted:
            return info
    if info.variants:
        raise ClipError("The video playlist nests master playlists too deeply.")
    return info


def segment_urls(text: str, *, playlist_url: str) -> list[str]:
    """Media segment URLs in playback order, resolved against the playlist."""
    urls: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        urls.append(urljoin(playlist_url, stripped))
    return urls


def read_media_playlist(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30,
) -> tuple[PlaylistInfo, list[str]]:
    """Return the media playlist and its segment URLs.

    The refusal checks are repeated on this reading: the caller pre-flighted an
    earlier response, and a server that rotates playlists could otherwise hand
    us an encrypted one here.
    """
    final_url, body = fetch_bytes(
        url, headers=headers, timeout=timeout, max_bytes=MAX_PLAYLIST_BYTES
    )
    text = body.decode("utf-8", errors="replace")
    info = parse_playlist(text, url=final_url)
    _reject_unsupported(info)
    if info.variants:
        raise ClipError("A master playlist must be probed before its segments are read.")
    if info.encrypted:
        raise ClipError("The video stream is encrypted (DRM or AES-128).")
    if info.live:
        raise ClipError("The video is a live stream.")
    if info.segments == 0:
        raise ClipError("The video playlist contains no segments.")
    return info, segment_urls(text, playlist_url=final_url)
