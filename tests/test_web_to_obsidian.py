import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest import mock

import yaml

import web_to_obsidian as clip


SUCCESS = {
    "ok": True,
    "title": "An Article",
    "author": "Ada",
    "published": "2026-07-23",
    "description": "A useful page",
    "site": "Example",
    "canonicalUrl": "https://example.com/article",
    "url": "https://example.com/article",
    "keywords": ["security", "clipping"],
    "markdown": "# An Article\r\n\r\nBody\r\n",
    "wordCount": 3,
    "method": "readability",
}


class ArgsTests(unittest.TestCase):
    def test_accepts_one_http_url_and_supported_flags(self):
        parsed = clip.parse_clip_args(
            '"https://example.com/a?x=1&y=2" --no-browser --no-git'
        )
        self.assertEqual(parsed.url, "https://example.com/a?x=1&y=2")
        self.assertTrue(parsed.no_browser)
        self.assertTrue(parsed.no_git)
        self.assertEqual(parsed.save_images, "ask")

    def test_accepts_save_images_modes(self):
        for mode in ("yes", "no", "ask"):
            with self.subTest(mode=mode):
                parsed = clip.parse_clip_args(
                    f"https://example.com/article --save-images {mode}"
                )
                self.assertEqual(parsed.save_images, mode)

    def test_rejects_unknown_option_extra_url_and_non_http_url(self):
        invalid = (
            "https://example.com --wat",
            "https://example.com https://other.example",
            "file:///etc/passwd",
            "",
            "https://example.com --save-images maybe",
        )
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(clip.ClipError):
                clip.parse_clip_args(raw)

    def test_rejects_malformed_shell_quoting(self):
        with self.assertRaises(clip.ClipError):
            clip.parse_clip_args("'https://example.com")

    def test_parses_favorite_flags(self):
        cases = (
            ("--favorite", True, False),
            ("--unfavorite", False, False),
            ("--favorite-only", True, True),
            ("--unfavorite-only", False, True),
        )
        for flag, value, metadata_only in cases:
            with self.subTest(flag=flag):
                parsed = clip.parse_clip_args(f"https://example.com/article {flag}")
                self.assertIs(parsed.favorite, value)
                self.assertIs(parsed.metadata_only, metadata_only)

    def test_rejects_conflicting_favorite_flags(self):
        invalid = (
            "https://example.com/article --favorite --unfavorite",
            "https://example.com/article --favorite --favorite-only",
            "https://example.com/article --favorite-only --refresh",
            "https://example.com/article --unfavorite-only --save-images no",
            "https://example.com/article --favorite-only --save-images ask",
        )
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(clip.ClipError):
                clip.parse_clip_args(raw)


class ConfigAndFilenameTests(unittest.TestCase):
    def test_destination_must_resolve_inside_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            with self.assertRaises(clip.ClipError):
                clip.ClipConfig.from_env(
                    {
                        "WEB_TO_OBSIDIAN_VAULT": str(vault),
                        "WEB_TO_OBSIDIAN_DEST": "../escape",
                    }
                )

    def test_toml_config_loads_and_lock_must_remain_outside_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            vault.mkdir()
            config_path = root / "config.toml"
            config_path.write_text(
                "[clip]\n"
                f'vault = "{vault}"\n'
                'destination = "Inbox"\n'
                'images = "images"\n'
                'sync_branch = "master"\n'
                f'lock_file = "{root / "vault.lock"}"\n',
                encoding="utf-8",
            )
            config = clip.ClipConfig.from_file(config_path)
            self.assertEqual(config.destination, vault / "Inbox")
            self.assertEqual(config.sync_branch, "master")

            with self.assertRaisesRegex(clip.ClipError, "lock file"):
                clip.ClipConfig.from_env(
                    {
                        "WEB_TO_OBSIDIAN_VAULT": str(vault),
                        "WEB_TO_OBSIDIAN_LOCK_FILE": str(vault / "bad.lock"),
                    }
                )

    def test_default_destination_is_inbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            config = clip.ClipConfig.from_env({"WEB_TO_OBSIDIAN_VAULT": str(vault)})
            self.assertEqual(config.destination, vault / "Inbox")

    def test_pending_root_reads_from_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            pending_root = Path(tmp) / "state"
            config = clip.ClipConfig.from_env(
                {
                    "WEB_TO_OBSIDIAN_VAULT": str(vault),
                    "WEB_TO_OBSIDIAN_PENDING_ROOT": str(pending_root),
                }
            )
            self.assertEqual(config.pending_root, pending_root.resolve())

    def test_pending_root_defaults_outside_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            config = clip.ClipConfig.from_env({"WEB_TO_OBSIDIAN_VAULT": str(vault)})
            self.assertNotEqual(config.pending_root, vault)
            self.assertNotIn(vault, config.pending_root.parents)

    def test_pending_root_from_toml_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            vault.mkdir()
            pending_root = root / "custom-pending-state"
            config_path = root / "config.toml"
            config_path.write_text(
                "[clip]\n"
                f'vault = "{vault}"\n'
                'destination = "Inbox"\n'
                'images = "images"\n'
                'sync_branch = "master"\n'
                f'lock_file = "{root / "vault.lock"}"\n'
                f'pending_root = "{pending_root}"\n',
                encoding="utf-8",
            )
            config = clip.ClipConfig.from_file(config_path)
            self.assertEqual(config.pending_root, pending_root.resolve())

    def test_filename_removes_traversal_controls_and_forbidden_characters(self):
        name = clip.safe_filename("  ../A:<B>\\C/\x00\n...  ", "https://example.com/x")
        self.assertTrue(name.endswith(".md"))
        self.assertNotIn("/", name)
        self.assertNotIn("\\", name)
        self.assertNotIn("..", name)
        self.assertNotIn(":", name)
        self.assertNotIn("\x00", name)

    def test_filename_avoids_reserved_dos_basename(self):
        for title in ("CON", "con.txt", "LPT1", "aux"):
            with self.subTest(title=title):
                name = clip.safe_filename(title, "https://example.com/reserved")
                self.assertFalse(name.removesuffix(".md").split(".", 1)[0].upper() in clip.DOS_RESERVED)

    def test_filename_caps_utf8_without_splitting_unicode(self):
        name = clip.safe_filename("界" * 200, "https://example.com/unicode", max_bytes=47)
        name.encode("utf-8")
        self.assertLessEqual(len(name.encode("utf-8")), 47)
        self.assertTrue(name.endswith(".md"))

    def test_empty_sanitized_title_uses_hash_fallback(self):
        first = clip.safe_filename("////", "https://example.com/fallback")
        second = clip.safe_filename("////", "https://example.com/fallback")
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{12}\.md$")


class RenderingTests(unittest.TestCase):
    def test_yaml_quotes_injection_strings_and_normalizes_line_endings(self):
        data = dict(SUCCESS)
        data["title"] = 'Title"\n---\nevil: true'
        data["description"] = "line one\r\nline two"
        note = clip.render_note(data, created="2026-07-23T12:00:00+00:00")

        self.assertNotIn("\r", note)
        self.assertTrue(note.startswith("---\n"))
        frontmatter, _ = note[4:].split("\n---\n", 1)
        parsed = yaml.safe_load(frontmatter)
        self.assertEqual(
            list(parsed),
            [
                "title",
                "url",
                "author",
                "site",
                "description",
                "keywords",
                "tags",
                "original_url",
                "original_host",
                "extraction_method",
                "status",
                "category",
                "word_count",
                "webclip_id",
                "source_content_hash",
                "content_hash",
                "published",
                "created",
            ],
        )
        self.assertEqual(parsed["title"], data["title"])
        self.assertEqual(parsed["url"], "https://example.com/article")
        self.assertEqual(parsed["original_url"], "https://example.com/article")
        self.assertEqual(parsed["original_host"], "example.com")
        self.assertEqual(parsed["keywords"], ["security", "clipping"])
        self.assertEqual(parsed["category"], "Inbox")
        self.assertEqual(parsed["created"], "2026-07-23T12:00:00+00:00")
        self.assertEqual(parsed["extraction_method"], "readability")
        self.assertEqual(parsed["tags"], ["web-clip"])
        self.assertNotIn("image_mode", parsed)
        self.assertEqual(parsed["source_content_hash"], parsed["content_hash"])
        self.assertNotIn("source", parsed)
        self.assertNotIn("source_host", parsed)
        self.assertEqual(note.count("\n---\n"), 1)

    def test_render_note_accepts_prevalidated_extractor_payload_without_ok_flag(self):
        validated = clip._validate_success_payload(SUCCESS)
        note = clip.render_note(validated, created="2026-07-23T12:00:00+00:00")
        self.assertIn("title: An Article", note)
        self.assertIn("keywords:", note)
        self.assertEqual(note.count("\n# An Article\n\n"), 1)

    def test_render_note_includes_remote_image_mode_when_requested(self):
        note = clip.render_note(
            SUCCESS,
            created="2026-07-23T12:00:00+00:00",
            image_mode="remote",
        )

        frontmatter, _ = note[4:].split("\n---\n", 1)
        parsed = yaml.safe_load(frontmatter)
        self.assertEqual(parsed["image_mode"], "remote")

    def test_render_note_includes_local_image_mode_when_requested(self):
        note = clip.render_note(
            SUCCESS,
            created="2026-07-23T12:00:00+00:00",
            image_mode="local",
        )

        frontmatter, _ = note[4:].split("\n---\n", 1)
        parsed = yaml.safe_load(frontmatter)
        self.assertEqual(parsed["image_mode"], "local")

    def test_render_note_injects_h1_when_markdown_has_no_h1(self):
        data = dict(SUCCESS, markdown="## Intro\n\nBody\n")
        note = clip.render_note(data, created="2026-07-23T12:00:00+00:00")
        self.assertIn(
            "<!-- webclip:managed:start -->\n# An Article\n\n## Intro\n\nBody\n",
            note,
        )

    def test_render_note_sanitizes_and_single_lines_injected_h1_title(self):
        data = dict(
            SUCCESS,
            title="Bad [[vault]]\n<script>alert(1)</script>",
            markdown="## Intro\n\nBody\n",
        )
        note = clip.render_note(data, created="2026-07-23T12:00:00+00:00")
        managed = note.split("<!-- webclip:managed:start -->\n", 1)[1].split(
            "\n<!-- webclip:managed:end -->", 1
        )[0]
        self.assertEqual(managed, "# Bad \\[\\[vault]]\n\n## Intro\n\nBody")
        self.assertNotIn("[[vault]]", managed)
        self.assertNotIn("<script>", managed)
        self.assertNotIn("# Bad \\[\\[vault]]\n<script>", managed)

    def test_render_note_preserves_existing_h1_without_duplicate_insertion(self):
        note = clip.render_note(SUCCESS, created="2026-07-23T12:00:00+00:00")
        self.assertIn("<!-- webclip:managed:start -->\n# An Article\n\nBody\n", note)
        self.assertEqual(note.count("\n# An Article\n\n"), 1)

    def test_render_note_preserves_setext_h1_without_duplicate_insertion(self):
        data = dict(SUCCESS, markdown="An Article\n===\n\nBody\n")
        note = clip.render_note(data, created="2026-07-23T12:00:00+00:00")
        self.assertIn(
            "<!-- webclip:managed:start -->\nAn Article\n===\n\nBody\n",
            note,
        )
        self.assertEqual(note.count("\n# An Article\n\n"), 0)

    def test_render_note_ignores_indented_code_when_deciding_to_inject_h1(self):
        data = dict(SUCCESS, markdown="    # not a heading\n\nBody\n")
        note = clip.render_note(data, created="2026-07-23T12:00:00+00:00")
        self.assertIn(
            "<!-- webclip:managed:start -->\n# An Article\n\n    # not a heading\n\nBody\n",
            note,
        )

    def test_render_note_preserves_fetched_url_when_request_url_differs(self):
        data = dict(
            SUCCESS,
            canonicalUrl="https://example.com/article",
            url="https://example.com/from-redirect",
        )
        note = clip.render_note(data, created="2026-07-23T12:00:00+00:00")

        frontmatter, _ = note[4:].split("\n---\n", 1)
        parsed = yaml.safe_load(frontmatter)
        self.assertEqual(
            list(parsed),
            [
                "title",
                "url",
                "author",
                "site",
                "description",
                "keywords",
                "tags",
                "original_url",
                "original_host",
                "fetched_url",
                "extraction_method",
                "status",
                "category",
                "word_count",
                "webclip_id",
                "source_content_hash",
                "content_hash",
                "published",
                "created",
            ],
        )
        self.assertEqual(parsed["fetched_url"], "https://example.com/from-redirect")
        self.assertNotIn("image_mode", parsed)


class ImageWorkflowHelpersTests(unittest.TestCase):
    def test_detects_remote_images_only_from_native_markdown_image_syntax(self):
        markdown = (
            "![one](https://cdn.example/a.png)\n"
            "<img src=\"https://cdn.example/b.jpeg\" alt=\"two\">\n"
            "![local](images/a.png)\n"
            "[link](https://cdn.example/not-an-image)\n"
        )
        self.assertEqual(
            clip.find_remote_images(markdown),
            ["https://cdn.example/a.png"],
        )

    def test_sanitize_markdown_keeps_html_images_out_of_remote_detection(self):
        sanitized = clip.sanitize_markdown(
            '<p>Lead</p><img src="https://cdn.example/hero.png" alt="Hero image">'
        )
        self.assertNotIn("![Hero image](https://cdn.example/hero.png)", sanitized)
        self.assertIn('&lt;img src="https://cdn.example/hero.png" alt="Hero image">', sanitized)
        self.assertEqual(clip.find_remote_images(sanitized), [])

    def test_localize_images_preserves_date_prefix_in_note_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images_root = root / "images"
            inbox = root / "Inbox"
            inbox.mkdir()
            note_one = inbox / "2026-07-25-Same Title.md"
            note_two = inbox / "2026-07-25-Same Title-deadbeef.md"
            payloads = iter((b"first-image", b"second-image"))

            def fake_download(url: str, destination_dir: Path, index: int) -> Path:
                self.assertEqual(url, "https://cdn.example/image.png")
                destination_dir.mkdir(parents=True, exist_ok=True)
                target = destination_dir / f"{index:02d}-image.png"
                target.write_bytes(next(payloads))
                return target

            markdown = "![x](https://cdn.example/image.png)\n"
            with mock.patch.object(clip, "download_remote_image", side_effect=fake_download):
                rewritten_one, paths_one = clip._localize_images(
                    markdown,
                    "Same Title",
                    "https://example.com/one",
                    images_root,
                    note_one,
                )
                rewritten_two, paths_two = clip._localize_images(
                    markdown,
                    "Same Title",
                    "https://example.com/two",
                    images_root,
                    note_two,
                )

            self.assertEqual(paths_one[0].parent.name, "2026-07-25-same-title")
            self.assertEqual(paths_two[0].parent.name, "2026-07-25-same-title-deadbeef")
            self.assertNotEqual(paths_one[0], paths_two[0])
            self.assertEqual(paths_one[0].read_bytes(), b"first-image")
            self.assertEqual(paths_two[0].read_bytes(), b"second-image")
            self.assertIn("![x](../images/2026-07-25-same-title/01-image.png)", rewritten_one)
            self.assertIn("![x](../images/2026-07-25-same-title-deadbeef/01-image.png)", rewritten_two)

    def test_builds_github_blob_url_for_master_branch(self):
        self.assertEqual(
            clip.github_blob_url(
                "https://github.com/shijistar/obsidian.git",
                "master",
                "Inbox/2026-07-25-An Article.md",
            ),
            "https://github.com/shijistar/obsidian/blob/master/Inbox/2026-07-25-An%20Article.md",
        )


class TargetAndAtomicWriteTests(unittest.TestCase):
    def _note(self, source, title="Old"):
        data = dict(SUCCESS, title=title, canonicalUrl=source, url=source)
        return clip.render_note(data, created="2026-07-23T12:00:00+00:00")

    def test_same_normalized_source_overwrites_same_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            target = destination / clip.safe_filename("An Article", SUCCESS["canonicalUrl"])
            target.write_text(self._note("HTTPS://EXAMPLE.COM:443/article#old"), encoding="utf-8")

            chosen = clip.choose_target(
                destination, "An Article", "https://example.com/article"
            )
            self.assertEqual(chosen, target)

    def test_new_target_uses_capture_date_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            chosen = clip.choose_target(
                destination,
                "An Article",
                "https://example.com/article",
                capture_date="2026-07-23",
            )
            self.assertEqual(chosen.name, "2026-07-23-An Article.md")

    def test_same_source_on_a_later_date_reuses_existing_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            existing = destination / "2026-07-22-An Article.md"
            existing.write_text(
                self._note("https://example.com/article"), encoding="utf-8"
            )

            chosen = clip.choose_target(
                destination,
                "Renamed Article",
                "https://example.com/article",
                capture_date="2026-07-23",
            )
            self.assertEqual(chosen, existing)

    def test_choose_target_accepts_existing_notes_with_original_url_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            existing = destination / "2026-07-22-An Article.md"
            existing.write_text(
                "---\n"
                "title: An Article\n"
                "original_url: https://example.com/article\n"
                "---\n\n"
                "# An Article\n",
                encoding="utf-8",
            )

            chosen = clip.choose_target(
                destination,
                "An Article",
                "https://example.com/article",
                capture_date="2026-07-23",
            )
            self.assertEqual(chosen, existing)

    def test_choose_target_accepts_existing_notes_with_legacy_source_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            existing = destination / "2026-07-22-An Article.md"
            existing.write_text(
                "---\n"
                "title: An Article\n"
                "source: https://example.com/article\n"
                "---\n\n"
                "# An Article\n",
                encoding="utf-8",
            )

            chosen = clip.choose_target(
                destination,
                "An Article",
                "https://example.com/article",
                capture_date="2026-07-23",
            )
            self.assertEqual(chosen, existing)

    def test_multiple_existing_notes_for_same_source_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            for day in ("2026-07-21", "2026-07-22"):
                (destination / f"{day}-An Article.md").write_text(
                    self._note("https://example.com/article"), encoding="utf-8"
                )

            with self.assertRaisesRegex(clip.ClipError, "multiple"):
                clip.choose_target(
                    destination,
                    "An Article",
                    "https://example.com/article",
                    capture_date="2026-07-23",
                )

    def test_title_collision_with_different_source_adds_url_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            base = destination / clip.safe_filename(
                "2026-07-23-An Article", "https://one.example"
            )
            base.write_text(self._note("https://one.example/"), encoding="utf-8")

            chosen1 = clip.choose_target(
                destination,
                "An Article",
                "https://two.example",
                capture_date="2026-07-23",
            )
            chosen2 = clip.choose_target(
                destination,
                "An Article",
                "https://two.example",
                capture_date="2026-07-23",
            )
            self.assertEqual(chosen1, chosen2)
            self.assertNotEqual(chosen1, base)
            self.assertRegex(
                chosen1.name, r"^2026-07-23-An Article-[0-9a-f]{8}\.md$"
            )
            self.assertEqual(chosen1.parent, destination)

    def test_existing_symlink_escaping_destination_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / "dest"
            destination.mkdir()
            outside = root / "outside.md"
            outside.write_text(self._note("https://example.com/article"), encoding="utf-8")
            target = destination / clip.safe_filename("An Article", SUCCESS["canonicalUrl"])
            target.symlink_to(outside)
            with self.assertRaises(clip.ClipError):
                clip.choose_target(destination, "An Article", SUCCESS["canonicalUrl"])

    def test_atomic_write_replaces_target_and_uses_same_directory_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.md"
            target.write_text("old", encoding="utf-8")
            real_replace = os.replace
            calls = []

            def recording_replace(source, destination):
                calls.append((Path(source), Path(destination)))
                return real_replace(source, destination)

            with mock.patch.object(clip.os, "replace", side_effect=recording_replace):
                clip.atomic_write(target, "new\n")

            self.assertEqual(target.read_text(encoding="utf-8"), "new\n")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0].parent, target.parent)
            self.assertEqual(calls[0][1], target)
            self.assertFalse(any(p.name.startswith(".clip-") for p in target.parent.iterdir()))


class ExtractorTests(unittest.TestCase):
    def test_node_command_is_a_list_and_never_uses_shell(self):
        process = mock.Mock()
        process.stdout = io.BytesIO(json.dumps(SUCCESS).encode())
        process.stderr = io.BytesIO(b"")
        process.wait.return_value = 0
        process.poll.return_value = 0

        with mock.patch.object(clip.subprocess, "Popen", return_value=process) as popen:
            result = clip.run_extractor(
                Path("/plugins/webclip-obsidian/plugin"),
                "https://example.com/article",
                no_browser=True,
            )

        args, kwargs = popen.call_args
        self.assertIsInstance(args[0], list)
        self.assertEqual(
            args[0],
            [
                "node",
                "/plugins/webclip-obsidian/extractor/src/cli.mjs",
                "https://example.com/article",
                "--no-browser",
            ],
        )
        self.assertIs(kwargs["shell"], False)
        self.assertLessEqual(kwargs.get("timeout", clip.EXTRACTOR_TIMEOUT), 120)
        self.assertEqual(result["title"], "An Article")

    def test_malformed_or_oversized_extractor_json_is_rejected_without_stderr(self):
        malformed = clip.ProcessResult(0, b"not json", b"SECRET traceback")
        with mock.patch.object(clip, "_run_bounded", return_value=malformed):
            with self.assertRaises(clip.ClipError) as caught:
                clip.run_extractor(Path("/plugin"), "https://example.com")
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertNotIn("traceback", str(caught.exception).lower())

    def test_extractor_success_payload_requires_all_typed_fields(self):
        bad = dict(SUCCESS, wordCount="three")
        result = clip.ProcessResult(0, json.dumps(bad).encode(), b"")
        with mock.patch.object(clip, "_run_bounded", return_value=result):
            with self.assertRaises(clip.ClipError):
                clip.run_extractor(Path("/plugin"), "https://example.com")

    def test_extractor_success_payload_requires_keywords_to_be_a_string_list(self):
        bad = dict(SUCCESS, keywords=["ok", 1])
        result = clip.ProcessResult(0, json.dumps(bad).encode(), b"")
        with mock.patch.object(clip, "_run_bounded", return_value=result):
            with self.assertRaises(clip.ClipError):
                clip.run_extractor(Path("/plugin"), "https://example.com")

    def test_extractor_dir_prefers_plugin_local_npm_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugin_root"
            plugin_root.mkdir(parents=True)
            npm_pkg = (
                plugin_root / "node_modules" / "@tiny-codes" / "web-clip-extractor"
            )
            (npm_pkg / "src").mkdir(parents=True)
            (npm_pkg / "src" / "cli.mjs").write_text(
                "#!/usr/bin/env node\n", encoding="utf-8"
            )
            # A bundled extractor also exists; npm install must win.
            direct = plugin_root / "extractor"
            (direct / "src").mkdir(parents=True)
            (direct / "src" / "cli.mjs").write_text(
                "#!/usr/bin/env node\n", encoding="utf-8"
            )
            self.assertEqual(clip._extractor_dir(plugin_root), npm_pkg)

    def test_extractor_dir_falls_back_to_bundled_subdirectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugin_root"
            plugin_root.mkdir(parents=True)
            direct = plugin_root / "extractor"
            (direct / "src").mkdir(parents=True)
            (direct / "src" / "cli.mjs").write_text(
                "#!/usr/bin/env node\n", encoding="utf-8"
            )
            self.assertEqual(clip._extractor_dir(plugin_root), direct)

    def test_extractor_dir_falls_back_to_legacy_source_repo_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugin_root"
            plugin_root.mkdir(parents=True)
            sibling = root / "extractor"
            (sibling / "src").mkdir(parents=True)
            (sibling / "src" / "cli.mjs").write_text(
                "#!/usr/bin/env node\n", encoding="utf-8"
            )
            self.assertEqual(clip._extractor_dir(plugin_root), sibling)


class GitSafetyTests(unittest.TestCase):
    def _git(self, root, *args):
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_refuses_dirty_worktree_before_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._git(repo, "init", "-b", "feature/clip")
            (repo / "dirty.txt").write_text("dirty", encoding="utf-8")
            with self.assertRaises(clip.ClipError) as caught:
                clip.GitSync.preflight(repo)
            self.assertIn("clean", str(caught.exception).lower())

    def test_allows_master_when_configured_branch_is_master(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote.git"
            repo = root / "vault"
            self._git(root, "init", "--bare", str(remote))
            self._git(root, "init", "-b", "master", str(repo))
            self._git(repo, "config", "user.name", "Clip Test")
            self._git(repo, "config", "user.email", "clip@example.invalid")
            self._git(repo, "remote", "add", "origin", str(remote))
            (repo / ".gitkeep").write_text("", encoding="utf-8")
            self._git(repo, "add", ".gitkeep")
            self._git(repo, "commit", "-m", "initial")
            self._git(repo, "push", "-u", "origin", "master")

            sync = clip.GitSync.preflight(repo, expected_branch="master")
            self.assertEqual(sync.branch, "master")

    def test_rejects_when_vault_is_not_on_configured_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote.git"
            repo = root / "vault"
            self._git(root, "init", "--bare", str(remote))
            self._git(root, "init", "-b", "feature/clip", str(repo))
            self._git(repo, "config", "user.name", "Clip Test")
            self._git(repo, "config", "user.email", "clip@example.invalid")
            self._git(repo, "remote", "add", "origin", str(remote))
            (repo / ".gitkeep").write_text("", encoding="utf-8")
            self._git(repo, "add", ".gitkeep")
            self._git(repo, "commit", "-m", "initial")
            self._git(repo, "push", "-u", "origin", "feature/clip")

            with self.assertRaisesRegex(clip.ClipError, "configured clip sync branch"):
                clip.GitSync.preflight(repo, expected_branch="master")

    def test_refuses_cherry_pick_and_revert_states(self):
        for state_name in ("CHERRY_PICK_HEAD", "REVERT_HEAD"):
            with self.subTest(state=state_name), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                self._git(repo, "init", "-b", "feature/clip")
                self._git(repo, "config", "user.name", "Clip Test")
                self._git(repo, "config", "user.email", "clip@example.invalid")
                (repo / ".gitkeep").write_text("", encoding="utf-8")
                self._git(repo, "add", ".gitkeep")
                self._git(repo, "commit", "-m", "initial")
                state_path = Path(
                    self._git(repo, "rev-parse", "--git-path", state_name)
                    .stdout.decode()
                    .strip()
                )
                if not state_path.is_absolute():
                    state_path = repo / state_path
                state_path.write_text(
                    self._git(repo, "rev-parse", "HEAD").stdout.decode(),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(clip.ClipError, "operation"):
                    clip.GitSync.preflight(repo)

    def test_stages_only_generated_path_commits_and_pushes_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote.git"
            repo = root / "vault"
            self._git(root, "init", "--bare", str(remote))
            self._git(root, "init", "-b", "feature/clip", str(repo))
            self._git(repo, "config", "user.name", "Clip Test")
            self._git(repo, "config", "user.email", "clip@example.invalid")
            self._git(repo, "remote", "add", "origin", str(remote))
            (repo / ".gitkeep").write_text("", encoding="utf-8")
            self._git(repo, "add", ".gitkeep")
            self._git(repo, "commit", "-m", "initial")

            sync = clip.GitSync.preflight(repo)
            dest = repo / "Unclassified"
            dest.mkdir()
            note = dest / "Article.md"
            note.write_text("body\n", encoding="utf-8")
            outcome = sync.finalize([note])

            self.assertEqual(outcome.commit_state, "committed")
            self.assertEqual(outcome.push_state, "pushed")
            changed = self._git(repo, "show", "--pretty=", "--name-only", "HEAD").stdout
            self.assertEqual(changed.decode().strip(), "Unclassified/Article.md")
            upstream = self._git(repo, "rev-parse", "--abbrev-ref", "@{upstream}").stdout
            self.assertEqual(upstream.decode().strip(), "origin/feature/clip")

    def test_post_commit_verification_blocks_hook_added_paths_from_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote.git"
            repo = root / "vault"
            self._git(root, "init", "--bare", str(remote))
            self._git(root, "init", "-b", "feature/clip", str(repo))
            self._git(repo, "config", "user.name", "Clip Test")
            self._git(repo, "config", "user.email", "clip@example.invalid")
            self._git(repo, "remote", "add", "origin", str(remote))
            (repo / ".gitkeep").write_text("", encoding="utf-8")
            self._git(repo, "add", ".gitkeep")
            self._git(repo, "commit", "-m", "initial")

            hook_path = repo / ".git" / "hooks" / "pre-commit"
            hook_path.write_text(
                "#!/bin/sh\n"
                "printf 'hook data\\n' > hook-added.txt\n"
                "git add -- hook-added.txt\n",
                encoding="utf-8",
            )
            hook_path.chmod(0o700)

            sync = clip.GitSync.preflight(repo)
            destination = repo / "Unclassified"
            destination.mkdir()
            note = destination / "Article.md"
            note.write_text("body\n", encoding="utf-8")
            outcome = sync.finalize([note])

            self.assertEqual(outcome.commit_state, "committed_unverified")
            self.assertEqual(outcome.push_state, "not_attempted")
            remote_branch = subprocess.run(
                [
                    "git",
                    f"--git-dir={remote}",
                    "show-ref",
                    "--verify",
                    "refs/heads/feature/clip",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertNotEqual(remote_branch.returncode, 0)

    def test_finalize_allows_image_only_changes_within_generated_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote.git"
            repo = root / "vault"
            self._git(root, "init", "--bare", str(remote))
            self._git(root, "init", "-b", "master", str(repo))
            self._git(repo, "config", "user.name", "Clip Test")
            self._git(repo, "config", "user.email", "clip@example.invalid")
            self._git(repo, "remote", "add", "origin", str(remote))
            (repo / "Inbox").mkdir()
            (repo / "images" / "2026-07-25-an-article").mkdir(parents=True)
            note = repo / "Inbox" / "2026-07-25-An Article.md"
            image = repo / "images" / "2026-07-25-an-article" / "01-image.png"
            note.write_text("same note\n", encoding="utf-8")
            image.write_bytes(b"old")
            self._git(
                repo,
                "add",
                "Inbox/2026-07-25-An Article.md",
                "images/2026-07-25-an-article/01-image.png",
            )
            self._git(repo, "commit", "-m", "initial")
            self._git(repo, "push", "-u", "origin", "master")

            sync = clip.GitSync.preflight(repo, expected_branch="master")
            image.write_bytes(b"new-bytes")
            outcome = sync.finalize([note, image])

            self.assertEqual(outcome.commit_state, "committed")
            self.assertEqual(outcome.push_state, "pushed")
            changed = self._git(repo, "show", "--pretty=", "--name-only", "HEAD").stdout
            self.assertEqual(changed.decode().strip(), "images/2026-07-25-an-article/01-image.png")

    def test_finalize_uses_custom_commit_message_when_provided(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote.git"
            repo = root / "vault"
            self._git(root, "init", "--bare", str(remote))
            self._git(root, "init", "-b", "master", str(repo))
            self._git(repo, "config", "user.name", "Clip Test")
            self._git(repo, "config", "user.email", "clip@example.invalid")
            self._git(repo, "remote", "add", "origin", str(remote))
            (repo / ".gitkeep").write_text("", encoding="utf-8")
            self._git(repo, "add", ".gitkeep")
            self._git(repo, "commit", "-m", "initial")
            self._git(repo, "push", "-u", "origin", "master")

            sync = clip.GitSync.preflight(repo, expected_branch="master")
            dest = repo / "Inbox"
            dest.mkdir()
            note = dest / "My Article.md"
            note.write_text("body\n", encoding="utf-8")
            outcome = sync.finalize([note], commit_message="clip: My Article")

            self.assertEqual(outcome.commit_state, "committed")
            self.assertEqual(outcome.push_state, "pushed")
            log_msg = self._git(repo, "log", "-1", "--pretty=%s").stdout.decode().strip()
            self.assertEqual(log_msg, "clip: My Article")

    def test_finalize_falls_back_to_default_commit_message_when_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote.git"
            repo = root / "vault"
            self._git(root, "init", "--bare", str(remote))
            self._git(root, "init", "-b", "master", str(repo))
            self._git(repo, "config", "user.name", "Clip Test")
            self._git(repo, "config", "user.email", "clip@example.invalid")
            self._git(repo, "remote", "add", "origin", str(remote))
            (repo / ".gitkeep").write_text("", encoding="utf-8")
            self._git(repo, "add", ".gitkeep")
            self._git(repo, "commit", "-m", "initial")
            self._git(repo, "push", "-u", "origin", "master")

            sync = clip.GitSync.preflight(repo, expected_branch="master")
            dest = repo / "Inbox"
            dest.mkdir()
            note = dest / "Article.md"
            note.write_text("body\n", encoding="utf-8")
            outcome = sync.finalize([note])

            self.assertEqual(outcome.commit_state, "committed")
            log_msg = self._git(repo, "log", "-1", "--pretty=%s").stdout.decode().strip()
            self.assertEqual(log_msg, "clip: save web article")

    def test_finalize_truncates_long_commit_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote.git"
            repo = root / "vault"
            self._git(root, "init", "--bare", str(remote))
            self._git(root, "init", "-b", "master", str(repo))
            self._git(repo, "config", "user.name", "Clip Test")
            self._git(repo, "config", "user.email", "clip@example.invalid")
            self._git(repo, "remote", "add", "origin", str(remote))
            (repo / ".gitkeep").write_text("", encoding="utf-8")
            self._git(repo, "add", ".gitkeep")
            self._git(repo, "commit", "-m", "initial")
            self._git(repo, "push", "-u", "origin", "master")

            sync = clip.GitSync.preflight(repo, expected_branch="master")
            dest = repo / "Inbox"
            dest.mkdir()
            note = dest / "Article.md"
            note.write_text("body\n", encoding="utf-8")
            long_title = "A" * 100
            outcome = sync.finalize([note], commit_message=f"clip: {long_title}")

            self.assertEqual(outcome.commit_state, "committed")
            log_msg = self._git(repo, "log", "-1", "--pretty=%s").stdout.decode().strip()
            self.assertTrue(log_msg.startswith("clip: A"))


class RemoteAssetDownloadTests(unittest.TestCase):
    def test_download_remote_image_rejects_blocked_addresses_before_request(self):
        def blocked_resolver(host, port, *, type=0, proto=0):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", port)),
            ]

        request_impl = mock.Mock()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(clip.ClipError, "blocked by network policy"):
                clip.download_remote_image(
                    "http://example.com/image.png",
                    Path(tmp),
                    1,
                    resolver=blocked_resolver,
                    request_impl=request_impl,
                )
        request_impl.assert_not_called()

    def test_download_remote_image_revalidates_redirect_destinations(self):
        def resolver(host, port, *, type=0, proto=0):
            if host == "public.example":
                return [
                    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port)),
                ]
            if host == "blocked.example":
                return [
                    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", port)),
                ]
            raise AssertionError(f"unexpected host: {host}")

        def request_impl(approved, *, timeout, max_bytes):
            self.assertEqual(approved.hostname, "public.example")
            return clip._PinnedRemoteResponse(
                status_code=302,
                headers={"Location": "http://blocked.example/image.png"},
                body=b"",
            )

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(clip.ClipError, "blocked by network policy"):
                clip.download_remote_image(
                    "http://public.example/image.png",
                    Path(tmp),
                    1,
                    resolver=resolver,
                    request_impl=request_impl,
                )


class WeChatExtractionTests(unittest.TestCase):
    def test_is_wechat_url(self):
        self.assertTrue(clip._is_wechat_url("https://mp.weixin.qq.com/s/abc123"))
        self.assertTrue(clip._is_wechat_url("https://weixin.qq.com/s/abc123"))
        self.assertFalse(clip._is_wechat_url("https://example.com/article"))
        self.assertFalse(clip._is_wechat_url("https://mp.notweixin.qq.com/s/x"))

    def test_parse_wechat_html_extracts_metadata(self):
        html = (
            '<html><script>'
            'var msg_title = "Test Article Title";'
            'var nickname = "Test Author";'
            'var ct = "1700000000";'
            '</script>'
            '<div id="js_content"><p>Hello world</p></div>'
            '<script>var other = 1;</script></html>'
        )
        result = clip._parse_wechat_html(html, "https://mp.weixin.qq.com/s/test")
        self.assertEqual(result["title"], "Test Article Title")
        self.assertEqual(result["author"], "Test Author")
        self.assertEqual(result["published"], "2023-11-14")
        self.assertEqual(result["site"], "mp.weixin.qq.com")
        self.assertEqual(result["method"], "wechat-curl")
        self.assertIn("Hello world", result["markdown"])

    def test_parse_wechat_html_rejects_missing_title(self):
        html = '<div id="js_content"><p>Body</p></div>'
        with self.assertRaises(clip.ClipError):
            clip._parse_wechat_html(html, "https://mp.weixin.qq.com/s/x")

    def test_parse_wechat_html_extracts_author_from_htmldecode(self):
        """Newer WeChat pages write var nickname = htmlDecode("...")."""
        html = (
            '<html><script>'
            'var msg_title = "Cloudflare tsrs";'
            'var nickname = htmlDecode("前端圈");'
            'var ct = "1700000000";'
            '</script>'
            '<div id="js_content"><p>Hello world</p></div></html>'
        )
        result = clip._parse_wechat_html(html, "https://mp.weixin.qq.com/s/test")
        self.assertEqual(result["author"], "前端圈")
        self.assertEqual(result["title"], "Cloudflare tsrs")

    def test_parse_wechat_html_rejects_missing_body(self):
        html = '<script>var msg_title = "Title";</script>'
        with self.assertRaises(clip.ClipError):
            clip._parse_wechat_html(html, "https://mp.weixin.qq.com/s/x")

    def test_wechat_html_to_markdown_images(self):
        html = '<p><img data-src="https://example.com/img.png" alt="pic"/></p>'
        md = clip._wechat_html_to_markdown(html)
        self.assertIn("![pic](https://example.com/img.png)", md)

    def test_wechat_html_to_markdown_headings_and_formatting(self):
        html = '<h2>Title</h2><p><strong>Bold</strong> and <em>italic</em></p>'
        md = clip._wechat_html_to_markdown(html)
        self.assertIn("## Title", md)
        self.assertIn("**Bold**", md)
        self.assertIn("*italic*", md)

    def test_wechat_html_to_markdown_strips_tags_and_entities(self):
        html = "<p>Hello &amp; world</p><div>inner</div>"
        md = clip._wechat_html_to_markdown(html)
        self.assertIn("Hello & world", md)
        self.assertNotIn("<p>", md)
        self.assertNotIn("<div>", md)

    def test_count_words_cjk(self):
        self.assertEqual(clip._count_words("你好世界"), 4)
        self.assertEqual(clip._count_words("Hello World"), 2)
        self.assertEqual(clip._count_words(""), 0)

    def test_run_extractor_with_fallback_falls_back_for_wechat(self):
        """When Node.js fails and URL is WeChat, curl fallback is used."""
        mock_html = (
            '<html><script>'
            'var msg_title = "Fallback Article";'
            'var nickname = "Author";'
            'var ct = "1700000000";'
            '</script>'
            '<div id="js_content"><p>Fallback content</p></div>'
            '</html>'
        )
        with mock.patch.object(clip, "run_extractor", side_effect=clip.ClipError("BROWSER_FAILED")):
            with mock.patch.object(clip, "_fetch_wechat_html", return_value=mock_html):
                result = clip.run_extractor_with_fallback(
                    Path("/plugin"), "https://mp.weixin.qq.com/s/test"
                )
        self.assertEqual(result["title"], "Fallback Article")
        self.assertEqual(result["method"], "wechat-curl")
        self.assertIn("Fallback content", result["markdown"])

    def test_run_extractor_with_fallback_raises_for_non_wechat(self):
        """When Node.js fails and URL is not WeChat, the error propagates."""
        with mock.patch.object(clip, "run_extractor", side_effect=clip.ClipError("BROWSER_FAILED")):
            with self.assertRaises(clip.ClipError):
                clip.run_extractor_with_fallback(
                    Path("/plugin"), "https://example.com/article"
                )

    def test_run_extractor_with_fallback_no_fallback_on_success(self):
        """When Node.js succeeds, no fallback is triggered."""
        fake_result = {
            "ok": True, "title": "T", "author": "", "published": "",
            "description": "", "site": "x", "canonicalUrl": "https://x",
            "url": "https://x", "keywords": [], "markdown": "body " * 50,
            "wordCount": 50, "method": "static",
        }
        with mock.patch.object(clip, "run_extractor", return_value=fake_result):
            with mock.patch.object(clip, "_fetch_wechat_html") as mock_fetch:
                result = clip.run_extractor_with_fallback(
                    Path("/plugin"), "https://mp.weixin.qq.com/s/test"
                )
        mock_fetch.assert_not_called()
        self.assertEqual(result["method"], "static")


class NeteaseVideoExtractionTests(unittest.TestCase):
    def test_is_netease_video_url(self):
        self.assertTrue(
            clip._is_netease_video_url("https://c.m.163.com/news/sv/VX86P5HB7.html")
        )
        self.assertTrue(
            clip._is_netease_video_url("http://c.m.163.com/news/sv/ABC.html")
        )
        # Regular Netease articles are not video links
        self.assertFalse(
            clip._is_netease_video_url("https://c.m.163.com/news/a/L8OB21Q2.html")
        )
        # Non-Netease hosts are rejected even with the /news/sv/ path
        self.assertFalse(
            clip._is_netease_video_url("https://example.com/news/sv/x.html")
        )

    def test_parse_netease_video_html_extracts_metadata_and_stream(self):
        html = (
            "<html><head><title>古法海盐</title></head><body>"
            '"nickname":"七怪看世界"'
            '<video src="http://flv0.bn.netease.com/abc.m3u8"></video>'
            "</body></html>"
        )
        result = clip._parse_netease_video_html(html, "https://c.m.163.com/news/sv/X.html")
        self.assertEqual(result["title"], "古法海盐")
        self.assertEqual(result["author"], "七怪看世界")
        self.assertEqual(result["method"], "netease-video-curl")
        self.assertIn("<video", result["markdown"])
        self.assertIn("abc.m3u8", result["markdown"])

    def test_parse_netease_video_html_rejects_missing_title(self):
        html = '<body><video src="http://x.com/a.m3u8"></video></body>'
        with self.assertRaises(clip.ClipError):
            clip._parse_netease_video_html(html, "https://c.m.163.com/news/sv/X.html")

    def test_parse_netease_video_html_without_stream_warns(self):
        html = "<html><head><title>No Stream</title></head><body></body></html>"
        result = clip._parse_netease_video_html(html, "https://c.m.163.com/news/sv/X.html")
        self.assertNotIn("<video", result["markdown"])
        self.assertIn("未能提取视频流链接", result["markdown"])

    def test_parse_netease_video_html_extracts_author_from_html_class(self):
        """Video pages use <div class="s-name"> for author, not JSON nickname."""
        html = (
            "<html><head><title>美食视频</title></head><body>"
            '<div class="exhibit-authors-info">'
            '<div class="s-name">小鹅美食</div>'
            '<div class="s-location">广东</div>'
            "</div>"
            '<video src="http://flv0.bn.netease.com/abc.m3u8"></video>'
            "</body></html>"
        )
        result = clip._parse_netease_video_html(html, "https://c.m.163.com/news/v/X.html")
        self.assertEqual(result["author"], "小鹅美食")
        self.assertEqual(result["method"], "netease-video-curl")

    def test_parse_netease_video_html_extracts_cover_image(self):
        """Cover URL is extracted from .poster[data-bg]."""
        html = (
            "<html><head><title>封面测试</title></head><body>"
            '<div class="poster js-poster js-lazy" '
            'data-bg="http://videoimg.ws.126.net/cover/20261008/pPhI6QDFq_cover.jpg">'
            "</div>"
            '<video src="http://flv0.bn.netease.com/abc.m3u8"></video>'
            "</body></html>"
        )
        result = clip._parse_netease_video_html(html, "https://c.m.163.com/news/v/X.html")
        self.assertIn(
            "http://videoimg.ws.126.net/cover/20261008/pPhI6QDFq_cover.jpg",
            result["markdown"],
        )

    def test_parse_netease_video_html_extracts_published_date(self):
        """Published date is parsed from the cover URL date segment."""
        html = (
            "<html><head><title>日期测试</title></head><body>"
            '<div class="poster js-poster js-lazy" '
            'data-bg="http://videoimg.ws.126.net/cover/20261008/pPhI6QDFq_cover.jpg">'
            "</div>"
            '<video src="http://flv0.bn.netease.com/abc.m3u8"></video>'
            "</body></html>"
        )
        result = clip._parse_netease_video_html(html, "https://c.m.163.com/news/v/X.html")
        self.assertEqual(result["published"], "2026-10-08")
        self.assertIn("2026-10-08", result["markdown"])

    def test_parse_netease_video_html_prefers_nickname_over_html_class(self):
        """When both JSON nickname and HTML class exist, nickname wins."""
        html = (
            "<html><head><title>优先级测试</title></head><body>"
            '"nickname":"JSON作者"'
            '<div class="s-name">HTML作者</div>'
            '<video src="http://flv0.bn.netease.com/abc.m3u8"></video>'
            "</body></html>"
        )
        result = clip._parse_netease_video_html(html, "https://c.m.163.com/news/sv/X.html")
        self.assertEqual(result["author"], "JSON作者")

    def test_parse_netease_video_html_author_only_matches_exhibit_author(self):
        """s-name inside exhibit-authors-info is matched; other s-name elements are ignored."""
        html = (
            "<html><head><title>作者范围测试</title></head><body>"
            '<div class="recommend"><div class="s-name">推荐视频作者</div></div>'
            '<div class="exhibit-authors-info">'
            '<div class="s-name">正确作者</div>'
            "</div>"
            '<video src="http://flv0.bn.netease.com/abc.m3u8"></video>'
            "</body></html>"
        )
        result = clip._parse_netease_video_html(html, "https://c.m.163.com/news/v/X.html")
        self.assertEqual(result["author"], "正确作者")

    def test_parse_netease_video_html_date_only_from_cover_url(self):
        """Date is parsed from cover URL, not from arbitrary HTML dates."""
        html = (
            "<html><head><title>日期范围测试</title></head><body>"
            '<div class="poster js-poster js-lazy" '
            'data-bg="http://videoimg.ws.126.net/cover/20261008/pPhI6QDFq_cover.jpg">'
            "</div>"
            '<a href="/news/v/20200101/xxxx.html">旧视频</a>'
            '<video src="http://flv0.bn.netease.com/abc.m3u8"></video>'
            "</body></html>"
        )
        result = clip._parse_netease_video_html(html, "https://c.m.163.com/news/v/X.html")
        self.assertEqual(result["published"], "2026-10-08")

    def test_run_extractor_with_fallback_falls_back_for_netease_video(self):
        """When Node.js fails on a Netease video URL, the video fallback is used."""
        mock_html = (
            "<html><head><title>Video Title</title></head><body>"
            '"nickname":"Author"'
            '<video src="http://flv0.bn.netease.com/v.m3u8"></video>'
            "</body></html>"
        )
        with mock.patch.object(clip, "run_extractor", side_effect=clip.ClipError("QUALITY_GATE")):
            with mock.patch.object(clip, "_fetch_netease_video_html", return_value=mock_html):
                result = clip.run_extractor_with_fallback(
                    Path("/plugin"), "https://c.m.163.com/news/sv/X.html"
                )
        self.assertEqual(result["title"], "Video Title")
        self.assertEqual(result["method"], "netease-video-curl")
        self.assertIn("v.m3u8", result["markdown"])


class VideoTagSanitizationTests(unittest.TestCase):
    def test_sanitize_markdown_preserves_safe_video_tag(self):
        md = (
            'before\n\n<video src="http://flv0.bn.netease.com/a.m3u8" '
            'controls preload="metadata" playsinline></video>\n\nafter'
        )
        out = clip.sanitize_markdown(md)
        self.assertIn("<video", out)
        self.assertIn("a.m3u8", out)
        self.assertIn("before", out)
        self.assertIn("after", out)

    def test_sanitize_markdown_rejects_javascript_video_src(self):
        out = clip.sanitize_markdown('<video src="javascript:alert(1)"></video>')
        self.assertNotIn("<video", out)
        self.assertIn("&lt;video", out)

    def test_sanitize_markdown_strips_video_event_handlers(self):
        md = '<video src="http://x.com/a.mp4" onerror="alert(1)"></video>'
        out = clip.sanitize_markdown(md)
        self.assertNotIn("onerror", out)
        self.assertIn("a.mp4", out)

    def test_sanitize_markdown_still_removes_dangerous_tags(self):
        out = clip.sanitize_markdown("<script>alert(1)</script>ok")
        self.assertNotIn("script", out)
        self.assertIn("ok", out)


class FavoriteMarkerTests(unittest.TestCase):
    """Frontmatter marker rendering, editing, and refresh semantics."""

    def _note(
        self,
        *,
        favorite: bool | None = None,
        markdown: str | None = None,
    ) -> str:
        created = "2026-07-23T12:00:00+00:00"
        if markdown is None:
            return clip.render_note(SUCCESS, created=created, favorite=favorite)
        return clip.render_note(
            SUCCESS, created=created, content_markdown=markdown, favorite=favorite
        )

    @staticmethod
    def _meta(note: str) -> dict[str, object]:
        metadata = clip._frontmatter_from_text(note)
        if metadata is None:
            raise AssertionError("note has no valid frontmatter")
        return metadata

    def test_render_note_omits_favorite_by_default(self):
        self.assertNotIn("favorite", self._meta(self._note()))

    def test_render_note_writes_favorite_after_original_host(self):
        note = self._note(favorite=True)
        frontmatter = note.split("\n---\n", 1)[0]
        lines = frontmatter.split("\n")
        host_index = lines.index("original_host: example.com")
        self.assertEqual(lines[host_index + 1], "favorite: true")
        self.assertIs(self._meta(note)["favorite"], True)

    def test_render_note_rejects_non_boolean_favorite(self):
        with self.assertRaises(clip.ClipError):
            clip.render_note(SUCCESS, favorite="yes")  # type: ignore[arg-type]

    def test_set_favorite_marker_adds_and_removes_the_key(self):
        note = self._note()
        marked, changed = clip._set_favorite_marker(note, True)
        self.assertTrue(changed)
        self.assertIs(self._meta(marked)["favorite"], True)
        self.assertIn("original_host: example.com\nfavorite: true\n", marked)

        cleared, changed = clip._set_favorite_marker(marked, False)
        self.assertTrue(changed)
        self.assertNotIn("favorite", self._meta(cleared))

    def test_set_favorite_marker_is_idempotent(self):
        marked, _ = clip._set_favorite_marker(self._note(), True)
        self.assertEqual(clip._set_favorite_marker(marked, True), (marked, False))
        cleared, _ = clip._set_favorite_marker(marked, False)
        self.assertEqual(clip._set_favorite_marker(cleared, False), (cleared, False))

    def test_set_favorite_marker_repositions_out_of_place_marker(self):
        note = self._note().replace("\n---\n", "\nfavorite: true\n---\n", 1)
        marked, changed = clip._set_favorite_marker(note, True)
        self.assertTrue(changed)
        lines = marked.split("\n---\n", 1)[0].split("\n")
        host_index = lines.index("original_host: example.com")
        self.assertEqual(lines[host_index + 1], "favorite: true")
        self.assertEqual(marked.count("favorite:"), 1)

    def test_set_favorite_marker_ignores_indented_original_host_lines(self):
        note = self._note().replace(
            "description: A useful page",
            "description: |-\n  first\n  original_host: not-a-key",
            1,
        )
        marked, changed = clip._set_favorite_marker(note, True)
        self.assertTrue(changed)
        lines = marked.split("\n---\n", 1)[0].split("\n")
        host_index = lines.index("original_host: example.com")
        self.assertEqual(lines[host_index + 1], "favorite: true")
        self.assertIn("  original_host: not-a-key", marked)

    def test_set_favorite_marker_only_touches_one_frontmatter_line(self):
        note = self._note().replace(
            "\n---\n", "\ncustom_field: 'keep  spacing'\n---\n", 1
        )
        body = note.split("\n---\n", 1)[1]
        marked, changed = clip._set_favorite_marker(note, True)
        self.assertTrue(changed)
        self.assertIn("custom_field: 'keep  spacing'", marked)
        self.assertEqual(marked.split("\n---\n", 1)[1], body)
        self.assertEqual(len(marked.split("\n")), len(note.split("\n")) + 1)

    def test_set_favorite_marker_normalizes_noncanonical_true(self):
        note = self._note().replace(
            "\n---\n", "\nfavorite: yes\n---\n", 1
        )
        marked, changed = clip._set_favorite_marker(note, True)
        self.assertTrue(changed)
        self.assertIn("original_host: example.com\nfavorite: true\n", marked)
        self.assertEqual(marked.count("favorite:"), 1)

    def test_set_favorite_marker_refuses_unmanaged_note(self):
        with self.assertRaises(clip.ClipError):
            clip._set_favorite_marker("---\ntitle: Mine\n---\n\nBody\n", True)

    def test_set_favorite_marker_refuses_webclip_id_without_boundaries(self):
        text = "---\ntitle: Mine\nwebclip_id: sha256:abc\n---\n\nBody\n"
        with self.assertRaises(clip.ClipError):
            clip._set_favorite_marker(text, True)

    def test_set_frontmatter_flag_refuses_missing_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(clip.ClipError):
                clip.set_frontmatter_flag(Path(tmp) / "absent.md", favorite=True)

    def test_favorite_only_change_does_not_require_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.md"
            target.write_text(self._note(), encoding="utf-8")
            self.assertEqual(
                clip.write_managed_note(target, self._note(favorite=True), refresh=False),
                "written",
            )
            self.assertIs(
                self._meta(target.read_text(encoding="utf-8"))["favorite"],
                True,
            )

    def test_favorite_change_preserves_the_manual_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.md"
            note = self._note().replace(
                "<!-- webclip:manual:start -->\n",
                "<!-- webclip:manual:start -->\nMY NOTES\n",
            )
            target.write_text(note, encoding="utf-8")
            clip.write_managed_note(target, self._note(favorite=True), refresh=False)
            updated = target.read_text(encoding="utf-8")
            self.assertIn("MY NOTES", updated)
            self.assertIs(self._meta(updated)["favorite"], True)

    def test_body_change_still_requires_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "note.md"
            target.write_text(self._note(), encoding="utf-8")
            changed = self._note(markdown="# An Article\n\nDifferent body\n")
            with self.assertRaisesRegex(clip.ClipError, "rerun with --refresh"):
                clip.write_managed_note(target, changed, refresh=False)

    def test_note_title_prefers_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "fallback.md"
            target.write_text(self._note(), encoding="utf-8")
            self.assertEqual(clip._note_title(target), "An Article")

    def test_user_message_describes_marker_actions(self):
        marked = clip.ClipResult(
            "Inbox/note.md", "committed", "pushed", None, "favorite"
        )
        cleared = clip.ClipResult(
            "Inbox/note.md", "committed", "pushed", None, "unfavorite"
        )
        self.assertTrue(marked.user_message().startswith("Marked clip as favorite:"))
        self.assertTrue(
            cleared.user_message().startswith(
                "Removed favorite marker from clip:"
            )
        )


class BatchClipServiceTests(unittest.TestCase):
    def _git(self, root, *args):
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _vault(self, tmp):
        root = Path(tmp)
        remote = root / "remote.git"
        repo = root / "vault"
        self._git(root, "init", "--bare", str(remote))
        self._git(root, "init", "-b", "master", str(repo))
        self._git(repo, "config", "user.name", "Clip Test")
        self._git(repo, "config", "user.email", "clip@example.invalid")
        self._git(repo, "remote", "add", "origin", str(remote))
        (repo / ".gitkeep").write_text("", encoding="utf-8")
        self._git(repo, "add", ".gitkeep")
        self._git(repo, "commit", "-m", "initial")
        self._git(repo, "push", "-u", "origin", "master")
        return root, repo

    def _service(self, root, repo):
        env = {
            "WEB_TO_OBSIDIAN_VAULT": str(repo),
            "WEB_TO_OBSIDIAN_DEST": "Inbox",
            "WEB_TO_OBSIDIAN_IMAGES": "images",
            "WEB_TO_OBSIDIAN_SYNC_BRANCH": "master",
            "WEB_TO_OBSIDIAN_LOCK_FILE": str(Path(root) / "vault.lock"),
            "WEB_TO_OBSIDIAN_PENDING_ROOT": str(Path(root) / "pending"),
        }
        return clip.ClipService(Path("."), env=env)

    @staticmethod
    def _payload(url, title):
        payload = dict(SUCCESS)
        payload["title"] = title
        payload["canonicalUrl"] = url
        payload["url"] = url
        return payload

    def _commit_count(self, repo):
        return int(
            self._git(repo, "rev-list", "--count", "HEAD").stdout.decode().strip()
        )

    def _commit_paths(self, repo, rev="HEAD"):
        raw = self._git(
            repo, "diff-tree", "--no-commit-id", "--name-only", "-z", "-r", rev
        ).stdout.decode()
        return {part for part in raw.split("\0") if part}

    @staticmethod
    def _note(repo, relative):
        return (repo / relative).read_text(encoding="utf-8")

    @staticmethod
    def _meta(text):
        start = text.index("---\n") + 4
        end = text.index("\n---\n", start)
        return yaml.safe_load(text[start:end])

    @staticmethod
    def _payload_with_image(url, title):
        payload = dict(SUCCESS)
        payload.update(
            {
                "title": title,
                "canonicalUrl": url,
                "url": url,
                "markdown": (
                    f"# {title}\r\n\r\n"
                    f"![shot](https://cdn.example.com/{title.lower()}.png)\r\n"
                ),
            }
        )
        return payload

    @staticmethod
    def _fake_download(url, directory, index):
        path = Path(directory) / f"image-{index}.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return path

    def _prepopulate(self, service, url, title, *, extra=""):
        """Clip one article up front so later specs can target an existing note."""
        payload = self._payload(url, title)
        spec = f"{url} --save-images no {extra}".strip()
        with mock.patch.object(
            clip,
            "run_extractor_with_fallback",
            side_effect=lambda plugin_root, u, no_browser=False: payload,
        ):
            result = service.run_batch([spec])
        self.assertTrue(result.items[0].ok, result.items[0].error)
        return result.items[0].path

    def test_writes_all_notes_in_a_single_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, repo = self._vault(tmp)
            service = self._service(root, repo)
            payloads = {
                "https://example.com/a": self._payload(
                    "https://example.com/a", "Alpha"
                ),
                "https://example.com/b": self._payload(
                    "https://example.com/b", "Beta"
                ),
            }

            def fake_extract(plugin_root, url, no_browser=False):
                return payloads[url]

            with mock.patch.object(
                clip, "run_extractor_with_fallback", side_effect=fake_extract
            ):
                result = service.run_batch(
                    [
                        "https://example.com/a --save-images no",
                        "https://example.com/b --save-images no",
                    ]
                )

            self.assertEqual(result.commit_state, "committed")
            self.assertEqual(result.push_state, "pushed")
            self.assertEqual([item.ok for item in result.items], [True, True])
            count = (
                self._git(repo, "rev-list", "--count", "HEAD")
                .stdout.decode()
                .strip()
            )
            self.assertEqual(count, "2")
            committed = (
                self._git(
                    repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
                )
                .stdout.decode()
                .split()
            )
            self.assertEqual(len(committed), 2)
            self.assertTrue(all(path.endswith(".md") for path in committed))

    def test_one_failure_does_not_block_the_other_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, repo = self._vault(tmp)
            service = self._service(root, repo)

            def fake_extract(plugin_root, url, no_browser=False):
                if url.endswith("/bad"):
                    raise clip.ClipError("blocked by test")
                return self._payload(url, "Good")

            with mock.patch.object(
                clip, "run_extractor_with_fallback", side_effect=fake_extract
            ):
                result = service.run_batch(
                    [
                        "https://example.com/bad --save-images no",
                        "https://example.com/good --save-images no",
                    ]
                )

            self.assertEqual([item.ok for item in result.items], [False, True])
            self.assertIn("blocked by test", result.items[0].error or "")
            committed = (
                self._git(
                    repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
                )
                .stdout.decode()
                .split()
            )
            self.assertEqual(len(committed), 1)

    def test_rejects_ambiguous_image_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, repo = self._vault(tmp)
            service = self._service(root, repo)
            with self.assertRaisesRegex(clip.ClipError, "--save-images"):
                service.run_batch(["https://example.com/a"])

    def test_rejects_mixed_no_git_setting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, repo = self._vault(tmp)
            service = self._service(root, repo)
            with self.assertRaisesRegex(clip.ClipError, "--no-git"):
                service.run_batch(
                    [
                        "https://example.com/a --save-images no",
                        "https://example.com/b --save-images no --no-git",
                    ]
                )


    def test_batch_applies_distinct_favorite_intents_per_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, repo = self._vault(tmp)
            service = self._service(root, repo)
            fav = "https://example.com/fav"
            plain = "https://example.com/plain"
            unfav = "https://example.com/unfav"
            payloads = {
                fav: self._payload(fav, "Fav"),
                plain: self._payload(plain, "Plain"),
                unfav: self._payload(unfav, "Unfav"),
            }

            with mock.patch.object(
                clip,
                "run_extractor_with_fallback",
                side_effect=lambda p, u, no_browser=False: payloads[u],
            ):
                result = service.run_batch(
                    [
                        f"{fav} --save-images no --favorite",
                        f"{plain} --save-images no",
                        f"{unfav} --save-images no --unfavorite",
                    ]
                )

            self.assertEqual([item.ok for item in result.items], [True, True, True])
            self.assertEqual(self._commit_count(repo), 2)
            self.assertEqual(len(self._commit_paths(repo)), 3)
            self.assertIs(
                self._meta(self._note(repo, result.items[0].path))["favorite"], True
            )
            self.assertNotIn(
                "favorite", self._meta(self._note(repo, result.items[1].path))
            )
            self.assertNotIn(
                "favorite", self._meta(self._note(repo, result.items[2].path))
            )

    def test_batch_mixes_marker_only_with_new_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, repo = self._vault(tmp)
            service = self._service(root, repo)
            old = "https://example.com/old"
            new = "https://example.com/new"
            self._prepopulate(service, old, "Old")
            payload = self._payload(new, "New")

            with mock.patch.object(
                clip,
                "run_extractor_with_fallback",
                side_effect=lambda p, u, no_browser=False: payload,
            ):
                result = service.run_batch(
                    [f"{old} --favorite-only", f"{new} --save-images no"]
                )

            self.assertEqual([item.ok for item in result.items], [True, True])
            self.assertEqual(
                [item.action for item in result.items], ["favorite", "clip"]
            )
            self.assertEqual(len(self._commit_paths(repo)), 2)
            self.assertIs(
                self._meta(self._note(repo, result.items[0].path))["favorite"], True
            )

    def test_batch_skips_an_unchanged_marker_from_the_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, repo = self._vault(tmp)
            service = self._service(root, repo)
            old = "https://example.com/old"
            new = "https://example.com/new"
            self._prepopulate(service, old, "Old", extra="--favorite")
            before = self._commit_count(repo)
            payload = self._payload(new, "New")

            with mock.patch.object(
                clip,
                "run_extractor_with_fallback",
                side_effect=lambda p, u, no_browser=False: payload,
            ):
                result = service.run_batch(
                    [f"{old} --favorite-only", f"{new} --save-images no"]
                )

            self.assertEqual([item.ok for item in result.items], [True, True])
            self.assertEqual(self._commit_count(repo), before + 1)
            self.assertEqual(self._commit_paths(repo), {result.items[1].path})

    def test_batch_marker_only_missing_note_fails_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, repo = self._vault(tmp)
            service = self._service(root, repo)
            missing = "https://example.com/missing"
            new = "https://example.com/new"
            payload = self._payload(new, "New")

            with mock.patch.object(
                clip,
                "run_extractor_with_fallback",
                side_effect=lambda p, u, no_browser=False: payload,
            ):
                result = service.run_batch(
                    [f"{missing} --favorite-only", f"{new} --save-images no"]
                )

            self.assertEqual([item.ok for item in result.items], [False, True])
            self.assertIn("No clipped note", result.items[0].error or "")
            self.assertEqual(self._commit_paths(repo), {result.items[1].path})

    def test_batch_mixes_local_and_remote_image_policies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, repo = self._vault(tmp)
            service = self._service(root, repo)
            local = "https://example.com/local"
            remote = "https://example.com/remote"
            payloads = {
                local: self._payload_with_image(local, "Local"),
                remote: self._payload_with_image(remote, "Remote"),
            }

            with mock.patch.object(
                clip,
                "run_extractor_with_fallback",
                side_effect=lambda p, u, no_browser=False: payloads[u],
            ), mock.patch.object(
                clip, "download_remote_image", side_effect=self._fake_download
            ):
                result = service.run_batch(
                    [f"{local} --save-images yes", f"{remote} --save-images no"]
                )

            self.assertTrue(
                all(item.ok for item in result.items),
                [item.error for item in result.items],
            )
            paths = self._commit_paths(repo)
            self.assertEqual(len(paths), 3)
            self.assertEqual(len([p for p in paths if p.endswith(".png")]), 1)
            self.assertEqual(
                self._meta(self._note(repo, result.items[0].path))["image_mode"],
                "local",
            )
            self.assertEqual(
                self._meta(self._note(repo, result.items[1].path))["image_mode"],
                "remote",
            )

    def test_batch_all_no_git_writes_files_without_a_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, repo = self._vault(tmp)
            service = self._service(root, repo)
            alpha = "https://example.com/alpha"
            beta = "https://example.com/beta"
            payloads = {
                alpha: self._payload(alpha, "Alpha"),
                beta: self._payload(beta, "Beta"),
            }
            before = self._commit_count(repo)

            with mock.patch.object(
                clip,
                "run_extractor_with_fallback",
                side_effect=lambda p, u, no_browser=False: payloads[u],
            ):
                result = service.run_batch(
                    [
                        f"{alpha} --save-images no --no-git",
                        f"{beta} --save-images no --no-git",
                    ]
                )

            self.assertEqual(result.commit_state, "disabled")
            self.assertEqual(result.push_state, "disabled")
            self.assertEqual([item.ok for item in result.items], [True, True])
            self.assertEqual(self._commit_count(repo), before)
            self.assertEqual(len(list((repo / "Inbox").iterdir())), 2)

    def test_batch_applies_no_browser_only_to_its_own_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, repo = self._vault(tmp)
            service = self._service(root, repo)
            headless = "https://example.com/headless"
            rendered = "https://example.com/rendered"
            seen = {}

            def fake_extract(plugin_root, url, no_browser=False):
                seen[url] = no_browser
                return self._payload(url, url.rsplit("/", 1)[-1].title())

            with mock.patch.object(
                clip, "run_extractor_with_fallback", side_effect=fake_extract
            ):
                service.run_batch(
                    [
                        f"{headless} --save-images no --no-browser",
                        f"{rendered} --save-images no",
                    ]
                )

            self.assertIs(seen[headless], True)
            self.assertIs(seen[rendered], False)

    def test_batch_uses_the_supplied_commit_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, repo = self._vault(tmp)
            service = self._service(root, repo)
            alpha = "https://example.com/alpha"
            beta = "https://example.com/beta"
            payloads = {
                alpha: self._payload(alpha, "Alpha"),
                beta: self._payload(beta, "Beta"),
            }

            with mock.patch.object(
                clip,
                "run_extractor_with_fallback",
                side_effect=lambda p, u, no_browser=False: payloads[u],
            ):
                result = service.run_batch(
                    [
                        f"{alpha} --save-images no",
                        f"{beta} --save-images no",
                    ],
                    commit_message="clip: custom batch subject",
                )

            self.assertEqual(result.commit_state, "committed")
            subject = (
                self._git(repo, "log", "-1", "--pretty=%s").stdout.decode().strip()
            )
            self.assertEqual(subject, "clip: custom batch subject")

    def test_batch_requires_refresh_only_for_the_changed_article(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, repo = self._vault(tmp)
            service = self._service(root, repo)
            changed = "https://example.com/changed"
            added = "https://example.com/added"
            self._prepopulate(service, changed, "Changed")
            updated = self._payload(changed, "Changed")
            updated["markdown"] = "# Changed\r\n\r\nUpdated body\r\n"
            payloads = {changed: updated, added: self._payload(added, "Added")}

            with mock.patch.object(
                clip,
                "run_extractor_with_fallback",
                side_effect=lambda p, u, no_browser=False: payloads[u],
            ):
                blocked = service.run_batch(
                    [f"{changed} --save-images no", f"{added} --save-images no"]
                )

            self.assertEqual([item.ok for item in blocked.items], [False, True])
            self.assertIn("--refresh", blocked.items[0].error or "")
            self.assertEqual(self._commit_paths(repo), {blocked.items[1].path})

            with mock.patch.object(
                clip,
                "run_extractor_with_fallback",
                side_effect=lambda p, u, no_browser=False: payloads[u],
            ):
                refreshed = service.run_batch(
                    [f"{changed} --save-images no --refresh"]
                )

            self.assertTrue(refreshed.items[0].ok, refreshed.items[0].error)
            self.assertIn(
                "Updated body", self._note(repo, refreshed.items[0].path)
            )

    def test_batch_unfavorite_only_removes_an_existing_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, repo = self._vault(tmp)
            service = self._service(root, repo)
            url = "https://example.com/old"
            self._prepopulate(service, url, "Old", extra="--favorite")

            result = service.run_batch([f"{url} --unfavorite-only"])

            self.assertTrue(result.items[0].ok, result.items[0].error)
            self.assertEqual(result.items[0].action, "unfavorite")
            self.assertNotIn("favorite: true", self._note(repo, result.items[0].path))
            self.assertEqual(self._commit_paths(repo), {result.items[0].path})

    def test_batch_combines_marker_updates_and_new_clips(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, repo = self._vault(tmp)
            service = self._service(root, repo)
            keep = "https://example.com/keep"
            drop = "https://example.com/drop"
            fresh = "https://example.com/fresh"
            gone = "https://example.com/gone"
            self._prepopulate(service, keep, "Keep")
            self._prepopulate(service, drop, "Drop", extra="--favorite")
            before = self._commit_count(repo)
            payload = self._payload(fresh, "Fresh")

            with mock.patch.object(
                clip,
                "run_extractor_with_fallback",
                side_effect=lambda p, u, no_browser=False: payload,
            ):
                result = service.run_batch(
                    [
                        f"{keep} --favorite-only",
                        f"{drop} --unfavorite-only",
                        f"{fresh} --save-images no",
                        f"{gone} --favorite-only",
                    ]
                )

            self.assertEqual(
                [item.ok for item in result.items], [True, True, True, False]
            )
            self.assertEqual(
                [item.action for item in result.items[:3]],
                ["favorite", "unfavorite", "clip"],
            )
            self.assertIn("No clipped note", result.items[3].error or "")
            self.assertEqual(self._commit_count(repo), before + 1)
            self.assertEqual(len(self._commit_paths(repo)), 3)
            self.assertIs(
                self._meta(self._note(repo, result.items[0].path))["favorite"], True
            )
            self.assertNotIn(
                "favorite", self._meta(self._note(repo, result.items[1].path))
            )


if __name__ == "__main__":
    unittest.main()

