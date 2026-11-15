"""Safe vault-writing and Git synchronization for the ``/webclip`` command."""

from __future__ import annotations

import sys as _sys
import types as _types
from pathlib import Path as _Path

# One `_webclip` instance for both loading modes: tests import this file as a
# top-level module, Hermes loads the package via spec_from_file_location.
# Registering it once keeps ClipError and the frozen dataclasses identical when
# both modes are used in one process.
_pkg = None
if "_webclip" not in _sys.modules:
    _pkg = _types.ModuleType("_webclip")
    _pkg.__path__ = [str(_Path(__file__).resolve().parent / "_webclip")]
    _sys.modules["_webclip"] = _pkg
del _sys, _types, _Path, _pkg

from _webclip.core import ClipError, EXTRACTOR_TIMEOUT, GIT_TIMEOUT, MAX_DESTINATION_SCAN_ENTRIES, MAX_GIT_OUTPUT_BYTES, MAX_IMAGE_BYTES, MAX_PREVIEW_URL_PARAMS_BYTES, MAX_STDERR_BYTES, MAX_STDOUT_BYTES, PENDING_TTL_SECONDS, _GITHUB_REMOTE_HTTPS, _GITHUB_REMOTE_SSH, _SAFE_BRANCH_NAME, _SAFE_ERROR_CODE, _SECRET_PATTERNS, _normalize_text
from _webclip.proc import ProcessResult, _decode_output, _run_bounded
from _webclip.urls import _SHA256_SELECTOR_RE, _normalize_preview_url_params, _parse_target_selector, _url_hash, _validate_http_url, append_query_params, github_blob_url, normalize_url
from _webclip.paths import DOS_RESERVED, MAX_FILENAME_BYTES, _FORBIDDEN_FILENAME, _filename_with_suffix, _require_within, _resolve_vault_path, _truncate_utf8, safe_filename
from _webclip.fsutil import atomic_write, atomic_write_bytes
from _webclip.article import _decode_json_object, _extractor_failure, _validate_success_payload
from _webclip.extract import _extractor_dir, _extractor_environment, run_extractor
from _webclip.sites import _NETEASE_HOST_RE, _NETEASE_VIDEO_AUTHOR_HTML_RE, _NETEASE_VIDEO_AUTHOR_RE, _NETEASE_VIDEO_COVER_RE, _NETEASE_VIDEO_DATE_RE, _NETEASE_VIDEO_PATH_RE, _NETEASE_VIDEO_STREAM_RE, _NETEASE_VIDEO_TITLE_RE, _WECHAT_AUTHOR_HTML_DECODE_RE, _WECHAT_AUTHOR_RE, _WECHAT_BODY_RE, _WECHAT_HOST_RE, _WECHAT_TIME_RE, _WECHAT_TITLE_RE, _count_words, _fetch_netease_video_html, _fetch_wechat_html, _is_netease_video_url, _is_wechat_url, _parse_netease_video_html, _parse_wechat_html, _wechat_html_to_markdown, run_extractor_with_fallback
from _webclip.config import ClipConfig, ClipOptions, parse_clip_args

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import ssl
import subprocess
import tempfile
import threading
import tomllib
import unicodedata
from urllib.parse import (
    parse_qsl,
    quote,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)
from typing import Mapping, Sequence

import yaml


_REMOTE_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\((https?://[^\s)]+)(?:\s+\"[^\"]*\")?\)", re.IGNORECASE)
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
class GitOutcome:
    commit_state: str
    push_state: str
    detail: str = ""
    # Short sha of the commit this outcome created; empty when no commit exists.
    commit_sha: str = ""
    # Subject Git actually stored (a commit-msg hook may rewrite it); empty when
    # there is no commit or the lookup itself failed.
    commit_subject: str = ""


_SUMMARY_LABELS: dict[str, dict[str, str]] = {
    "zh": {
        "item": "项",
        "value": "内容",
        "author": "作者",
        "published": "发布时间",
        "source": "来源",
        "images": "图片",
        "size": "大小",
        "commit": "提交",
        "preview": "文章预览",
        "none": "—",
        "image_remote": "{n} 张，**全部远程链接**（image_mode: remote）",
        "image_local": "{n} 张，**已本地化到 vault**（image_mode: local）",
        "size_fmt": "{lines} 行 / {kb} KB",
        "warn_push_failed": "> ⚠️ 已提交但推送失败，vault 与远端可能不同步",
        "warn_commit_failed": "> ⚠️ Git 提交失败，笔记已写入但未提交",
        "warn_stage_failed": "> ⚠️ Git 暂存失败，笔记已写入但未提交",
        "warn_unverified": "> ⚠️ 提交已创建但校验未通过，未推送",
        "warn_verification_failed": "> ⚠️ Git 校验未通过，未提交也未推送",
    },
    "en": {
        "item": "Item",
        "value": "Value",
        "author": "Author",
        "published": "Published",
        "source": "Source",
        "images": "Images",
        "size": "Size",
        "commit": "Commit",
        "preview": "Article preview",
        "none": "—",
        "image_remote": "{n}, **all remote** (image_mode: remote)",
        "image_local": "{n}, **localized into the vault** (image_mode: local)",
        "size_fmt": "{lines} lines / {kb} KB",
        "warn_push_failed": "> ⚠️ committed but the push failed; the vault may be out of sync",
        "warn_commit_failed": "> ⚠️ the Git commit failed; the note is written but not committed",
        "warn_stage_failed": "> ⚠️ Git staging failed; the note is written but not committed",
        "warn_unverified": "> ⚠️ the commit exists but verification failed; not pushed",
        "warn_verification_failed": "> ⚠️ Git verification failed; nothing was committed or pushed",
    },
}


def _summary_cell(value: object) -> str:
    """Escape a value so it cannot break out of a Markdown table cell."""
    return str(value).replace("\r", " ").replace("\n", " ").replace("|", "\\|")


@dataclass(frozen=True)
class ClipResult:
    path: str
    commit_state: str
    push_state: str
    github_url: str | None = None
    action: str = "clip"
    # Every note the operation touched; ``path`` is the first entry.
    paths: tuple[str, ...] = ()
    # Which frontmatter field resolved a hash selector, when applicable.
    matched_by: str | None = None
    # Report metadata. All defaulted so the public structured API stays compatible.
    title: str = ""
    author: str = ""
    published: str = ""
    source_host: str = ""
    image_mode: str = ""
    image_count: int = 0
    size_bytes: int = 0
    line_count: int = 0
    # The commit message subject that actually landed, verbatim from the commit.
    commit_subject: str = ""
    commit_sha: str = ""

    def _git_detail(self) -> str:
        if self.commit_state == "disabled":
            return "Git synchronization disabled"
        if self.commit_state == "committed" and self.push_state == "pushed":
            return "committed and pushed"
        if self.commit_state == "unchanged":
            return (
                "content unchanged; no Git commit needed"
                if self.action == "clip"
                else "already in the requested state; no Git commit needed"
            )
        if self.commit_state == "committed":
            return "committed; push failed"
        if self.commit_state == "committed_unverified":
            return (
                "local commit created, but post-commit verification failed; not pushed"
            )
        if self.commit_state == "commit_failed":
            return "Git commit failed; not pushed"
        if self.commit_state == "stage_failed":
            return "Git staging failed; not committed or pushed"
        return "Git safety verification refused synchronization; not committed or pushed"

    def user_message(self) -> str:
        headline = {
            "favorite": "Marked clip as favorite",
            "unfavorite": "Removed favorite marker from clip",
        }.get(self.action, "Saved clip")
        paths: tuple[str, ...] = tuple(self.paths) if self.paths else (self.path,)
        if len(paths) > 1:
            lines = [f"{headline} ({len(paths)} notes):"]
            lines.extend(f"- {path}" for path in paths)
            lines.append(f"({self._git_detail()}).")
            message = "\n".join(lines)
        else:
            message = f"{headline}: {paths[0]} ({self._git_detail()})."
        if self.matched_by == "source_content_hash":
            message += " Matched by source_content_hash."
        if self.github_url:
            message += f" GitHub: {self.github_url}"
        return message

    def summary_markdown(self, lang: str = "zh") -> str:
        """Markdown report for a finished clip.

        The agent prints this verbatim instead of recomputing figures, so the
        numbers come from the plugin rather than from the model. Favorite marker
        operations keep the short ``user_message()`` form: a table of author,
        images and note size says nothing useful about them.
        """
        if self.action in {"favorite", "unfavorite"}:
            return self.user_message()
        labels = _SUMMARY_LABELS.get(lang, _SUMMARY_LABELS["zh"])
        rows = (
            (labels["author"], self.author or labels["none"]),
            (labels["published"], self.published or labels["none"]),
            (labels["source"], self.source_host or labels["none"]),
            (labels["images"], self._summary_images(labels)),
            (labels["size"], self._summary_size(labels)),
            (labels["commit"], self._summary_commit(labels)),
        )
        lines = [
            f"| {labels['item']} | {labels['value']} |",
            "| --- | --- |",
            *(
                f"| {_summary_cell(name)} | {_summary_cell(value)} |"
                for name, value in rows
            ),
        ]
        warning = self._summary_warning(labels)
        if warning:
            lines.extend(("", warning))
        if self.github_url:
            lines.extend(("", f"[{labels['preview']}]({self.github_url})"))
        return "\n".join(lines)

    def _summary_warning(self, labels: Mapping[str, str]) -> str:
        """One line, only when synchronization did not fully succeed.

        A successful push prints nothing extra, so the receipt stays a plain
        table; a failed push or commit must not look like a clean clip.
        """
        if self.commit_state == "committed" and self.push_state == "push_failed":
            return labels["warn_push_failed"]
        if self.commit_state == "committed_unverified":
            return labels["warn_unverified"]
        if self.commit_state in {
            "commit_failed",
            "stage_failed",
            "verification_failed",
        }:
            return labels[f"warn_{self.commit_state}"]
        return ""

    def _summary_images(self, labels: Mapping[str, str]) -> str:
        if self.image_count <= 0:
            return labels["none"]
        template = (
            labels["image_local"] if self.image_mode == "local" else labels["image_remote"]
        )
        return template.format(n=self.image_count)

    def _summary_size(self, labels: Mapping[str, str]) -> str:
        if self.line_count <= 0:
            return labels["none"]
        return labels["size_fmt"].format(
            lines=self.line_count, kb=f"{self.size_bytes / 1024:.1f}"
        )

    def _summary_commit(self, labels: Mapping[str, str]) -> str:
        if not self.commit_sha:
            return labels["none"]
        if self.commit_subject:
            return f"{self.commit_sha} {self.commit_subject}"
        return self.commit_sha


@dataclass(frozen=True)
class PendingClipResult:
    title: str
    image_count: int

    def user_message(self) -> str:
        noun = "image" if self.image_count == 1 else "images"
        return (
            f"Found {self.image_count} remote {noun} in '{self.title}'. "
            "Reply yes or no: yes downloads and localizes them, no keeps the remote image URLs."
        )


def _batch_label(selector: str) -> str:
    """Shorten a sha256 selector for batch summaries; URLs pass through."""
    if selector.startswith("sha256:") and len(selector) > 27:
        return f"{selector[:19]}…"
    return selector


@dataclass(frozen=True)
class BatchClipItem:
    url: str
    ok: bool
    path: str | None = None
    action: str = "clip"
    error: str | None = None


@dataclass(frozen=True)
class BatchClipResult:
    items: tuple[BatchClipItem, ...]
    commit_state: str
    push_state: str
    github_urls: tuple[str, ...] = ()

    def user_message(self) -> str:
        saved = [item for item in self.items if item.ok]
        failed = [item for item in self.items if not item.ok]
        lines = [f"Batch clip: {len(saved)} saved, {len(failed)} failed."]
        if self.commit_state == "disabled":
            lines.append("Git synchronization disabled for this batch.")
        elif self.commit_state == "committed" and self.push_state == "pushed":
            lines.append("Saved notes were committed and pushed together in one commit.")
        elif self.commit_state == "unchanged":
            lines.append("No content changes; no Git commit was needed.")
        elif self.commit_state == "committed":
            lines.append("Saved notes were committed together; push failed.")
        else:
            lines.append(
                f"Git state: {self.commit_state}/{self.push_state}; "
                "saved notes remain on disk."
            )
        lines.extend(f"- saved: {item.path}" for item in saved)
        lines.extend(
            f"- failed: {_batch_label(item.url)} ({item.error})" for item in failed
        )
        lines.extend(f"GitHub: {url}" for url in self.github_urls)
        return "\n".join(lines)


@dataclass(frozen=True)
class PendingClipState:
    pending_id: str
    created_at: str
    expires_at: str
    article: Mapping[str, object]
    refresh: bool
    no_git: bool
    favorite: bool | None
    vault: str
    destination: str
    images: str
    sync_branch: str

    def to_json(self) -> dict[str, object]:
        return {
            "pending_id": self.pending_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "article": dict(self.article),
            "refresh": self.refresh,
            "no_git": self.no_git,
            "favorite": self.favorite,
            "vault": self.vault,
            "destination": self.destination,
            "images": self.images,
            "sync_branch": self.sync_branch,
        }

    def matches_config(self, config: ClipConfig) -> bool:
        # ``preview_url_params`` is intentionally excluded: it only changes the
        # preview URL returned to the caller, not where or what is written, so
        # editing it mid-way through a two-step clip must not invalidate the
        # pending state.
        return (
            self.vault == str(config.vault)
            and self.destination == str(config.destination)
            and self.images == str(config.images)
            and self.sync_branch == config.sync_branch
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


def _content_hash(markdown: str) -> str:
    normalized = _normalize_text(markdown).rstrip("\n") + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


_DANGEROUS_SCHEMES = r"(?:javascript|vbscript|file|obsidian|data)"
_INLINE_CODE_SPAN = re.compile(r"(`+)([^`\n]*?)\1")
# A single-line `<video>...</video>` tag (the shape emitted for video clips).
_VIDEO_TAG_RE = re.compile(r"(?is)<video\b[^>]*>\s*</video>")
_VIDEO_SRC_ATTR_RE = re.compile(r"""(?i)\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)')""")
# Only http(s) URLs without characters that could break out of the attribute.
_SAFE_VIDEO_SRC_RE = re.compile(r"^https?://[^\s\"'<>]+$", re.IGNORECASE)
_VIDEO_PLACEHOLDER = "\x00webclip-video-{index}\x00"


def _canonical_video_tag(tag: str) -> str | None:
    """Return a rebuilt, safe ``<video>`` tag when *tag* has a safe http(s) src.

    The tag is rebuilt from scratch so no attacker-controlled attributes (event
    handlers, ``srcset``, etc.) survive sanitization; only a validated URL is
    carried over. Returns ``None`` when the src is missing or unsafe, letting
    the normal HTML-escaping path neutralize the tag.
    """
    match = _VIDEO_SRC_ATTR_RE.search(tag)
    if not match:
        return None
    src = match.group(1) if match.group(1) is not None else match.group(2)
    if not _SAFE_VIDEO_SRC_RE.match(src):
        return None
    return f'<video src="{src}" controls preload="metadata" playsinline></video>'


def _protect_video_tags(text: str) -> tuple[str, list[str]]:
    """Swap validated ``<video>`` tags for placeholders so sanitization keeps them."""
    tags: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        canonical = _canonical_video_tag(match.group(0))
        if canonical is None:
            return match.group(0)
        index = len(tags)
        tags.append(canonical)
        return _VIDEO_PLACEHOLDER.format(index=index)

    return _VIDEO_TAG_RE.sub(_replace, text), tags


def _restore_video_tags(text: str, tags: list[str]) -> str:
    for index, tag in enumerate(tags):
        text = text.replace(_VIDEO_PLACEHOLDER.format(index=index), tag)
    return text


def _sanitize_active_markdown_segment(text: str) -> str:
    text, video_tags = _protect_video_tags(text)
    text = re.sub(r"(?s)<!--.*?-->", "", text)
    dangerous_tags = r"script|iframe|object|embed|form|input|button|textarea|select|option|style|link|meta|base|svg|math"
    text = re.sub(
        rf"(?is)<(?P<tag>{dangerous_tags})\b[^>]*>.*?</(?P=tag)\s*>",
        "",
        text,
    )
    text = re.sub(rf"(?is)</?(?:{dangerous_tags})\b[^>]*>", "", text)
    text = re.sub(r"(?i)<(?=/?[A-Za-z][A-Za-z0-9-]*(?:\s|/?>))", "&lt;", text)
    text = re.sub(
        rf"(?i)(\]\(\s*<?){_DANGEROUS_SCHEMES}:",
        r"\1blocked:",
        text,
    )
    text = re.sub(
        rf"(?im)^(\s*\[[^\]\n]+\]:\s*<?){_DANGEROUS_SCHEMES}:",
        r"\1blocked:",
        text,
    )
    text = text.replace("[[", r"\[\[")
    return _restore_video_tags(text, video_tags)


def _sanitize_text_preserving_inline_code(text: str) -> str:
    pieces: list[str] = []
    cursor = 0
    for match in _INLINE_CODE_SPAN.finditer(text):
        pieces.append(_sanitize_active_markdown_segment(text[cursor:match.start()]))
        pieces.append(match.group(0))
        cursor = match.end()
    pieces.append(_sanitize_active_markdown_segment(text[cursor:]))
    return "".join(pieces)


def _scan_remote_images_in_plain_text(text: str, seen: set[str], found: list[str]) -> None:
    cursor = 0
    for inline_code in _INLINE_CODE_SPAN.finditer(text):
        _collect_remote_images(text[cursor:inline_code.start()], seen, found)
        cursor = inline_code.end()
    _collect_remote_images(text[cursor:], seen, found)


def _is_indented_code_line(line: str, leading_spaces: int | None = None) -> bool:
    if line.startswith("\t"):
        return True
    if leading_spaces is None:
        leading_spaces = len(line) - len(line.lstrip(" "))
    return leading_spaces >= 4 and bool(line.strip())


def _collect_remote_images(text: str, seen: set[str], found: list[str]) -> None:
    for match in _REMOTE_MARKDOWN_IMAGE.finditer(text):
        normalized_url = normalize_url(match.group(1))
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        found.append(normalized_url)


def sanitize_markdown(markdown: str) -> str:
    text = _normalize_text(markdown)
    result: list[str] = []
    plain: list[str] = []
    fenced: list[str] = []
    in_fence = False
    fence_char = ""
    fence_length = 0

    for line in text.splitlines(keepends=True):
        leading_spaces = len(line) - len(line.lstrip(" "))
        content = line[leading_spaces:]
        fence_match = None
        if leading_spaces <= 3:
            fence_match = re.match(r"(`{3,}|~{3,})", content)

        if in_fence:
            fenced.append(line)
            if fence_match:
                marker = fence_match.group(1)
                if marker[0] == fence_char and len(marker) >= fence_length:
                    result.append("".join(fenced))
                    fenced = []
                    in_fence = False
                    fence_char = ""
                    fence_length = 0
            continue

        if fence_match:
            if plain:
                result.append(_sanitize_text_preserving_inline_code("".join(plain)))
                plain = []
            marker = fence_match.group(1)
            in_fence = True
            fence_char = marker[0]
            fence_length = len(marker)
            fenced = [line]
            continue

        if _is_indented_code_line(line, leading_spaces):
            if plain:
                result.append(_sanitize_text_preserving_inline_code("".join(plain)))
                plain = []
            result.append(line)
            continue

        plain.append(line)

    if plain:
        result.append(_sanitize_text_preserving_inline_code("".join(plain)))
    if fenced:
        result.append("".join(fenced))
    return "".join(result)


def _contains_markdown_h1(markdown: str) -> bool:
    in_fence = False
    fence_char = ""
    fence_length = 0
    previous_text_line = None
    for raw_line in _normalize_text(markdown).split("\n"):
        if raw_line.startswith("\t"):
            previous_text_line = None
            continue

        leading_spaces = len(raw_line) - len(raw_line.lstrip(" "))
        content = raw_line[leading_spaces:]

        if leading_spaces <= 3:
            fence_match = re.match(r"(`{3,}|~{3,})", content)
            if fence_match:
                marker = fence_match.group(1)
                if not in_fence:
                    in_fence = True
                    fence_char = marker[0]
                    fence_length = len(marker)
                elif marker[0] == fence_char and len(marker) >= fence_length:
                    in_fence = False
                    fence_char = ""
                    fence_length = 0
                previous_text_line = None
                continue

        if in_fence:
            continue

        if leading_spaces >= 4:
            previous_text_line = None
            continue

        if re.match(r"^#(?:\s+\S|\s*$)", content):
            return True
        if re.match(r"^=+\s*$", content) and previous_text_line:
            return True

        previous_text_line = content if content.strip() else None
    return False


def _sanitized_heading_title(title: str) -> str:
    sanitized = sanitize_markdown(title)
    return re.sub(r"\s+", " ", sanitized).strip()


def _managed_markdown(title: str, markdown: str) -> str:
    cleaned_title = _sanitized_heading_title(title)
    cleaned_markdown = _normalize_text(markdown).rstrip("\n")
    if _contains_markdown_h1(cleaned_markdown):
        return cleaned_markdown
    if not cleaned_markdown:
        return f"# {cleaned_title}"
    return f"# {cleaned_title}\n\n{cleaned_markdown}"


def render_note(
    data: Mapping[str, object],
    created: str | None = None,
    *,
    content_markdown: str | None = None,
    image_mode: str | None = None,
    favorite: bool | None = None,
) -> str:
    """Render extractor data as normalized Markdown with YAML frontmatter."""
    if image_mode not in {None, "remote", "local"}:
        raise ClipError("The image save mode is invalid.")
    if favorite is not None and not isinstance(favorite, bool):
        raise ClipError("The favorite marker is invalid.")
    checked = _validate_success_payload(data)
    timestamp = created or datetime.now(timezone.utc).isoformat(timespec="seconds")
    source = normalize_url(str(checked["canonicalUrl"] or checked["url"]))
    fetched_url = normalize_url(str(checked["url"]))
    source_markdown = sanitize_markdown(str(checked["markdown"])).rstrip("\n")
    effective_markdown = (
        _normalize_text(content_markdown).rstrip("\n")
        if content_markdown is not None
        else source_markdown
    )
    managed_markdown = _managed_markdown(str(checked["title"]), effective_markdown)
    metadata = {
        "title": checked["title"],
        "url": source,
        "author": checked["author"],
        "site": checked["site"],
        "description": checked["description"],
        "keywords": checked["keywords"],
        "tags": ["web-clip"],
        "original_url": source,
        "original_host": urlsplit(source).hostname or "",
        **({"favorite": True} if favorite else {}),
        **({"fetched_url": fetched_url} if fetched_url != source else {}),
        "extraction_method": checked["method"],
        "status": "needs-review",
        "category": "Inbox",
        "word_count": checked["wordCount"],
        "webclip_id": "sha256:" + _url_hash(source),
        "source_content_hash": "sha256:" + _content_hash(source_markdown),
        "content_hash": "sha256:" + _content_hash(effective_markdown),
        **({"image_mode": image_mode} if image_mode is not None else {}),
        "published": checked["published"],
        "created": timestamp,
    }
    frontmatter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip("\n")
    return (
        f"---\n{frontmatter}\n---\n\n"
        "<!-- webclip:managed:start -->\n"
        f"{managed_markdown}\n"
        "<!-- webclip:managed:end -->\n\n"
        "<!-- webclip:manual:start -->\n"
        "<!-- webclip:manual:end -->\n"
    )


def find_remote_images(markdown: str) -> list[str]:
    normalized = _normalize_text(markdown)
    found: list[str] = []
    seen: set[str] = set()
    plain: list[str] = []
    in_fence = False
    fence_char = ""
    fence_length = 0

    for line in normalized.splitlines(keepends=True):
        leading_spaces = len(line) - len(line.lstrip(" "))
        content = line[leading_spaces:]
        fence_match = None
        if leading_spaces <= 3:
            fence_match = re.match(r"(`{3,}|~{3,})", content)

        if in_fence:
            if fence_match:
                marker = fence_match.group(1)
                if marker[0] == fence_char and len(marker) >= fence_length:
                    in_fence = False
                    fence_char = ""
                    fence_length = 0
            continue

        if fence_match:
            if plain:
                _scan_remote_images_in_plain_text("".join(plain), seen, found)
                plain = []
            marker = fence_match.group(1)
            in_fence = True
            fence_char = marker[0]
            fence_length = len(marker)
            continue

        if _is_indented_code_line(line, leading_spaces):
            if plain:
                _scan_remote_images_in_plain_text("".join(plain), seen, found)
                plain = []
            continue

        plain.append(line)

    if plain:
        _scan_remote_images_in_plain_text("".join(plain), seen, found)
    return found


def _active_pending_pointer(root: Path) -> Path:
    return root / "active.json"


def _pending_state_path(root: Path, pending_id: str) -> Path:
    return root / f"{pending_id}.json"


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    atomic_write(path, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def _clear_pending(root: Path, pending_id: str | None = None) -> None:
    pointer = _active_pending_pointer(root)
    if pending_id is None and pointer.is_file():
        try:
            data = json.loads(pointer.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                pending_id = data.get("pending_id") if isinstance(data.get("pending_id"), str) else None
        except (OSError, UnicodeError, json.JSONDecodeError):
            pending_id = None
    candidates = [pointer]
    if pending_id:
        candidates.append(_pending_state_path(root, pending_id))
    for candidate in candidates:
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ClipError("Could not clear the pending image confirmation state.") from exc


def _load_pending_state(root: Path) -> PendingClipState:
    pointer = _active_pending_pointer(root)
    if not pointer.is_file():
        raise ClipError("No pending image confirmation exists.")
    try:
        active = json.loads(pointer.read_text(encoding="utf-8"))
        pending_id = active.get("pending_id")
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError) as exc:
        raise ClipError("The pending image confirmation state is invalid.") from exc
    if not isinstance(pending_id, str) or not pending_id:
        raise ClipError("The pending image confirmation state is invalid.")
    path = _pending_state_path(root, pending_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        _clear_pending(root, pending_id)
        raise ClipError("No pending image confirmation exists.") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClipError("The pending image confirmation state is invalid.") from exc
    if not isinstance(payload, dict):
        raise ClipError("The pending image confirmation state is invalid.")
    required = {
        "pending_id": str,
        "created_at": str,
        "expires_at": str,
        "article": dict,
        "refresh": bool,
        "no_git": bool,
        "vault": str,
        "destination": str,
        "images": str,
        "sync_branch": str,
    }
    for field, expected_type in required.items():
        value = payload.get(field)
        if not isinstance(value, expected_type):
            raise ClipError("The pending image confirmation state is invalid.")
    expires_at = datetime.fromisoformat(str(payload["expires_at"]))
    if datetime.now(timezone.utc) >= expires_at:
        _clear_pending(root, pending_id)
        raise ClipError("The pending image confirmation expired; please run /webclip again.")
    favorite = payload.get("favorite")
    if favorite is not None and not isinstance(favorite, bool):
        raise ClipError("The pending image confirmation state is invalid.")
    return PendingClipState(
        pending_id=str(payload["pending_id"]),
        created_at=str(payload["created_at"]),
        expires_at=str(payload["expires_at"]),
        article=dict(payload["article"]),
        refresh=bool(payload["refresh"]),
        no_git=bool(payload["no_git"]),
        favorite=favorite,
        vault=str(payload["vault"]),
        destination=str(payload["destination"]),
        images=str(payload["images"]),
        sync_branch=str(payload["sync_branch"]),
    )


def _store_pending_state(root: Path, state: PendingClipState) -> None:
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise ClipError("Could not create the pending image confirmation directory.") from exc
    try:
        if root.is_symlink():
            raise ClipError("Refusing to use a symbolic-link pending state directory.")
        os.chmod(root, 0o700)
    except OSError as exc:
        raise ClipError("Could not secure the pending image confirmation directory.") from exc
    pointer = _active_pending_pointer(root)
    if pointer.exists():
        existing = _load_pending_state(root)
        raise ClipError(
            f"Another clipped article ('{existing.article.get('title', 'unknown')}') is already waiting for yes/no confirmation."
        )
    _write_json(_pending_state_path(root, state.pending_id), state.to_json())
    _write_json(pointer, {"pending_id": state.pending_id})


def _slugify_image_dir(note_path: Path, url: str) -> str:
    ascii_text = (
        unicodedata.normalize("NFKD", note_path.stem).encode("ascii", "ignore").decode("ascii")
    )
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-").lower()
    return cleaned or _url_hash(url)[:12]


# Canonical extension per image subtype. Unknown subtypes fall back to the URL's own
# suffix so a server can never make us invent an extension from an arbitrary token.
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


def _frontmatter_from_text(text: str) -> dict[str, object] | None:
    normalized = _normalize_text(text)
    if not normalized.startswith("---\n"):
        return None
    end = normalized.find("\n---\n", 4)
    if end < 0:
        return None
    try:
        parsed = yaml.safe_load(normalized[4:end])
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None


def read_skill_frontmatter(skill_md: Path) -> dict[str, object]:
    """Parsed frontmatter of a SKILL.md; ``{}`` when it is missing, unreadable, or empty.

    register() hands this to ``ctx.register_skill()`` so the registry sees the same
    metadata the file declares — description, and the platform/condition gates Hermes
    evaluates for plugin skills — instead of a second hardcoded copy in ``__init__.py``.
    """
    try:
        text = skill_md.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return {}
    return _frontmatter_from_text(text) or {}


def _note_prefix(path: Path, limit: int = 64 * 1024) -> str | None:
    """Read a bounded note prefix for frontmatter lookups.

    The writer puts the frontmatter at the top, so a prefix identifies the
    note even when the article body pushes the file past *limit*. Decoding
    ignores a multibyte character split at the read boundary.
    """
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit)
        return raw.decode("utf-8", errors="ignore")
    except OSError:
        return None


def _sources_from_note(path: Path) -> set[str]:
    """Return every normalized source URL the note records for itself.

    ``fetched_url`` is included so a note clipped through an entry URL whose
    canonical URL differs can still be found by the URL the user requested.
    """
    text = _note_prefix(path)
    if text is None:
        return set()
    metadata = _frontmatter_from_text(text)
    sources: set[str] = set()
    if metadata is None:
        return sources
    for field in ("url", "original_url", "source", "fetched_url"):
        candidate = metadata.get(field)
        if not isinstance(candidate, str) or not candidate:
            continue
        try:
            sources.add(normalize_url(candidate))
        except ClipError:
            continue
    return sources


def _checked_candidate(destination: Path, filename: str) -> Path:
    candidate = destination / filename
    if candidate.is_symlink():
        raise ClipError("Refusing to replace a symbolic-link note.")
    resolved = candidate.resolve()
    _require_within(resolved, destination, "Generated note path escaped its destination.")
    return candidate


def _destination_notes(destination: Path) -> list[Path]:
    """Regular ``.md`` notes in *destination*, refusing symlinks and bounded scans."""
    entries: list[Path] = []
    for index, existing in enumerate(destination.iterdir(), start=1):
        if index > MAX_DESTINATION_SCAN_ENTRIES:
            raise ClipError("The clip destination contains too many entries to scan safely.")
        entries.append(existing)

    notes: list[Path] = []
    for existing in sorted(entries, key=lambda path: path.name):
        if existing.suffix.lower() != ".md":
            continue
        if existing.is_symlink():
            raise ClipError("Refusing to scan a symbolic-link note.")
        if existing.is_file():
            notes.append(existing)
    return notes


def _scan_source_matches(destination: Path, source: str) -> list[Path]:
    """Return notes in *destination* whose recorded source matches *source*."""
    normalized_source = normalize_url(source)
    return [
        note
        for note in _destination_notes(destination)
        if normalized_source in _sources_from_note(note)
    ]


def _note_hashes(path: Path) -> tuple[str | None, str | None]:
    """Return ``(webclip_id, source_content_hash)`` from a note's frontmatter."""
    text = _note_prefix(path)
    if text is None:
        return None, None
    metadata = _frontmatter_from_text(text)
    if not metadata:
        return None, None
    webclip_id = metadata.get("webclip_id")
    content_hash = metadata.get("source_content_hash")
    return (
        webclip_id if isinstance(webclip_id, str) else None,
        content_hash if isinstance(content_hash, str) else None,
    )


def _digest_matches(value: str | None, digest: str) -> bool:
    """Whether a frontmatter hash equals *digest* (bare or ``sha256:`` prefixed)."""
    if not value:
        return False
    normalized = value.strip().lower()
    if normalized.startswith("sha256:"):
        normalized = normalized[len("sha256:") :]
    return normalized == digest


def _scan_hash_matches(destination: Path, digest: str) -> tuple[list[Path], str | None]:
    """Find notes by ``webclip_id`` first, then by ``source_content_hash``.

    Returns every match plus the field that matched (``None`` when nothing did).
    """
    wanted = digest.lower()
    by_id: list[Path] = []
    by_content: list[Path] = []
    for note in _destination_notes(destination):
        webclip_id, content_hash = _note_hashes(note)
        if _digest_matches(webclip_id, wanted):
            by_id.append(note)
        elif _digest_matches(content_hash, wanted):
            by_content.append(note)
    if by_id:
        return by_id, "webclip_id"
    if by_content:
        return by_content, "source_content_hash"
    return [], None


def _write_target_ok(note: Path, webclip_id: str) -> bool:
    """A scan match is a write target only when its webclip_id agrees.

    A note can record a URL under ``fetched_url`` while belonging to a
    different canonical source. Marker lookups may match any recorded URL
    form, but rewriting such a note from a new clip would hijack another
    article's note, so choose_target skips it. Legacy notes without a
    webclip_id keep the pre-existing behavior.
    """
    note_id, _ = _note_hashes(note)
    return note_id is None or note_id == webclip_id


def choose_target(
    destination: Path,
    title: str,
    source: str,
    *,
    capture_date: str | None = None,
) -> Path:
    """Choose an idempotent target without scanning outside the destination."""
    destination = destination.resolve()
    if not destination.is_dir():
        raise ClipError("The configured clip destination is unavailable.")
    digest = _url_hash(source)
    webclip_id = f"sha256:{digest}"
    matches = [
        note
        for note in _scan_source_matches(destination, source)
        if _write_target_ok(note, webclip_id)
    ]
    if len(matches) > 1:
        raise ClipError("The clip destination contains multiple notes for this source.")
    if matches:
        return matches[0]

    if capture_date is None:
        capture_date = datetime.now(timezone.utc).date().isoformat()
    try:
        parsed_date = datetime.strptime(capture_date, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ClipError("The capture date is invalid.") from exc
    if parsed_date != capture_date:
        raise ClipError("The capture date is invalid.")

    normalized_source = normalize_url(source)
    dated_title = f"{capture_date}-{title}"
    base = _checked_candidate(destination, safe_filename(dated_title, source))
    if not base.exists() or (
        normalized_source in _sources_from_note(base)
        and _write_target_ok(base, webclip_id)
    ):
        return base

    for length in range(8, len(digest) + 1, 4):
        candidate = _checked_candidate(
            destination, _filename_with_suffix(dated_title, source, digest[:length])
        )
        if not candidate.exists() or (
            normalized_source in _sources_from_note(candidate)
            and _write_target_ok(candidate, webclip_id)
        ):
            return candidate
    raise ClipError("Unable to choose a unique filename for the clip.")


def _manual_section(text: str) -> str:
    start_marker = "<!-- webclip:manual:start -->\n"
    end_marker = "<!-- webclip:manual:end -->"
    start = text.find(start_marker)
    if start < 0:
        return ""
    start += len(start_marker)
    end = text.find(end_marker, start)
    return text[start:end] if end >= 0 else ""


def _managed_section(text: str) -> str | None:
    start_marker = "<!-- webclip:managed:start -->\n"
    end_marker = "<!-- webclip:managed:end -->"
    start = text.find(start_marker)
    if start < 0:
        return None
    start += len(start_marker)
    end = text.find(end_marker, start)
    return text[start:end] if end >= 0 else None


def _note_semantic_state(text: str) -> tuple[dict[str, object], str] | None:
    metadata = _frontmatter_from_text(text)
    managed = _managed_section(text)
    if metadata is None or managed is None:
        return None
    comparable_metadata = dict(metadata)
    comparable_metadata.pop("created", None)
    return comparable_metadata, managed


def _with_manual_section(note: str, manual: str) -> str:
    marker = "<!-- webclip:manual:start -->\n"
    start = note.find(marker)
    end_marker = "<!-- webclip:manual:end -->"
    end = note.find(end_marker, start + len(marker)) if start >= 0 else -1
    if start < 0 or end < 0:
        raise ClipError("The generated note is missing managed boundaries.")
    return note[: start + len(marker)] + manual + note[end:]


_FAVORITE_LINE = re.compile(r"^favorite[ \t]*:")


def _find_original_host_index(lines: Sequence[str]) -> int | None:
    """Return the index of the top-level ``original_host`` key, if present.

    YAML top-level keys start at column zero. Matching without stripping
    leading whitespace keeps indented continuation lines inside multi-line
    values from being mistaken for the real key.
    """
    for i, line in enumerate(lines):
        if line.startswith("original_host:"):
            return i
    return None


def _favorite_insert_index(lines: Sequence[str]) -> int:
    """Return the index where ``favorite: true`` belongs.

    Immediately after the top-level ``original_host`` key, or at the end of
    the frontmatter when that key is absent.
    """
    host_index = _find_original_host_index(lines)
    return len(lines) if host_index is None else host_index + 1


def _favorite_position_ok(lines: Sequence[str], index: int) -> bool:
    """Return whether the favorite line at *index* sits in its canonical spot."""
    host_index = _find_original_host_index(lines)
    if host_index is not None:
        return index == host_index + 1
    return index == len(lines) - 1


def _remove_existing_favorite(lines: list[str]) -> list[str]:
    """Remove any existing favorite lines from the list, return the filtered list."""
    return [line for line in lines if not _FAVORITE_LINE.match(line)]


def _insert_favorite(lines: list[str]) -> list[str]:
    """Insert exactly one canonical favorite line at its canonical position."""
    remaining = _remove_existing_favorite(lines)
    remaining.insert(_favorite_insert_index(remaining), "favorite: true")
    return remaining


def _set_favorite_marker(text: str, favorite: bool) -> tuple[str, bool]:
    """Add or remove the favorite key in a managed note's frontmatter.

    Only the favorite line is touched, so the remaining frontmatter and the
    body (including the manual section) stay byte-for-byte unchanged.

    The favorite marker is inserted after the ``original_host`` field
    when adding, to keep the frontmatter well-organized.
    """
    normalized = _normalize_text(text)
    if not normalized.startswith("---\n"):
        raise ClipError("The clipped note has no YAML frontmatter to update.")
    end = normalized.find("\n---\n", 4)
    if end < 0:
        raise ClipError("The clipped note has invalid frontmatter boundaries.")
    try:
        metadata = yaml.safe_load(normalized[4:end])
    except yaml.YAMLError as exc:
        raise ClipError("The clipped note has invalid YAML frontmatter.") from exc
    if not isinstance(metadata, dict):
        raise ClipError("The clipped note has invalid YAML frontmatter.")
    if not metadata.get("webclip_id"):
        raise ClipError("Refusing to modify a note that is not webclip-managed.")
    if (
        _managed_section(normalized) is None
        or "<!-- webclip:manual:start -->" not in normalized
        or "<!-- webclip:manual:end -->" not in normalized
    ):
        raise ClipError("The existing note is not a valid webclip note.")

    lines = normalized[4:end].split("\n")
    indexes = [index for index, line in enumerate(lines) if _FAVORITE_LINE.match(line)]

    if favorite:
        if metadata.get("favorite") is True and len(indexes) == 1:
            if lines[indexes[0]].strip() in {"favorite: true", "favorite: True"}:
                if _favorite_position_ok(lines, indexes[0]):
                    return text, False
        # Drop any existing marker and re-insert one at its canonical position,
        # so an out-of-place marker is repositioned instead of left behind.
        lines = _insert_favorite(lines)
    else:
        if not indexes:
            if "favorite" in metadata:
                raise ClipError(
                    "The favorite marker is not stored as a simple frontmatter field."
                )
            return text, False
        for index in reversed(indexes):
            del lines[index]
    return "---\n" + "\n".join(lines) + normalized[end:], True


def _read_note_for_marker(target: Path) -> str:
    """Read a note for a marker update, refusing symlinks and missing files."""
    if target.is_symlink():
        raise ClipError("Refusing to modify a symbolic-link note.")
    if not target.exists():
        raise ClipError("The clipped note does not exist.")
    try:
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ClipError("Could not read the existing clipped note.") from exc


def set_frontmatter_flag(target: Path, *, favorite: bool) -> str:
    """Set or clear the favorite marker without touching the article body."""
    existing = _read_note_for_marker(target)
    updated, changed = _set_favorite_marker(existing, favorite)
    if not changed:
        return "unchanged"
    atomic_write(target, updated)
    return "written"


def _has_favorite_flag(target: Path) -> bool:
    """Return whether the note already carries ``favorite: true``."""
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    metadata = _frontmatter_from_text(text)
    return bool(metadata and metadata.get("favorite") is True)


def _note_title(target: Path) -> str:
    """Return the note title for commit messages, falling back to its stem."""
    try:
        metadata = _frontmatter_from_text(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        metadata = None
    title = metadata.get("title") if metadata else None
    if not isinstance(title, str) or not title.strip():
        return target.stem
    return title.strip()


def _marker_commit_message(action: str, targets: Sequence[Path]) -> str:
    """One title for a single note, a count when several notes share the marker."""
    if len(targets) == 1:
        return f"{action}: {_note_title(targets[0])[:60]}"
    return f"{action}: {len(targets)} notes"


def write_managed_note(target: Path, content: str, *, refresh: bool) -> str:
    """Write a new managed note, no-op identical content, or require refresh."""
    if not target.exists():
        atomic_write(target, content)
        return "written"
    if target.is_symlink():
        raise ClipError("Refusing to replace a symbolic-link note.")
    try:
        existing = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ClipError("Could not read the existing clipped note.") from exc
    old_state = _note_semantic_state(existing)
    new_state = _note_semantic_state(content)
    if old_state is None or new_state is None:
        raise ClipError("The existing clipped note has invalid managed metadata.")
    old_meta, old_managed = old_state
    new_meta, new_managed = new_state
    if old_meta.get("webclip_id") != new_meta.get("webclip_id"):
        raise ClipError("Refusing to replace a note managed for a different URL.")
    if old_state == new_state:
        return "unchanged"
    if (
        old_managed == new_managed
        and {key: value for key, value in old_meta.items() if key != "favorite"}
        == {key: value for key, value in new_meta.items() if key != "favorite"}
    ):
        # The marker is user intent, not article content: apply it without
        # requiring --refresh while preserving the manual section.
        atomic_write(target, _with_manual_section(content, _manual_section(existing)))
        return "written"
    if not refresh:
        raise ClipError("The saved page changed; rerun with --refresh to update it.")
    atomic_write(target, _with_manual_section(content, _manual_section(existing)))
    return "written"


# Newer WeChat pages write var nickname = htmlDecode("...").
def _status_paths(raw: bytes) -> set[str]:
    try:
        chunks = raw.decode("utf-8").split("\0")
    except UnicodeDecodeError as exc:
        raise ClipError("Git returned an invalid status response.") from exc
    paths: set[str] = set()
    index = 0
    while index < len(chunks):
        entry = chunks[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4 or entry[2] != " ":
            raise ClipError("Git returned an invalid status response.")
        status = entry[:2]
        paths.add(entry[3:])
        if "R" in status or "C" in status:
            if index >= len(chunks) or not chunks[index]:
                raise ClipError("Git returned an invalid status response.")
            paths.add(chunks[index])
            index += 1
    return paths


class VaultLock:
    """A non-blocking cross-process lock shared by all Vault writers."""

    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self._handle = None

    def __enter__(self) -> "VaultLock":
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._handle = self.path.open("a+", encoding="utf-8")
            os.chmod(self.path, 0o600)
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._handle.seek(0)
            self._handle.truncate()
            self._handle.write(f"pid={os.getpid()}\n")
            self._handle.flush()
        except BlockingIOError as exc:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            raise ClipError("Another Vault write operation is already running.") from exc
        except OSError as exc:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            raise ClipError("Could not acquire the shared Vault write lock.") from exc
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


class GitSync:
    """A preflight-approved Git repository that may receive one clip note."""

    def __init__(self, vault: Path, repo_root: Path, branch: str):
        self.vault = vault
        self.repo_root = repo_root
        self.branch = branch

    @staticmethod
    def _git(repo: Path, *args: str, timeout: int = GIT_TIMEOUT) -> ProcessResult:
        return _run_bounded(
            ["git", "-C", str(repo), *args],
            timeout=timeout,
            stdout_limit=MAX_GIT_OUTPUT_BYTES,
            stderr_limit=MAX_STDERR_BYTES,
        )

    @classmethod
    def preflight(
        cls, vault: Path, expected_branch: str | None = None
    ) -> "GitSync":
        vault = vault.resolve()
        top = cls._git(vault, "rev-parse", "--show-toplevel")
        if top.returncode != 0:
            raise ClipError("Git protection requires the vault to be a Git repository.")
        repo_root = Path(_decode_output(top).strip()).resolve()
        _require_within(vault, repo_root, "The vault Git repository is invalid.")

        branch_result = cls._git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD")
        if branch_result.returncode != 0:
            raise ClipError("Git protection requires an active branch.")
        branch = _decode_output(branch_result).strip()
        if expected_branch is not None and branch != expected_branch:
            raise ClipError("The Vault is not on the configured clip sync branch.")

        for state_name in (
            "MERGE_HEAD",
            "CHERRY_PICK_HEAD",
            "REVERT_HEAD",
            "rebase-merge",
            "rebase-apply",
            "sequencer",
        ):
            state = cls._git(repo_root, "rev-parse", "--git-path", state_name)
            if state.returncode != 0:
                raise ClipError("Could not verify the Git operation state.")
            state_path = Path(_decode_output(state).strip())
            if not state_path.is_absolute():
                state_path = repo_root / state_path
            if state_path.exists():
                raise ClipError("Refusing to clip during an in-progress Git operation.")

        status = cls._git(
            repo_root, "status", "--porcelain=v1", "-z", "--untracked-files=all"
        )
        if status.returncode != 0:
            raise ClipError("Could not verify the Git worktree state.")
        if status.stdout:
            raise ClipError("Git protection requires an entirely clean worktree.")
        if expected_branch is not None:
            remote = cls._git(repo_root, "remote", "get-url", "origin")
            if remote.returncode != 0:
                raise ClipError("Git protection requires an origin remote.")
            fetched = cls._git(repo_root, "fetch", "--prune", "origin")
            if fetched.returncode != 0:
                raise ClipError("Could not fetch the Vault Git remote.")
            upstream = cls._git(
                repo_root,
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{u}",
            )
            if upstream.returncode != 0:
                raise ClipError("The clip sync branch has no upstream.")
            rebased = cls._git(repo_root, "rebase", _decode_output(upstream).strip())
            if rebased.returncode != 0:
                cls._git(repo_root, "rebase", "--abort")
                raise ClipError("Vault Git rebase conflicted; no clip was written.")
        return cls(vault, repo_root, branch)

    def _relative_paths(self, generated_paths: Sequence[Path]) -> set[str]:
        relative: set[str] = set()
        for path in generated_paths:
            resolved = path.resolve()
            _require_within(resolved, self.vault, "Generated note is outside the vault.")
            _require_within(resolved, self.repo_root, "Generated note is outside Git.")
            relative.add(resolved.relative_to(self.repo_root).as_posix())
        if not relative:
            raise ClipError("No generated note was supplied to Git.")
        return relative

    def finalize(
        self, generated_paths: Sequence[Path], *, commit_message: str | None = None
    ) -> GitOutcome:
        """Synchronize generated paths, preserving the note on every Git failure."""
        try:
            return self._finalize(generated_paths, commit_message=commit_message)
        except ClipError:
            return GitOutcome("verification_failed", "not_attempted")

    def _finalize(
        self, generated_paths: Sequence[Path], *, commit_message: str | None = None
    ) -> GitOutcome:
        expected = self._relative_paths(generated_paths)
        status = self._git(
            self.repo_root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        )
        if status.returncode != 0:
            return GitOutcome("verification_failed", "not_attempted")
        try:
            changed = _status_paths(status.stdout)
        except ClipError:
            return GitOutcome("verification_failed", "not_attempted")
        if not changed.issubset(expected):
            return GitOutcome("refused", "not_attempted")
        if not changed:
            return GitOutcome("unchanged", "not_needed")

        add = self._git(self.repo_root, "add", "--", *sorted(changed))
        if add.returncode != 0:
            return GitOutcome("stage_failed", "not_attempted")

        staged = self._git(self.repo_root, "diff", "--cached", "--name-only", "-z")
        unstaged = self._git(self.repo_root, "diff", "--name-only", "-z")
        if staged.returncode != 0 or unstaged.returncode != 0:
            return GitOutcome("verification_failed", "not_attempted")
        staged_paths = {part for part in _decode_output(staged).split("\0") if part}
        unstaged_paths = {part for part in _decode_output(unstaged).split("\0") if part}
        if staged_paths != changed or unstaged_paths:
            return GitOutcome("verification_failed", "not_attempted")

        commit = self._git(
            self.repo_root,
            "commit",
            "-m",
            commit_message or "clip: save web article",
        )
        if commit.returncode != 0:
            return GitOutcome("commit_failed", "not_attempted")
        commit_sha, commit_subject = self._commit_identity()
        committed = self._git(
            self.repo_root,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-z",
            "-r",
            "HEAD",
        )
        post_status = self._git(
            self.repo_root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        )
        if committed.returncode != 0 or post_status.returncode != 0:
            return GitOutcome(
                "committed_unverified",
                "not_attempted",
                commit_sha=commit_sha,
                commit_subject=commit_subject,
            )
        committed_paths = {
            part for part in _decode_output(committed).split("\0") if part
        }
        if committed_paths != changed or post_status.stdout:
            return GitOutcome(
                "committed_unverified",
                "not_attempted",
                commit_sha=commit_sha,
                commit_subject=commit_subject,
            )
        push = self._git(self.repo_root, "push", "-u", "origin", "HEAD")
        if push.returncode != 0:
            return GitOutcome(
                "committed",
                "push_failed",
                commit_sha=commit_sha,
                commit_subject=commit_subject,
            )
        return GitOutcome(
            "committed",
            "pushed",
            commit_sha=commit_sha,
            commit_subject=commit_subject,
        )

    def _commit_identity(self) -> tuple[str, str]:
        """(short sha, stored subject) of HEAD; ("", "") when the lookup fails.

        This runs after a successful commit, so a timeout or a missing command
        must not turn a finished commit into a clip error: the caller still has
        to verify and push it, and only the report loses its sha.
        """
        try:
            head = self._git(self.repo_root, "log", "-1", "--format=%h%x00%s")
        except ClipError:
            return "", ""
        if head.returncode != 0:
            return "", ""
        sha, _, subject = _decode_output(head).partition("\0")
        return sha.strip(), subject.strip()


def _format_published(value: object) -> str:
    """``2026-11-14 03:07:09`` / ISO → ``2026-11-14 03:07``; other text passes through."""
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}))?", text)
    if match:
        date, clock = match.group(1), match.group(2)
        return f"{date} {clock}" if clock else date
    return text


def _article_report_fields(
    article: Mapping[str, object] | None,
) -> tuple[str, str, str, str]:
    """(title, author, published, host) for the clip summary."""
    if not article:
        return "", "", "", ""
    title = str(article.get("title") or "").strip()
    author = str(article.get("author") or "").strip()
    published = _format_published(article.get("published"))
    source = str(article.get("canonicalUrl") or article.get("url") or "").strip()
    host = urlsplit(source).netloc.lower() if source else ""
    return title, author, published, host


def _note_size(path: Path) -> tuple[int, int]:
    """(bytes, lines) of the written note; (0, 0) when it cannot be read."""
    try:
        data = path.read_bytes()
    except OSError:
        return 0, 0
    if not data:
        return 0, 0
    return len(data), data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def _ensure_no_secret_markers(note: str) -> None:
    if any(pattern.search(note) for pattern in _SECRET_PATTERNS):
        raise ClipError("The extracted page contains a credential-like marker; refusing to save it.")


class ClipService:
    def __init__(self, plugin_root: Path, env: Mapping[str, str] | None = None):
        self.plugin_root = plugin_root.resolve()
        self.env = env

    def _load_config(self) -> ClipConfig:
        return (
            ClipConfig.from_env(self.env)
            if self.env is not None
            else ClipConfig.from_file(self.plugin_root / "config.toml")
        )

    def run(self, raw_args: str) -> ClipResult | PendingClipResult:
        options = parse_clip_args(raw_args)
        config = self._load_config()
        with VaultLock(config.lock_file):
            # Preflight (fetch + rebase) before any scan: marker lookups and
            # clip targeting must see the same vault state Git commits against.
            git_sync = (
                None
                if options.no_git
                else GitSync.preflight(config.vault, config.sync_branch)
            )
            if options.target_kind == "webclip_id":
                return self._mark_by_hash(options, config, git_sync)
            if options.favorite is False and not options.refresh:
                # Clearing a marker never creates or refreshes content.
                targets = self._marker_targets(config, options.selector)
                if not targets:
                    raise ClipError("No clipped note exists for this URL.")
                return self._mark_targets(
                    options, config, targets, git_sync=git_sync
                )
            if options.favorite is True and not options.refresh:
                # ensure-favorited: an existing note is marked without the network.
                targets = self._marker_targets(config, options.selector)
                if targets:
                    return self._mark_targets(
                        options, config, targets, git_sync=git_sync
                    )
            return self._run_locked(options, config, git_sync=git_sync)

    def resume_pending(self, decision: str) -> ClipResult:
        normalized = decision.strip().lower()
        if normalized not in {"yes", "no"}:
            raise ClipError("The resume tool requires decision=yes or decision=no.")
        config = self._load_config()
        with VaultLock(config.lock_file):
            return self._resume_locked(config, normalized)

    def run_batch(
        self, specs: Sequence[str], *, commit_message: str | None = None
    ) -> BatchClipResult:
        """Clip or mark several URLs under one vault lock and one Git commit.

        Each *spec* is ``<url> [flags]`` and keeps its own options. Articles are
        written one by one, but every written path is committed and pushed
        together exactly once, so a batch never produces one commit per note.

        A failure on one article is recorded and does not abort the others.
        ``--save-images ask`` is rejected because a single pending confirmation
        cannot represent more than one article.
        """
        if not specs:
            raise ClipError("Batch mode requires at least one URL or webclip_id.")
        options_list = [parse_clip_args(spec) for spec in specs]
        no_git_flags = {options.no_git for options in options_list}
        if len(no_git_flags) > 1:
            raise ClipError("Batch mode requires a consistent --no-git setting.")
        no_git = no_git_flags.pop()

        config = self._load_config()
        with VaultLock(config.lock_file):
            # Preflight (fetch + rebase) before classifying: marker detection
            # reads the vault, so it must see the state Git will commit against.
            git_sync = (
                None
                if no_git
                else GitSync.preflight(config.vault, config.sync_branch)
            )
            # Classify each spec before enforcing the image decision: a spec that
            # only marks an existing note must not require --save-images.
            plans: list[tuple[ClipOptions, str]] = []
            for options in options_list:
                if (
                    options.target_kind == "webclip_id"
                    or (options.favorite is False and not options.refresh)
                ):
                    plans.append((options, "marker"))
                elif (
                    options.favorite is True
                    and not options.refresh
                    and self._marker_targets(config, options.selector)
                ):
                    plans.append((options, "marker"))
                else:
                    plans.append((options, "clip"))
            if any(
                options.save_images == "ask" and kind == "clip"
                for options, kind in plans
            ):
                raise ClipError(
                    "Batch mode requires an explicit --save-images yes or no for "
                    "every URL that extracts a page, so no per-article image prompt "
                    "is silently dropped."
                )

            collected: list[Path] = []
            items: list[BatchClipItem] = []
            saved: list[str] = []
            # Only actions that changed a note may name the commit: a no-op
            # re-favorite must not turn an unfavorite batch into "marker".
            changed_actions: set[str] = set()
            has_clip = False

            for options, kind in plans:
                try:
                    if kind == "marker":
                        matched_by = None
                        if options.target_kind == "webclip_id":
                            matches, matched_by = self._hash_targets(options, config)
                        else:
                            matches = self._marker_targets(config, options.selector)
                            if not matches:
                                raise ClipError("No clipped note exists for this URL.")
                        result = self._mark_targets(
                            options,
                            config,
                            matches,
                            matched_by=matched_by,
                            git_sync=git_sync,
                            defer_git=True,
                            collected=collected,
                        )
                        if result.commit_state != "unchanged":
                            changed_actions.add(result.action)
                        for relative in result.paths:
                            items.append(
                                BatchClipItem(
                                    options.selector, True, relative, result.action
                                )
                            )
                            saved.append(relative)
                        continue

                    result = self._run_locked(
                        options,
                        config,
                        git_sync=git_sync,
                        defer_git=True,
                        collected=collected,
                    )
                    if isinstance(result, PendingClipResult):
                        raise ClipError(
                            "remote images require an explicit --save-images decision"
                        )
                    has_clip = True
                    items.append(
                        BatchClipItem(options.selector, True, result.path, result.action)
                    )
                    saved.append(result.path)
                except ClipError as exc:
                    items.append(BatchClipItem(options.selector, False, error=str(exc)))

            if git_sync is None:
                outcome = GitOutcome("disabled", "disabled")
            elif not collected:
                outcome = GitOutcome("unchanged", "not_needed")
            else:
                # A marker-only batch commits under its own action, and the
                # count reflects the notes actually changed, not every match.
                if has_clip:
                    batch_message = f"clip: batch ({len(saved)} notes)"
                elif changed_actions == {"favorite"}:
                    batch_message = f"favorite: batch ({len(collected)} notes)"
                elif changed_actions == {"unfavorite"}:
                    batch_message = f"unfavorite: batch ({len(collected)} notes)"
                elif changed_actions:
                    batch_message = f"marker: batch ({len(collected)} notes)"
                else:
                    batch_message = f"clip: batch ({len(saved)} notes)"
                outcome = git_sync.finalize(
                    collected,
                    commit_message=commit_message or batch_message,
                )

            github_urls: list[str] = []
            if git_sync is not None and outcome.commit_state == "committed":
                remote = GitSync._git(
                    git_sync.repo_root, "remote", "get-url", "origin"
                )
                if remote.returncode == 0:
                    remote_url = _decode_output(remote).strip()
                    for relative in saved:
                        url = github_blob_url(
                            remote_url, git_sync.branch, relative
                        )
                        if url:
                            github_urls.append(
                                append_query_params(url, config.preview_url_params)
                            )
            return BatchClipResult(
                tuple(items),
                outcome.commit_state,
                outcome.push_state,
                tuple(github_urls),
            )

    def _ensure_destination(self, config: ClipConfig) -> Path:
        try:
            config.destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ClipError("Could not create the configured clip destination.") from exc
        destination = config.destination.resolve()
        _require_within(
            destination,
            config.vault,
            "Configured destination escaped the Obsidian vault.",
        )
        return destination

    @staticmethod
    def _publish_date(article: Mapping[str, object], fallback: str) -> str:
        """Return the article's published date if valid, otherwise *fallback*."""
        published = str(article.get("published") or "").strip()
        if published:
            # Accept full ISO timestamps like "2026-05-20T01:20:46+00:00" and bare dates
            date_part = published[:10]
            try:
                datetime.strptime(date_part, "%Y-%m-%d")
                return date_part
            except ValueError:
                pass
        return fallback

    def _target_for(self, config: ClipConfig, article: Mapping[str, object], capture_date: str) -> Path:
        destination = self._ensure_destination(config)
        source = str(article["canonicalUrl"] or article["url"])
        date_prefix = self._publish_date(article, capture_date)
        return choose_target(
            destination,
            str(article["title"]),
            source,
            capture_date=date_prefix,
        )

    def _result_for_targets(
        self,
        config: ClipConfig,
        targets: Sequence[Path],
        outcome: GitOutcome,
        git_sync: GitSync | None,
        action: str = "clip",
        matched_by: str | None = None,
        article: Mapping[str, object] | None = None,
        image_mode: str = "",
        image_count: int = 0,
    ) -> ClipResult:
        if not targets:
            raise ClipError("No target notes were supplied.")
        relative_paths = tuple(
            target.resolve().relative_to(config.vault).as_posix() for target in targets
        )
        github_url = None
        if git_sync is not None and relative_paths:
            remote = GitSync._git(git_sync.repo_root, "remote", "get-url", "origin")
            if remote.returncode == 0:
                github_url = github_blob_url(
                    _decode_output(remote).strip(),
                    git_sync.branch,
                    relative_paths[0],
                )
                if github_url is not None:
                    github_url = append_query_params(
                        github_url, config.preview_url_params
                    )
        title, author, published, source_host = _article_report_fields(article)
        size_bytes, line_count = _note_size(targets[0])
        return ClipResult(
            relative_paths[0],
            outcome.commit_state,
            outcome.push_state,
            github_url,
            action,
            relative_paths,
            matched_by,
            title=title,
            author=author,
            published=published,
            source_host=source_host,
            image_mode=image_mode,
            image_count=image_count,
            size_bytes=size_bytes,
            line_count=line_count,
            commit_subject=outcome.commit_subject,
            commit_sha=outcome.commit_sha,
        )

    def _result_with_github_url(
        self,
        config: ClipConfig,
        target: Path,
        outcome: GitOutcome,
        git_sync: GitSync | None,
        action: str = "clip",
        *,
        article: Mapping[str, object] | None = None,
        image_mode: str = "",
        image_count: int = 0,
    ) -> ClipResult:
        return self._result_for_targets(
            config,
            [target],
            outcome,
            git_sync,
            action,
            article=article,
            image_mode=image_mode,
            image_count=image_count,
        )

    def _marker_destination(self, config: ClipConfig) -> Path | None:
        """The clip destination when it exists; marker operations never create it."""
        destination = config.destination.resolve()
        _require_within(
            destination,
            config.vault,
            "Configured destination escaped the Obsidian vault.",
        )
        return destination if destination.is_dir() else None

    def _marker_targets(self, config: ClipConfig, source: str) -> list[Path]:
        """Notes recorded for *source*; duplicates are all returned."""
        destination = self._marker_destination(config)
        if destination is None:
            return []
        return _scan_source_matches(destination, source)

    def _hash_targets(
        self, options: ClipOptions, config: ClipConfig
    ) -> tuple[list[Path], str | None]:
        """Notes matching a webclip_id, falling back to their content hash."""
        destination = self._marker_destination(config)
        if destination is None:
            raise ClipError(
                "No clipped note matches this webclip_id or source_content_hash."
            )
        matches, matched_by = _scan_hash_matches(destination, options.target_hash or "")
        if not matches:
            raise ClipError(
                "No clipped note matches this webclip_id or source_content_hash."
            )
        return matches, matched_by

    def _mark_by_hash(
        self,
        options: ClipOptions,
        config: ClipConfig,
        git_sync: GitSync | None,
    ) -> ClipResult:
        """Mark every note matching a webclip_id, falling back to its content hash."""
        matches, matched_by = self._hash_targets(options, config)
        return self._mark_targets(
            options, config, matches, git_sync=git_sync, matched_by=matched_by
        )

    def _mark_targets(
        self,
        options: ClipOptions,
        config: ClipConfig,
        targets: Sequence[Path],
        *,
        git_sync: GitSync | None,
        matched_by: str | None = None,
        defer_git: bool = False,
        collected: list[Path] | None = None,
    ) -> ClipResult:
        """Apply the favorite marker to every target, committing all changes once."""
        if options.favorite is None:
            raise ClipError("A favorite option is required.")
        action = "favorite" if options.favorite else "unfavorite"
        # Validate every target and compute its update before writing anything,
        # so one malformed duplicate cannot leave a half-marked vault behind.
        updates: list[tuple[Path, str]] = []
        for target in targets:
            updated, changed = _set_favorite_marker(
                _read_note_for_marker(target), options.favorite
            )
            if changed:
                updates.append((target, updated))
        for target, updated in updates:
            atomic_write(target, updated)
        changed = [target for target, _ in updates]
        if not changed:
            return self._result_for_targets(
                config,
                targets,
                GitOutcome("unchanged", "not_needed"),
                git_sync,
                action,
                matched_by,
            )
        if defer_git:
            if collected is not None:
                collected.extend(changed)
            outcome = GitOutcome("deferred", "deferred")
        elif git_sync is None:
            outcome = GitOutcome("disabled", "disabled")
        else:
            outcome = git_sync.finalize(
                changed, commit_message=_marker_commit_message(action, changed)
            )
        return self._result_for_targets(
            config, targets, outcome, git_sync, action, matched_by
        )

    def _persist_article(
        self,
        *,
        config: ClipConfig,
        article: Mapping[str, object],
        captured_at: datetime,
        refresh: bool,
        git_sync: GitSync | None,
        content_markdown: str,
        image_mode: str | None,
        image_count: int = 0,
        favorite: bool | None = None,
        generated_paths: Sequence[Path] = (),
        defer_git: bool = False,
        collected: list[Path] | None = None,
    ) -> ClipResult:
        source = str(article["canonicalUrl"] or article["url"])
        target = self._target_for(config, article, captured_at.date().isoformat())
        resolved_favorite = favorite
        if resolved_favorite is None:
            # No explicit intent: keep the marker already stored on the note.
            resolved_favorite = _has_favorite_flag(target) if target.exists() else False
        note = render_note(
            article,
            created=captured_at.isoformat(timespec="seconds"),
            content_markdown=content_markdown,
            image_mode=image_mode,
            favorite=resolved_favorite,
        )
        _ensure_no_secret_markers(note)
        write_managed_note(target, note, refresh=refresh)
        short_title = str(article.get("title", "web article"))[:60]
        commit_msg = f"clip: {short_title}"
        if defer_git:
            # Batch mode: collect every written path so the caller can issue a
            # single commit for the whole run instead of one commit per article.
            if collected is not None:
                collected.append(target)
                collected.extend(generated_paths)
            outcome = GitOutcome("deferred", "deferred")
        else:
            outcome = (
                GitOutcome("disabled", "disabled")
                if git_sync is None
                else git_sync.finalize(
                    [target, *generated_paths], commit_message=commit_msg
                )
            )
        return self._result_with_github_url(
            config,
            target,
            outcome,
            git_sync,
            article=article,
            image_mode=image_mode or "",
            image_count=image_count,
        )

    def _run_locked(
        self,
        options: ClipOptions,
        config: ClipConfig,
        *,
        git_sync: GitSync | None = None,
        defer_git: bool = False,
        collected: list[Path] | None = None,
    ) -> ClipResult | PendingClipResult:
        # Batch mode resolves Git once and passes the object in; standalone
        # calls resolve it here so preflight still runs before extraction.
        if git_sync is None and not options.no_git:
            git_sync = GitSync.preflight(config.vault, config.sync_branch)
        article = _validate_success_payload(
            run_extractor_with_fallback(
                self.plugin_root, options.selector, no_browser=options.no_browser
            )
        )
        captured_at = datetime.now(timezone.utc)
        source_markdown = sanitize_markdown(str(article["markdown"])).rstrip("\n")
        remote_images = find_remote_images(source_markdown)
        if options.save_images == "ask" and remote_images:
            pending_id = _url_hash(str(article["canonicalUrl"] or article["url"]))[:16]
            state = PendingClipState(
                pending_id=pending_id,
                created_at=captured_at.isoformat(timespec="seconds"),
                expires_at=(
                    captured_at.replace(microsecond=0)
                    + timedelta(seconds=PENDING_TTL_SECONDS)
                ).isoformat(),
                article=article,
                refresh=options.refresh,
                no_git=options.no_git,
                favorite=options.favorite,
                vault=str(config.vault),
                destination=str(config.destination),
                images=str(config.images),
                sync_branch=config.sync_branch,
            )
            _store_pending_state(config.pending_root, state)
            return PendingClipResult(str(article["title"]), len(remote_images))
        content_markdown = source_markdown
        image_mode = None
        generated_paths: list[Path] = []
        if options.save_images == "yes" and remote_images:
            target = self._target_for(config, article, captured_at.date().isoformat())
            content_markdown, generated_paths = _localize_images(
                source_markdown,
                str(article["title"]),
                str(article["canonicalUrl"] or article["url"]),
                config.images.resolve(),
                target,
            )
            image_mode = "local"
        elif remote_images:
            image_mode = "remote"
        try:
            return self._persist_article(
                config=config,
                article=article,
                captured_at=captured_at,
                refresh=options.refresh,
                git_sync=git_sync,
                content_markdown=content_markdown,
                image_mode=image_mode,
                image_count=(
                    len(generated_paths) if image_mode == "local" else len(remote_images)
                ),
                favorite=options.favorite,
                generated_paths=generated_paths,
                defer_git=defer_git,
                collected=collected,
            )
        except ClipError:
            if generated_paths:
                _cleanup_localized_files(generated_paths, images_root=config.images.resolve())
            raise

    def _resume_locked(self, config: ClipConfig, decision: str) -> ClipResult:
        pending_root = config.pending_root
        state = _load_pending_state(pending_root)
        if not state.matches_config(config):
            raise ClipError(
                "The pending image confirmation belongs to a different vault or clip configuration."
            )
        article = _validate_success_payload(state.article)
        git_sync = None if state.no_git else GitSync.preflight(config.vault, config.sync_branch)
        captured_at = datetime.fromisoformat(state.created_at)
        source_markdown = sanitize_markdown(str(article["markdown"])).rstrip("\n")
        content_markdown = source_markdown
        image_mode = "remote"
        generated_paths: list[Path] = []
        if decision == "yes":
            target = self._target_for(config, article, captured_at.date().isoformat())
            content_markdown, generated_paths = _localize_images(
                source_markdown,
                str(article["title"]),
                str(article["canonicalUrl"] or article["url"]),
                config.images.resolve(),
                target,
            )
            image_mode = "local"
        try:
            result = self._persist_article(
                config=config,
                article=article,
                captured_at=captured_at,
                refresh=state.refresh,
                git_sync=git_sync,
                content_markdown=content_markdown,
                image_mode=image_mode,
                image_count=(
                    len(generated_paths)
                    if image_mode == "local"
                    else len(find_remote_images(source_markdown))
                ),
                favorite=state.favorite,
                generated_paths=generated_paths,
            )
        except ClipError:
            if generated_paths:
                _cleanup_localized_files(generated_paths, images_root=config.images.resolve())
            raise
        _clear_pending(pending_root, state.pending_id)
        return result


def build_handler(plugin_root: Path):
    """Create the exception boundary required by Hermes slash commands."""
    service = ClipService(plugin_root)

    def handle(raw_args: str) -> str:
        try:
            return service.run(raw_args).user_message()
        except ClipError as exc:
            return f"Clip failed: {exc}"
        except BaseException:
            # The slash-command boundary must never leak stacks, stderr, or secrets.
            return "Clip failed due to an unexpected local error."

    return handle


def build_resume_tool(plugin_root: Path):
    service = ClipService(plugin_root)

    def handle(
        arguments: Mapping[str, object] | None = None,
        decision: str | None = None,
        **_: object,
    ) -> str:
        chosen = decision
        if chosen is None and isinstance(arguments, Mapping):
            raw = arguments.get("decision")
            if isinstance(raw, str):
                chosen = raw
        try:
            return service.resume_pending(chosen or "").user_message()
        except ClipError as exc:
            return f"Clip failed: {exc}"
        except BaseException:
            return "Clip failed due to an unexpected local error."

    return handle