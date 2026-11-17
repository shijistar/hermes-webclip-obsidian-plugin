"""HLS download flow: pre-flight refusals, segment fetch, local remux."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from _webclip.core import ClipError
from _webclip.video.download import hls as hls_module
from _webclip.video.download.hls import download_hls
from _webclip.video.models import DownloadPlan
from _webclip.video.probe import PlaylistInfo

PLAN = DownloadPlan(urls=("https://cdn.example.com/master.m3u8",), kind="hls")
SEGMENTS = [
    "https://cdn.example.com/seg-1.ts",
    "https://cdn.example.com/seg-2.ts",
]


def _info(
    *,
    url: str = "https://cdn.example.com/media.m3u8",
    segments: int = 2,
    duration_s: float = 12.0,
    encrypted: bool = False,
    live: bool = False,
    variants: tuple[str, ...] = (),
) -> PlaylistInfo:
    return PlaylistInfo(
        url=url,
        segments=segments,
        duration_s=duration_s,
        encrypted=encrypted,
        live=live,
        variants=variants,
    )


class RefusalTests(unittest.TestCase):
    def _run(self, info: PlaylistInfo):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            hls_module, "probe", return_value=info
        ):
            return download_hls(PLAN, Path(tmp) / "out.mp4")

    def test_encrypted_streams_are_refused(self):
        with self.assertRaises(ClipError) as caught:
            self._run(_info(encrypted=True))
        self.assertIn("encrypted", str(caught.exception))

    def test_live_streams_are_refused(self):
        with self.assertRaises(ClipError) as caught:
            self._run(_info(live=True))
        self.assertIn("live", str(caught.exception))

    def test_playlists_without_segments_are_refused(self):
        with self.assertRaises(ClipError) as caught:
            self._run(_info(segments=0))
        self.assertIn("no segments", str(caught.exception))


class DownloadFlowTests(unittest.TestCase):
    def test_segments_are_fetched_in_order_and_remuxed_from_local_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.mp4"
            fetched: list[str] = []
            ffmpeg_calls: list[list[str]] = []
            captured: dict[str, str] = {}

            def fake_download(url, destination, **kwargs):
                fetched.append(url)
                destination.write_bytes(b"x" * 10)
                return url, 10

            def fake_ffmpeg(args, **kwargs):
                ffmpeg_calls.append(args)
                # The temporary directory is gone once download_hls returns, so
                # the concat list has to be read while ffmpeg "runs".
                list_file = Path(args[args.index("-i") + 1])
                captured["concat"] = list_file.read_text(encoding="utf-8")
                Path(args[-1]).write_bytes(b"merged")

            with (
                mock.patch.object(hls_module, "probe", return_value=_info()),
                mock.patch.object(
                    hls_module, "read_media_playlist", return_value=(_info(), SEGMENTS)
                ),
                mock.patch.object(hls_module, "download_to_file", side_effect=fake_download),
                mock.patch.object(hls_module, "run_ffmpeg", side_effect=fake_ffmpeg),
                mock.patch.object(hls_module, "probe_duration", return_value=12.5),
            ):
                result = download_hls(PLAN, target)

            self.assertEqual(fetched, SEGMENTS)
            self.assertEqual(result.bytes_written, 6)  # the fake merged file
            self.assertEqual(result.duration_s, 12.5)

            args = ffmpeg_calls[0]
            # ffmpeg must be told it may only read local files.
            self.assertIn("-protocol_whitelist", args)
            self.assertEqual(args[args.index("-protocol_whitelist") + 1], "file")
            self.assertEqual(args[args.index("-c") + 1], "copy")
            self.assertNotIn("http", captured["concat"])
            self.assertEqual(captured["concat"].count("file '"), 2)

    def test_a_failed_segment_leaves_no_target_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.mp4"
            target.write_bytes(b"stale")

            def failing(url, destination, **kwargs):
                raise ClipError("the server refused")

            with (
                mock.patch.object(hls_module, "probe", return_value=_info()),
                mock.patch.object(
                    hls_module, "read_media_playlist", return_value=(_info(), SEGMENTS)
                ),
                mock.patch.object(hls_module, "download_to_file", side_effect=failing),
            ):
                with self.assertRaises(ClipError):
                    download_hls(PLAN, target)
            # The caller removes the target; the downloader must not have created one.
            self.assertEqual(target.read_bytes(), b"stale")

    def test_an_empty_merge_result_is_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.mp4"

            def fake_download(url, destination, **kwargs):
                destination.write_bytes(b"x")
                return url, 1

            def noop_ffmpeg(args, **kwargs):
                # ffmpeg "succeeds" without writing anything.
                return None

            with (
                mock.patch.object(hls_module, "probe", return_value=_info()),
                mock.patch.object(
                    hls_module, "read_media_playlist", return_value=(_info(), SEGMENTS)
                ),
                mock.patch.object(hls_module, "download_to_file", side_effect=fake_download),
                mock.patch.object(hls_module, "run_ffmpeg", side_effect=noop_ffmpeg),
            ):
                with self.assertRaises(ClipError):
                    download_hls(PLAN, target)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
