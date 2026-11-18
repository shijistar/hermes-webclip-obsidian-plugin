"""Candidate discovery: choose an adapter, then normalise and de-duplicate.

Order matters. A site adapter must be tried before the generic one, because the
generic adapter matches everything and would otherwise shadow it.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .adapters.base import SiteAdapter
from .adapters.generic_html5 import GenericHtml5Adapter
from .adapters.netease import NeteaseAdapter
from .models import VideoCandidate

_ADAPTERS: tuple[SiteAdapter, ...] = (NeteaseAdapter(), GenericHtml5Adapter())


def adapter_for(url: str) -> SiteAdapter:
    for adapter in _ADAPTERS:
        if adapter.matches(url):
            return adapter
    return _ADAPTERS[-1]


def dedupe(candidates: Sequence[VideoCandidate]) -> list[VideoCandidate]:
    seen: set[str] = set()
    unique: list[VideoCandidate] = []
    for candidate in candidates:
        if not candidate.src or candidate.src in seen:
            continue
        seen.add(candidate.src)
        unique.append(candidate)
    return unique


def discover(
    url: str, *, article: Mapping[str, object] | None = None
) -> list[VideoCandidate]:
    return dedupe(adapter_for(url).discover(url, article=article))
