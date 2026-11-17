"""``/save-video`` orchestration.

The pipeline for one URL is:

1. pick an adapter (site-specific first, generic last);
2. let the adapter produce candidates — the generic one uses the extractor's
   ``videos`` field, which is why ``with_videos=True`` is passed there;
3. pre-flight and download each candidate, one at a time;
4. report every outcome, including the failures.

A failure on one video never aborts the rest of the batch: with a list of URLs
the useful behaviour is to save what can be saved and say exactly what could not.
"""

from __future__ import annotations

from pathlib import Path
import os
import secrets
import tomllib
from typing import Mapping
from urllib.parse import urlsplit

from ..config import VideoConfig, parse_save_video_args
from ..core import ClipError
from ..extract import run_extractor
from ..git_sync import VaultLock
from .discover import adapter_for, discover
from .download.direct import download_direct
from .download.hls import download_hls
from .models import DownloadPlan, VideoCandidate, VideoOutcome, VideoReport
from .naming import build_filename, unique_path
from .report import render_report
from .store import commit_gitignore, ensure_gitignore, resolve_destination

DEFAULT_VAULT = "~/obsidian/shijistar"


def _is_hls(candidate: VideoCandidate) -> bool:
    if "mpegurl" in candidate.type.lower():
        return True
    path = urlsplit(candidate.src).path.lower()
    return path.endswith(".m3u8")


class VideoService:
    def __init__(self, plugin_root: Path, env: Mapping[str, str] | None = None):
        self.plugin_root = plugin_root.resolve()
        self.env = env

    def _settings(self) -> VideoConfig:
        return VideoConfig.from_file(self.plugin_root / "config.toml")

    def _clip_section(self) -> dict:
        """``[clip]`` values, read leniently.

        The video command must not fail because some *other* part of the clip
        configuration is broken — it only needs the vault location and the lock
        file to agree with ``/webclip``.

        When ``config.toml`` is absent, ``/webclip`` falls back to the
        environment (``ClipConfig.from_env``); the vault and the lock have to
        come from the same place or the two commands work on different vaults
        and stop excluding each other.
        """
        section: dict = {}
        config_path = self.plugin_root / "config.toml"
        if config_path.is_file():
            try:
                data = tomllib.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, tomllib.TOMLDecodeError):
                data = {}
            found = data.get("clip")
            if isinstance(found, dict):
                section = dict(found)
        env = self.env if self.env is not None else os.environ
        if "vault" not in section and env.get("WEB_TO_OBSIDIAN_VAULT"):
            section["vault"] = env["WEB_TO_OBSIDIAN_VAULT"]
        if "lock_file" not in section and env.get("WEB_TO_OBSIDIAN_LOCK_FILE"):
            section["lock_file"] = env["WEB_TO_OBSIDIAN_LOCK_FILE"]
        return section

    def _vault(self) -> Path:
        raw = DEFAULT_VAULT
        value = self._clip_section().get("vault")
        if isinstance(value, str) and value.strip():
            raw = value.strip()
        vault = Path(raw).expanduser().resolve()
        if not vault.is_dir():
            raise ClipError("The configured Obsidian vault does not exist.")
        return vault

    def _lock_path(self) -> Path:
        """The same lock ``/webclip`` uses.

        Sharing it is the point: both commands write into the vault and inspect
        its worktree, so they must not interleave. A separate lock would let
        ``/save-video`` commit a ``.gitignore`` while ``/webclip`` is staging a
        note, and a single ``git commit`` would sweep both into one commit.
        """
        raw = "~/.hermes/workspace/cache/webclip-obsidian/vault.lock"
        value = self._clip_section().get("lock_file")
        if isinstance(value, str) and value.strip():
            raw = value.strip()
        return Path(raw).expanduser()

    def run(self, raw_args: str) -> VideoReport:
        options = parse_save_video_args(raw_args)
        settings = self._settings()
        vault = self._vault()
        # Two concurrent runs would both pick the same free filename and then
        # overwrite each other's partial file, so a run holds an exclusive lock
        # for its whole duration (the same non-blocking flock the vault uses).
        with VaultLock(self._lock_path()):
            return self._run_locked(options, settings, vault)

    def _run_locked(self, options, settings: VideoConfig, vault: Path) -> VideoReport:
        destination = resolve_destination(
            vault, options.destination or settings.destination
        )
        try:
            destination.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ClipError("Could not create the video destination directory.") from exc

        # Doing this before the download keeps the worktree clean afterwards; a
        # dirty tree makes the next /webclip refuse to run. The commit is
        # attempted unconditionally: an earlier run may have written the block
        # and then failed to commit it, and skipping the retry here would leave
        # that modification in the tree forever.
        ignored = destination.inside_vault and settings.gitignore
        if ignored:
            ensure_gitignore(vault, destination.directory)
            commit_gitignore(vault)

        outcomes: list[VideoOutcome] = []
        attempted = 0
        multi_page = len(options.urls) >= 2
        for url in options.urls:
            for outcome, attempted_next in self._process(
                url,
                options=options,
                settings=settings,
                directory=destination.directory,
                multi_page=multi_page,
                attempted=attempted,
            ):
                outcomes.append(outcome)
                attempted = attempted_next

        return VideoReport(
            outcomes=tuple(outcomes),
            destination=destination.directory,
            inside_vault=destination.inside_vault,
            warnings=settings.warnings,
            ignored=bool(ignored),
        )

    def _process(
        self,
        url: str,
        *,
        options,
        settings: VideoConfig,
        directory: Path,
        multi_page: bool,
        attempted: int,
    ):
        adapter = adapter_for(url)
        try:
            article = None
            if adapter.needs_article:
                article = run_extractor(
                    self.plugin_root,
                    url,
                    no_browser=options.no_browser,
                    with_videos=True,
                )
            candidates = discover(url, article=article)
        except ClipError as exc:
            yield (
                VideoOutcome(source=url, title="", ok=False, message=str(exc)),
                attempted,
            )
            return

        if not candidates:
            yield (
                VideoOutcome(
                    source=url,
                    title="",
                    ok=False,
                    message="No video was found on this page.",
                ),
                attempted,
            )
            return

        use_index = len(candidates) >= 2 or multi_page
        for position, candidate in enumerate(candidates, start=1):
            if attempted >= settings.max_per_run:
                yield (
                    VideoOutcome(
                        source=candidate.src,
                        title=candidate.title,
                        ok=False,
                        message=(
                            f"Skipped: the per-run limit of {settings.max_per_run} "
                            "downloads was reached."
                        ),
                    ),
                    attempted,
                )
                continue
            attempted += 1
            yield (
                self._download_one(
                    url,
                    candidate,
                    adapter=adapter,
                    options=options,
                    settings=settings,
                    directory=directory,
                    index=position if use_index else None,
                ),
                attempted,
            )

    def _download_one(
        self,
        page_url: str,
        candidate: VideoCandidate,
        *,
        adapter,
        options,
        settings: VideoConfig,
        directory: Path,
        index: int | None,
    ) -> VideoOutcome:
        max_bytes = settings.max_size_mb * 1024 * 1024
        kind = "hls" if _is_hls(candidate) else "direct"
        plan = DownloadPlan(
            urls=(candidate.src,),
            kind=kind,
            headers=adapter.headers(page_url),
            title=candidate.title,
        )
        try:
            filename = build_filename(
                title=candidate.title,
                src=candidate.src,
                candidate_type=candidate.type,
                name=options.name,
                index=index,
            )
            target = unique_path(directory, filename, overwrite=options.overwrite)
        except (ValueError, ClipError) as exc:
            # `build_filename` hashes the URL as a last resort, and that hash
            # validates it — a page-supplied source with a bad port or embedded
            # credentials surfaces as ClipError here, not ValueError. Letting it
            # escape would abort the whole batch.
            return VideoOutcome(
                source=candidate.src,
                title=candidate.title,
                ok=False,
                message=str(exc),
            )
        # Download next to the target and rename only after the merge succeeded.
        # Writing straight to `target` would destroy an existing file the moment
        # `--overwrite` was used and the download then failed.
        # The extension stays last: ffmpeg infers the output container from it,
        # and `name.mp4.part` makes it fail with "no suitable output format".
        # The random infix lets `download_to_file` create the file with O_EXCL:
        # a name derived only from the title is guessable, and an existing
        # symlink at that path would redirect the write.
        working = target.with_name(
            f"{target.stem}.{secrets.token_hex(4)}.part{target.suffix}"
        )

        try:
            if kind == "hls":
                downloaded = download_hls(
                    plan,
                    working,
                    timeout=settings.download_timeout_s,
                    max_bytes=max_bytes,
                )
            else:
                downloaded = download_direct(
                    plan,
                    working,
                    timeout=settings.download_timeout_s,
                    max_bytes=max_bytes,
                )
            os.replace(working, target)
        except ClipError as exc:
            working.unlink(missing_ok=True)
            return VideoOutcome(
                source=candidate.src,
                title=candidate.title,
                ok=False,
                message=str(exc),
            )
        except OSError:
            working.unlink(missing_ok=True)
            return VideoOutcome(
                source=candidate.src,
                title=candidate.title,
                ok=False,
                message="Could not write the downloaded file.",
            )
        except BaseException:
            working.unlink(missing_ok=True)
            raise

        return VideoOutcome(
            source=candidate.src,
            title=candidate.title,
            ok=True,
            message="",
            path=target,
            bytes_written=downloaded.bytes_written,
            duration_s=downloaded.duration_s,
        )


def build_handler(plugin_root: Path):
    """Create the exception boundary required by Hermes slash commands."""
    service = VideoService(plugin_root)

    def handle(raw_args: str) -> str:
        try:
            return render_report(service.run(raw_args))
        except ClipError as exc:
            return f"Video download failed: {exc}"
        except BaseException:
            # The command boundary must never leak stacks, stderr, or secrets.
            return "Video download failed due to an unexpected local error."

    return handle
