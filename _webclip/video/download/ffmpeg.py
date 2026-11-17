"""ffmpeg discovery and invocation.

ffmpeg is only ever used to **remux local files**. The playlist and every
segment are fetched by :mod:`_webclip.netguard`, which enforces the SSRF policy
and the byte ceiling; handing a page-controlled URL straight to ffmpeg would
bypass both.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil

from ...core import ClipError, MAX_STDERR_BYTES, MAX_STDOUT_BYTES
from ...proc import _run_bounded

FFMPEG_TIMEOUT = 1800
DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def find_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    # The gateway inherits a different PATH than an interactive shell, so the
    # tools directory is checked explicitly instead of trusting `which`.
    tools = Path.home() / ".hermes" / "tools"
    if tools.is_dir():
        for candidate in sorted(tools.glob("ffmpeg-*/ffmpeg"), reverse=True):
            if candidate.is_file():
                return str(candidate)
    raise ClipError("ffmpeg is required to merge a video stream but was not found.")


def run_ffmpeg(args: list[str], *, timeout: int = FFMPEG_TIMEOUT) -> None:
    # `-y`: overwrite semantics are decided by the plugin (it writes to a
    # `.part` file and renames), so ffmpeg must never stop to ask. With the
    # stdin closed (`-nostdin`) that prompt is an immediate failure instead.
    command = [
        find_ffmpeg(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        *args,
    ]
    result = _run_bounded(
        command,
        timeout=timeout,
        stdout_limit=MAX_STDOUT_BYTES,
        stderr_limit=MAX_STDERR_BYTES,
    )
    if result.returncode != 0:
        raise ClipError("Merging the downloaded stream failed.")


def probe_duration(path: Path) -> float | None:
    """Container duration in seconds, or None when it cannot be read.

    `ffmpeg -i` without an output file always exits non-zero; that is expected
    here, so the return code is deliberately ignored and only stderr is read.
    """
    try:
        result = _run_bounded(
            [find_ffmpeg(), "-hide_banner", "-nostdin", "-i", str(path)],
            timeout=120,
            stdout_limit=MAX_STDOUT_BYTES,
            stderr_limit=MAX_STDERR_BYTES,
        )
    except ClipError:
        return None
    match = DURATION_RE.search(result.stderr.decode("utf-8", errors="replace"))
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
