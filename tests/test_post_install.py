"""post-install.sh tests (issue #20): config.toml preservation on refresh.

These tests run the real ``post-install.sh`` against a hermetic fake Hermes
home. A ``hermes`` shim on PATH simulates ``hermes plugins install`` and
``install --force`` (fresh clone replacement) without any network access;
the fake payload omits ``extractor/`` so the npm-install step is skipped.
"""

import os
import re
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
POST_INSTALL = REPO_ROOT / "post-install.sh"
PLUGIN_REL = Path("plugins/webclip-obsidian")

USER_CONFIG = '[clip]\nvault = "~/obsidian/custom"\nuser_marker = "keep-me"\n'
ORIGINAL_CONFIG = '[clip]\nvault = "~/obsidian/original"\n'

FAKE_HERMES = r"""#!/usr/bin/env bash
# Fake `hermes plugins install` for post-install.sh tests.
set -euo pipefail
if [[ "${1:-}" != "plugins" || "${2:-}" != "install" ]]; then
  echo "fake-hermes: unexpected args: $*" >&2
  exit 2
fi
shift 2
FORCE=0
SRC=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=1; shift ;;
    --enable) shift ;;
    file://*) SRC="${1#file://}"; shift ;;
    *) echo "fake-hermes: unknown arg: $1" >&2; exit 2 ;;
  esac
done
PLUGIN_DIR="$HERMES_HOME/plugins/webclip-obsidian"
if [[ "$FORCE" -eq 1 ]]; then
  rm -rf "$PLUGIN_DIR"          # like a real forced reinstall: fresh clone
fi
if [[ -d "$PLUGIN_DIR" ]]; then
  echo "fake-hermes: plugin already installed; nothing to do" >&2
  exit 0
fi
mkdir -p "$PLUGIN_DIR"
cp "$SRC/config.example.toml" "$PLUGIN_DIR/config.example.toml"
cp "$SRC/plugin.yaml" "$PLUGIN_DIR/plugin.yaml"
: > "$PLUGIN_DIR/__init__.py"
if [[ "${FAKE_HERMES_READONLY:-0}" == "1" ]]; then
  chmod 555 "$PLUGIN_DIR"       # simulate an unwritable install target
fi
echo "fake-hermes: installed plugin from $SRC" >&2
"""


def _write_shim(bin_dir: Path) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "hermes"
    shim.write_text(textwrap.dedent(FAKE_HERMES))
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return shim


def _run_install(
    hermes_home: Path, bin_dir: Path, *args: str, readonly: bool = False
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HERMES_HOME"] = str(hermes_home)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    if readonly:
        env["FAKE_HERMES_READONLY"] = "1"
    return subprocess.run(
        ["bash", str(POST_INSTALL), "--hermes-home", str(hermes_home), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )


@pytest.fixture()
def hermes_env(tmp_path: Path):
    hermes_home = tmp_path / "hermes_home"
    hermes_home.mkdir()
    bin_dir = tmp_path / "bin"
    _write_shim(bin_dir)
    return hermes_home, bin_dir


def _plugin_dir(hermes_home: Path) -> Path:
    return hermes_home / PLUGIN_REL


def test_first_time_install_works_and_bootstraps_config(hermes_env):
    """A first-time --install-plugin install still works (behavior unchanged)."""
    hermes_home, bin_dir = hermes_env
    result = _run_install(hermes_home, bin_dir, "--install-plugin")
    assert result.returncode == 0, result.stderr

    plugin_dir = _plugin_dir(hermes_home)
    assert plugin_dir.is_dir()
    assert (plugin_dir / "config.toml").is_file()  # bootstrapped from example
    assert "fake-hermes: installed plugin" in result.stderr


def test_refresh_preserves_user_config(hermes_env):
    """Refreshing an existing install does not lose the user's config.toml."""
    hermes_home, bin_dir = hermes_env
    first = _run_install(hermes_home, bin_dir, "--install-plugin")
    assert first.returncode == 0, first.stderr

    plugin_dir = _plugin_dir(hermes_home)
    (plugin_dir / "config.toml").write_text(USER_CONFIG)

    second = _run_install(hermes_home, bin_dir, "--install-plugin")
    assert second.returncode == 0, second.stderr
    assert "Refreshing plugin" in second.stdout
    assert "Restored config.toml from backup" in second.stdout

    restored = (plugin_dir / "config.toml").read_text()
    assert 'user_marker = "keep-me"' in restored
    assert "~/obsidian/custom" in restored


def test_refresh_without_user_config_still_works(hermes_env):
    """Refresh with no config.toml present re-bootstraps from the example."""
    hermes_home, bin_dir = hermes_env
    first = _run_install(hermes_home, bin_dir, "--install-plugin")
    assert first.returncode == 0, first.stderr

    plugin_dir = _plugin_dir(hermes_home)
    (plugin_dir / "config.toml").unlink()  # user deleted it

    second = _run_install(hermes_home, bin_dir, "--install-plugin")
    assert second.returncode == 0, second.stderr
    assert (plugin_dir / "config.toml").is_file()


@pytest.mark.skipif(
    os.geteuid() == 0, reason="chmod-based permission tests need a non-root user"
)
def test_refresh_backup_failure_aborts_and_leaves_plugin_untouched(hermes_env):
    """If the config.toml backup fails, abort before the forced reinstall."""
    hermes_home, bin_dir = hermes_env
    first = _run_install(hermes_home, bin_dir, "--install-plugin")
    assert first.returncode == 0, first.stderr

    plugin_dir = _plugin_dir(hermes_home)
    config = plugin_dir / "config.toml"
    config.write_text(ORIGINAL_CONFIG)
    config.chmod(0)  # unreadable -> backup cp must fail
    try:
        second = _run_install(hermes_home, bin_dir, "--install-plugin")
    finally:
        config.chmod(0o644)

    assert second.returncode != 0
    assert "back up" in second.stderr.lower()
    # The plugin dir must NOT have been replaced by a refresh.
    assert config.read_text() == ORIGINAL_CONFIG


@pytest.mark.skipif(
    os.geteuid() == 0, reason="chmod-based permission tests need a non-root user"
)
def test_refresh_restore_failure_reports_error_and_keeps_backup(hermes_env):
    """If restore fails, report a clear error and keep the backup on disk."""
    hermes_home, bin_dir = hermes_env
    first = _run_install(hermes_home, bin_dir, "--install-plugin")
    assert first.returncode == 0, first.stderr

    plugin_dir = _plugin_dir(hermes_home)
    (plugin_dir / "config.toml").write_text(USER_CONFIG)

    # The forced reinstall produces an unwritable plugin dir, so the restore
    # cp fails and the script must keep the backup and tell the user where.
    second = _run_install(hermes_home, bin_dir, "--install-plugin", readonly=True)
    assert second.returncode != 0
    assert "restore" in second.stderr.lower()

    match = re.search(r"preserved at: (\S+)", second.stderr)
    assert match, second.stderr
    backup = Path(match.group(1))
    try:
        assert backup.is_file()
        assert backup.read_text() == USER_CONFIG
    finally:
        backup.unlink(missing_ok=True)
