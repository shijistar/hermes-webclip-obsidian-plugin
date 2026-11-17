"""Command-line parsing and the [video] config table."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from _webclip.config import MAX_SAVE_VIDEO_URLS, VideoConfig, parse_save_video_args
from _webclip.core import ClipError

URL = "https://example.com/page"


class ArgumentTests(unittest.TestCase):
    def test_a_single_url(self):
        options = parse_save_video_args(URL)
        self.assertEqual(options.urls, (URL,))
        self.assertIsNone(options.name)
        self.assertFalse(options.overwrite)
        self.assertFalse(options.no_browser)

    def test_several_urls(self):
        options = parse_save_video_args(f"{URL} https://example.com/two")
        self.assertEqual(len(options.urls), 2)

    def test_name_to_and_flags(self):
        options = parse_save_video_args(
            f'{URL} --name "My clip" --to ~/Videos --overwrite --no-browser'
        )
        self.assertEqual(options.name, "My clip")
        self.assertEqual(options.destination, "~/Videos")
        self.assertTrue(options.overwrite)
        self.assertTrue(options.no_browser)

    def test_no_url_is_a_usage_error(self):
        with self.assertRaises(ClipError) as caught:
            parse_save_video_args("--overwrite")
        self.assertIn("Usage", str(caught.exception))

    def test_an_unknown_option_is_rejected(self):
        with self.assertRaises(ClipError):
            parse_save_video_args(f"{URL} --save-images yes")

    def test_a_flag_without_its_value_is_rejected(self):
        for flag in ("--name", "--to"):
            with self.subTest(flag=flag):
                with self.assertRaises(ClipError):
                    parse_save_video_args(f"{URL} {flag}")

    def test_a_repeated_name_is_rejected(self):
        with self.assertRaises(ClipError):
            parse_save_video_args(f'{URL} --name a --name b')

    def test_a_non_http_url_is_rejected(self):
        for bad in ("file:///etc/passwd", "ftp://example.com/a", "not-a-url"):
            with self.subTest(url=bad):
                with self.assertRaises(ClipError):
                    parse_save_video_args(bad)

    def test_too_many_urls_are_rejected(self):
        urls = " ".join(f"https://example.com/{index}" for index in range(MAX_SAVE_VIDEO_URLS + 1))
        with self.assertRaises(ClipError) as caught:
            parse_save_video_args(urls)
        self.assertIn(str(MAX_SAVE_VIDEO_URLS), str(caught.exception))

    def test_broken_quoting_is_rejected(self):
        with self.assertRaises(ClipError):
            parse_save_video_args(f'{URL} --name "unterminated')


class VideoConfigTests(unittest.TestCase):
    def _load(self, content: str | None) -> VideoConfig:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            if content is not None:
                path.write_text(content, encoding="utf-8")
            return VideoConfig.from_file(path)

    def test_defaults_when_the_file_is_missing(self):
        settings = self._load(None)
        self.assertEqual(settings.destination, "~/Videos/webclip")
        self.assertTrue(settings.gitignore)
        self.assertEqual(settings.max_size_mb, 500)
        self.assertEqual(settings.max_per_run, 10)
        self.assertEqual(settings.warnings, ())

    def test_defaults_when_the_table_is_absent(self):
        settings = self._load('[clip]\nvault = "~/vault"\n')
        self.assertEqual(settings.max_size_mb, 500)
        self.assertEqual(settings.warnings, ())

    def test_every_supported_key_is_read(self):
        settings = self._load(
            "[video]\n"
            'destination = "attachments/video"\n'
            "gitignore = false\n"
            "max_size_mb = 42\n"
            "max_per_run = 3\n"
            "download_timeout_s = 60\n"
            'ytdlp = "/opt/bin/yt-dlp"\n'
        )
        self.assertEqual(settings.destination, "attachments/video")
        self.assertFalse(settings.gitignore)
        self.assertEqual(settings.max_size_mb, 42)
        self.assertEqual(settings.max_per_run, 3)
        self.assertEqual(settings.download_timeout_s, 60)
        self.assertEqual(settings.ytdlp, "/opt/bin/yt-dlp")

    def test_a_wrong_type_degrades_with_a_warning(self):
        settings = self._load('[video]\nmax_size_mb = "lots"\ngitignore = "yes"\n')
        self.assertEqual(settings.max_size_mb, 500)
        self.assertTrue(settings.gitignore)
        self.assertEqual(len(settings.warnings), 2)

    def test_out_of_range_values_degrade(self):
        settings = self._load("[video]\nmax_size_mb = 0\nmax_per_run = 9999\n")
        self.assertEqual(settings.max_size_mb, 500)
        self.assertEqual(settings.max_per_run, 10)
        self.assertEqual(len(settings.warnings), 2)

    def test_an_unknown_key_warns_but_keeps_the_rest(self):
        settings = self._load("[video]\nfrobnicate = true\nmax_size_mb = 10\n")
        self.assertEqual(settings.max_size_mb, 10)
        self.assertEqual(len(settings.warnings), 1)
        self.assertIn("frobnicate", settings.warnings[0])

    def test_an_empty_destination_degrades(self):
        settings = self._load('[video]\ndestination = "  "\n')
        self.assertEqual(settings.destination, "~/Videos/webclip")
        self.assertEqual(len(settings.warnings), 1)

    def test_broken_toml_degrades_instead_of_raising(self):
        settings = self._load("[video\nnope")
        self.assertEqual(settings.max_size_mb, 500)
        self.assertEqual(len(settings.warnings), 1)


if __name__ == "__main__":
    unittest.main()
