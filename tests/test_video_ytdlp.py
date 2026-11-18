"""The yt-dlp backend: which binary is used, which flags are non-negotiable,
and what happens when the subprocess misbehaves."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _webclip.core import ClipError
from _webclip.proc import ProcessResult
from _webclip.video.download import ytdlp as ytdlp_module
from _webclip.video.download.ytdlp import download_ytdlp, find_ytdlp
from _webclip.video.models import DownloadPlan

PLAN = DownloadPlan(
    urls=("https://www.youtube.com/watch?v=dQw4w9WgXcQ",), kind="ytdlp"
)


class FindExecutableTests(unittest.TestCase):
    def test_an_explicit_path_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "yt-dlp"
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            binary.chmod(0o755)
            self.assertEqual(find_ytdlp(str(binary)), str(binary))

    def test_a_configured_path_that_does_not_exist_is_an_error(self):
        with self.assertRaises(ClipError) as raised:
            find_ytdlp("/nonexistent/yt-dlp")
        self.assertIn("[video].ytdlp", str(raised.exception))

    def test_the_path_lookup_is_tried_before_the_fixed_prefixes(self):
        with mock.patch.object(ytdlp_module.shutil, "which", return_value="/opt/bin/yt-dlp"):
            self.assertEqual(find_ytdlp(), "/opt/bin/yt-dlp")

    def test_the_managed_copy_is_used_when_path_and_prefixes_have_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "yt-dlp"
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            binary.chmod(0o755)
            with mock.patch.object(ytdlp_module.shutil, "which", return_value=None), \
                 mock.patch.object(ytdlp_module, "_MANAGED", binary), \
                 mock.patch.object(ytdlp_module, "_CANDIDATE_DIRS", ()):
                self.assertEqual(find_ytdlp(), str(binary))

    def test_path_still_beats_the_managed_copy(self):
        # A user's own install is an explicit choice; ours is the fallback.
        with mock.patch.object(ytdlp_module.shutil, "which", return_value="/opt/bin/yt-dlp"), \
             mock.patch.object(ytdlp_module, "_MANAGED", Path("/tmp/would-not-be-used")):
            self.assertEqual(find_ytdlp(), "/opt/bin/yt-dlp")

    def test_the_homebrew_prefix_is_used_when_path_lacks_it(self):
        # The gateway inherits a different PATH than an interactive shell; this
        # is the regression that would otherwise report "not enabled" wrongly.
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "yt-dlp"
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            binary.chmod(0o755)
            with mock.patch.object(ytdlp_module.shutil, "which", return_value=None), \
                 mock.patch.object(ytdlp_module, "_MANAGED", Path(tmp) / "absent"), \
                 mock.patch.object(ytdlp_module, "_CANDIDATE_DIRS", (tmp,)):
                self.assertEqual(find_ytdlp(), str(binary))

    def test_a_missing_binary_explains_how_to_install_it(self):
        with mock.patch.object(ytdlp_module.shutil, "which", return_value=None), \
             mock.patch.object(ytdlp_module, "_MANAGED", Path("/nonexistent/yt-dlp")), \
             mock.patch.object(ytdlp_module, "_CANDIDATE_DIRS", ()):
            with self.assertRaises(ClipError) as raised:
                find_ytdlp()
        message = str(raised.exception)
        self.assertIn("post-install.sh --force-ytdlp", message)
        self.assertIn("brew install yt-dlp", message)


class DownloadTests(unittest.TestCase):
    def _run(self, *, returncode=0, stderr=b"", render=b"x" * 32, produced=True):
        """Run the downloader with the subprocess and ffmpeg stubbed out."""
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            # The real tool writes into the `-o` template's directory.
            template = Path(command[command.index("-o") + 1])
            if produced:
                (template.parent / "video.mp4").write_bytes(render * 4)
            return ProcessResult(returncode=returncode, stdout=b"", stderr=stderr)

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "out.mp4"
            with mock.patch.object(ytdlp_module, "_run_bounded", side_effect=fake_run), \
                 mock.patch.object(ytdlp_module, "find_ffmpeg", return_value="/usr/bin/ffmpeg"), \
                 mock.patch.object(ytdlp_module, "probe_duration", return_value=213.0):
                result = download_ytdlp(PLAN, destination, executable="/opt/bin/yt-dlp")
            captured["destination"] = destination
            captured["exists"] = destination.exists()
            captured["size"] = destination.stat().st_size if destination.exists() else 0
        return result, captured

    def test_the_guard_flags_are_all_present(self):
        _result, captured = self._run()
        command = captured["command"]
        # A user-level config can carry `--exec`, which would run shell commands
        # from inside the plugin; a playlist URL would ignore max_per_run; the
        # m3u8_native variants answered 403 on every measured attempt.
        self.assertIn("--ignore-config", command)
        self.assertIn("--no-playlist", command)
        self.assertIn("--max-filesize", command)
        self.assertIn("--no-progress", command)
        selector = command[command.index("-f") + 1]
        self.assertIn("[protocol=https]", selector)
        # A throttled track must fail fast, not hang until the wall clock expires.
        self.assertIn("--socket-timeout", command)
        self.assertIn("--merge-output-format", command)
        self.assertEqual(command[command.index("--") + 1], PLAN.urls[0])
        self.assertEqual(command[-1], PLAN.urls[0])

    def test_a_node_runtime_is_named_so_deno_is_not_required(self):
        with mock.patch.object(ytdlp_module, "find_js_runtime", return_value="/opt/node"):
            _result, captured = self._run()
        command = captured["command"]
        self.assertEqual(command[command.index("--js-runtimes") + 1], "node:/opt/node")

    def test_the_runtime_flag_is_omitted_when_no_node_exists(self):
        # yt-dlp still has deno as a default; passing `node:` with an empty path
        # would be an error, so the flag must be absent rather than empty.
        with mock.patch.object(ytdlp_module, "find_js_runtime", return_value=""):
            _result, captured = self._run()
        self.assertNotIn("--js-runtimes", captured["command"])

    def test_the_guard_flags_carry_the_values_they_are_supposed_to(self):
        _result, captured = self._run()
        command = captured["command"]

        def value_of(flag: str) -> str:
            return command[command.index(flag) + 1]

        self.assertEqual(value_of("--max-filesize"), str(500 * 1024 * 1024))
        self.assertEqual(value_of("--socket-timeout"), "20")
        self.assertEqual(value_of("--retries"), "2")
        self.assertEqual(value_of("--playlist-items"), "1")
        self.assertEqual(value_of("-S"), "res:1080,codec:avc1")
        self.assertEqual(value_of("--merge-output-format"), "mp4")
        self.assertEqual(value_of("--ffmpeg-location"), "/usr/bin/ffmpeg")

    def test_the_proxy_variables_are_forwarded(self):
        # Dropping them makes YouTube unreachable from this machine, so the docs
        # promise this behaviour; it is not an implementation detail.
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:7890"}):
            _result, captured = self._run()
        self.assertEqual(
            captured["kwargs"]["env"].get("HTTPS_PROXY"), "http://127.0.0.1:7890"
        )

    def test_a_non_mp4_result_is_refused_instead_of_mislabelled(self):
        def fake_run(command, **kwargs):
            template = Path(command[command.index("-o") + 1])
            (template.parent / "video.webm").write_bytes(b"x" * 64)
            return ProcessResult(returncode=0, stdout=b"", stderr=b"")

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "out.mp4"
            with mock.patch.object(ytdlp_module, "_run_bounded", side_effect=fake_run), \
                 mock.patch.object(ytdlp_module, "find_ffmpeg", return_value="/usr/bin/ffmpeg"):
                with self.assertRaises(ClipError) as raised:
                    download_ytdlp(PLAN, destination, executable="/opt/bin/yt-dlp")
        self.assertIn("webm", str(raised.exception))

    def test_a_size_skipped_download_names_the_size_limit(self):
        with self.assertRaises(ClipError) as raised:
            self._run(
                produced=False,
                stderr=b"ERROR: File is larger than max-filesize (600MB > 500MB)",
            )
        self.assertIn("size limit", str(raised.exception))

    def test_a_generic_failure_is_not_reported_as_a_login_wall(self):
        # `"age" in text` used to match "webpage" and "storage".
        for stderr in (
            b"ERROR: unable to download webpage: HTTP Error 500",
            b"ERROR: storage failure",
        ):
            with self.subTest(stderr=stderr):
                with self.assertRaises(ClipError) as raised:
                    self._run(returncode=1, stderr=stderr)
                self.assertNotIn("signed-in", str(raised.exception))

    def test_the_subprocess_gets_a_wall_clock_budget_of_its_own(self):
        _result, captured = self._run()
        self.assertGreaterEqual(captured["kwargs"]["timeout"], ytdlp_module.YTDLP_TIMEOUT)

    def test_only_a_whitelisted_environment_is_forwarded(self):
        with mock.patch.dict(os.environ, {"WEBCLIP_TEST_SECRET": "leak"}, clear=False):
            _result, captured = self._run()
        self.assertNotIn("WEBCLIP_TEST_SECRET", captured["kwargs"]["env"])
        self.assertIn("PATH", captured["kwargs"]["env"])

    def test_the_downloaded_file_lands_on_the_destination(self):
        result, captured = self._run()
        self.assertTrue(captured["exists"])
        self.assertEqual(result.bytes_written, captured["size"])
        self.assertEqual(result.duration_s, 213.0)

    def test_a_forbidden_download_is_explained(self):
        with self.assertRaises(ClipError) as raised:
            self._run(returncode=1, stderr=b"ERROR: unable to download video data: HTTP Error 403: Forbidden")
        self.assertIn("403", str(raised.exception))

    def test_a_sign_in_wall_is_explained(self):
        with self.assertRaises(ClipError) as raised:
            self._run(returncode=1, stderr=b"ERROR: Sign in to confirm your age")
        self.assertIn("signed-in", str(raised.exception))

    def test_a_generic_failure_stays_generic(self):
        with self.assertRaises(ClipError) as raised:
            self._run(returncode=1, stderr=b"ERROR: something odd happened at https://cdn/x.mp4?sig=secret")
        message = str(raised.exception)
        self.assertNotIn("secret", message)

    def test_no_output_file_is_an_error(self):
        with self.assertRaises(ClipError) as raised:
            self._run(produced=False)
        self.assertIn("exactly one", str(raised.exception))

    def test_an_oversized_result_is_rejected_even_if_the_tool_agreed(self):
        original = ytdlp_module.download_ytdlp

        def fake_run(command, **kwargs):
            template = Path(command[command.index("-o") + 1])
            (template.parent / "video.mp4").write_bytes(b"x" * 4096)
            return ProcessResult(returncode=0, stdout=b"", stderr=b"")

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "out.mp4"
            with mock.patch.object(ytdlp_module, "_run_bounded", side_effect=fake_run), \
                 mock.patch.object(ytdlp_module, "find_ffmpeg", return_value="/usr/bin/ffmpeg"):
                with self.assertRaises(ClipError) as raised:
                    original(PLAN, destination, executable="/opt/bin/yt-dlp", max_bytes=1024)
        self.assertIn("size limit", str(raised.exception))

    def test_an_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "out.mp4"
            destination.write_bytes(b"existing")

            def fake_run(command, **kwargs):
                template = Path(command[command.index("-o") + 1])
                (template.parent / "video.mp4").write_bytes(b"x" * 64)
                return ProcessResult(returncode=0, stdout=b"", stderr=b"")

            with mock.patch.object(ytdlp_module, "_run_bounded", side_effect=fake_run), \
                 mock.patch.object(ytdlp_module, "find_ffmpeg", return_value="/usr/bin/ffmpeg"):
                with self.assertRaises(FileExistsError):
                    download_ytdlp(PLAN, destination, executable="/opt/bin/yt-dlp")
            self.assertEqual(destination.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
