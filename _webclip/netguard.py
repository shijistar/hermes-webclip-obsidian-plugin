"""SSRF-safe HTTP access for media downloads.

A `<video>` source is attacker-controlled text: without a guard, the download
layer would happily connect to `http://192.168.1.1/`, a link-local metadata
endpoint, or a hostname that resolves public first and private second. This
module owns the two checks that prevent that:

* **resolve then pin** — the hostname is resolved once, every answer must be a
  public address, and the connection is made to *that* address, so a later DNS
  answer cannot move us into the private range (DNS rebinding);
* **per-hop validation** — every redirect target is resolved and validated
  again before it is requested.

The blocked-network table and the pinned connection classes live in
``images.py`` and are imported here on purpose: "what counts as public" must
have exactly one definition in the repository. Anything image-specific (its
headers, its fixed 15 MB ceiling, its error wording) stays there.
"""

from __future__ import annotations

from pathlib import Path
import http.client
import os
import socket
import ssl
from typing import Mapping
from urllib.parse import urljoin, urlsplit

from .core import ClipError
from .images import (
    _ApprovedRemoteImageUrl as ApprovedAddress,
    _PinnedHTTPConnection,
    _PinnedHTTPSConnection,
    _is_blocked_remote_ip,
    _remote_host_header,
)
from .urls import normalize_url

DEFAULT_USER_AGENT = "Mozilla/5.0 Hermes webclip-obsidian"
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5
CHUNK_BYTES = 64 * 1024

_POLICY_MESSAGE = "The video address is blocked by network policy."
_TOO_LARGE_MESSAGE = "The video is larger than the configured size limit."
_TRUNCATED_MESSAGE = "The video server ended the response before its declared length."
_REDIRECT_LIMIT_MESSAGE = "The video address redirected too many times."
_BAD_REDIRECT_MESSAGE = "The video address returned an invalid redirect."


# `ApprovedAddress` is the same frozen record the image pipeline uses, so the
# shape of "a resolved and approved URL" has exactly one definition.


def resolve_and_validate(
    value: str, *, resolver=socket.getaddrinfo
) -> ApprovedAddress:
    """Resolve *value* and refuse anything that is not a public http(s) host."""
    normalized = normalize_url(value)
    parsed = urlsplit(normalized)
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname or ""
    default_port = 80 if scheme == "http" else 443
    port = parsed.port or default_port
    # Non-default ports are refused: a page-supplied `:8082` is either a P2P
    # CDN node we cannot reach or an attempt to reach something else entirely.
    if parsed.port is not None and port != default_port:
        raise ClipError(_POLICY_MESSAGE)
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ClipError(_POLICY_MESSAGE) from exc
    try:
        infos = resolver(
            ascii_hostname, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except OSError as exc:
        raise ClipError("The video hostname could not be resolved.") from exc
    if not infos:
        raise ClipError("The video hostname could not be resolved.")

    approved: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for family, _socktype, _proto, _canonname, sockaddr in infos:
        if family not in {socket.AF_INET, socket.AF_INET6} or not sockaddr:
            raise ClipError(_POLICY_MESSAGE)
        address = sockaddr[0]
        key = (family, address)
        if key in seen:
            continue
        seen.add(key)
        # One private answer is enough to reject the hostname: the rest of the
        # answers may be public, but we cannot tell which one the request would
        # have used.
        if _is_blocked_remote_ip(address):
            raise ClipError(_POLICY_MESSAGE)
        approved.append(key)
    if not approved:
        raise ClipError("The video hostname could not be resolved.")

    request_target = parsed.path or "/"
    if parsed.query:
        request_target = f"{request_target}?{parsed.query}"
    family, address = approved[0]
    return ApprovedAddress(
        url=normalized,
        scheme=scheme,
        hostname=ascii_hostname,
        port=port,
        host_header=_remote_host_header(ascii_hostname, port, scheme),
        request_target=request_target,
        address=address,
        family=family,
    )


def _open_pinned(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30,
    resolver=socket.getaddrinfo,
):
    approved = resolve_and_validate(url, resolver=resolver)
    connection = (
        _PinnedHTTPSConnection if approved.scheme == "https" else _PinnedHTTPConnection
    )(approved, timeout=timeout)
    request_headers = {
        "Host": approved.host_header,
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Connection": "close",
    }
    if headers:
        request_headers.update(headers)
    try:
        connection.request("GET", approved.request_target, headers=request_headers)
        response = connection.getresponse()
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        # `BadStatusLine`, `LineTooLong` and friends are HTTPException, not
        # OSError; uncaught they would escape every caller's error handling and
        # abort the whole batch instead of failing one video.
        connection.close()
        raise ClipError("The video request failed.") from exc
    except BaseException:
        connection.close()
        raise
    return approved, connection, response


def _declared_length(response) -> int | None:
    """The body length the server declares, when it declares a usable one."""
    declared = response.getheader("Content-Length")
    if declared is None:
        return None
    try:
        value = int(declared)
    except ValueError:
        return None
    return value if value >= 0 else None


def _declared_size_exceeds(response, max_bytes: int) -> bool:
    declared = _declared_length(response)
    return declared is not None and declared > max_bytes


def _next_redirect(current_url: str, location: str | None) -> str:
    if not location:
        raise ClipError(_BAD_REDIRECT_MESSAGE)
    try:
        return urljoin(current_url, location)
    except ValueError as exc:
        raise ClipError(_BAD_REDIRECT_MESSAGE) from exc


def fetch_bytes(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30,
    max_bytes: int = 1_000_000,
    resolver=socket.getaddrinfo,
) -> tuple[str, bytes]:
    """Fetch a small resource (a playlist) into memory.

    Returns ``(final_url, body)``. Used for playlist probing, where the payload
    is kilobytes: the byte ceiling is a hard stop, not a hint.
    """
    current = url
    for redirect in range(MAX_REDIRECTS + 1):
        approved, connection, response = _open_pinned(
            current, headers=headers, timeout=timeout, resolver=resolver
        )
        try:
            status = int(response.status)
            if status in REDIRECT_STATUSES:
                if redirect >= MAX_REDIRECTS:
                    raise ClipError(_REDIRECT_LIMIT_MESSAGE)
                current = _next_redirect(approved.url, response.getheader("Location"))
                continue
            if status < 200 or status >= 300:
                raise ClipError(f"The video server returned HTTP {status}.")
            if _declared_size_exceeds(response, max_bytes):
                raise ClipError(_TOO_LARGE_MESSAGE)
            payload = bytearray()
            while True:
                chunk = response.read(min(CHUNK_BYTES, max_bytes + 1 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > max_bytes:
                    raise ClipError(_TOO_LARGE_MESSAGE)
            # `read(amt)` returns b"" instead of raising IncompleteRead when the
            # peer closes early (measured: 10 bytes of a declared 100), so a
            # short body would otherwise look complete.
            declared = _declared_length(response)
            if declared is not None and len(payload) != declared:
                raise ClipError(_TRUNCATED_MESSAGE)
            return approved.url, bytes(payload)
        finally:
            connection.close()
    raise ClipError(_REDIRECT_LIMIT_MESSAGE)


def download_to_file(
    url: str,
    destination: Path,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30,
    max_bytes: int = 500 * 1024 * 1024,
    resolver=socket.getaddrinfo,
) -> tuple[str, int]:
    """Stream *url* into *destination*.

    Returns ``(final_url, bytes_written)``. The caller owns the file: on a
    raised error a partially written file must be deleted by the caller.
    """
    current = url
    for redirect in range(MAX_REDIRECTS + 1):
        approved, connection, response = _open_pinned(
            current, headers=headers, timeout=timeout, resolver=resolver
        )
        try:
            status = int(response.status)
            if status in REDIRECT_STATUSES:
                if redirect >= MAX_REDIRECTS:
                    raise ClipError(_REDIRECT_LIMIT_MESSAGE)
                current = _next_redirect(approved.url, response.getheader("Location"))
                continue
            if status < 200 or status >= 300:
                raise ClipError(f"The video server returned HTTP {status}.")
            if _declared_size_exceeds(response, max_bytes):
                raise ClipError(_TOO_LARGE_MESSAGE)
            declared = _declared_length(response)
            written = 0
            # O_EXCL: the name is derived from page-controlled text, so a
            # pre-placed symlink must make the create fail rather than redirect
            # the write outside the destination directory.
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "wb") as handle:
                while True:
                    chunk = response.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    written += len(chunk)
                    # Content-Length is advisory: chunked responses and lying
                    # headers both exist, so the cap is enforced while writing.
                    if written > max_bytes:
                        raise ClipError(_TOO_LARGE_MESSAGE)
                    handle.write(chunk)
            if declared is not None and written != declared:
                destination.unlink(missing_ok=True)
                raise ClipError(_TRUNCATED_MESSAGE)
            return approved.url, written
        finally:
            connection.close()
    raise ClipError(_REDIRECT_LIMIT_MESSAGE)
