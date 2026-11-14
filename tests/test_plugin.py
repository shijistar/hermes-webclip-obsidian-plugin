import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

import web_to_obsidian as clip


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
    def _load_plugin(self):
        spec = importlib.util.spec_from_file_location(
            "web_to_obsidian_plugin",
            ROOT / "__init__.py",
            submodule_search_locations=[str(ROOT)],
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

    def test_registers_webclip_with_documented_hint_and_closed_over_handler(self):
        plugin = self._load_plugin()
        context = FakeContext()
        plugin.register(context)

        self.assertEqual(len(context.command_calls), 1)
        args, kwargs = context.command_calls[0]
        self.assertEqual(args, ("webclip",))
        self.assertEqual(
            kwargs["args_hint"],
            "<url|webclip_id> [--refresh] [--no-browser] [--no-git] "
            "[--save-images yes|no|ask] [--favorite|--unfavorite]",
        )
        self.assertIn("Obsidian", kwargs["description"])
        self.assertTrue(callable(kwargs["handler"]))
        self.assertEqual(len(context.tool_calls), 1)
        self.assertEqual(
            context.tool_calls[0]["name"], "web_to_obsidian_resume_pending"
        )

    def test_registers_the_skill_under_the_plugin_namespace(self):
        plugin = self._load_plugin()
        context = FakeContext()
        plugin.register(context)

        self.assertEqual(len(context.skill_calls), 1)
        args, kwargs = context.skill_calls[0]
        self.assertEqual(args[0], "web-clip-to-obsidian")
        skill_md = args[1]                      # path is the second positional arg
        self.assertEqual(skill_md.name, "SKILL.md")
        self.assertEqual(skill_md.parent.name, "skill")
        self.assertTrue(skill_md.is_file())
        # The description must come from the file, not a second hardcoded string.
        head = skill_md.read_text(encoding="utf-8-sig")
        self.assertIn(kwargs["description"], head)
        self.assertIn("Obsidian", kwargs["description"])
        # frontmatter travels with the registration so Hermes can apply the file's
        # platform/condition gates instead of seeing an empty mapping.
        self.assertEqual(kwargs["frontmatter"]["name"], "web-clip-to-obsidian")
        self.assertEqual(kwargs["frontmatter"]["description"], kwargs["description"])
        self.assertIn("version", kwargs["frontmatter"])

    def test_failed_skill_registration_keeps_the_command_registered(self):
        plugin = self._load_plugin()
        context = FakeContext()
        context.skill_error = FileNotFoundError("no SKILL.md")
        plugin.register(context)

        self.assertEqual(len(context.command_calls), 1)   # /webclip still there
        self.assertEqual(len(context.tool_calls), 1)      # the resume tool too
        self.assertEqual(context.skill_calls, [])         # skill dropped, not fatal

    def test_handler_never_propagates_and_does_not_expose_exception_details(self):
        with mock.patch.object(clip.ClipService, "run", side_effect=RuntimeError("SECRET stack")):
            response = clip.build_handler(ROOT)("https://example.com --no-git")
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
            mock.patch.object(clip, "parse_clip_args", return_value=options),
            mock.patch.object(clip.ClipConfig, "from_file", return_value=config),
            mock.patch.object(clip, "VaultLock", return_value=mock.MagicMock()),
            mock.patch.object(
                clip.GitSync,
                "preflight",
                side_effect=lambda vault, branch: order.append("preflight") or mock.Mock(),
            ),
            mock.patch.object(
                clip,
                "run_extractor",
                side_effect=lambda *a, **k: order.append("extractor") or {},
            ),
            mock.patch.object(clip, "render_note", side_effect=clip.ClipError("stop")),
        ):
            with self.assertRaises(clip.ClipError):
                clip.ClipService(ROOT).run("https://example.com")
        self.assertEqual(order, ["preflight", "extractor"])


if __name__ == "__main__":
    unittest.main()