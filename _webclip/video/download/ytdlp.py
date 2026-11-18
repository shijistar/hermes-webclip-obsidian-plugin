"""Optional ``yt-dlp`` backend.

This is the only downloader that fetches the media itself instead of handing each
address to :mod:`_webclip.netguard`, so the guards below are the whole safety
argument and each one earns its place:

* ``--ignore-config``: yt-dlp otherwise reads the user's config file, which may
  contain ``--exec`` — that would let a config file run arbitrary commands from
  inside the plugin;
* ``--no-playlist``: a ``watch?v=..&list=..`` URL would otherwise download an
  entire playlist past the per-run limit;
* ``[protocol=https]`` in the format selector: the ``m3u8_native`` variants
  returned ``HTTP 403`` on every attempt from this machine, while the ``https``
  ones downloaded and merged fine (measured 2026-11-18);
* ``--max-filesize`` plus a post-hoc size check: ``max_size_mb`` keeps its
  meaning even when the reported size was only an estimate;
* a wall-clock timeout of its own: ``download_timeout_s`` is a per-request
  ceiling in the HLS path and would kill any long video here.
"""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import tempfile

from ...core import ClipError, MAX_STDERR_BYTES, MAX_STDOUT_BYTES
from ...proc import _run_bounded
from ..models import DownloadPlan, DownloadedFile
from .ffmpeg import find_ffmpeg, probe_duration

#: Whole-run budget. A 10 minute clip needs far more than the 300 s default that
#: applies to a single HTTP request elsewhere.
YTDLP_TIMEOUT = 1800
_FORMAT = "bv*[protocol=https]+ba[protocol=https]/b[protocol=https]/b"
#: Audio is whatever yt-dlp considers best (in practice Opus). Preferring
#: `[ext=m4a]` was tried and abandoned: on this machine that variant stalled at
#: 1.8 MB for ten minutes with no progress, while the default audio completed.
#: Chromium (and therefore Obsidian) plays Opus in mp4.
_RENDERED_SUFFIXES = {".mp4", ".mkv", ".webm"}
#: The gateway inherits a different PATH than an interactive shell, and the
#: binary lands here on the two supported platforms.
_CANDIDATE_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
_PASSTHROUGH_ENV = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "SSL_CERT_FILE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)
_NOT_ENABLED = (
    "YouTube downloads need yt-dlp, which is not enabled. Install it with "
    "`brew install yt-dlp`, or point [video].ytdlp at the binary."
)


def find_ytdlp(configured: str = "") -> str:
    """Locate the binary: explicit config, then PATH, then the usual prefixes."""
    if configured:
        path = Path(configured).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        raise ClipError(
            f"[video].ytdlp points at {configured}, which is not an executable file."
        )
    found = shutil.which("yt-dlp")
    if found:
        return found
    for directory in _CANDIDATE_DIRS:
        candidate = Path(directory) / "yt-dlp"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise ClipError(_NOT_ENABLED)


def _environment() -> dict[str, str]:
    # yt-dlp needs HOME for its cache and PATH for ffmpeg/deno; proxies are
    # passed through because the extractor's own allowlist drops them.
    return {key: value for key, value in os.environ.items() if key in _PASSTHROUGH_ENV}


def _reason(stderr: bytes) -> str:
    """Map the common upstream failures to something a user can act on."""
    text = stderr.decode("utf-8", errors="replace")
    if "403" in text or "Forbidden" in text:
        return "YouTube refused the download (HTTP 403); retry later."
    if "Sign in" in text or "age" in text.lower():
        return "YouTube requires a signed-in account for this video."
    if "Requested format is not available" in text:
        return "YouTube offered no downloadable format for this video."
    return "yt-dlp could not download this video."


def _claim(destination: Path) -> None:
    """Create the output exclusively, so a pre-placed symlink cannot redirect it."""
    os.close(os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644))


def download_ytdlp(
    plan: DownloadPlan,
    destination: Path,
    *,
    executable: str,
    timeout: int = YTDLP_TIMEOUT,
    max_bytes: int = 500 * 1024 * 1024,
) -> DownloadedFile:
    with tempfile.TemporaryDirectory(prefix="webclip-ytdlp-") as tmp:
        directory = Path(tmp)
        # yt-dlp picks the extension and the merge target itself, so it writes
        # into its own directory and the plugin renames afterwards. Feeding it the
        # final `.part.mp4` name would fight with its own `.part` handling.
        template = str(directory / "video.%(ext)s")
        command = [
            executable,
            "--ignore-config",
            "--no-playlist",
            "--no-progress",
            "--no-warnings",
            # Without a socket timeout a throttled track hangs until the 1800 s
            # wall clock expires (measured: an m4a audio stream stalled at 1.8 MB
            # for ten minutes). Fail fast and let the retries decide.
            "--socket-timeout",
            "20",
            "--retries",
            "2",
            "--max-filesize",
            str(max_bytes),
            "-f",
            _FORMAT,
            "-S",
            "res:1080,codec:avc1",
            "--merge-output-format",
            "mp4",
            "--ffmpeg-location",
            find_ffmpeg(),
            "-o",
            template,
            "--",
            plan.urls[0],
        ]
        result = _run_bounded(
            command,
            timeout=timeout,
            stdout_limit=MAX_STDOUT_BYTES,
            stderr_limit=MAX_STDERR_BYTES,
            env=_environment(),
        )
        if result.returncode != 0:
            raise ClipError(_reason(result.stderr))

        produced = [
            item
            for item in directory.iterdir()
            if item.is_file() and item.suffix.lower() in _RENDERED_SUFFIXES
        ]
        if len(produced) != 1:
            raise ClipError("yt-dlp did not leave exactly one video file behind.")
        output = produced[0]
        size = output.stat().st_size
        if size == 0:
            raise ClipError("yt-dlp produced an empty file.")
        if size > max_bytes:
            raise ClipError("The video is larger than the configured size limit.")

        _claim(destination)
        with output.open("rb") as source, destination.open("wb") as target:
            shutil.copyfileobj(source, target)

    return DownloadedFile(
        path=destination,
        bytes_written=size,
        duration_s=probe_duration(destination),
    )
