"""Adapter selection and candidate discovery."""

from __future__ import annotations

import unittest
from unittest import mock

from _webclip.core import ClipError
from _webclip.video import discover as discover_module
from _webclip.video.discover import adapter_for, dedupe, discover
from _webclip.video.models import VideoCandidate

NETEASE_HTML = """
<html><head><title>某条新闻标题_网易视频</title></head><body>
  <figure data-alt="图注里的视频标题">
    <video data-mp4="undefined" data-m3u8="//flv0.bn.netease.com/a.m3u8" src=""></video>
  </figure>
  <video data-m3u8="//flv0.bn.netease.com/b.m3u8" title="第二个"></video>
  <video src="https://flv1.bn.netease.com/c.mp4"></video>
</body></html>
"""


class AdapterSelectionTests(unittest.TestCase):
    def test_netease_urls_pick_the_netease_adapter(self):
        for url in (
            "https://www.163.com/news/a/ABC.html",
            "https://c.m.163.com/news/v/ABC.html",
            "https://m.163.com/dy/article/ABC.html",
        ):
            with self.subTest(url=url):
                self.assertEqual(adapter_for(url).name, "netease")

    def test_other_urls_pick_the_generic_adapter(self):
        for url in ("https://example.com/a", "https://not163.com/a"):
            with self.subTest(url=url):
                self.assertEqual(adapter_for(url).name, "generic")


class GenericDiscoveryTests(unittest.TestCase):
    def test_candidates_come_from_the_extractor_payload(self):
        article = {
            "videos": [
                {"src": "https://cdn.example.com/a.m3u8", "title": "A", "width": 1280},
                {"src": "https://cdn.example.com/b.mp4", "title": "B"},
            ]
        }
        found = discover("https://example.com/page", article=article)
        self.assertEqual([item.src for item in found], [
            "https://cdn.example.com/a.m3u8",
            "https://cdn.example.com/b.mp4",
        ])
        self.assertEqual(found[0].width, 1280)

    def test_no_article_means_no_candidates(self):
        self.assertEqual(discover("https://example.com/page"), [])

    def test_malformed_entries_are_skipped(self):
        article = {"videos": [{"title": "no src"}, "nope", {"src": "https://cdn/x.mp4"}]}
        found = discover("https://example.com/page", article=article)
        self.assertEqual(len(found), 1)


class NeteaseDiscoveryTests(unittest.TestCase):
    def _discover(self, html: str):
        with mock.patch(
            "_webclip.video.adapters.netease._fetch_netease_video_html",
            return_value=html,
        ):
            adapter = discover_module.NeteaseAdapter()
            return adapter.discover("https://c.m.163.com/news/v/ABC.html")

    def test_multiple_players_are_all_returned(self):
        found = self._discover(NETEASE_HTML)
        self.assertEqual(len(found), 3)
        self.assertTrue(all(item.src.startswith("https://") for item in found))
        self.assertEqual(found[0].src, "https://flv0.bn.netease.com/a.m3u8")

    def test_the_figure_caption_wins_over_the_page_title(self):
        found = self._discover(NETEASE_HTML)
        self.assertEqual(found[0].title, "图注里的视频标题")

    def test_the_page_title_loses_its_site_suffix(self):
        html = '<html><head><title>标题_网易视频</title></head><body><video src="https://c/x.mp4"></video></body></html>'
        found = self._discover(html)
        self.assertEqual(found[0].title, "标题")

    def test_undefined_attributes_are_ignored(self):
        html = '<html><body><video data-mp4="undefined" data-m3u8="//c/x.m3u8"></video></body></html>'
        found = self._discover(html)
        self.assertEqual(len(found), 1)
        self.assertIn(".m3u8", found[0].src)

    def test_a_fetch_failure_is_reported_as_a_clip_error(self):
        with mock.patch(
            "_webclip.video.adapters.netease._fetch_netease_video_html",
            side_effect=ClipError("boom"),
        ):
            adapter = discover_module.NeteaseAdapter()
            with self.assertRaises(ClipError):
                adapter.discover("https://www.163.com/news/a/ABC.html")


class DedupeTests(unittest.TestCase):
    def test_duplicate_sources_collapse(self):
        items = [
            VideoCandidate(src="https://cdn/a.mp4"),
            VideoCandidate(src="https://cdn/a.mp4", title="dup"),
            VideoCandidate(src="https://cdn/b.mp4"),
        ]
        self.assertEqual([item.src for item in dedupe(items)], [
            "https://cdn/a.mp4",
            "https://cdn/b.mp4",
        ])


if __name__ == "__main__":
    unittest.main()
