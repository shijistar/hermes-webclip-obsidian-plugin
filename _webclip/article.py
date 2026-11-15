"""Payload validation for extractor output."""

from __future__ import annotations

from typing import Mapping
import json

from .core import ClipError, _SAFE_ERROR_CODE
from .urls import normalize_url

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


def _validate_success_payload(data: Mapping[str, object]) -> dict[str, object]:
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
    return checked
