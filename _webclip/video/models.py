"""Value objects for the video pipeline.

Kept separate from the clip pipeline on purpose: a video has a source URL, a
container, a byte count and a duration, and none of those map onto a note
record. Sharing a class would force every consumer to branch on which one it
holds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class VideoCandidate:
    """One playable address found on a page, before any network work."""

    src: str
    type: str = ""
    title: str = ""
    poster: str = ""
    width: int = 0
    height: int = 0
    origin: str = ""
    #: Backend hint from the adapter. ``""`` means "infer from the type and the
    #: extension"; ``"ytdlp"`` is the only value the service dispatches on, and it
    #: is reserved for sites where the media cannot be fetched by us at all.
    kind: str = ""

    @staticmethod
    def _as_dimension(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            return 0
        return value if value > 0 else 0

    @classmethod
    def from_extractor(cls, item: Mapping[str, object]) -> "VideoCandidate":
        return cls(
            src=str(item.get("src", "")),
            type=str(item.get("type", "")),
            title=str(item.get("title", "")),
            poster=str(item.get("poster", "")),
            width=cls._as_dimension(item.get("width")),
            height=cls._as_dimension(item.get("height")),
            origin=str(item.get("origin", "")),
        )


@dataclass(frozen=True)
class DownloadPlan:
    """What the downloader needs: addresses in preference order plus headers.

    ``fallbacks`` exists because CDN endpoints are not equally reachable:
    Bilibili hands out a P2P node first and a mirror second, and only the mirror
    answered from this machine. Whichever entry is used, it went through the same
    SSRF guard.
    """

    urls: tuple[str, ...]
    kind: str
    headers: Mapping[str, str] = field(default_factory=dict)
    title: str = ""

    def __post_init__(self) -> None:
        if not self.urls:
            raise ValueError("A download plan needs at least one URL.")
        if self.kind not in {"hls", "dash", "direct", "ytdlp"}:
            raise ValueError(f"Unsupported download kind: {self.kind}")


@dataclass(frozen=True)
class DownloadedFile:
    path: Path
    bytes_written: int
    duration_s: float | None = None


@dataclass(frozen=True)
class VideoOutcome:
    """One candidate's result, successful or not.

    A batch reports every item: silently dropping a failure is the failure mode
    that makes a downloader untrustworthy.
    """

    source: str
    title: str
    ok: bool
    message: str
    path: Path | None = None
    bytes_written: int = 0
    duration_s: float | None = None


@dataclass(frozen=True)
class VideoReport:
    outcomes: tuple[VideoOutcome, ...]
    destination: Path
    inside_vault: bool
    warnings: tuple[str, ...] = ()
    #: True when the destination is inside the vault *and* the ignore rule was
    #: applied. Reporting "ignored by Git" without this is simply false.
    ignored: bool = False

    @property
    def succeeded(self) -> tuple[VideoOutcome, ...]:
        return tuple(item for item in self.outcomes if item.ok)

    @property
    def failed(self) -> tuple[VideoOutcome, ...]:
        return tuple(item for item in self.outcomes if not item.ok)
