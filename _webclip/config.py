"""Options, configuration loading and argument parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import os
import shlex
import tomllib

from .core import ClipError, _SAFE_BRANCH_NAME
from .paths import _resolve_vault_path
from .urls import _normalize_preview_url_params, _parse_target_selector, _validate_http_url

@dataclass(frozen=True)
class ClipOptions:
    # A URL, or a sha256 selector (``sha256:<hex>``) naming a clipped note.
    selector: str
    no_browser: bool
    no_git: bool
    refresh: bool
    save_images: str = "ask"
    # None means "not specified": an existing note keeps its current marker.
    favorite: bool | None = None
    # "url" extracts the page; "webclip_id" can only mark an existing note.
    target_kind: str = "url"
    # The bare 64-hex digest when target_kind == "webclip_id".
    target_hash: str | None = None


@dataclass(frozen=True)
class ClipConfig:
    vault: Path
    destination: Path
    images: Path
    sync_branch: str
    lock_file: Path
    pending_root: Path
    preview_url_params: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ClipConfig":
        values = os.environ if env is None else env
        vault = Path(
            values.get("WEB_TO_OBSIDIAN_VAULT", "~/obsidian/shijistar")
        ).expanduser().resolve()
        if not vault.is_dir():
            raise ClipError("The configured Obsidian vault does not exist.")

        destination = _resolve_vault_path(
            vault, values.get("WEB_TO_OBSIDIAN_DEST", "Inbox")
        )
        images = _resolve_vault_path(
            vault, values.get("WEB_TO_OBSIDIAN_IMAGES", "images")
        )
        sync_branch = values.get("WEB_TO_OBSIDIAN_SYNC_BRANCH", "master").strip()
        if not sync_branch or not _SAFE_BRANCH_NAME.fullmatch(sync_branch):
            raise ClipError("The configured Git sync branch is unsafe.")
        default_lock = Path(
            "~/.hermes/workspace/cache/webclip-obsidian/vault.lock"
        ).expanduser()
        lock_file = Path(
            values.get("WEB_TO_OBSIDIAN_LOCK_FILE", str(default_lock))
        ).expanduser().resolve()
        if lock_file == vault or vault in lock_file.parents:
            raise ClipError("The shared lock file must be outside the Obsidian vault.")
        default_pending_root = Path(
            "~/.hermes/workspace/cache/webclip-obsidian/pending-state"
        ).expanduser()
        pending_root = Path(
            values.get("WEB_TO_OBSIDIAN_PENDING_ROOT", str(default_pending_root))
        ).expanduser().resolve()
        preview_url_params = _normalize_preview_url_params(
            values.get("WEB_TO_OBSIDIAN_PREVIEW_URL_PARAMS", "")
        )
        return cls(
            vault=vault,
            destination=destination,
            images=images,
            sync_branch=sync_branch,
            lock_file=lock_file,
            pending_root=pending_root,
            preview_url_params=preview_url_params,
        )

    @classmethod
    def from_file(cls, path: Path) -> "ClipConfig":
        if not path.is_file():
            return cls.from_env()
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise ClipError("The plugin config.toml is invalid.") from exc
        section = data.get("clip")
        if not isinstance(section, dict):
            raise ClipError("The plugin config.toml must contain a [clip] table.")
        supported = {
            "vault",
            "destination",
            "images",
            "sync_branch",
            "lock_file",
            "pending_root",
            "preview_url_params",
        }
        if set(section) - supported or any(
            not isinstance(value, str) for value in section.values()
        ):
            raise ClipError("The plugin config.toml contains unsupported values.")
        mapping = {
            "WEB_TO_OBSIDIAN_VAULT": section.get("vault", "~/obsidian/shijistar"),
            "WEB_TO_OBSIDIAN_DEST": section.get("destination", "Inbox"),
            "WEB_TO_OBSIDIAN_IMAGES": section.get("images", "images"),
            "WEB_TO_OBSIDIAN_SYNC_BRANCH": section.get("sync_branch", "master"),
        }
        if "lock_file" in section:
            mapping["WEB_TO_OBSIDIAN_LOCK_FILE"] = section["lock_file"]
        if "pending_root" in section:
            mapping["WEB_TO_OBSIDIAN_PENDING_ROOT"] = section["pending_root"]
        if "preview_url_params" in section:
            mapping["WEB_TO_OBSIDIAN_PREVIEW_URL_PARAMS"] = section[
                "preview_url_params"
            ]
        return cls.from_env(mapping)


def parse_clip_args(raw_args: str) -> ClipOptions:
    """Parse one URL or webclip_id and the supported flags without invoking a shell."""
    try:
        tokens = shlex.split(raw_args, posix=True)
    except ValueError as exc:
        raise ClipError("Invalid quoting in /webclip arguments.") from exc

    no_browser = False
    no_git = False
    refresh = False
    save_images = "ask"
    save_images_seen = False
    favorite: bool | None = None
    selectors: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--no-browser":
            no_browser = True
        elif token == "--no-git":
            no_git = True
        elif token == "--refresh":
            refresh = True
        elif token in {"--favorite", "--unfavorite"}:
            value = token == "--favorite"
            if favorite is not None and favorite != value:
                raise ClipError("Conflicting favorite options were provided.")
            favorite = value
        elif token == "--save-images":
            index += 1
            if index >= len(tokens):
                raise ClipError("The --save-images option requires yes, no, or ask.")
            save_images = tokens[index].strip().lower()
            if save_images not in {"yes", "no", "ask"}:
                raise ClipError("The --save-images option only accepts yes, no, or ask.")
            save_images_seen = True
        elif token.startswith("-"):
            raise ClipError("Unknown /webclip option.")
        else:
            selectors.append(token)
        index += 1
    if len(selectors) != 1:
        raise ClipError(
            "Usage: /webclip <url|webclip_id> [--refresh] [--no-browser] [--no-git] "
            "[--save-images yes|no|ask] [--favorite|--unfavorite]"
        )
    target_kind, selector, target_hash = _parse_target_selector(selectors[0])
    if target_kind == "webclip_id":
        if favorite is None:
            raise ClipError(
                "A webclip_id target requires --favorite or --unfavorite."
            )
        if refresh:
            raise ClipError("--refresh cannot be used with a webclip_id.")
        if save_images_seen:
            raise ClipError("--save-images cannot be used with a webclip_id.")
    return ClipOptions(
        selector=selector,
        no_browser=no_browser,
        no_git=no_git,
        refresh=refresh,
        save_images=save_images,
        favorite=favorite,
        target_kind=target_kind,
        target_hash=target_hash,
    )


# --------------------------------------------------------------------------- video


@dataclass(frozen=True)
class VideoOptions:
    urls: tuple[str, ...]
    name: str | None = None
    destination: str | None = None
    overwrite: bool = False
    no_browser: bool = False


MAX_SAVE_VIDEO_URLS = 10


def parse_save_video_args(raw_args: str) -> VideoOptions:
    """Parse ``/save-video`` arguments without invoking a shell."""
    try:
        tokens = shlex.split(raw_args, posix=True)
    except ValueError as exc:
        raise ClipError("Invalid quoting in /save-video arguments.") from exc

    urls: list[str] = []
    name: str | None = None
    destination: str | None = None
    overwrite = False
    no_browser = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--overwrite":
            overwrite = True
        elif token == "--no-browser":
            no_browser = True
        elif token in {"--name", "--to"}:
            index += 1
            if index >= len(tokens):
                raise ClipError(f"The {token} option requires a value.")
            value = tokens[index].strip()
            if not value:
                raise ClipError(f"The {token} option requires a value.")
            if token == "--name":
                if name is not None:
                    raise ClipError("The --name option can only be given once.")
                name = value
            else:
                if destination is not None:
                    raise ClipError("The --to option can only be given once.")
                destination = value
        elif token.startswith("-"):
            raise ClipError("Unknown /save-video option.")
        else:
            _validate_http_url(token)
            urls.append(token)
        index += 1

    if not urls:
        raise ClipError(
            "Usage: /save-video <url> [<url> ...] [--name <name>] [--to <dir>] "
            "[--overwrite] [--no-browser]"
        )
    if len(urls) > MAX_SAVE_VIDEO_URLS:
        raise ClipError(
            f"/save-video accepts at most {MAX_SAVE_VIDEO_URLS} URLs per command."
        )
    return VideoOptions(
        urls=tuple(urls),
        name=name,
        destination=destination,
        overwrite=overwrite,
        no_browser=no_browser,
    )


@dataclass(frozen=True)
class VideoConfig:
    """``[video]`` settings.

    Parsed separately from :class:`ClipConfig` on purpose: a typo in this table
    must degrade to defaults with a warning, never take ``/webclip`` down with
    it.
    """

    destination: str = "~/Movies/Videos/webclip"
    gitignore: bool = True
    max_size_mb: int = 500
    max_per_run: int = 10
    download_timeout_s: int = 300
    ytdlp: str = ""
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_file(cls, path: Path) -> "VideoConfig":
        if not path.is_file():
            return cls()
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            return cls(warnings=("[video] could not be read; using defaults.",))
        section = data.get("video")
        if section is None:
            return cls()
        if not isinstance(section, dict):
            return cls(warnings=("The [video] table is invalid; using defaults.",))

        warnings: list[str] = []
        supported = {
            "destination",
            "gitignore",
            "max_size_mb",
            "max_per_run",
            "download_timeout_s",
            "ytdlp",
        }
        unknown = sorted(set(section) - supported)
        if unknown:
            warnings.append(
                "Unsupported [video] keys ignored: " + ", ".join(unknown) + "."
            )

        destination = section.get("destination", cls.destination)
        if not isinstance(destination, str) or not destination.strip():
            warnings.append("[video].destination must be a non-empty string; using the default.")
            destination = cls.destination

        gitignore = section.get("gitignore", cls.gitignore)
        if not isinstance(gitignore, bool):
            warnings.append("[video].gitignore must be true or false; using true.")
            gitignore = cls.gitignore

        def _bounded_int(key: str, default: int, minimum: int, maximum: int) -> int:
            raw = section.get(key, default)
            if isinstance(raw, bool) or not isinstance(raw, int):
                warnings.append(f"[video].{key} must be an integer; using {default}.")
                return default
            if not minimum <= raw <= maximum:
                warnings.append(
                    f"[video].{key} must be between {minimum} and {maximum}; using {default}."
                )
                return default
            return raw

        ytdlp = section.get("ytdlp", "")
        if not isinstance(ytdlp, str):
            warnings.append("[video].ytdlp must be a path string; using auto-detection.")
            ytdlp = ""

        return cls(
            destination=destination.strip(),
            gitignore=gitignore,
            max_size_mb=_bounded_int("max_size_mb", cls.max_size_mb, 1, 20_000),
            max_per_run=_bounded_int("max_per_run", cls.max_per_run, 1, 50),
            download_timeout_s=_bounded_int(
                "download_timeout_s", cls.download_timeout_s, 10, 7200
            ),
            ytdlp=ytdlp.strip(),
            warnings=tuple(warnings),
        )
