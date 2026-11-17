import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import web_to_obsidian as clip
from _webclip import service as service_module
from _webclip import sites as sites_module


# Tests live next to the plugin package: tests/ → repo root
ROOT = Path(__file__).resolve().parents[1]


class FakeContext:
    def __init__(self):
        self.command_calls = []
        self.tool_calls = []
        self.skill_calls = []
        self.skill_error: BaseException | None = None   # inject a registration failure

    def register_command(self, *args, **kwargs):
        self.command_calls.append((args, kwargs))

    def register_tool(self, **kwargs):
        self.tool_calls.append(kwargs)

    def register_skill(self, *args, **kwargs):
        if self.skill_error is not None:
            raise self.skill_error
        self.skill_calls.append((args, kwargs))


class PluginRegistrationTests(unittest.TestCase):
    def _load_plugin(self, root: Path = ROOT):
        spec = importlib.util.spec_from_file_location(
            "web_to_obsidian_plugin",
            root / "__init__.py",
            submodule_search_locations=[str(root)],
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        # Keep the package registered until the test finishes: __init__.py
        # resolves `from .web_to_obsidian import ...` lazily inside
        # register(), so the package name must still be importable when the
        # test calls plugin.register(...).
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        return module

    def test_registers_both_commands_with_documented_hints(self):
        plugin = self._load_plugin()
        context = FakeContext()
        plugin.register(context)

        self.assertEqual(
            [call[0][0] for call in context.command_calls], ["webclip", "save-video"]
        )
        webclip = context.command_calls[0][1]
        self.assertEqual(
            webclip["args_hint"],
            "<url|webclip_id> [--refresh] [--no-browser] [--no-git] "
            "[--save-images yes|no|ask] [--favorite|--unfavorite]",
        )
        self.assertIn("Obsidian", webclip["description"])
        self.assertTrue(callable(webclip["handler"]))

        video = context.command_calls[1][1]
        self.assertEqual(
            video["args_hint"],
            "<url> [<url> ...] [--name <name>] [--to <dir>] [--overwrite] [--no-browser]",
        )
        self.assertIn("video", video["description"].lower())
        self.assertTrue(callable(video["handler"]))

        self.assertEqual(len(context.tool_calls), 1)
        self.assertEqual(
            context.tool_calls[0]["name"], "web_to_obsidian_resume_pending"
        )

    def test_registers_both_skills_under_the_plugin_namespace(self):
        plugin = self._load_plugin()
        context = FakeContext()
        plugin.register(context)

        self.assertEqual(len(context.skill_calls), 2)
        registered = {call[0][0]: call for call in context.skill_calls}
        self.assertEqual(
            set(registered), {"web-clip-to-obsidian", "web-save-video"}
        )
        for name, (args, kwargs) in registered.items():
            skill_md = args[1]                  # path is the second positional arg
            self.assertEqual(skill_md.name, "SKILL.md")
            # skills/<name>/SKILL.md — the directory carries the registration name
            self.assertEqual(skill_md.parent.name, name)
            self.assertEqual(skill_md.parent.parent.name, "skills")
            self.assertTrue(skill_md.is_file())
            # The description must come from the file, not a second hardcoded string.
            head = skill_md.read_text(encoding="utf-8-sig")
            self.assertIn(kwargs["description"], head)
            self.assertEqual(kwargs["frontmatter"]["name"], name)
            self.assertEqual(kwargs["frontmatter"]["description"], kwargs["description"])
            self.assertIn("version", kwargs["frontmatter"])

        self.assertIn("Obsidian", registered["web-clip-to-obsidian"][1]["description"])
        self.assertIn("video", registered["web-save-video"][1]["description"].lower())

    def test_failed_skill_registration_keeps_both_commands_registered(self):
        plugin = self._load_plugin()
        context = FakeContext()
        context.skill_error = FileNotFoundError("no SKILL.md")
        plugin.register(context)

        self.assertEqual(len(context.command_calls), 2)   # both commands survive
        self.assertEqual(len(context.tool_calls), 1)      # the resume tool too
        self.assertEqual(context.skill_calls, [])         # skills dropped, not fatal

    def test_a_damaged_skill_file_does_not_take_the_commands_down(self):
        # Invalid UTF-8 raises UnicodeDecodeError, which is not an OSError: reading
        # the frontmatter must not escape register() and drop the commands with it.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy(ROOT / "__init__.py", root / "__init__.py")
            shutil.copy(ROOT / "web_to_obsidian.py", root / "web_to_obsidian.py")
            shutil.copytree(ROOT / "skills", root / "skills")
            (root / "skills" / "web-save-video" / "SKILL.md").write_bytes(
                b"---\nname: \xff\xfe\n---\n"
            )
            plugin = self._load_plugin(root)
            context = FakeContext()
            plugin.register(context)

        self.assertEqual(len(context.command_calls), 2)   # both commands still there
        self.assertEqual(len(context.tool_calls), 1)      # the resume tool too
        self.assertEqual(len(context.skill_calls), 2)     # damaged one degrades to {}
        damaged = [call for call in context.skill_calls if call[0][0] == "web-save-video"]
        self.assertEqual(damaged[0][1]["frontmatter"], {})
        self.assertEqual(damaged[0][1]["description"], "")

    def test_handler_never_propagates_and_does_not_expose_exception_details(self):
        with mock.patch.object(clip.ClipService, "run", side_effect=RuntimeError("SECRET stack")):
            response = clip.build_handler(ROOT)("https://example.com --no-git")
        self.assertIn("failed", response.lower())
        self.assertNotIn("SECRET", response)
        self.assertNotIn("RuntimeError", response)

    def test_video_handler_never_propagates_and_does_not_expose_exception_details(self):
        from _webclip.video import service as video_service

        with mock.patch.object(
            video_service.VideoService, "run", side_effect=RuntimeError("SECRET stack")
        ):
            response = video_service.build_handler(ROOT)("https://example.com")
        self.assertIn("failed", response.lower())
        self.assertNotIn("SECRET", response)
        self.assertNotIn("RuntimeError", response)

    def test_git_preflight_happens_before_extractor(self):
        config = mock.Mock()
        options = clip.ClipOptions("https://example.com", False, False, False)
        config.vault = Path("/tmp/vault")
        config.sync_branch = "master"
        config.lock_file = Path("/tmp/test-webclip-obsidian.lock")
        order = []
        with (
            mock.patch.object(service_module, "parse_clip_args", return_value=options),
            mock.patch.object(clip.ClipConfig, "from_file", return_value=config),
            mock.patch.object(service_module, "VaultLock", return_value=mock.MagicMock()),
            mock.patch.object(
                clip.GitSync,
                "preflight",
                side_effect=lambda vault, branch: order.append("preflight") or mock.Mock(),
            ),
            mock.patch.object(
                sites_module,
                "run_extractor",
                side_effect=lambda *a, **k: order.append("extractor") or {},
            ),
            mock.patch.object(service_module, "render_note", side_effect=clip.ClipError("stop")),
        ):
            with self.assertRaises(clip.ClipError):
                clip.ClipService(ROOT).run("https://example.com")
        self.assertEqual(order, ["preflight", "extractor"])


if __name__ == "__main__":
    unittest.main()
