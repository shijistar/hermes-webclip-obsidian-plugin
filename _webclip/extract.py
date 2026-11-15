"""Node.js extractor invocation."""

from __future__ import annotations

from pathlib import Path
import os

from .article import _decode_json_object, _extractor_failure, _validate_success_payload
from .core import ClipError, EXTRACTOR_TIMEOUT, MAX_STDERR_BYTES, MAX_STDOUT_BYTES
from .proc import _run_bounded

def _extractor_environment() -> dict[str, str]:
    allowed = (
        "HOME",
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TZ",
        "PLAYWRIGHT_BROWSERS_PATH",
    )
    child = {key: os.environ[key] for key in allowed if os.environ.get(key)}
    child.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    child.setdefault("HOME", str(Path.home()))
    return child


def _extractor_dir(plugin_root: Path) -> Path:
    """Locate the standalone Node.js extractor package.

    Resolution order (first match wins):

    1. **Plugin-local npm install** — ``plugin_root/node_modules`` contains
       the published ``@tiny-codes/web-clip-extractor`` package (installed
       with ``npm install`` inside the plugin directory). This is the
       production layout after ``hermes plugins install`` pulls the plugin:
       the extractor npm package rides with the plugin version.
    2. **Bundled subdirectory** — ``plugin_root/extractor`` (the repo root is
       the plugin package, so a source checkout ships the extractor inside the
       plugin and it can be used without an npm install).
    3. **Legacy source-repo sibling** — extractor at ``plugin_root.parent /
       "extractor"`` (old monorepo layout where ``plugin/`` and ``extractor/``
       sat side by side).
    """
    npm_pkg = (
        plugin_root / "node_modules" / "@tiny-codes" / "web-clip-extractor"
    )
    if (npm_pkg / "src" / "cli.mjs").is_file():
        return npm_pkg
    direct = plugin_root / "extractor"
    if (direct / "src" / "cli.mjs").is_file():
        return direct
    return plugin_root.parent / "extractor"


def run_extractor(
    plugin_root: Path, url: str, no_browser: bool = False
) -> dict[str, object]:
    extractor_dir = _extractor_dir(plugin_root)
    command = ["node", str(extractor_dir / "src" / "cli.mjs"), url]
    if no_browser:
        command.append("--no-browser")
    result = _run_bounded(
        command,
        timeout=EXTRACTOR_TIMEOUT,
        stdout_limit=MAX_STDOUT_BYTES,
        stderr_limit=MAX_STDERR_BYTES,
        cwd=extractor_dir,
        env=_extractor_environment(),
    )
    try:
        payload = _decode_json_object(result.stdout)
    except ClipError:
        raise
    if result.returncode != 0 or payload.get("ok") is not True:
        raise _extractor_failure(payload)
    return _validate_success_payload(payload)
