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
from _webclip.service import ClipService, build_handler, build_resume_tool

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