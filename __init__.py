"""Hermes registration for the standalone webclip-obsidian plugin."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# NOTE: submodule imports stay inside register() on purpose. Hermes loads this
# package via spec_from_file_location with a proper __package__, so relative
# imports work at register time; but a bare `import <repo>` from pytest or a
# REPL has no package context and must not fail while merely importing this
# module (the repo root doubles as the root package directory).
_RESUME_PENDING_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["yes", "no"],
            "description": "yes to download remote article images into the vault; no to keep remote image URLs.",
        }
    },
    "required": ["decision"],
    "additionalProperties": False,
}

# Both skills ship inside the plugin package and are registered here, so the
# package holds the only copy. The name is the registration name; the path is
# where the file lives.
_SKILLS = (
    ("web-clip-to-obsidian", "skills/web-clip-to-obsidian/SKILL.md"),
    ("web-save-video", "skills/web-save-video/SKILL.md"),
)


def register(ctx) -> None:
    from .web_to_obsidian import (
        build_handler,
        build_resume_tool,
        read_skill_frontmatter,
    )
    plugin_root = Path(__file__).resolve().parent
    handler = build_handler(plugin_root)
    ctx.register_command(
        "webclip",
        handler=handler,
        description="Clip a public web article into an Obsidian vault with guarded Git sync.",
        args_hint="<url|webclip_id> [--refresh] [--no-browser] [--no-git] [--save-images yes|no|ask] [--favorite|--unfavorite]",
    )
    # The video subsystem is imported here, inside its own guard: a broken or
    # partially installed `_webclip/video` package must cost the /save-video
    # command only, exactly like a broken skill costs its own registration.
    try:
        # Absolute import on purpose: web_to_obsidian has just registered
        # `_webclip` in sys.modules, and importing through that same entry keeps
        # one ClipError class for the whole plugin.
        from _webclip.video.service import build_handler as build_video_handler

        ctx.register_command(
            "save-video",
            handler=build_video_handler(plugin_root),
            description="Download the video(s) on a page to local disk, outside the vault by default.",
            args_hint="<url> [<url> ...] [--name <name>] [--to <dir>] [--overwrite] [--no-browser]",
        )
    except Exception as exc:
        logger.warning(
            "save-video command registration skipped: %s", exc, exc_info=True
        )
    # A broken skill must not take the commands down with it: each registration
    # degrades to "no skill" on its own.
    for skill_name, relative_path in _SKILLS:
        skill_md = plugin_root / relative_path
        try:
            frontmatter = read_skill_frontmatter(skill_md)
            ctx.register_skill(
                skill_name,
                skill_md,
                description=str(frontmatter.get("description") or "").strip(),
                frontmatter=frontmatter,
            )
        except Exception as exc:  # FileNotFoundError, or an older ctx without register_skill
            # Keep the traceback: a bare message cannot distinguish "the file is
            # missing" from a real API mismatch (TypeError) that needs fixing.
            logger.warning("%s skill registration skipped: %s", skill_name, exc, exc_info=True)

    ctx.register_tool(
        name="web_to_obsidian_resume_pending",
        toolset="web_to_obsidian",
        schema=_RESUME_PENDING_SCHEMA,
        handler=build_resume_tool(plugin_root),
        emoji="🖼️",
    )
