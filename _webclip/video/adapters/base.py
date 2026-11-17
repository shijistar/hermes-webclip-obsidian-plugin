"""Site adapter contract.

Adapters exist only where a site needs something the generic DOM collector
cannot supply. The contract is deliberately tiny: decide whether the adapter
owns the URL, produce candidates, and say which headers the download needs.
"""

from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from ..models import VideoCandidate


@runtime_checkable
class SiteAdapter(Protocol):
    name: str
    #: True when candidates come from the extractor's article payload; False when
    #: the adapter fetches the page itself (a pure video page has no article).
    needs_article: bool

    def matches(self, url: str) -> bool: ...

    def discover(
        self, url: str, *, article: Mapping[str, object] | None = None
    ) -> list[VideoCandidate]: ...

    def headers(self, url: str) -> Mapping[str, str]: ...
