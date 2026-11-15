"""URL validation, normalisation, preview-link construction."""

from __future__ import annotations

from urllib.parse import parse_qsl
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.parse import urlsplit
from urllib.parse import urlunsplit
import hashlib
import re
import unicodedata

from .core import ClipError, MAX_PREVIEW_URL_PARAMS_BYTES, _GITHUB_REMOTE_HTTPS, _GITHUB_REMOTE_SSH

def _validate_http_url(value: str) -> None:
    if len(value) > 8192:
        raise ClipError("The URL is too long.")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ClipError("A valid HTTP or HTTPS URL is required.") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None and not 0 < port < 65536
    ):
        raise ClipError("A valid HTTP or HTTPS URL is required.")


_SHA256_SELECTOR_RE = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$", re.IGNORECASE)


def _parse_target_selector(value: str) -> tuple[str, str, str | None]:
    """Classify the positional as a URL or a sha256 selector.

    Returns ``(target_kind, selector, digest)`` where *digest* is the bare
    lowercase hex string for a ``webclip_id`` target and ``None`` for a URL.
    """
    match = _SHA256_SELECTOR_RE.match(value.strip())
    if match:
        digest = match.group(1).lower()
        return "webclip_id", f"sha256:{digest}", digest
    _validate_http_url(value)
    return "url", value, None


def normalize_url(value: str) -> str:
    """Return a stable URL form used only for source identity comparisons."""
    _validate_http_url(value)
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ClipError("The page returned an invalid source URL.") from exc
    port = parsed.port
    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def _url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


def _normalize_preview_url_params(value: str) -> str:
    """Validate and canonicalize the configured preview query parameters.

    Only plain ``k=v&k2=v2`` pairs are accepted, with at most one optional
    leading ``?``. Surrounding whitespace is rejected rather than trimmed, and
    control characters (C0, DEL and C1) are refused. The value becomes part of a
    Markdown link, so anything that could alter the URL structure or inject
    markup is rejected here.
    """
    raw = value
    if not raw:
        return ""
    if raw.startswith("?"):
        raw = raw[1:]
    if len(raw.encode("utf-8")) > MAX_PREVIEW_URL_PARAMS_BYTES:
        raise ClipError("The configured preview URL parameters are too long.")
    if not raw or any(ch in raw for ch in "?#") or any(
        unicodedata.category(ch) == "Cc" or ch.isspace() for ch in raw
    ):
        raise ClipError(
            "The configured preview URL parameters contain unsafe characters."
        )
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise ClipError(
            "The configured preview URL parameters must be k=v pairs."
        ) from exc
    if not pairs or any(not key for key, _ in pairs):
        raise ClipError("The configured preview URL parameters must be k=v pairs.")
    return urlencode(pairs, doseq=True)


def append_query_params(url: str, params: str) -> str:
    """Append pre-validated query parameters to *url*.

    The path is preserved verbatim, but an existing query string is parsed and
    re-encoded together with *params*, so its byte representation may change
    (for example ``%20`` becomes ``+``). *params* must already be normalized by
    ``_normalize_preview_url_params``; a malformed value raises ``ValueError``.
    """
    if not params:
        return url
    pairs = parse_qsl(params, keep_blank_values=True, strict_parsing=True)
    parts = urlsplit(url)
    merged = parse_qsl(parts.query, keep_blank_values=True) + pairs
    return urlunsplit(parts._replace(query=urlencode(merged, doseq=True)))


def github_blob_url(origin_url: str, branch: str, relative_path: str) -> str | None:
    remote = origin_url.strip()
    match = _GITHUB_REMOTE_HTTPS.fullmatch(remote) or _GITHUB_REMOTE_SSH.fullmatch(remote)
    if match is None:
        return None
    owner, repo = match.groups()
    return (
        f"https://github.com/{owner}/{repo}/blob/{quote(branch, safe='')}/"
        f"{quote(relative_path, safe='/')}"
    )
