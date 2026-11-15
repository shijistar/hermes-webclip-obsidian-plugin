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
from _webclip.markdown import _DANGEROUS_SCHEMES, _INLINE_CODE_SPAN, _REMOTE_MARKDOWN_IMAGE, _SAFE_VIDEO_SRC_RE, _VIDEO_PLACEHOLDER, _VIDEO_SRC_ATTR_RE, _VIDEO_TAG_RE, _canonical_video_tag, _collect_remote_images, _contains_markdown_h1, _content_hash, _is_indented_code_line, _managed_markdown, _protect_video_tags, _restore_video_tags, _sanitize_active_markdown_segment, _sanitize_text_preserving_inline_code, _sanitized_heading_title, _scan_remote_images_in_plain_text, find_remote_images, render_note, sanitize_markdown
from _webclip.notes import _FAVORITE_LINE, _checked_candidate, _destination_notes, _digest_matches, _favorite_insert_index, _favorite_position_ok, _find_original_host_index, _frontmatter_from_text, _has_favorite_flag, _insert_favorite, _managed_section, _manual_section, _marker_commit_message, _note_hashes, _note_prefix, _note_semantic_state, _note_title, _read_note_for_marker, _remove_existing_favorite, _scan_hash_matches, _scan_source_matches, _set_favorite_marker, _sources_from_note, _with_manual_section, _write_target_ok, choose_target, read_skill_frontmatter, set_frontmatter_flag, write_managed_note
from _webclip.images import _ApprovedRemoteImageUrl, _BLOCKED_IMAGE_IPV4_NETWORKS, _BLOCKED_IMAGE_IPV6_NETWORKS, _IMAGE_SUFFIX_BY_SUBTYPE, _PinnedHTTPConnection, _PinnedHTTPSConnection, _PinnedRemoteResponse, _REMOTE_FETCH_POLICY_MESSAGE, _REMOTE_REDIRECT_STATUSES, _cleanup_localized_files, _fetch_remote_image, _first_remote_header, _is_blocked_remote_ip, _localize_images, _perform_pinned_remote_image_request, _read_remote_response_body, _remote_host_header, _resolve_remote_image_url, _rewrite_remote_image_references, _slugify_image_dir, _socket_target, _suffix_for_content_type, download_remote_image
from _webclip.pending import PendingClipState, _active_pending_pointer, _clear_pending, _load_pending_state, _pending_state_path, _store_pending_state, _write_json
from _webclip.git_sync import GitOutcome, GitSync, VaultLock, _status_paths
from _webclip.report import BatchClipItem, BatchClipResult, ClipResult, PendingClipResult, _SUMMARY_LABELS, _article_report_fields, _batch_label, _ensure_no_secret_markers, _format_published, _note_size, _summary_cell

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


# A single-line `<video>...</video>` tag (the shape emitted for video clips).
# Only http(s) URLs without characters that could break out of the attribute.
# Canonical extension per image subtype. Unknown subtypes fall back to the URL's own
# suffix so a server can never make us invent an extension from an arbitrary token.
# Newer WeChat pages write var nickname = htmlDecode("...").
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