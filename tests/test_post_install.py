"""post-install.sh tests (issue #20): config.toml preservation on refresh.

These tests run the real ``post-install.sh`` against a hermetic fake Hermes
home. A ``hermes`` shim on PATH simulates ``hermes plugins install`` and
``install --force`` (fresh clone replacement) without any network access;
the fake payload omits ``extractor/`` so the npm-install step is skipped.
"""

import hashlib
import os
import platform
import re
import shutil
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
    hermes_home: Path,
    bin_dir: Path,
    *args: str,
    readonly: bool = False,
    youtube: bool = False,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HERMES_HOME"] = str(hermes_home)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    # Keep the suite hermetic: without this the yt-dlp step would reach GitHub.
    # Tests that exercise the download override this with their own release dir.
    env.setdefault("YTDLP_RELEASE_BASE", "file:///nonexistent-ytdlp-release")
    if env_extra:
        env.update(env_extra)
    if readonly:
        env["FAKE_HERMES_READONLY"] = "1"
    flags = [] if youtube else ["--no-youtube"]
    return subprocess.run(
        ["bash", str(POST_INSTALL), "--hermes-home", str(hermes_home), *flags, *args],
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


def _install_installer_copy(plugin_dir: Path) -> None:
    """Lay out an installed plugin dir that carries its own installer copy."""
    plugin_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(POST_INSTALL, plugin_dir / "post-install.sh")
    shutil.copy2(REPO_ROOT / "config.example.toml", plugin_dir / "config.example.toml")
    (plugin_dir / "plugin.yaml").write_text("name: webclip-obsidian\n")


def _run_from_plugin_dir(
    plugin_dir: Path, hermes_home: Path, bin_dir: Path, *args: str
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HERMES_HOME"] = str(hermes_home)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    # These tests are about profile/config resolution, not the download; without
    # this they would fetch 36 MB from GitHub on every run.
    env.setdefault("YTDLP_RELEASE_BASE", "file:///nonexistent-ytdlp-release")
    return subprocess.run(
        [
            "bash",
            str(plugin_dir / "post-install.sh"),
            "--hermes-home",
            str(hermes_home),
            "--no-youtube",
            *args,
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(plugin_dir),
    )


def test_default_install_with_single_profile_bootstraps_default_plugin(hermes_env):
    """A default-profile install must not be hijacked by one named profile.

    Regression for: running the installer from <HERMES_HOME>/plugins/<key>
    while <HERMES_HOME>/profiles/ holds exactly one profile used to select
    that profile and write config.toml into it.
    """
    hermes_home, bin_dir = hermes_env
    named_plugin = hermes_home / "profiles" / "coder" / PLUGIN_REL
    named_plugin.mkdir(parents=True)
    default_plugin = _plugin_dir(hermes_home)
    _install_installer_copy(default_plugin)

    result = _run_from_plugin_dir(default_plugin, hermes_home, bin_dir)
    assert result.returncode == 0, result.stderr
    assert (default_plugin / "config.toml").is_file()
    assert not (named_plugin / "config.toml").exists()


def test_named_profile_install_keeps_its_own_config(hermes_env):
    """Running from a named-profile plugin dir still targets that profile."""
    hermes_home, bin_dir = hermes_env
    named_plugin = hermes_home / "profiles" / "coder" / PLUGIN_REL
    _install_installer_copy(named_plugin)

    result = _run_from_plugin_dir(named_plugin, hermes_home, bin_dir)
    assert result.returncode == 0, result.stderr
    assert (named_plugin / "config.toml").is_file()
    assert not (_plugin_dir(hermes_home) / "config.toml").exists()


def test_hermes_home_wins_over_plugin_dir_from_another_home(tmp_path):
    """An explicit --hermes-home is not overridden by the checkout's own home."""
    source_home = tmp_path / "source_home"
    source_plugin = source_home / "plugins" / "webclip-obsidian"
    _install_installer_copy(source_plugin)

    requested_home = tmp_path / "requested_home"
    requested_plugin = requested_home / PLUGIN_REL
    requested_plugin.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    _write_shim(bin_dir)

    result = _run_from_plugin_dir(source_plugin, requested_home, bin_dir)
    assert result.returncode == 0, result.stderr
    assert (requested_plugin / "config.toml").is_file()
    assert not (source_plugin / "config.toml").exists()


# --------------------------------------------------------------- yt-dlp step


def _ytdlp_asset_name() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin":
        return "yt-dlp_macos"
    if system == "Linux":
        return "yt-dlp_linux_aarch64" if machine in {"aarch64", "arm64"} else "yt-dlp_linux"
    pytest.skip(f"post-install.sh does not fetch yt-dlp on {system}")
    raise AssertionError("unreachable")  # keeps the return type honest for checkers


def _fake_release(root: Path, *, correct: bool = True) -> str:
    """A file:// release tree shaped like a GitHub release, with a SUMS file."""
    asset = _ytdlp_asset_name()
    release = root / "release" / "2026.10.26"
    release.mkdir(parents=True)
    payload = b"#!/bin/sh\necho fake-yt-dlp\n"
    (release / asset).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest() if correct else "0" * 64
    (release / "SHA2-256SUMS").write_text(f"{digest}  {asset}\n", encoding="utf-8")
    return (root / "release").as_uri()


def test_ytdlp_binary_is_fetched_and_checksum_verified(tmp_path, hermes_env):
    hermes_home, bin_dir = hermes_env
    base = _fake_release(tmp_path)

    result = _run_install(
        hermes_home,
        bin_dir,
        "--install-plugin",
        youtube=True,
        env_extra={"YTDLP_RELEASE_BASE": base},
    )

    assert result.returncode == 0, result.stderr
    binary = hermes_home / "tools" / "yt-dlp" / "yt-dlp"
    assert binary.is_file()
    assert os.access(binary, os.X_OK)
    version = (hermes_home / "tools" / "yt-dlp" / "VERSION").read_text().strip()
    assert version == "2026.10.26"
    assert "checksum mismatch" not in result.stdout + result.stderr


def test_a_bad_checksum_warns_but_does_not_fail_the_install(tmp_path, hermes_env):
    hermes_home, bin_dir = hermes_env
    base = _fake_release(tmp_path, correct=False)

    result = _run_install(
        hermes_home,
        bin_dir,
        "--install-plugin",
        youtube=True,
        env_extra={"YTDLP_RELEASE_BASE": base},
    )

    assert result.returncode == 0, result.stderr
    assert "checksum mismatch" in result.stdout + result.stderr
    assert not (hermes_home / "tools" / "yt-dlp" / "yt-dlp").exists()


def test_no_youtube_skips_the_download_entirely(hermes_env):
    hermes_home, bin_dir = hermes_env

    result = _run_install(hermes_home, bin_dir, "--install-plugin")

    assert result.returncode == 0, result.stderr
    assert "Skipping yt-dlp" in result.stdout
    assert not (hermes_home / "tools" / "yt-dlp" / "yt-dlp").exists()


def test_an_unwritable_tools_dir_warns_but_does_not_fail(tmp_path, hermes_env):
    hermes_home, bin_dir = hermes_env
    base = _fake_release(tmp_path)
    tools = hermes_home / "tools"
    tools.mkdir()
    tools.chmod(0o555)
    try:
        result = _run_install(
            hermes_home,
            bin_dir,
            "--install-plugin",
            youtube=True,
            env_extra={"YTDLP_RELEASE_BASE": base},
        )
    finally:
        tools.chmod(0o755)

    assert result.returncode == 0, result.stderr
    assert "could not write" in result.stdout + result.stderr
    assert not (hermes_home / "tools" / "yt-dlp" / "yt-dlp").exists()


def test_a_second_run_is_idempotent(tmp_path, hermes_env):
    hermes_home, bin_dir = hermes_env
    base = _fake_release(tmp_path)
    first = _run_install(
        hermes_home,
        bin_dir,
        "--install-plugin",
        youtube=True,
        env_extra={"YTDLP_RELEASE_BASE": base},
    )
    assert first.returncode == 0, first.stderr

    second = _run_install(
        hermes_home,
        bin_dir,
        "--install-plugin",
        youtube=True,
        env_extra={"YTDLP_RELEASE_BASE": base},
    )

    assert second.returncode == 0, second.stderr
    assert "already installed" in second.stdout
