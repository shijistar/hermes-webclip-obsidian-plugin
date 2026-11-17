"""Playlist parsing and probe behaviour."""

from __future__ import annotations

import unittest
from unittest import mock

from _webclip.core import ClipError
from _webclip.video import probe as probe_module
from _webclip.video.probe import parse_playlist, probe, read_media_playlist, segment_urls

MEDIA_PLAYLIST = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:10
#EXTINF:9.009,
seg-1.ts
#EXTINF:9.009,
https://cdn.example.com/seg-2.ts
#EXTINF:3.003,
/seg-3.ts
#EXT-X-ENDLIST
"""

MASTER_PLAYLIST = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2400000,RESOLUTION=1280x720
high/index.m3u8
"""


class ParseTests(unittest.TestCase):
    def test_a_media_playlist_reports_segments_and_duration(self):
        info = parse_playlist(MEDIA_PLAYLIST, url="https://cdn.example.com/a.m3u8")
        self.assertEqual(info.segments, 3)
        self.assertAlmostEqual(info.duration_s, 21.021, places=3)
        self.assertFalse(info.live)
        self.assertFalse(info.encrypted)
        self.assertEqual(info.variants, ())

    def test_a_master_playlist_exposes_variants(self):
        info = parse_playlist(MASTER_PLAYLIST, url="https://cdn.example.com/master.m3u8")
        self.assertEqual(
            info.variants,
            (
                "https://cdn.example.com/low/index.m3u8",
                "https://cdn.example.com/high/index.m3u8",
            ),
        )

    def test_encryption_is_detected(self):
        text = MEDIA_PLAYLIST.replace(
            "#EXT-X-TARGETDURATION:10",
            '#EXT-X-TARGETDURATION:10\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"',
        )
        info = parse_playlist(text, url="https://cdn.example.com/a.m3u8")
        self.assertTrue(info.encrypted)

    def test_a_session_key_on_the_master_counts_as_encryption(self):
        # DRM is normally declared once on the master; the media playlist below
        # it carries no key, so missing this lets protected streams through.
        master = (
            "#EXTM3U\n"
            '#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES,URI="skd://key-id"\n'
            "#EXT-X-STREAM-INF:BANDWIDTH=800000\n"
            "low/index.m3u8\n"
        )
        info = parse_playlist(master, url="https://cdn.example.com/master.m3u8")
        self.assertTrue(info.encrypted)

    def test_a_blank_line_before_the_variant_uri_is_tolerated(self):
        master = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000\n\nlow/index.m3u8\n"
        info = parse_playlist(master, url="https://cdn.example.com/master.m3u8")
        self.assertEqual(info.variants, ("https://cdn.example.com/low/index.m3u8",))

    def test_method_none_is_not_encryption(self):
        text = MEDIA_PLAYLIST.replace(
            "#EXT-X-TARGETDURATION:10",
            "#EXT-X-TARGETDURATION:10\n#EXT-X-KEY:METHOD=NONE",
        )
        info = parse_playlist(text, url="https://cdn.example.com/a.m3u8")
        self.assertFalse(info.encrypted)

    def test_a_playlist_without_endlist_is_live(self):
        text = MEDIA_PLAYLIST.replace("#EXT-X-ENDLIST\n", "")
        info = parse_playlist(text, url="https://cdn.example.com/a.m3u8")
        self.assertTrue(info.live)

    def test_a_non_playlist_is_rejected(self):
        with self.assertRaises(ClipError):
            parse_playlist("<html>not a playlist</html>", url="https://cdn/a.m3u8")

    def test_segments_resolve_against_the_playlist_url(self):
        urls = segment_urls(MEDIA_PLAYLIST, playlist_url="https://cdn.example.com/hls/a.m3u8")
        self.assertEqual(
            urls,
            [
                "https://cdn.example.com/hls/seg-1.ts",
                "https://cdn.example.com/seg-2.ts",
                "https://cdn.example.com/seg-3.ts",
            ],
        )


class ProbeTests(unittest.TestCase):
    def test_probe_follows_one_master_level(self):
        responses = [
            ("https://cdn.example.com/master.m3u8", MASTER_PLAYLIST.encode()),
            ("https://cdn.example.com/low/index.m3u8", MEDIA_PLAYLIST.encode()),
        ]

        def fake_fetch(url, **kwargs):
            for candidate_url, body in responses:
                if candidate_url == url:
                    return candidate_url, body
            raise AssertionError(f"unexpected fetch: {url}")

        with mock.patch.object(probe_module, "fetch_bytes", side_effect=fake_fetch):
            info = probe("https://cdn.example.com/master.m3u8")
        self.assertEqual(info.segments, 3)
        self.assertEqual(info.url, "https://cdn.example.com/low/index.m3u8")

    def test_reading_segments_from_a_master_is_refused(self):
        with mock.patch.object(
            probe_module, "fetch_bytes", return_value=("https://cdn/x.m3u8", MASTER_PLAYLIST.encode())
        ):
            with self.assertRaises(ClipError):
                read_media_playlist("https://cdn/x.m3u8")


class UnsupportedAndMalformedTests(unittest.TestCase):
    """A playlist the downloader cannot honour must be refused, not mangled."""

    def test_a_malformed_duration_is_a_clip_error(self):
        text = MEDIA_PLAYLIST.replace("#EXTINF:9.009,", "#EXTINF:1.2.3,", 1)
        with self.assertRaises(ClipError) as caught:
            parse_playlist(text, url="https://cdn.example.com/a.m3u8")
        self.assertIn("duration", str(caught.exception))

    def test_a_byte_range_playlist_is_marked_unsupported(self):
        text = MEDIA_PLAYLIST.replace(
            "#EXTINF:9.009,\nseg-1.ts",
            "#EXT-X-BYTERANGE:1000@0\n#EXTINF:9.009,\nseg-1.ts",
            1,
        )
        info = parse_playlist(text, url="https://cdn.example.com/a.m3u8")
        self.assertEqual(info.unsupported, "#EXT-X-BYTERANGE")

    def test_an_fmp4_playlist_is_marked_unsupported(self):
        text = MEDIA_PLAYLIST.replace(
            "#EXT-X-TARGETDURATION:10",
            '#EXT-X-TARGETDURATION:10\n#EXT-X-MAP:URI="init.mp4"',
            1,
        )
        info = parse_playlist(text, url="https://cdn.example.com/a.m3u8")
        self.assertEqual(info.unsupported, "#EXT-X-MAP")

    def test_probe_refuses_an_unsupported_playlist(self):
        text = MEDIA_PLAYLIST.replace(
            "#EXT-X-TARGETDURATION:10",
            '#EXT-X-TARGETDURATION:10\n#EXT-X-MAP:URI="init.mp4"',
            1,
        )
        with mock.patch.object(
            probe_module,
            "fetch_bytes",
            return_value=("https://cdn.example.com/a.m3u8", text.encode()),
        ):
            with self.assertRaises(ClipError) as caught:
                probe("https://cdn.example.com/a.m3u8")
        self.assertIn("EXT-X-MAP", str(caught.exception))

    def test_a_plain_playlist_reports_no_unsupported_tag(self):
        info = parse_playlist(MEDIA_PLAYLIST, url="https://cdn.example.com/a.m3u8")
        self.assertEqual(info.unsupported, "")


if __name__ == "__main__":
    unittest.main()
