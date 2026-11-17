"""SSRF guards and byte limits for video downloads."""

from __future__ import annotations

import io
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _webclip import netguard
from _webclip.core import ClipError
from _webclip.netguard import ApprovedAddress, download_to_file, fetch_bytes, resolve_and_validate


def _infos(*addresses: str):
    infos = []
    for address in addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        infos.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 0)))
    return infos


def _resolver(*addresses: str):
    return lambda host, port, **kwargs: _infos(*addresses)


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None):
        self.status = status
        self._stream = io.BytesIO(body)
        self._headers = headers or {}

    def getheader(self, name: str):
        for key, value in self._headers.items():
            if key.lower() == name.lower():
                return value
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


class _FakeConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _approved(url: str) -> ApprovedAddress:
    return ApprovedAddress(
        url=url,
        scheme="https",
        hostname="cdn.example.com",
        port=443,
        host_header="cdn.example.com",
        request_target="/a.mp4",
        address="93.184.216.34",
        family=socket.AF_INET,
    )


class ResolveTests(unittest.TestCase):
    def test_public_address_is_approved(self):
        approved = resolve_and_validate(
            "https://cdn.example.com/a.mp4", resolver=_resolver("93.184.216.34")
        )
        self.assertEqual(approved.address, "93.184.216.34")
        self.assertEqual(approved.request_target, "/a.mp4")

    def test_private_address_is_rejected(self):
        for address in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1"):
            with self.subTest(address=address):
                with self.assertRaises(ClipError):
                    resolve_and_validate(
                        "https://cdn.example.com/a.mp4", resolver=_resolver(address)
                    )

    def test_one_private_answer_rejects_the_whole_hostname(self):
        with self.assertRaises(ClipError):
            resolve_and_validate(
                "https://cdn.example.com/a.mp4",
                resolver=_resolver("93.184.216.34", "10.0.0.5"),
            )

    def test_non_default_port_is_rejected(self):
        with self.assertRaises(ClipError):
            resolve_and_validate(
                "https://cdn.example.com:8082/a.mp4",
                resolver=_resolver("93.184.216.34"),
            )

    def test_credentials_are_rejected(self):
        with self.assertRaises(ClipError):
            resolve_and_validate(
                "https://user:pass@cdn.example.com/a.mp4",
                resolver=_resolver("93.184.216.34"),
            )

    def test_unresolvable_host_is_rejected(self):
        def failing(host, port, **kwargs):
            raise OSError("no dns")

        with self.assertRaises(ClipError):
            resolve_and_validate("https://cdn.example.com/a.mp4", resolver=failing)


class DownloadTests(unittest.TestCase):
    def _patch(self, responses):
        queue = list(responses)

        def fake_open(url, **kwargs):
            response = queue.pop(0)
            return _approved(url), _FakeConnection(), response

        return mock.patch.object(netguard, "_open_pinned", side_effect=fake_open)

    def test_writes_the_body_and_reports_the_byte_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.mp4"
            with self._patch([_FakeResponse(200, b"abcdef")]):
                url, written = download_to_file("https://cdn.example.com/a.mp4", target)
            self.assertEqual(written, 6)
            self.assertEqual(target.read_bytes(), b"abcdef")
            self.assertEqual(url, "https://cdn.example.com/a.mp4")

    def test_follows_a_redirect(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.mp4"
            with self._patch(
                [
                    _FakeResponse(302, b"", {"Location": "/moved.mp4"}),
                    _FakeResponse(200, b"payload"),
                ]
            ):
                _, written = download_to_file("https://cdn.example.com/a.mp4", target)
            self.assertEqual(written, 7)

    def test_stops_after_too_many_redirects(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.mp4"
            with self._patch(
                [_FakeResponse(302, b"", {"Location": "/loop.mp4"})] * (netguard.MAX_REDIRECTS + 1)
            ):
                with self.assertRaises(ClipError):
                    download_to_file("https://cdn.example.com/a.mp4", target)

    def test_enforces_the_cap_while_streaming_even_without_content_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.mp4"
            with self._patch([_FakeResponse(200, b"x" * 100)]):
                with self.assertRaises(ClipError) as caught:
                    download_to_file(
                        "https://cdn.example.com/a.mp4", target, max_bytes=10
                    )
            self.assertIn("larger than", str(caught.exception))

    def test_rejects_a_declared_size_over_the_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.mp4"
            with self._patch([_FakeResponse(200, b"", {"Content-Length": "999"})]):
                with self.assertRaises(ClipError):
                    download_to_file(
                        "https://cdn.example.com/a.mp4", target, max_bytes=10
                    )

    def test_non_2xx_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.mp4"
            with self._patch([_FakeResponse(404)]):
                with self.assertRaises(ClipError):
                    download_to_file("https://cdn.example.com/a.mp4", target)

    def test_fetch_bytes_reads_a_small_playlist(self):
        with self._patch([_FakeResponse(200, b"#EXTM3U\n")]):
            url, body = fetch_bytes("https://cdn.example.com/a.m3u8")
        self.assertEqual(body, b"#EXTM3U\n")
        self.assertEqual(url, "https://cdn.example.com/a.m3u8")


if __name__ == "__main__":
    unittest.main()
