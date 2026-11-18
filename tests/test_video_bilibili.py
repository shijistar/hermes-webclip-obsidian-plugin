"""Bilibili adapter: URL forms, the html5 durl path, and multi-part handling.

The API payloads below are trimmed copies of real responses (2026-11-18). Live
URLs are deliberately absent: Bilibili retires video ids, so the fixtures are the
only thing that can stay green.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from _webclip.core import ClipError
from _webclip.video import discover as discover_module
from _webclip.video.adapters.bilibili import BilibiliAdapter

VIEW_SINGLE = {
    "code": 0,
    "data": {
        "bvid": "BV1GJ411x7h7",
        "aid": 80433022,
        "title": "【官方 MV】Never Gonna Give You Up - Rick Astley",
        "pages": [{"page": 1, "cid": 137649199, "part": "Never Gonna Give You Up"}],
    },
}

VIEW_MULTI = {
    "code": 0,
    "data": {
        "bvid": "BV16Bs26FEAM",
        "aid": 117635043827705,
        "title": "在普罗米厄的怀抱下",
        "pages": [
            {"page": 1, "cid": 43698621267, "part": "【中】在普罗米厄的怀抱下"},
            {"page": 2, "cid": 43700915118, "part": "玫瑰与妄欲"},
        ],
    },
}

PLAYURL_SINGLE = {
    "code": 0,
    "data": {
        "quality": 64,
        "format": "mp4720",
        "durl": [
            {
                "url": "https://upos-sz-estgoss.bilivideo.com/upgcxcode/a.mp4?deadline=1",
                "size": 51973319,
                "length": 213000,
            }
        ],
    },
}

PLAYURL_PAGE_TWO = {
    "code": 0,
    "data": {
        "quality": 64,
        "durl": [
            {
                "url": "https://upos-sz-estgcos.bilivideo.com/upgcxcode/b.mp4?deadline=1",
                "size": 14188762,
                "length": 14000,
            }
        ],
    },
}


def _payload(payload: dict) -> tuple[str, bytes]:
    return "https://api.bilibili.com/final", json.dumps(payload).encode("utf-8")


class SelectionTests(unittest.TestCase):
    def test_bilibili_urls_pick_the_bilibili_adapter(self):
        adapter = discover_module.adapter_for
        for url in (
            "https://www.bilibili.com/video/BV1GJ411x7h7",
            "https://m.bilibili.com/video/BV1GJ411x7h7?p=2",
            "https://b23.tv/BV1GJ411x7h7",
            "https://live.bilibili.com/12345",
        ):
            with self.subTest(url=url):
                self.assertEqual(adapter(url).name, "bilibili")

    def test_neighbouring_hosts_still_fall_through(self):
        for url in ("https://notbilibili.com/video/BV1", "https://example.com/x"):
            with self.subTest(url=url):
                self.assertNotEqual(discover_module.adapter_for(url).name, "bilibili")


class DiscoveryTests(unittest.TestCase):
    def _discover(self, url: str, *responses):
        with mock.patch(
            "_webclip.video.adapters.bilibili.fetch_bytes", side_effect=list(responses)
        ) as fetched:
            found = BilibiliAdapter().discover(url)
        return found, fetched

    def test_a_single_part_video_yields_one_candidate(self):
        found, _ = self._discover(
            "https://www.bilibili.com/video/BV1GJ411x7h7",
            _payload(VIEW_SINGLE),
            _payload(PLAYURL_SINGLE),
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].src, PLAYURL_SINGLE["data"]["durl"][0]["url"])
        self.assertEqual(found[0].title, VIEW_SINGLE["data"]["title"])
        self.assertEqual(found[0].type, "video/mp4")
        self.assertEqual(found[0].origin, "bilibili")

    def test_the_download_request_carries_the_referer_the_cdn_requires(self):
        # Measured: the CDN answers 403 without it, so this is a contract, not a
        # cosmetic header. Deleting it from the adapter must fail this test.
        with mock.patch(
            "_webclip.video.adapters.bilibili.fetch_bytes",
            side_effect=[_payload(VIEW_SINGLE), _payload(PLAYURL_SINGLE)],
        ) as fetched:
            BilibiliAdapter().discover("https://www.bilibili.com/video/BV1GJ411x7h7")
        for call in fetched.call_args_list:
            self.assertEqual(
                call.kwargs["headers"].get("Referer"), "https://www.bilibili.com/"
            )
        self.assertEqual(
            BilibiliAdapter().headers("https://www.bilibili.com/video/x"),
            {"Referer": "https://www.bilibili.com/"},
        )

    def test_a_segmented_durl_is_refused_instead_of_truncated(self):
        payload = {
            "code": 0,
            "data": {
                "durl": [
                    {"url": "https://upos-sz-estgoss.bilivideo.com/a.mp4"},
                    {"url": "https://upos-sz-estgoss.bilivideo.com/b.mp4"},
                ]
            },
        }
        with self.assertRaises(ClipError) as raised:
            self._discover(
                "https://www.bilibili.com/video/BV1GJ411x7h7",
                _payload(VIEW_SINGLE),
                _payload(payload),
            )
        self.assertIn("segmented", str(raised.exception))

    def test_a_lowercase_bv_prefix_is_normalized(self):
        # The id itself is case-sensitive; only the prefix is safe to normalize.
        _found, fetched = self._discover(
            "https://www.bilibili.com/video/bv1GJ411x7h7",
            _payload(VIEW_SINGLE),
            _payload(PLAYURL_SINGLE),
        )
        self.assertIn("bvid=BV1GJ411x7h7", fetched.call_args_list[0].args[0])

    def test_an_av_url_sends_the_bare_aid(self):
        # `aid=av80433022` is rejected with -400; the API wants the number alone.
        found, fetched = self._discover(
            "https://www.bilibili.com/video/av80433022",
            _payload(VIEW_SINGLE),
            _payload(PLAYURL_SINGLE),
        )
        view_query = fetched.call_args_list[0].args[0]
        self.assertIn("aid=80433022", view_query)
        self.assertNotIn("aid=av", view_query)
        self.assertEqual(len(found), 1)

    def test_a_page_number_selects_that_part(self):
        found, fetched = self._discover(
            "https://www.bilibili.com/video/BV16Bs26FEAM?p=2",
            _payload(VIEW_MULTI),
            _payload(PLAYURL_PAGE_TWO),
        )
        playurl_query = fetched.call_args_list[1].args[0]
        self.assertIn("cid=43700915118", playurl_query)
        self.assertEqual(found[0].title, "在普罗米厄的怀抱下 - P2 玫瑰与妄欲")

    def test_an_out_of_range_part_is_an_error(self):
        with self.assertRaises(ClipError) as raised:
            self._discover(
                "https://www.bilibili.com/video/BV16Bs26FEAM?p=9",
                _payload(VIEW_MULTI),
            )
        self.assertIn("out of range", str(raised.exception))

    def test_a_short_link_is_resolved_first(self):
        found, fetched = self._discover(
            "https://b23.tv/BV1GJ411x7h7",
            ("https://www.bilibili.com/video/BV1GJ411x7h7", b""),
            _payload(VIEW_SINGLE),
            _payload(PLAYURL_SINGLE),
        )
        self.assertEqual(fetched.call_count, 3)
        self.assertIn("/x/web-interface/view", fetched.call_args_list[1].args[0])
        self.assertEqual(len(found), 1)

    def test_an_api_error_is_reported_with_its_code(self):
        with self.assertRaises(ClipError) as raised:
            self._discover(
                "https://www.bilibili.com/video/BV1GJ411x7h7",
                _payload({"code": -404, "message": "啥都木有"}),
            )
        self.assertIn("-404", str(raised.exception))

    def test_a_dash_only_video_is_an_error_not_an_empty_list(self):
        with self.assertRaises(ClipError) as raised:
            self._discover(
                "https://www.bilibili.com/video/BV1GJ411x7h7",
                _payload(VIEW_SINGLE),
                _payload({"code": 0, "data": {"durl": []}}),
            )
        self.assertIn("no downloadable file", str(raised.exception))

    def test_an_unreachable_api_is_a_clip_error(self):
        with mock.patch(
            "_webclip.video.adapters.bilibili.fetch_bytes",
            side_effect=ClipError("network policy"),
        ):
            with self.assertRaises(ClipError):
                BilibiliAdapter().discover("https://www.bilibili.com/video/BV1GJ411x7h7")


class UnsupportedFormTests(unittest.TestCase):
    def test_live_streams_are_refused_by_name(self):
        with self.assertRaises(ClipError) as raised:
            BilibiliAdapter().discover("https://live.bilibili.com/12345")
        self.assertIn("live streams", str(raised.exception))

    def test_bangumi_is_refused_by_name(self):
        with self.assertRaises(ClipError) as raised:
            BilibiliAdapter().discover("https://www.bilibili.com/bangumi/play/ep123")
        self.assertIn("DRM", str(raised.exception))

    def test_a_url_without_an_id_is_refused(self):
        with self.assertRaises(ClipError) as raised:
            BilibiliAdapter().discover("https://www.bilibili.com/read/cv123")
        self.assertIn("no video id", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
