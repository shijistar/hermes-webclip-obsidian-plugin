import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import yaml

import web_to_obsidian as clip
from _webclip import netguard
from _webclip.article import _validate_videos
from _webclip.config import ClipConfig
from _webclip.video import naming, probe, report, store
from _webclip.video.download import direct as direct_module
from _webclip.video.download.hls import _claim_output
from _webclip.video.models import DownloadPlan
from _webclip.video.service import VideoService


def _proc_alive(pid: int) -> bool:
    """True while `/proc/<pid>` has a live (non-zombie) process entry.///"""
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    m = re.search(r"^State:\s*(\S)", status, re.MULTILINE)
    return bool(m) and m.group(1) not in ("Z", "X")


SUCCESS = {
    "ok": True,
    "title": 'Title: "quoted"',
    "author": "Ada",
    "published": "2026-07-23",
    "description": "Description",
    "site": "Example",
    "canonicalUrl": "https://example.com/article",
    "url": "https://example.com/article",
    "keywords": ["security", "clipping"],
    "markdown": "# Article\n\n" + ("body " * 60),
    "wordCount": 61,
    "method": "static",
}


class ExtractorIsolationRegressionTests(unittest.TestCase):
    def test_extractor_receives_allowlisted_environment_without_secret_tokens(self):
        process = mock.Mock()
        process.stdout = mock.Mock()
        process.stderr = mock.Mock()
        process.stdout.read.side_effect = [json.dumps(SUCCESS).encode(), b""]
        process.stderr.read.side_effect = [b""]
        process.wait.return_value = 0
        process.pid = 12345

        env = {
            "HOME": "/home/test",
            "PATH": "/safe/bin",
            "LANG": "C.UTF-8",
            "GH_TOKEN": "secret",
            "OPENAI_API_KEY": "secret",
            "NODE_OPTIONS": "--require=/tmp/evil.js",
        }
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(clip.subprocess, "Popen", return_value=process) as popen,
        ):
            clip.run_extractor(Path("/plugin"), SUCCESS["url"])

        child_env = popen.call_args.kwargs["env"]
        self.assertEqual(child_env["HOME"], "/home/test")
        self.assertEqual(child_env["PATH"], "/safe/bin")
        self.assertNotIn("GH_TOKEN", child_env)
        self.assertNotIn("OPENAI_API_KEY", child_env)
        self.assertNotIn("NODE_OPTIONS", child_env)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    @unittest.skipUnless(Path("/proc").is_dir(), "Linux process checks require /proc")
    def test_timeout_terminates_the_complete_child_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "grandchild.pid"
            code = (
                "import subprocess,sys,time; "
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                f"open({str(pid_file)!r},'w').write(str(p.pid)); "
                "time.sleep(60)"
            )
            started = time.monotonic()
            with self.assertRaises(clip.ClipError):
                clip._run_bounded(
                    [os.sys.executable, "-c", code],
                    timeout=1,
                    stdout_limit=1024,
                    stderr_limit=1024,
                )
            self.assertLess(time.monotonic() - started, 5)
            grandchild = int(pid_file.read_text(encoding="utf-8"))
            deadline = time.monotonic() + 3
            while _proc_alive(grandchild) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(_proc_alive(grandchild))


class VaultIdempotencyRegressionTests(unittest.TestCase):
    def test_frontmatter_is_yaml_serialized_and_contains_stable_hashes(self):
        note = clip.render_note(SUCCESS, created="2026-07-23T12:00:00+00:00")
        _, frontmatter, _ = note.split("---\n", 2)
        parsed = yaml.safe_load(frontmatter)
        self.assertEqual(parsed["title"], SUCCESS["title"])
        self.assertEqual(parsed["original_url"], SUCCESS["canonicalUrl"])
        self.assertEqual(parsed["original_host"], "example.com")
        self.assertRegex(parsed["webclip_id"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(parsed["content_hash"], r"^sha256:[0-9a-f]{64}$")

    def test_active_markdown_content_is_neutralized_but_https_images_remain(self):
        data = dict(SUCCESS)
        data["markdown"] = (
            "<!-- webclip:manual:start -->\n"
            "<iframe src=\"file:///etc/passwd\">hidden</iframe>\n"
            "<a href=\"file:///etc/passwd\">raw local</a>\n"
            "[local](file:///etc/passwd)\n"
            "[code](javascript:alert(1))\n"
            "![[Private Note]]\n"
            "![remote](https://cdn.example/image.png)\n"
        )
        note = clip.render_note(data, created="2026-07-23T00:00:00+00:00")
        self.assertNotIn("<iframe", note.lower())
        self.assertNotIn("<!-- webclip:manual:start -->\n<!-- webclip:manual:start -->", note)
        self.assertNotIn("](file:", note.lower())
        self.assertNotIn("](javascript:", note.lower())
        self.assertNotIn("![[", note)
        self.assertIn("![remote](https://cdn.example/image.png)", note)
        self.assertIn("&lt;a href=\"file:///etc/passwd\">", note)

    def test_same_content_is_noop_and_changed_content_requires_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "article.md"
            first = clip.render_note(SUCCESS, created="2026-07-23T12:00:00+00:00")
            self.assertEqual(clip.write_managed_note(target, first, refresh=False), "written")
            before = target.stat().st_mtime_ns
            self.assertEqual(clip.write_managed_note(target, first, refresh=False), "unchanged")
            self.assertEqual(target.stat().st_mtime_ns, before)

            changed_data = dict(SUCCESS, markdown=SUCCESS["markdown"] + "changed\n")
            changed = clip.render_note(changed_data, created="2026-07-23T13:00:00+00:00")
            with self.assertRaisesRegex(clip.ClipError, "--refresh"):
                clip.write_managed_note(target, changed, refresh=False)
            self.assertEqual(target.read_text(encoding="utf-8"), first)
            self.assertEqual(clip.write_managed_note(target, changed, refresh=True), "written")
            self.assertEqual(target.read_text(encoding="utf-8"), changed)

    def test_refresh_rewrites_existing_note_when_title_changes_but_markdown_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "article.md"
            first = clip.render_note(
                dict(SUCCESS, title="Old Title", markdown="## Intro\n\nBody\n"),
                created="2026-07-23T12:00:00+00:00",
            )
            self.assertEqual(clip.write_managed_note(target, first, refresh=False), "written")

            updated = clip.render_note(
                dict(SUCCESS, title="New Title", markdown="## Intro\n\nBody\n"),
                created="2026-07-24T12:00:00+00:00",
            )
            self.assertEqual(clip.write_managed_note(target, updated, refresh=True), "written")

            rewritten = target.read_text(encoding="utf-8")
            self.assertIn("title: New Title\n", rewritten)
            self.assertIn(
                "<!-- webclip:managed:start -->\n# New Title\n\n## Intro\n\nBody\n",
                rewritten,
            )
            self.assertIn("created: '2026-07-24T12:00:00+00:00'", rewritten)

    def test_refresh_rewrites_existing_note_when_fetched_url_changes_but_markdown_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "article.md"
            first = clip.render_note(SUCCESS, created="2026-07-23T12:00:00+00:00")
            self.assertEqual(clip.write_managed_note(target, first, refresh=False), "written")

            updated = clip.render_note(
                dict(SUCCESS, url="https://example.com/from-redirect"),
                created="2026-07-24T12:00:00+00:00",
            )
            self.assertEqual(clip.write_managed_note(target, updated, refresh=True), "written")

            rewritten = target.read_text(encoding="utf-8")
            self.assertIn("fetched_url: https://example.com/from-redirect\n", rewritten)
            self.assertIn("created: '2026-07-24T12:00:00+00:00'", rewritten)

    def test_refresh_rewrites_existing_note_when_title_changes_but_markdown_has_stable_h1(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "article.md"
            first = clip.render_note(
                dict(SUCCESS, title="Old Title", markdown="# Stable H1\n\nBody\n"),
                created="2026-07-23T12:00:00+00:00",
            )
            self.assertEqual(clip.write_managed_note(target, first, refresh=False), "written")

            updated = clip.render_note(
                dict(SUCCESS, title="New Title", markdown="# Stable H1\n\nBody\n"),
                created="2026-07-24T12:00:00+00:00",
            )
            self.assertEqual(clip.write_managed_note(target, updated, refresh=True), "written")

            rewritten = target.read_text(encoding="utf-8")
            self.assertIn("title: New Title\n", rewritten)
            self.assertIn("<!-- webclip:managed:start -->\n# Stable H1\n\nBody\n", rewritten)
            self.assertNotIn("# New Title\n\n# Stable H1", rewritten)
            self.assertIn("created: '2026-07-24T12:00:00+00:00'", rewritten)

    def test_refresh_preserves_manual_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "article.md"
            first = clip.render_note(
                dict(SUCCESS, markdown="## Intro\n\nBody\n"),
                created="2026-07-23T12:00:00+00:00",
            )
            self.assertEqual(clip.write_managed_note(target, first, refresh=False), "written")

            existing = target.read_text(encoding="utf-8")
            manual = "Personal notes\n- keep this\n"
            target.write_text(
                existing.replace(
                    "<!-- webclip:manual:start -->\n<!-- webclip:manual:end -->\n",
                    f"<!-- webclip:manual:start -->\n{manual}<!-- webclip:manual:end -->\n",
                ),
                encoding="utf-8",
            )

            updated = clip.render_note(
                dict(SUCCESS, markdown="## Intro\n\nBody updated\n"),
                created="2026-07-24T12:00:00+00:00",
            )
            self.assertEqual(clip.write_managed_note(target, updated, refresh=True), "written")

            rewritten = target.read_text(encoding="utf-8")
            self.assertIn(
                f"# {SUCCESS['title']}\n\n## Intro\n\nBody updated\n",
                rewritten,
            )
            self.assertIn(
                f"<!-- webclip:manual:start -->\n{manual}<!-- webclip:manual:end -->\n",
                rewritten,
            )


class SharedLockRegressionTests(unittest.TestCase):
    def test_second_lock_contender_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vault.lock"
            with clip.VaultLock(path):
                with self.assertRaises(clip.ClipError):
                    with clip.VaultLock(path):
                        self.fail("second contender unexpectedly acquired the lock")


class PreviewUrlParamsSecurityTests(unittest.TestCase):
    def test_unsafe_preview_params_are_rejected(self):
        unsafe = [
            "a=1#fragment",
            "a=1\r\nX-Injected: 1",
            "a=1\nX-Injected: 1",
            "a=1\tX",
            "a=1&&b=2",
            "justkey",
            "=novalue",
            "a=" * 600,
            "  a=1",
            "a=1  ",
            "a=" + chr(0x80),
        ]
        for value in unsafe:
            with self.subTest(value=value[:24]):
                with self.assertRaises(clip.ClipError):
                    clip._normalize_preview_url_params(value)

    def test_rejected_params_never_reach_the_preview_url(self):
        url = "https://github.com/o/r/blob/master/Inbox/note.md"
        with self.assertRaises(clip.ClipError):
            clip._normalize_preview_url_params("a=1#evil")
        configured = clip._normalize_preview_url_params("a=1")
        rendered = clip.append_query_params(url, configured)
        self.assertEqual(rendered, url + "?a=1")
        self.assertNotIn("#", rendered)

    def test_loader_rejects_unsafe_preview_params(self):
        unsafe = "a=1#fragment"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            vault.mkdir()
            mapping = {
                "WEB_TO_OBSIDIAN_VAULT": str(vault),
                "WEB_TO_OBSIDIAN_LOCK_FILE": str(root / "vault.lock"),
            }
            with self.assertRaises(clip.ClipError):
                clip.ClipConfig.from_env(
                    {**mapping, "WEB_TO_OBSIDIAN_PREVIEW_URL_PARAMS": unsafe}
                )
            config_path = root / "config.toml"
            config_path.write_text(
                "[clip]\n"
                f'vault = "{vault}"\n'
                'destination = "Inbox"\n'
                'images = "images"\n'
                'sync_branch = "master"\n'
                f'lock_file = "{root / "vault.lock"}"\n'
                f'preview_url_params = "{unsafe}"\n',
                encoding="utf-8",
            )
            with self.assertRaises(clip.ClipError):
                clip.ClipConfig.from_file(config_path)


class ReceiptCellInjectionTests(unittest.TestCase):
    """Page-derived receipt cells must render as literal text.

    Every value below was measured against GitHub's GFM renderer: without the
    wrap it becomes an ``<a>`` (autolink), ``<em>``, ``<strong>`` or ``<del>``,
    so a scraped title can turn into a live link or a mention of a real account.
    """

    def test_autolink_triggers_are_wrapped_in_a_code_span(self):
        for value in (
            "https://example.com",
            "www.example.com",
            "contact a@b.com",
            "thanks @shijistar",
        ):
            with self.subTest(value=value):
                self.assertEqual(clip._summary_cell(value), f"` {value} `")

    def test_emphasis_and_strikethrough_are_wrapped_in_a_code_span(self):
        for value in ("**Important**", "_italic_", "~~strike~~"):
            with self.subTest(value=value):
                self.assertEqual(clip._summary_cell(value), f"` {value} `")

    def test_plain_text_keeps_its_characters(self):
        for value, expected in (
            ("普通标题 2026", "普通标题 2026"),
            ("Tom & Jerry", "Tom &amp; Jerry"),
            ("A | B", "A \\| B"),
        ):
            with self.subTest(value=value):
                self.assertEqual(clip._summary_cell(value), expected)

    def test_an_underscore_inside_a_word_still_gets_a_code_span(self):
        # Deliberate over-protection: `_` is an emphasis delimiter, so a title
        # such as snake_case_title renders monospace instead of risking <em>.
        self.assertEqual(clip._summary_cell("snake_case_title"), "` snake_case_title `")

    def test_the_plugin_image_row_keeps_its_emphasis(self):
        result = clip.ClipResult(
            path="note.md",
            commit_state="disabled",
            push_state="disabled",
            image_mode="remote",
            image_count=3,
        )
        self.assertIn("**全部远程链接**", result.summary_markdown())


class RenderOnlyRefreshRegressionTests(unittest.TestCase):
    """A body that only the renderer changed must not demand --refresh.

    The fallback contract puts the untrimmed page in ``article["markdown"]`` (what
    ``source_content_hash`` fingerprints) and the trimmed body in ``content_markdown``.
    Every case below fails on the pre-fix code, where the source fingerprint was the
    constant ``sha256("\\n")`` and nothing could tell a rewrite from a re-render.
    """

    PAGE = "# Article\n\npage text\n"
    BODY_V1 = "# Article\n\nbody v1\n"
    BODY_V2 = "# Article\n\nbody v2\n"
    EMPTY_SOURCE = "sha256:" + hashlib.sha256(b"\n").hexdigest()

    def _note(
        self,
        *,
        page: str | None = None,
        body: str | None = None,
        favorite: bool | None = None,
    ) -> str:
        data = dict(SUCCESS, markdown=self.PAGE if page is None else page)
        return clip.render_note(
            data,
            created="2026-11-17T00:00:00+00:00",
            content_markdown=body,
            favorite=favorite,
        )

    def test_a_rendered_body_without_source_text_is_refused(self):
        with self.assertRaisesRegex(clip.ClipError, "empty 'markdown'"):
            clip.render_note(
                dict(SUCCESS, markdown=""),
                created="2026-11-17T00:00:00+00:00",
                content_markdown=self.BODY_V1,
            )

    def test_a_renderer_change_rewrites_without_asking_for_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.md"
            self.assertEqual(
                clip.write_managed_note(target, self._note(body=self.BODY_V1), refresh=False),
                "written",
            )
            self.assertEqual(
                clip.write_managed_note(target, self._note(body=self.BODY_V2), refresh=False),
                "written",
            )
            text = target.read_text(encoding="utf-8")
            self.assertIn("body v2", text)
            self.assertNotIn("body v1", text)

    def test_a_reader_edited_status_does_not_block_the_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.md"
            clip.write_managed_note(target, self._note(body=self.BODY_V1), refresh=False)
            target.write_text(
                target.read_text(encoding="utf-8").replace(
                    "status: needs-review", "status: done", 1
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                clip.write_managed_note(target, self._note(body=self.BODY_V2), refresh=False),
                "written",
            )

    def test_a_changed_source_still_requires_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.md"
            clip.write_managed_note(target, self._note(body=self.BODY_V1), refresh=False)
            moved = self._note(page=self.PAGE + "the author edited this\n", body=self.BODY_V2)
            with self.assertRaisesRegex(clip.ClipError, "--refresh"):
                clip.write_managed_note(target, moved, refresh=False)

    def test_a_note_without_a_fingerprint_is_not_exempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.md"
            clip.write_managed_note(target, self._note(body=self.BODY_V1), refresh=False)
            target.write_text(
                "\n".join(
                    line
                    for line in target.read_text(encoding="utf-8").split("\n")
                    if not line.startswith("content_hash:")
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(clip.ClipError, "--refresh"):
                clip.write_managed_note(target, self._note(body=self.BODY_V2), refresh=False)

    def test_a_raw_note_keeps_the_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.md"
            # No content_markdown: content_hash == source_content_hash, the shape of a
            # note saved before any render rules existed.
            raw = clip.render_note(SUCCESS, created="2026-11-17T00:00:00+00:00")
            clip.write_managed_note(target, raw, refresh=False)
            with self.assertRaisesRegex(clip.ClipError, "--refresh"):
                clip.write_managed_note(target, self._note(body=self.BODY_V1), refresh=False)

    def test_the_favorite_marker_survives_a_render_only_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.md"
            clip.write_managed_note(
                target, self._note(body=self.BODY_V1, favorite=True), refresh=False
            )
            clip.write_managed_note(target, self._note(body=self.BODY_V2), refresh=False)
            metadata = clip._frontmatter_from_text(target.read_text(encoding="utf-8"))
            self.assertIsNotNone(metadata)
            self.assertIs((metadata or {}).get("favorite"), True)

    def test_a_whitespace_body_with_an_empty_source_is_refused(self):
        """Stripping the body let " " through and replaced a real article with a space."""
        with self.assertRaisesRegex(clip.ClipError, "empty 'markdown'"):
            clip.render_note(
                dict(SUCCESS, markdown=""),
                created="2026-11-17T00:00:00+00:00",
                content_markdown=" ",
            )

    def test_a_legacy_empty_fingerprint_note_is_not_exempt(self):
        """A note whose source fingerprint is the empty-body hash has no source identity.

        Built by rewriting the fingerprints directly: the render guard refuses to create
        this shape any more, so the only remaining source is a note written before it.
        """

        def with_hashes(text: str, source: str, content: str) -> str:
            text = re.sub(r"source_content_hash: sha256:[0-9a-f]+", f"source_content_hash: {source}", text)
            return re.sub(r"content_hash: sha256:[0-9a-f]+", f"content_hash: {content}", text)

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.md"
            target.write_text(
                with_hashes(self._note(body=self.BODY_V1), self.EMPTY_SOURCE, "sha256:" + "a" * 64),
                encoding="utf-8",
            )
            incoming = with_hashes(
                self._note(body=self.BODY_V2), self.EMPTY_SOURCE, "sha256:" + "b" * 64
            )
            with self.assertRaisesRegex(clip.ClipError, "--refresh"):
                clip.write_managed_note(target, incoming, refresh=False)

    def test_an_explicit_favorite_removal_wins_over_the_exemption(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.md"
            clip.write_managed_note(
                target, self._note(body=self.BODY_V1, favorite=True), refresh=False
            )
            clip.write_managed_note(
                target, self._note(body=self.BODY_V2, favorite=False), refresh=True
            )
            metadata = clip._frontmatter_from_text(target.read_text(encoding="utf-8"))
            self.assertNotIn("favorite", metadata or {})


class SaveVideoSecurityTests(unittest.TestCase):
    """Regressions for `/save-video`, where every field comes from the page."""

    class _Connection:
        def close(self):
            pass

    class _Response:
        """Minimal stand-in for `http.client.HTTPResponse`."""

        status = 200

        def __init__(self, read):
            self._read = read

        def getheader(self, name):
            return None

        def read(self, size=-1):
            return self._read()

    def _patched(self, response):
        approved = mock.Mock(url="https://cdn.example.com/a")
        return mock.patch.object(
            netguard, "_open_pinned", return_value=(approved, self._Connection(), response)
        )

    def test_a_chunked_body_that_stops_mid_chunk_is_a_clip_error(self):
        def truncated():
            raise http.client.IncompleteRead(b"#EXTM3U", 4096)

        with self._patched(self._Response(truncated)):
            # `IncompleteRead` is an `HTTPException`, not an `OSError`: uncaught
            # it escaped the per-candidate handler and aborted the whole batch.
            with self.assertRaises(netguard.ClipError):
                netguard.fetch_bytes("https://cdn.example.com/a")

    def test_a_truncated_download_leaves_no_partial_file(self):
        def truncated():
            raise http.client.IncompleteRead(b"\x00" * 16, 8192)

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "clip.mp4"
            with self._patched(self._Response(truncated)):
                with self.assertRaises(netguard.ClipError):
                    netguard.download_to_file("https://cdn.example.com/a", target)
            self.assertFalse(target.exists())

    def test_a_keyformat_value_cannot_mask_the_encryption_method(self):
        playlist = (
            "#EXTM3U\n#EXT-X-TARGETDURATION:10\n"
            '#EXT-X-KEY:KEYFORMAT="METHOD=NONE",METHOD=AES-128,URI="key.bin"\n'
            "#EXTINF:10,\nsegment.ts\n#EXT-X-ENDLIST\n"
        )
        info = probe.parse_playlist(playlist, url="https://cdn.example.com/a.m3u8")
        self.assertTrue(info.encrypted)

    def test_a_page_url_cannot_smuggle_a_media_tag(self):
        # The gateway honours `MEDIA:` at any offset, so a word boundary is not
        # enough: `xMEDIA:` must be neutralised too.
        rendered = report._text("https://cdn.example.com/xMEDIA:/tmp/report.pdf")
        self.assertNotIn("MEDIA:", rendered.upper())
        self.assertIn("\u2044tmp", rendered)

    def test_a_page_supplied_subtype_cannot_choose_the_extension(self):
        for subtype in ("md", "exe", "html", "x" * 64):
            with self.subTest(subtype=subtype):
                chosen = naming.extension_for(
                    f"video/{subtype}", "https://cdn.example.com/clip"
                )
                self.assertNotEqual(chosen, f".{subtype}")
                self.assertTrue(chosen.startswith("."))

    def test_a_relative_destination_cannot_escape_the_vault_through_a_symlink(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            (vault / "videos").symlink_to(Path(out), target_is_directory=True)
            with self.assertRaises(netguard.ClipError):
                store.resolve_destination(vault, "videos")

    def test_an_hls_merge_cannot_be_redirected_through_a_symlink(self):
        # ffmpeg is started with `-y` and follows symlinks, so the output name
        # has to be claimed before it runs. A pre-placed link must fail the
        # candidate rather than let the merge overwrite its target.
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside.bin"
            outside.write_bytes(b"ORIGINAL")
            target = Path(tmp) / "clip.mp4"
            target.symlink_to(outside)

            with self.assertRaises(FileExistsError):
                _claim_output(target)

            self.assertEqual(outside.read_bytes(), b"ORIGINAL")

    def test_a_partial_clip_table_does_not_split_the_vault_or_the_lock(self):
        # `/webclip` resolves `[clip]` through `ClipConfig.from_file`, which
        # never reads `os.environ`. Reading the environment here for the keys the
        # table omits gave the two commands different locks on the same vault.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "plugin"
            root.mkdir()
            vault = Path(tmp) / "vault"
            vault.mkdir()
            elsewhere = Path(tmp) / "elsewhere.lock"
            (root / "config.toml").write_text(
                f'[clip]\nvault = "{vault}"\n', encoding="utf-8"
            )

            with mock.patch.dict(
                os.environ, {"WEB_TO_OBSIDIAN_LOCK_FILE": str(elsewhere)}
            ):
                expected = ClipConfig.from_file(root / "config.toml")
                service = VideoService(root)
                self.assertEqual(service._vault(), expected.vault)
                self.assertEqual(service._lock_path(), expected.lock_file)
                self.assertNotEqual(service._lock_path(), elsewhere.resolve())

    def test_without_a_config_file_both_commands_read_the_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "plugin"
            root.mkdir()
            vault = Path(tmp) / "vault"
            vault.mkdir()
            shared = Path(tmp) / "shared.lock"

            with mock.patch.dict(
                os.environ,
                {
                    "WEB_TO_OBSIDIAN_VAULT": str(vault),
                    "WEB_TO_OBSIDIAN_LOCK_FILE": str(shared),
                },
            ):
                expected = ClipConfig.from_file(root / "config.toml")
                service = VideoService(root)
                self.assertEqual(service._vault(), expected.vault)
                self.assertEqual(service._lock_path(), expected.lock_file)
                self.assertEqual(service._lock_path(), shared.resolve())

    def test_a_truncated_url_falls_through_to_the_next_candidate(self):
        # The point of converting `IncompleteRead` was to keep the batch going,
        # not merely to change the exception type: `download_direct` has to move
        # on to the next URL instead of re-raising.
        plan = DownloadPlan(
            urls=("https://cdn.example.com/a", "https://cdn.example.com/b"),
            kind="direct",
            headers={},
            title="clip",
        )
        attempts = []

        def fake(url, destination, **kwargs):
            attempts.append(url)
            if url.endswith("/a"):
                raise netguard.ClipError("the response ended early")
            destination.write_bytes(b"\x00" * 4096)
            return url, 4096

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                direct_module, "download_to_file", side_effect=fake
            ), mock.patch.object(direct_module, "probe_duration", return_value=1.0):
                result = direct_module.download_direct(plan, Path(tmp) / "out.mp4")

            self.assertEqual(
                attempts,
                ["https://cdn.example.com/a", "https://cdn.example.com/b"],
            )
            self.assertEqual(result.bytes_written, 4096)

    def test_the_collector_limits_are_accepted_by_the_python_validator(self):
        # The Node collector clamps to exactly these bounds. If the two sets of
        # limits drift apart, a page near the edge makes the validator raise and
        # the whole page fails to extract — the failure mode the clamp exists to
        # prevent, so the pair is asserted here rather than in either unit alone.
        base = "https://example.com/"
        items = [
            {
                "src": base + "a" * (8192 - len(base)),
                "type": "video/" + "x" * 250,
                "title": "t" * 10_000,
                "poster": base + "p" * (8192 - len(base)),
                "origin": "o" * 64,
                "width": 100_000,
                "height": 0,
            }
        ]

        self.assertEqual(len(_validate_videos(items)), 1)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class CollectorContractTests(unittest.TestCase):
    """The collector's real output has to satisfy the Python validator.

    A hand-built candidate cannot catch this: it asserts what the validator
    accepts, not what the collector produces. Only running `collectVideos` and
    feeding its output to `_validate_videos` fails when one side's limits move
    without the other.
    """

    EXTRACTOR = Path(__file__).resolve().parents[1] / "extractor"

    def _collect(self, html: str) -> list[dict]:
        script = (
            "import { parseHTML } from 'linkedom';\n"
            "import { collectVideos } from './src/video-collect.mjs';\n"
            f"const {{ document }} = parseHTML({json.dumps(html)});\n"
            "process.stdout.write(JSON.stringify("
            "collectVideos(document, 'https://example.com/a')));\n"
        )
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=self.EXTRACTOR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[:800])
        return json.loads(completed.stdout)

    def test_a_page_at_every_limit_passes_python_validation(self):
        if not (self.EXTRACTOR / "node_modules" / "linkedom").is_dir():
            self.skipTest("extractor dependencies are not installed")

        oversized = "https://example.com/" + "a" * 8200 + ".mp4"
        html = (
            "<html><head><title>" + "t" * 20000 + "</title></head><body>"
            '<video width="100001" height="-5">'
            '<source src="/clip.mp4" type="video/mp4"></video>'
            f'<video><source src="{oversized}"></video>'
            "</body></html>"
        )

        items = self._collect(html)

        # The 8200-byte source is dropped by the collector, and whatever survives
        # is accepted by the validator. Either limit moving alone breaks this.
        self.assertEqual(
            [item["src"] for item in items], ["https://example.com/clip.mp4"]
        )
        self.assertEqual(len(_validate_videos(items)), 1)
        self.assertLessEqual(items[0]["width"], 100_000)
        self.assertGreaterEqual(items[0]["height"], 0)


if __name__ == "__main__":
    unittest.main()
