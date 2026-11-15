"""Remote image fetching, SSRF guards and localisation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from typing import Sequence
from urllib.parse import urljoin
from urllib.parse import urlsplit
import http.client
import ipaddress
import os
import re
import socket
import ssl
import unicodedata

from .core import ClipError, MAX_IMAGE_BYTES
from .fsutil import atomic_write_bytes
from .markdown import _REMOTE_MARKDOWN_IMAGE, find_remote_images
from .paths import _require_within
from .urls import _url_hash, normalize_url

_REMOTE_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


_REMOTE_FETCH_POLICY_MESSAGE = "The remote image URL is blocked by network policy."


_BLOCKED_IMAGE_IPV4_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
    )
)


_BLOCKED_IMAGE_IPV6_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "::/96",
        "::/128",
        "::1/128",
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "100::/64",
        "2001::/23",
        "2001:2::/48",
        "2001:10::/28",
        "2001:20::/28",
        "2001:db8::/32",
        "2002::/16",
        "3fff::/20",
        "5f00::/16",
        "fc00::/7",
        "fe80::/10",
        "fec0::/10",
        "ff00::/8",
    )
)


@dataclass(frozen=True)
class _ApprovedRemoteImageUrl:
    url: str
    scheme: str
    hostname: str
    port: int
    host_header: str
    request_target: str
    address: str
    family: int


@dataclass(frozen=True)
class _PinnedRemoteResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


def _is_blocked_remote_ip(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return True
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    networks = (
        _BLOCKED_IMAGE_IPV4_NETWORKS
        if isinstance(parsed, ipaddress.IPv4Address)
        else _BLOCKED_IMAGE_IPV6_NETWORKS
    )
    return any(parsed in network for network in networks)


def _remote_host_header(hostname: str, port: int, scheme: str) -> str:
    formatted = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 80 if scheme == "http" else 443
    return formatted if port == default_port else f"{formatted}:{port}"


def _resolve_remote_image_url(
    value: str,
    *,
    resolver=socket.getaddrinfo,
) -> _ApprovedRemoteImageUrl:
    normalized = normalize_url(value)
    parsed = urlsplit(normalized)
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname or ""
    port = parsed.port or (80 if scheme == "http" else 443)
    default_port = 80 if scheme == "http" else 443
    if parsed.port is not None and port != default_port:
        raise ClipError(_REMOTE_FETCH_POLICY_MESSAGE)
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ClipError(_REMOTE_FETCH_POLICY_MESSAGE) from exc
    try:
        infos = resolver(
            ascii_hostname,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except OSError as exc:
        raise ClipError("Downloading a remote image failed.") from exc
    if not infos:
        raise ClipError("Downloading a remote image failed.")
    approved: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for family, _socktype, _proto, _canonname, sockaddr in infos:
        if family not in {socket.AF_INET, socket.AF_INET6} or not sockaddr:
            raise ClipError(_REMOTE_FETCH_POLICY_MESSAGE)
        address = sockaddr[0]
        key = (family, address)
        if key in seen:
            continue
        seen.add(key)
        if _is_blocked_remote_ip(address):
            raise ClipError(_REMOTE_FETCH_POLICY_MESSAGE)
        approved.append(key)
    if not approved:
        raise ClipError("Downloading a remote image failed.")
    request_target = parsed.path or "/"
    if parsed.query:
        request_target = f"{request_target}?{parsed.query}"
    family, address = approved[0]
    return _ApprovedRemoteImageUrl(
        url=normalized,
        scheme=scheme,
        hostname=ascii_hostname,
        port=port,
        host_header=_remote_host_header(ascii_hostname, port, scheme),
        request_target=request_target,
        address=address,
        family=family,
    )


def _socket_target(address: str, family: int, port: int) -> tuple[object, ...]:
    return (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, approved: _ApprovedRemoteImageUrl, *, timeout: float):
        super().__init__(approved.hostname, approved.port, timeout=timeout)
        self._approved = approved

    def connect(self) -> None:
        sock = socket.socket(self._approved.family, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect(_socket_target(self._approved.address, self._approved.family, self._approved.port))
        except Exception:
            sock.close()
            raise
        self.sock = sock


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, approved: _ApprovedRemoteImageUrl, *, timeout: float):
        super().__init__(approved.hostname, approved.port, timeout=timeout)
        self._approved = approved

    def connect(self) -> None:
        raw_sock = socket.socket(self._approved.family, socket.SOCK_STREAM)
        try:
            raw_sock.settimeout(self.timeout)
            raw_sock.connect(_socket_target(self._approved.address, self._approved.family, self._approved.port))
            context = ssl.create_default_context()
            self.sock = context.wrap_socket(raw_sock, server_hostname=self._approved.hostname)
        except Exception:
            raw_sock.close()
            raise


def _read_remote_response_body(response: http.client.HTTPResponse, max_bytes: int) -> bytes:
    declared = response.getheader("Content-Length")
    if declared is not None:
        try:
            if int(declared) > max_bytes:
                raise ClipError("A remote image is too large to save safely.")
        except ValueError:
            pass
    payload = bytearray()
    while True:
        chunk = response.read(min(64 * 1024, max_bytes + 1 - len(payload)))
        if not chunk:
            break
        payload.extend(chunk)
        if len(payload) > max_bytes:
            raise ClipError("A remote image is too large to save safely.")
    return bytes(payload)


def _perform_pinned_remote_image_request(
    approved: _ApprovedRemoteImageUrl,
    *,
    timeout: int,
    max_bytes: int,
) -> _PinnedRemoteResponse:
    connection: http.client.HTTPConnection
    if approved.scheme == "https":
        connection = _PinnedHTTPSConnection(approved, timeout=timeout)
    else:
        connection = _PinnedHTTPConnection(approved, timeout=timeout)
    try:
        connection.request(
            "GET",
            approved.request_target,
            headers={
                "Host": approved.host_header,
                "User-Agent": "Mozilla/5.0 Hermes webclip-obsidian",
                "Accept": "image/*,*/*;q=0.8",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        status_code = int(response.status)
        headers = {name: value for name, value in response.getheaders()}
        body = (
            b""
            if status_code in _REMOTE_REDIRECT_STATUSES
            else _read_remote_response_body(response, max_bytes)
        )
        return _PinnedRemoteResponse(status_code=status_code, headers=headers, body=body)
    except ClipError:
        raise
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise ClipError("Downloading a remote image failed.") from exc
    finally:
        connection.close()


def _first_remote_header(headers: Mapping[str, str], name: str) -> str | None:
    for header_name, value in headers.items():
        if header_name.lower() == name.lower():
            return value
    return None


def _fetch_remote_image(
    url: str,
    *,
    resolver=socket.getaddrinfo,
    request_impl=None,
) -> tuple[str, str, bytes]:
    current = url
    fetch = _perform_pinned_remote_image_request if request_impl is None else request_impl
    for redirect_count in range(6):
        approved = _resolve_remote_image_url(current, resolver=resolver)
        response = fetch(approved, timeout=30, max_bytes=MAX_IMAGE_BYTES)
        if response.status_code in _REMOTE_REDIRECT_STATUSES:
            location = _first_remote_header(response.headers, "Location")
            if not location or redirect_count >= 5:
                raise ClipError("Downloading a remote image failed.")
            try:
                current = normalize_url(urljoin(approved.url, location))
            except ClipError as exc:
                raise ClipError(_REMOTE_FETCH_POLICY_MESSAGE) from exc
            continue
        if response.status_code < 200 or response.status_code >= 300:
            raise ClipError(
                f"Downloading a remote image failed with HTTP {response.status_code}."
            )
        content_type = (
            _first_remote_header(response.headers, "Content-Type") or ""
        ).split(";", 1)[0].strip().lower()
        if not content_type.startswith("image/"):
            raise ClipError("A remote image URL returned non-image content.")
        return approved.url, content_type, response.body
    raise ClipError("Downloading a remote image failed.")


def _slugify_image_dir(note_path: Path, url: str) -> str:
    ascii_text = (
        unicodedata.normalize("NFKD", note_path.stem).encode("ascii", "ignore").decode("ascii")
    )
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-").lower()
    return cleaned or _url_hash(url)[:12]


_IMAGE_SUFFIX_BY_SUBTYPE = {
    "jpeg": ".jpg",
    "pjpeg": ".jpg",
    "jpg": ".jpg",
    "png": ".png",
    "apng": ".png",
    "gif": ".gif",
    "webp": ".webp",
    "avif": ".avif",
    "bmp": ".bmp",
    "tiff": ".tiff",
    "svg": ".svg",
    "x-icon": ".ico",
    "vnd.microsoft.icon": ".ico",
    "heic": ".heic",
    "heif": ".heif",
}


def _suffix_for_content_type(content_type: str) -> str:
    """Return the canonical extension for a normalised ``image/<subtype>`` type."""
    subtype = content_type.removeprefix("image/").split("+", 1)[0].strip()
    return _IMAGE_SUFFIX_BY_SUBTYPE.get(subtype, "")


def download_remote_image(
    url: str,
    destination_dir: Path,
    index: int,
    *,
    resolver=socket.getaddrinfo,
    request_impl=None,
) -> Path:
    final_url, content_type, payload = _fetch_remote_image(
        url,
        resolver=resolver,
        request_impl=request_impl,
    )
    url_suffix = Path(urlsplit(final_url).path).suffix.lower()
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,8}", url_suffix or ""):
        url_suffix = ""
    # The served Content-Type wins over the URL: sites routinely return PNG or WebP
    # payloads from ".jpg" paths, and a wrong extension misleads anything that trusts it.
    suffix = _suffix_for_content_type(content_type) or url_suffix or ".img"
    base_name = Path(urlsplit(final_url).path).stem or "image"
    base_name = re.sub(r"[^A-Za-z0-9._-]+", "-", base_name).strip("-._") or "image"
    file_name = f"{index:02d}-{base_name}{suffix}"
    target = destination_dir / file_name
    atomic_write_bytes(target, payload)
    return target


def _rewrite_remote_image_references(markdown: str, replacements: Mapping[str, str]) -> str:
    def replace_markdown(match: re.Match[str]) -> str:
        url = normalize_url(match.group(1))
        replacement = replacements.get(url)
        return match.group(0).replace(match.group(1), replacement, 1) if replacement else match.group(0)

    return _REMOTE_MARKDOWN_IMAGE.sub(replace_markdown, markdown)


def _cleanup_localized_files(paths: Sequence[Path], *, images_root: Path) -> None:
    root = images_root.resolve()
    resolved_paths = sorted({path.resolve() for path in paths}, key=lambda path: len(path.parents), reverse=True)
    for path in resolved_paths:
        try:
            _require_within(path, root, "Generated image path escaped the configured image directory.")
        except ClipError:
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            continue
        parent = path.parent
        while parent != root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def _localize_images(
    markdown: str,
    title: str,
    source_url: str,
    images_root: Path,
    note_path: Path,
) -> tuple[str, list[Path]]:
    remote_images = find_remote_images(markdown)
    if not remote_images:
        return markdown, []
    article_dir = images_root / _slugify_image_dir(note_path, source_url)
    try:
        article_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ClipError("Could not create the configured image directory.") from exc
    replacements: dict[str, str] = {}
    generated_paths: list[Path] = []
    try:
        for index, image_url in enumerate(remote_images, start=1):
            downloaded = download_remote_image(image_url, article_dir, index)
            relative = os.path.relpath(downloaded, start=note_path.parent)
            replacements[image_url] = Path(relative).as_posix()
            generated_paths.append(downloaded)
    except Exception:
        _cleanup_localized_files(generated_paths, images_root=images_root)
        raise
    return _rewrite_remote_image_references(markdown, replacements), generated_paths
