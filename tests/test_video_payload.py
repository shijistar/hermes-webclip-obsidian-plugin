"""Video payload validation and extractor version negotiation."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from _webclip.article import _validate_success_payload
from _webclip.core import ClipError
from _webclip.extract import _require_video_capable_extractor

BASE_PAYLOAD = {
    "title": "Example article",
    "author": "",
    "published": "",
    "description": "",
    "site": "example.com",
    "canonicalUrl": "https://example.com/a/1.html",
    "url": "https://example.com/a/1.html",
    "markdown": "body",
    "method": "static",
    "keywords": [],
    "wordCount": 1,
}


def payload(**overrides):
    merged = dict(BASE_PAYLOAD)
    merged.update(overrides)
    return merged


class VideoPayloadTests(unittest.TestCase):
    def test_absent_videos_are_left_absent_for_article_callers(self):
        checked = _validate_success_payload(payload())
        self.assertNotIn("videos", checked)

    def test_absent_videos_fail_when_the_caller_requires_them(self):
        with self.assertRaises(ClipError) as caught:
            _validate_success_payload(payload(), require_videos=True)
        self.assertIn("outdated extractor", str(caught.exception))

    def test_an_empty_list_is_a_valid_answer(self):
        checked = _validate_success_payload(payload(videos=[]), require_videos=True)
        self.assertEqual(checked["videos"], [])

    def test_a_valid_candidate_is_normalised(self):
        checked = _validate_success_payload(
            payload(
                videos=[
                    {
                        "src": "https://cdn.example.com/a.m3u8",
                        "type": "application/x-mpegURL",
                        "title": "Clip",
                        "poster": "https://cdn.example.com/p.jpg",
                        "origin": "video-data",
                        "width": 1280,
                        "height": 720,
                    }
                ]
            ),
            require_videos=True,
        )
        self.assertEqual(
            checked["videos"],
            [
                {
                    "src": "https://cdn.example.com/a.m3u8",
                    "type": "application/x-mpegURL",
                    "title": "Clip",
                    "poster": "https://cdn.example.com/p.jpg",
                    "origin": "video-data",
                    "width": 1280,
                    "height": 720,
                }
            ],
        )

    def test_missing_optional_fields_default_to_empty(self):
        checked = _validate_success_payload(
            payload(videos=[{"src": "https://cdn.example.com/a.mp4"}])
        )
        candidates = checked["videos"]
        assert isinstance(candidates, list)
        candidate = candidates[0]
        assert isinstance(candidate, dict)
        self.assertEqual(candidate["type"], "")
        self.assertEqual(candidate["width"], 0)

    def test_non_http_sources_are_rejected(self):
        for bad in ("file:///etc/passwd", "javascript:alert(1)", "ftp://cdn/a.mp4"):
            with self.subTest(src=bad):
                with self.assertRaises(ClipError):
                    _validate_success_payload(payload(videos=[{"src": bad}]))

    def test_credentials_in_a_source_are_rejected(self):
        with self.assertRaises(ClipError):
            _validate_success_payload(
                payload(videos=[{"src": "https://user:pass@cdn.example.com/a.mp4"}])
            )

    def test_too_many_candidates_are_rejected(self):
        candidates = [
            {"src": f"https://cdn.example.com/{index}.mp4"} for index in range(21)
        ]
        with self.assertRaises(ClipError):
            _validate_success_payload(payload(videos=candidates))

    def test_a_boolean_dimension_is_rejected(self):
        with self.assertRaises(ClipError):
            _validate_success_payload(
                payload(videos=[{"src": "https://cdn.example.com/a.mp4", "width": True}])
            )

    def test_a_non_list_videos_field_is_rejected(self):
        with self.assertRaises(ClipError):
            _validate_success_payload(payload(videos="nope"))


class ExtractorVersionTests(unittest.TestCase):
    def _package(self, root: Path, version: str | None) -> Path:
        if version is not None:
            (root / "package.json").write_text(
                json.dumps({"name": "x", "version": version}), encoding="utf-8"
            )
        return root

    def test_video_capable_version_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._package(Path(tmp), "0.5.0")
            _require_video_capable_extractor(root)

    def test_a_newer_version_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._package(Path(tmp), "1.2.3")
            _require_video_capable_extractor(root)

    def test_an_old_version_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._package(Path(tmp), "0.4.1")
            with self.assertRaises(ClipError) as caught:
                _require_video_capable_extractor(root)
            self.assertIn("too old", str(caught.exception))

    def test_an_unreadable_package_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._package(Path(tmp), None)
            with self.assertRaises(ClipError):
                _require_video_capable_extractor(root)


if __name__ == "__main__":
    unittest.main()
