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


def register(ctx) -> None:
    from .web_to_obsidian import (
        build_handler,
        build_resume_tool,
        read_skill_description,
    )

    plugin_root = Path(__file__).resolve().parent
    handler = build_handler(plugin_root)
    ctx.register_command(
        "webclip",
        handler=handler,
        description="Clip a public web article into an Obsidian vault with guarded Git sync.",
        args_hint="<url|webclip_id> [--refresh] [--no-browser] [--no-git] [--save-images yes|no|ask] [--favorite|--unfavorite]",
    )
    # The skill ships inside the plugin package and is registered here rather than
    # through a profile-level symlink: one copy, no drift between a profile path and
    # the source repo. A missing skill/ directory must not take the /webclip command
    # down with it, so this degrades to "no skill" instead of raising.
    skill_md = plugin_root / "skill" / "SKILL.md"
    try:
        ctx.register_skill(
            "web-clip-to-obsidian",
            skill_md,
            description=read_skill_description(skill_md),
        )
    except Exception as exc:  # FileNotFoundError, or an older ctx without register_skill
        # Keep the traceback: a bare message cannot distinguish "skill/ is missing"
        # from a real API mismatch (TypeError) that needs fixing.
        logger.warning(
            "web-clip-to-obsidian skill registration skipped: %s", exc, exc_info=True
        )

    ctx.register_tool(
        name="web_to_obsidian_resume_pending",
        toolset="web_to_obsidian",
        schema=_RESUME_PENDING_SCHEMA,
        handler=build_resume_tool(plugin_root),
        emoji="🖼️",
    )
