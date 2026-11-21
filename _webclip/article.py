"""Payload validation for extractor output."""

from __future__ import annotations

from typing import Mapping
import json
import re

from .core import ClipError, _SAFE_ERROR_CODE
from .urls import _validate_http_url, normalize_url

def _decode_json_object(raw: bytes) -> Mapping[str, object]:
    try:
        text = raw.decode("utf-8")
        payload = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClipError("The extractor returned an invalid response.") from exc
    if not isinstance(payload, dict):
        raise ClipError("The extractor returned an invalid response.")
    return payload


# Statuses where one bounded retry can genuinely help. 403 is deliberately
# absent: a bot wall re-scores every attempt, so retrying it makes things worse.
# 501/505/508 are absent for the opposite reason: they are permanent answers
# (unsupported feature, HTTP version, loop detected), so a second attempt only
# costs a round trip before the same verdict.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

# A challenge marker is the literal string the extractor matched (an English or
# Chinese UI phrase). Keep it to printable characters so it cannot inject
# line breaks or quotes into a note the user reads.
_SAFE_MARKER = re.compile(r"""[A-Za-z0-9 '\-\u4e00-\u9fff]{1,60}""")

# Codes that already carry a verdict; their message is the whole answer.
_VERDICT_MESSAGES = {
    "CHALLENGE_PAGE": (
        "The site answered with a browser challenge instead of the page. Repeating the "
        "same request will not clear it — use the site's API or a real browser session."
    ),
    "FAKE_SUCCESS": (
        "The page loaded but its body was not the article its title promised (JS shell or "
        "wall). Nothing was saved."
    ),
}


def _status_message(payload: Mapping[str, object]) -> str:
    status = payload.get("status")
    if not isinstance(status, int) or isinstance(status, bool):
        return "Web extraction failed (HTTP_STATUS)."
    # `cf-mitigated` is set on a managed challenge specifically. Plenty of
    # ordinary sites answer 403 behind Cloudflare without challenging, so the
    # server banner alone must not be read as "bot wall".
    challenged = bool(payload.get("cfMitigated"))
    if status == 401:
        return (
            "The page is reachable but requires credentials (HTTP 401). "
            "Sign in first; retrying the same request will not help."
        )
    if status == 403 and challenged:
        return (
            "The site answered with a bot wall (HTTP 403, challenge). This is not a "
            "network fault: open it in a real browser or use the site's API — a retry "
            "only re-scores the request."
        )
    if status == 403:
        return (
            "The site refused the request (HTTP 403). This is usually a bot wall or an "
            "egress/identity gate; a retry rarely helps."
        )
    if status == 429:
        return (
            "The site is rate limiting this client (HTTP 429). Back off and retry later; "
            "repeating the request immediately keeps the score high."
        )
    if status >= 500:
        return f"The site returned a server error (HTTP {status}); retry later."
    return f"The site returned an unsuccessful status (HTTP {status})."


def _extractor_failure(payload: Mapping[str, object]) -> ClipError:
    code = payload.get("code")
    if not (isinstance(code, str) and _SAFE_ERROR_CODE.fullmatch(code)):
        return ClipError("Web extraction failed.")
    if code in _VERDICT_MESSAGES:
        message = _VERDICT_MESSAGES[code]
        marker = payload.get("marker")
        if code == "CHALLENGE_PAGE" and isinstance(marker, str) and _SAFE_MARKER.fullmatch(marker):
            message = f'{message} Marker: "{marker}".'
        return ClipError(message)
    if code == "HTTP_STATUS":
        status = payload.get("status")
        retry_after = payload.get("retryAfter")
        return ClipError(
            _status_message(payload),
            status=status if isinstance(status, int) and not isinstance(status, bool) else None,
            retry_after=retry_after if isinstance(retry_after, str) else None,
        )
    return ClipError(f"Web extraction failed ({code}).")


_MAX_VIDEO_CANDIDATES = 20


def _validate_videos(value: object) -> list[dict[str, object]]:
    """Validate the extractor's video candidates.

    A page with no players legitimately returns an empty list; what must never
    happen is smuggling a non-http source or an unbounded blob through this
    field, because downstream code hands those strings to a downloader.
    """
    if not isinstance(value, list):
        raise ClipError("The extractor returned invalid video metadata.")
    if len(value) > _MAX_VIDEO_CANDIDATES:
        raise ClipError("The extractor returned too many video candidates.")
    checked: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ClipError("The extractor returned invalid video metadata.")
        src = item.get("src")
        if not isinstance(src, str) or not src or len(src.encode("utf-8")) > 8192:
            raise ClipError("The extractor returned invalid video metadata.")
        _validate_http_url(src)
        entry: dict[str, object] = {"src": src}
        for field, limit in (("type", 256), ("title", 10_000), ("poster", 8192), ("origin", 64)):
            raw = item.get(field, "")
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > limit:
                raise ClipError("The extractor returned invalid video metadata.")
            entry[field] = raw
        for field in ("width", "height"):
            raw = item.get(field, 0)
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0 or raw > 100_000:
                raise ClipError("The extractor returned invalid video metadata.")
            entry[field] = raw
        checked.append(entry)
    return checked


def _validate_success_payload(
    data: Mapping[str, object], *, require_videos: bool = False
) -> dict[str, object]:
    limits = {
        "title": 10_000,
        "author": 100_000,
        "published": 10_000,
        "description": 1_000_000,
        "site": 100_000,
        "canonicalUrl": 8192,
        "url": 8192,
        "markdown": 10 * 1024 * 1024,
        "method": 1000,
    }
    checked: dict[str, object] = {}
    for field, limit in limits.items():
        value = data.get(field)
        if not isinstance(value, str) or len(value.encode("utf-8")) > limit:
            raise ClipError("The extractor returned incomplete or invalid article data.")
        checked[field] = value
    if not checked["title"] or not checked["method"]:
        raise ClipError("The extractor returned incomplete or invalid article data.")
    # Optional: older extractors do not report how well the body matched the title.
    verification = data.get("verification")
    if isinstance(verification, str) and verification in {"strong", "weak"}:
        checked["verification"] = verification
    keywords = data.get("keywords")
    if not isinstance(keywords, list) or len(keywords) > 128:
        raise ClipError("The extractor returned incomplete or invalid article data.")
    normalized_keywords: list[str] = []
    for keyword in keywords:
        if not isinstance(keyword, str) or not keyword or len(keyword.encode("utf-8")) > 256:
            raise ClipError("The extractor returned incomplete or invalid article data.")
        normalized_keywords.append(keyword)
    checked["keywords"] = normalized_keywords
    word_count = data.get("wordCount")
    if isinstance(word_count, bool) or not isinstance(word_count, int) or word_count < 0:
        raise ClipError("The extractor returned incomplete or invalid article data.")
    checked["wordCount"] = word_count
    if "ok" in data and data.get("ok") is not True:
        raise _extractor_failure(data)
    source = checked["canonicalUrl"] or checked["url"]
    if not isinstance(source, str):
        raise ClipError("The extractor returned incomplete or invalid article data.")
    normalize_url(source)
    normalize_url(str(checked["url"]))
    if "videos" in data:
        checked["videos"] = _validate_videos(data.get("videos"))
    elif require_videos:
        # Distinguish "this extractor cannot report videos" from "this page has
        # none": the first is a broken install, the second is a normal answer.
        raise ClipError(
            "The extractor does not report video metadata (outdated extractor)."
        )
    return checked
