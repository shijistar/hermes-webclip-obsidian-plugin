"""Payload validation for extractor output."""

from __future__ import annotations

from typing import Mapping
import json

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


def _extractor_failure(payload: Mapping[str, object]) -> ClipError:
    code = payload.get("code")
    if isinstance(code, str) and _SAFE_ERROR_CODE.fullmatch(code):
        return ClipError(f"Web extraction failed ({code}).")
    return ClipError("Web extraction failed.")


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
