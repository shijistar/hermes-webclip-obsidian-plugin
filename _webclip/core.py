"""Errors, shared limits and constants, pure text helpers."""

from __future__ import annotations

import re

EXTRACTOR_TIMEOUT = 90


GIT_TIMEOUT = 120


MAX_STDOUT_BYTES = 12 * 1024 * 1024


MAX_STDERR_BYTES = 64 * 1024


MAX_GIT_OUTPUT_BYTES = 2 * 1024 * 1024


MAX_DESTINATION_SCAN_ENTRIES = 10_000


MAX_IMAGE_BYTES = 15 * 1024 * 1024


PENDING_TTL_SECONDS = 60 * 60


_SAFE_ERROR_CODE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


_SAFE_BRANCH_NAME = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")


_GITHUB_REMOTE_HTTPS = re.compile(r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$")


_GITHUB_REMOTE_SSH = re.compile(r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$")


class ClipError(Exception):
    """An expected error whose message is safe to show to the user.

    ``status`` and ``retry_after`` carry the extractor's machine-readable
    context when it had one, so callers can classify a failure (bot wall vs
    auth vs rate limit) instead of pattern-matching the message.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retry_after: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _normalize_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


MAX_PREVIEW_URL_PARAMS_BYTES = 1024


_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
