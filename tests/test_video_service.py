"""End-to-end orchestration of /save-video with the network stubbed out."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from _webclip.core import ClipError
from _webclip.video import service as service_module
from _webclip.video.models import DownloadedFile
from _webclip.video.service import VideoService


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=Test", *args],
        capture_output=True,
        text=True,
    )


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.plugin = self.root / "plugin"
        self.plugin.mkdir()
        (self.plugin / "config.toml").write_text(
            f'[clip]\nvault = "{self.vault}"\n', encoding="utf-8"
        )
        self.outside = self.root / "videos"
        lock_patch = mock.patch.object(
            VideoService, "_lock_path", return_value=self.root / "video.lock"
        )
        lock_patch.start()
        self.addCleanup(lock_patch.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def _article(self, *videos):
        return {"videos": list(videos)}

    def _download_ok(self):
        def fake(plan, target, **kwargs):
            target.write_bytes(b"x" * 100)
            return DownloadedFile(path=target, bytes_written=100, duration_s=12.0)

        return fake

    def test_a_single_video_keeps_its_plain_name(self):
        service = VideoService(self.plugin)
        article = self._article({"src": "https://cdn.example.com/a.mp4", "title": "Clip"})
        with mock.patch.object(service_module, "run_extractor", return_value=article), mock.patch.object(
            service_module, "download_direct", side_effect=self._download_ok()
        ):
            report = service.run(f"https://example.com/page --to {self.outside}")
        self.assertEqual(len(report.succeeded), 1)
        path = report.outcomes[0].path
        assert path is not None
        self.assertEqual(path.name, "Clip.mp4")

    def test_two_videos_on_one_page_get_numeric_suffixes(self):
        service = VideoService(self.plugin)
        article = self._article(
            {"src": "https://cdn.example.com/a.mp4", "title": "Clip"},
            {"src": "https://cdn.example.com/b.mp4", "title": "Clip"},
        )
        with mock.patch.object(service_module, "run_extractor", return_value=article), mock.patch.object(
            service_module, "download_direct", side_effect=self._download_ok()
        ):
            report = service.run(f"https://example.com/page --to {self.outside}")
        names = sorted(
            outcome.path.name for outcome in report.succeeded if outcome.path is not None
        )
        self.assertEqual(names, ["Clip-1.mp4", "Clip-2.mp4"])

    def test_a_failure_does_not_stop_the_rest_of_the_batch(self):
        service = VideoService(self.plugin)
        article = self._article(
            {"src": "https://cdn.example.com/a.mp4", "title": "First"},
            {"src": "https://cdn.example.com/b.mp4", "title": "Second"},
        )

        calls = {"count": 0}

        def flaky(plan, target, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise ClipError("the server refused")
            target.write_bytes(b"x" * 10)
            return DownloadedFile(path=target, bytes_written=10)

        with mock.patch.object(service_module, "run_extractor", return_value=article), mock.patch.object(
            service_module, "download_direct", side_effect=flaky
        ):
            report = service.run(f"https://example.com/page --to {self.outside}")
        self.assertEqual(len(report.failed), 1)
        self.assertEqual(len(report.succeeded), 1)

    def test_the_per_run_limit_marks_the_extra_video_as_skipped(self):
        service = VideoService(self.plugin)
        (self.plugin / "config.toml").write_text(
            f'[clip]\nvault = "{self.vault}"\n[video]\nmax_per_run = 1\n', encoding="utf-8"
        )
        article = self._article(
            {"src": "https://cdn.example.com/a.mp4", "title": "First"},
            {"src": "https://cdn.example.com/b.mp4", "title": "Second"},
        )
        with mock.patch.object(service_module, "run_extractor", return_value=article), mock.patch.object(
            service_module, "download_direct", side_effect=self._download_ok()
        ):
            report = service.run(f"https://example.com/page --to {self.outside}")
        self.assertEqual(len(report.succeeded), 1)
        self.assertIn("per-run limit", report.failed[0].message)

    def test_a_page_without_video_reports_instead_of_silently_succeeding(self):
        service = VideoService(self.plugin)
        with mock.patch.object(service_module, "run_extractor", return_value=self._article()):
            report = service.run(f"https://example.com/page --to {self.outside}")
        self.assertEqual(len(report.outcomes), 1)
        self.assertFalse(report.outcomes[0].ok)
        self.assertIn("No video", report.outcomes[0].message)

    def test_an_extractor_failure_is_reported_as_a_failed_outcome(self):
        service = VideoService(self.plugin)
        with mock.patch.object(
            service_module, "run_extractor", side_effect=ClipError("outdated extractor")
        ):
            report = service.run(f"https://example.com/page --to {self.outside}")
        self.assertFalse(report.outcomes[0].ok)
        self.assertIn("outdated extractor", report.outcomes[0].message)

    def test_a_vault_destination_writes_and_commits_the_ignore_block(self):
        _git(self.vault, "init", "-q")
        _git(self.vault, "commit", "--allow-empty", "-q", "-m", "init")
        service = VideoService(self.plugin)
        article = self._article({"src": "https://cdn.example.com/a.mp4", "title": "Clip"})
        with mock.patch.object(service_module, "run_extractor", return_value=article), mock.patch.object(
            service_module, "download_direct", side_effect=self._download_ok()
        ):
            report = service.run("https://example.com/page --to attachments/video")
        self.assertTrue(report.inside_vault)
        self.assertIn("/attachments/video/", (self.vault / ".gitignore").read_text(encoding="utf-8"))
        status = _git(self.vault, "status", "--porcelain=v1", "--untracked-files=all")
        self.assertEqual(status.stdout.strip(), "")

    def test_an_outside_destination_never_touches_the_vault(self):
        service = VideoService(self.plugin)
        article = self._article({"src": "https://cdn.example.com/a.mp4", "title": "Clip"})
        with mock.patch.object(service_module, "run_extractor", return_value=article), mock.patch.object(
            service_module, "download_direct", side_effect=self._download_ok()
        ):
            service.run(f"https://example.com/page --to {self.outside}")
        self.assertFalse((self.vault / ".gitignore").exists())

    def test_a_failed_overwrite_keeps_the_previous_file(self):
        self.outside.mkdir(parents=True, exist_ok=True)
        existing = self.outside / "Clip.mp4"
        existing.write_bytes(b"original")
        service = VideoService(self.plugin)
        article = self._article({"src": "https://cdn.example.com/a.mp4", "title": "Clip"})
        with mock.patch.object(service_module, "run_extractor", return_value=article), mock.patch.object(
            service_module, "download_direct", side_effect=ClipError("network died")
        ):
            report = service.run(
                f"https://example.com/page --to {self.outside} --overwrite"
            )
        self.assertFalse(report.outcomes[0].ok)
        self.assertEqual(existing.read_bytes(), b"original")
        self.assertEqual(
            [path.name for path in self.outside.iterdir()], ["Clip.mp4"]
        )

    def test_no_part_files_are_left_behind(self):
        service = VideoService(self.plugin)
        article = self._article({"src": "https://cdn.example.com/a.mp4", "title": "Clip"})
        with mock.patch.object(service_module, "run_extractor", return_value=article), mock.patch.object(
            service_module, "download_direct", side_effect=self._download_ok()
        ):
            service.run(f"https://example.com/page --to {self.outside}")
        self.assertEqual(
            [path.name for path in self.outside.iterdir()], ["Clip.mp4"]
        )

    def test_a_second_run_is_refused_while_the_lock_is_held(self):
        from _webclip.git_sync import VaultLock

        service = VideoService(self.plugin)
        article = self._article({"src": "https://cdn.example.com/a.mp4", "title": "Clip"})
        with VaultLock(self.root / "video.lock"):
            with mock.patch.object(service_module, "run_extractor", return_value=article):
                with self.assertRaises(ClipError):
                    service.run(f"https://example.com/page --to {self.outside}")


if __name__ == "__main__":
    unittest.main()
