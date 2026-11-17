"""Fallback adapter: whatever the extractor found in the DOM.

This is the only adapter that consumes the ``videos`` field. It matches every
URL, so it must stay last in the registry — a site-specific adapter placed after
it would never run.
"""

from __future__ import annotations

from typing import Mapping

from ..models import VideoCandidate


class GenericHtml5Adapter:
    name = "generic"
    needs_article = True

    def matches(self, url: str) -> bool:
        return True

    def discover(
        self, url: str, *, article: Mapping[str, object] | None = None
    ) -> list[VideoCandidate]:
        if not article:
            return []
        raw = article.get("videos")
        if not isinstance(raw, list):
            return []
        return [VideoCandidate.from_extractor(item) for item in raw if isinstance(item, dict)]

    def headers(self, url: str) -> Mapping[str, str]:
        return {}
