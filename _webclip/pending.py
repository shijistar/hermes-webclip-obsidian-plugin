"""Image-confirmation state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Mapping
import json
import os

from .config import ClipConfig
from .core import ClipError
from .fsutil import atomic_write

@dataclass(frozen=True)
class PendingClipState:
    pending_id: str
    created_at: str
    expires_at: str
    article: Mapping[str, object]
    refresh: bool
    no_git: bool
    favorite: bool | None
    vault: str
    destination: str
    images: str
    sync_branch: str

    def to_json(self) -> dict[str, object]:
        return {
            "pending_id": self.pending_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "article": dict(self.article),
            "refresh": self.refresh,
            "no_git": self.no_git,
            "favorite": self.favorite,
            "vault": self.vault,
            "destination": self.destination,
            "images": self.images,
            "sync_branch": self.sync_branch,
        }

    def matches_config(self, config: ClipConfig) -> bool:
        # ``preview_url_params`` is intentionally excluded: it only changes the
        # preview URL returned to the caller, not where or what is written, so
        # editing it mid-way through a two-step clip must not invalidate the
        # pending state.
        return (
            self.vault == str(config.vault)
            and self.destination == str(config.destination)
            and self.images == str(config.images)
            and self.sync_branch == config.sync_branch
        )


def _active_pending_pointer(root: Path) -> Path:
    return root / "active.json"


def _pending_state_path(root: Path, pending_id: str) -> Path:
    return root / f"{pending_id}.json"


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    atomic_write(path, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def _clear_pending(root: Path, pending_id: str | None = None) -> None:
    pointer = _active_pending_pointer(root)
    if pending_id is None and pointer.is_file():
        try:
            data = json.loads(pointer.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                pending_id = data.get("pending_id") if isinstance(data.get("pending_id"), str) else None
        except (OSError, UnicodeError, json.JSONDecodeError):
            pending_id = None
    candidates = [pointer]
    if pending_id:
        candidates.append(_pending_state_path(root, pending_id))
    for candidate in candidates:
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ClipError("Could not clear the pending image confirmation state.") from exc


def _load_pending_state(root: Path) -> PendingClipState:
    pointer = _active_pending_pointer(root)
    if not pointer.is_file():
        raise ClipError("No pending image confirmation exists.")
    try:
        active = json.loads(pointer.read_text(encoding="utf-8"))
        pending_id = active.get("pending_id")
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError) as exc:
        raise ClipError("The pending image confirmation state is invalid.") from exc
    if not isinstance(pending_id, str) or not pending_id:
        raise ClipError("The pending image confirmation state is invalid.")
    path = _pending_state_path(root, pending_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        _clear_pending(root, pending_id)
        raise ClipError("No pending image confirmation exists.") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClipError("The pending image confirmation state is invalid.") from exc
    if not isinstance(payload, dict):
        raise ClipError("The pending image confirmation state is invalid.")
    required = {
        "pending_id": str,
        "created_at": str,
        "expires_at": str,
        "article": dict,
        "refresh": bool,
        "no_git": bool,
        "vault": str,
        "destination": str,
        "images": str,
        "sync_branch": str,
    }
    for field, expected_type in required.items():
        value = payload.get(field)
        if not isinstance(value, expected_type):
            raise ClipError("The pending image confirmation state is invalid.")
    expires_at = datetime.fromisoformat(str(payload["expires_at"]))
    if datetime.now(timezone.utc) >= expires_at:
        _clear_pending(root, pending_id)
        raise ClipError("The pending image confirmation expired; please run /webclip again.")
    favorite = payload.get("favorite")
    if favorite is not None and not isinstance(favorite, bool):
        raise ClipError("The pending image confirmation state is invalid.")
    return PendingClipState(
        pending_id=str(payload["pending_id"]),
        created_at=str(payload["created_at"]),
        expires_at=str(payload["expires_at"]),
        article=dict(payload["article"]),
        refresh=bool(payload["refresh"]),
        no_git=bool(payload["no_git"]),
        favorite=favorite,
        vault=str(payload["vault"]),
        destination=str(payload["destination"]),
        images=str(payload["images"]),
        sync_branch=str(payload["sync_branch"]),
    )


def _store_pending_state(root: Path, state: PendingClipState) -> None:
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise ClipError("Could not create the pending image confirmation directory.") from exc
    try:
        if root.is_symlink():
            raise ClipError("Refusing to use a symbolic-link pending state directory.")
        os.chmod(root, 0o700)
    except OSError as exc:
        raise ClipError("Could not secure the pending image confirmation directory.") from exc
    pointer = _active_pending_pointer(root)
    if pointer.exists():
        existing = _load_pending_state(root)
        raise ClipError(
            f"Another clipped article ('{existing.article.get('title', 'unknown')}') is already waiting for yes/no confirmation."
        )
    _write_json(_pending_state_path(root, state.pending_id), state.to_json())
    _write_json(pointer, {"pending_id": state.pending_id})
