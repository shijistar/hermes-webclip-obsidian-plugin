"""Destination resolution, ignore rules and file naming."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from _webclip.core import ClipError
from _webclip.video import store as store_module
from _webclip.video.naming import build_filename, extension_for, unique_path
from _webclip.video.store import (
    BLOCK_END,
    BLOCK_START,
    commit_gitignore,
    ensure_gitignore,
    resolve_destination,
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=Test", *args],
        capture_output=True,
        text=True,
    )


class DestinationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.vault = self.root / "vault"
        (self.vault / "attachments").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_relative_path_is_inside_the_vault(self):
        destination = resolve_destination(self.vault, "attachments/video")
        self.assertTrue(destination.inside_vault)
        self.assertEqual(destination.directory, self.vault / "attachments" / "video")

    def test_absolute_path_outside_the_vault_is_outside(self):
        destination = resolve_destination(self.vault, str(self.root / "Videos"))
        self.assertFalse(destination.inside_vault)

    def test_tilde_expansion_outside_the_vault_stays_outside(self):
        destination = resolve_destination(self.vault, "~/Movies/Videos/webclip")
        self.assertFalse(destination.inside_vault)

    def test_an_absolute_path_inside_the_vault_counts_as_inside(self):
        # The old rule ("absolute means outside") got this case wrong.
        configured = str(self.vault / "attachments" / "video")
        destination = resolve_destination(self.vault, configured)
        self.assertTrue(destination.inside_vault)

    def test_a_relative_destination_escaping_through_a_symlink_is_rejected(self):
        # A relative destination is defined as vault-contained: following a link
        # out of the vault would write outside while the config claims otherwise,
        # and the managed ignore block could never cover those files.
        outside = self.root / "elsewhere"
        outside.mkdir()
        (self.vault / "linked").symlink_to(outside)
        with self.assertRaises(ClipError):
            resolve_destination(self.vault, "linked/video")

    def test_an_absolute_destination_through_a_symlink_stays_outside(self):
        outside = self.root / "elsewhere"
        outside.mkdir()
        (self.vault / "linked").symlink_to(outside)
        destination = resolve_destination(self.vault, str(self.vault / "linked" / "video"))
        self.assertFalse(destination.inside_vault)


class GitignoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.vault = self.root / "vault"
        (self.vault / "attachments" / "video").mkdir(parents=True)
        _git(self.vault, "init", "-q")
        # The plugin commits on its own (no `-c`), so the repo needs a local
        # identity: newer git refuses to invent `user@hostname`.
        _git(self.vault, "config", "user.email", "t@example.com")
        _git(self.vault, "config", "user.name", "Test")
        _git(self.vault, "commit", "--allow-empty", "-q", "-m", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_block_is_created_with_the_resolved_entry(self):
        self.assertTrue(ensure_gitignore(self.vault, self.vault / "attachments" / "video"))
        text = (self.vault / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(BLOCK_START, text)
        self.assertIn("/attachments/video/", text)
        self.assertIn(BLOCK_END, text)

    def test_a_second_run_changes_nothing(self):
        ensure_gitignore(self.vault, self.vault / "attachments" / "video")
        first = (self.vault / ".gitignore").read_text(encoding="utf-8")
        self.assertFalse(ensure_gitignore(self.vault, self.vault / "attachments" / "video"))
        self.assertEqual((self.vault / ".gitignore").read_text(encoding="utf-8"), first)

    def test_glob_characters_in_the_directory_name_are_escaped(self):
        # `clips[2026]` is a literal name, not a pattern: unescaped, the rule
        # matches a different directory (or nothing) and the files stay untracked.
        (self.vault / "clips[2026]").mkdir(parents=True)
        ensure_gitignore(self.vault, self.vault / "clips[2026]")
        text = (self.vault / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/clips\\[2026\\]/", text)

    def test_a_second_destination_is_added_without_losing_the_first(self):
        # Videos already downloaded into the first directory must stay ignored:
        # dropping the old entry would make them untracked again and the next
        # /webclip would refuse to run.
        (self.vault / ".gitignore").write_text("node_modules\n", encoding="utf-8")
        ensure_gitignore(self.vault, self.vault / "attachments" / "video")
        (self.vault / "other").mkdir()
        ensure_gitignore(self.vault, self.vault / "other")
        text = (self.vault / ".gitignore").read_text(encoding="utf-8")
        self.assertEqual(text.count(BLOCK_START), 1)
        self.assertIn("/other/", text)
        self.assertIn("/attachments/video/", text)
        self.assertIn("node_modules", text)

    def test_the_vault_root_is_refused_as_a_destination(self):
        with self.assertRaises(ClipError):
            ensure_gitignore(self.vault, self.vault)

    def test_committing_only_the_gitignore_leaves_a_clean_tree(self):
        ensure_gitignore(self.vault, self.vault / "attachments" / "video")
        self.assertTrue(commit_gitignore(self.vault))
        status = _git(self.vault, "status", "--porcelain=v1")
        self.assertEqual(status.stdout.strip(), "")

    def test_committing_is_refused_when_other_changes_exist(self):
        ensure_gitignore(self.vault, self.vault / "attachments" / "video")
        (self.vault / "notes.md").write_text("work in progress", encoding="utf-8")
        with self.assertRaises(ClipError):
            commit_gitignore(self.vault)


class NamingTests(unittest.TestCase):
    def test_an_explicit_name_wins(self):
        name = build_filename(title="Title", src="https://cdn/a.m3u8", name="My clip")
        self.assertEqual(name, "My clip.mp4")

    def test_the_title_is_used_when_no_name_is_given(self):
        name = build_filename(title="如果黄仁勋来中国公司面试", src="https://cdn/a.m3u8")
        self.assertEqual(name, "如果黄仁勋来中国公司面试.mp4")

    def test_a_hash_is_the_last_resort(self):
        name = build_filename(title="", src="https://cdn/e25593ed.m3u8")
        self.assertTrue(name.endswith(".mp4"))
        self.assertNotIn("/", name)
        self.assertGreater(len(name), 5)

    def test_forbidden_characters_are_removed(self):
        name = build_filename(title='a/b:c*d?e"f<g>h|i', src="https://cdn/a.mp4")
        for char in '/:*?"<>|':
            self.assertNotIn(char, name)
        self.assertTrue(name.endswith(".mp4"))

    def test_multiple_files_get_a_numeric_suffix(self):
        name = build_filename(title="Clip", src="https://cdn/a.mp4", index=2)
        self.assertEqual(name, "Clip-2.mp4")

    def test_the_extension_follows_the_container(self):
        self.assertEqual(extension_for("video/webm", "https://cdn/a"), ".webm")
        self.assertEqual(extension_for("application/x-mpegURL", "https://cdn/a.m3u8"), ".mp4")
        self.assertEqual(extension_for("", "https://cdn/a.mkv"), ".mkv")
        self.assertEqual(extension_for("", "https://cdn/stream"), ".mp4")

    def test_the_suffix_is_counted_against_the_byte_budget(self):
        name = build_filename(title="长" * 200, src="https://cdn/a.mp4", index=1)
        self.assertLessEqual(len(name.encode("utf-8")), 180)

    def test_an_empty_name_is_rejected(self):
        with self.assertRaises(ValueError):
            build_filename(title="", src="https://cdn/a.mp4", name="///")

    def test_a_page_declared_subtype_outside_the_video_set_is_ignored(self):
        # The subtype is page text; `video/md` would otherwise save a `.md` file
        # that looks like a note inside the vault.
        for declared in ("video/exe", "video/md", "video/html", "video/" + "a" * 300):
            with self.subTest(declared=declared[:24]):
                self.assertEqual(extension_for(declared, "https://cdn/a.mp4"), ".mp4")
        self.assertEqual(extension_for("video/webm", "https://cdn/a.jpg"), ".webm")

    def test_unique_path_avoids_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "Clip.mp4").write_bytes(b"x")
            self.assertEqual(unique_path(directory, "Clip.mp4").name, "Clip-1.mp4")
            self.assertEqual(
                unique_path(directory, "Clip.mp4", overwrite=True).name, "Clip.mp4"
            )


class GitErrorTests(unittest.TestCase):
    """The plugin commits without `-c`, so identity errors reach the user."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.vault.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_missing_identity_is_reported_actionably(self):
        # git >=2.5x refuses to invent `user@hostname`; the old generic message
        # left the user with no idea what to configure.
        result = mock.Mock(
            returncode=1,
            stdout=b"",
            stderr=b"fatal: no email was given and auto-detection is disabled",
        )
        with mock.patch.object(store_module, "_run_bounded", return_value=result):
            with self.assertRaises(ClipError) as caught:
                store_module._git(self.vault, "commit", "-m", "x")
        self.assertIn("user.name", str(caught.exception))
        self.assertNotIn("A Git command failed", str(caught.exception))

    def test_other_failures_carry_the_git_detail(self):
        result = mock.Mock(
            returncode=1, stdout=b"", stderr=b"fatal: something odd happened"
        )
        with mock.patch.object(store_module, "_run_bounded", return_value=result):
            with self.assertRaises(ClipError) as caught:
                store_module._git(self.vault, "status")
        self.assertIn("something odd happened", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
