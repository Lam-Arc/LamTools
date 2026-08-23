"""Core domain objects for the desktop Pet.

The Pet is a projection of the existing Core runtime.  This module deliberately
contains no UI or second runtime: it validates user-owned Pet Packs, persists
the small ``core.pet`` settings namespace, and reduces runtime projections into
the compact state consumed by the desktop surface.
"""

from __future__ import annotations

import json
import re
import asyncio
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, TYPE_CHECKING

from lamtools_core.config.root import core_config_root
from lamtools_core.config.settings_store import get_setting, set_setting

PET_NAMESPACE = "core.pet"
PET_PACKS_DIR_NAME = "pets"
DEFAULT_PET_ID = "default-cat"
PET_STATES = ("idle", "running", "waiting", "error")
PET_IMAGE_SUFFIXES = {".png", ".webp"}
MIN_OPACITY = 0.2
MAX_OPACITY = 1.0
MIN_SCALE = 0.5
MAX_SCALE = 2.0
MAX_PACK_FRAMES = 240
_PACK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .live_hub import CoreAppEventHub


def pet_packs_root() -> Path:
    """Return the user-editable Pet Pack root beside the unified config."""

    return core_config_root() / PET_PACKS_DIR_NAME


def bundled_pet_packs_root() -> Path:
    """Return the read-only Pet Packs shipped with LamTools."""

    from lamtools_core.config.defaults import bundled_resources_dir

    return bundled_resources_dir() / PET_PACKS_DIR_NAME


def ensure_default_pet_packs() -> list[Path]:
    """Seed shipped packs without ever overwriting a user's pack.

    Built-ins live in the application resources so a fresh install works even
    before the user has opened the Pet settings.  Copying them into the same
    user-editable root as custom packs keeps the existing HTTP serving and
    pack-management contract unchanged.  A directory with the same id is
    always treated as user-owned and left alone.
    """

    source_root = bundled_pet_packs_root()
    target_root = pet_packs_root()
    if not source_root.is_dir():
        return []
    created: list[Path] = []
    try:
        target_root.mkdir(parents=True, exist_ok=True)
        for source in sorted(source_root.iterdir(), key=lambda item: item.name.casefold()):
            target = target_root / source.name
            if not source.is_dir() or source.is_symlink() or target.exists():
                continue
            shutil.copytree(source, target)
            created.append(target)
    except OSError as exc:
        _logger.warning("Could not seed default Pet Packs into %s: %s", target_root, exc)
    return created


def ensure_default_pet_resources() -> None:
    """Copy pack documentation/template without replacing user files."""

    source_root = bundled_pet_packs_root()
    target_root = pet_packs_root()
    try:
        target_root.mkdir(parents=True, exist_ok=True)
        for name in ("README.md", "template"):
            source = source_root / name
            target = target_root / name
            if not source.exists() or target.exists():
                continue
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
    except OSError as exc:
        _logger.warning("Could not seed Pet Pack documentation into %s: %s", target_root, exc)


@dataclass(frozen=True)
class PetPlacement:
    monitor: str = ""
    x: float | None = None
    y: float | None = None

    @classmethod
    def from_value(cls, value: Any) -> "PetPlacement":
        if not isinstance(value, Mapping):
            return cls()
        return cls(
            monitor=str(value.get("monitor") or ""),
            x=_finite_number(value.get("x")),
            y=_finite_number(value.get("y")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"monitor": self.monitor, "x": self.x, "y": self.y}


@dataclass(frozen=True)
class PetSettings:
    enabled: bool = True
    selected_pet: str = DEFAULT_PET_ID
    opacity: float = 1.0
    scale: float = 1.0
    placement: PetPlacement = field(default_factory=PetPlacement)

    @classmethod
    def from_value(cls, value: Any) -> "PetSettings":
        value = value if isinstance(value, Mapping) else {}
        return cls(
            enabled=value.get("enabled", True) is not False,
            selected_pet=_normalize_pet_id(value.get("selected_pet"), default=DEFAULT_PET_ID),
            opacity=_clamp_number(value.get("opacity"), MIN_OPACITY, MAX_OPACITY, 1.0),
            scale=_clamp_number(value.get("scale"), MIN_SCALE, MAX_SCALE, 1.0),
            placement=PetPlacement.from_value(value.get("placement")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "selected_pet": self.selected_pet,
            "opacity": self.opacity,
            "scale": self.scale,
            "placement": self.placement.to_dict(),
        }


def load_pet_settings() -> PetSettings:
    return PetSettings.from_value(get_setting(PET_NAMESPACE))


def update_pet_settings(updates: Mapping[str, Any]) -> PetSettings:
    """Merge and validate user updates without resetting omitted fields."""

    current = load_pet_settings()
    incoming = dict(updates)
    placement = incoming.pop("placement", None)
    merged = current.to_dict()
    for key in ("enabled", "selected_pet", "opacity", "scale"):
        if key in incoming:
            merged[key] = incoming[key]
    if isinstance(placement, Mapping):
        merged["placement"] = {**current.placement.to_dict(), **dict(placement)}
    result = PetSettings.from_value(merged)
    set_setting(PET_NAMESPACE, result.to_dict())
    return result


@dataclass(frozen=True)
class PetAnimation:
    state: str
    fps: float
    frames: tuple[Path, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fps": self.fps,
            "frames": [str(frame) for frame in self.frames],
        }


@dataclass(frozen=True)
class PetPack:
    id: str
    name: str
    path: Path
    schema_version: int = 1
    sprite_version_number: int = 1
    atlas: dict[str, Any] = field(default_factory=dict)
    animations: dict[str, PetAnimation] = field(default_factory=dict)
    valid: bool = True
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "path": str(self.path),
            "schemaVersion": self.schema_version,
            "spriteVersionNumber": self.sprite_version_number,
            "atlas": dict(self.atlas),
            "valid": self.valid,
            "error": self.error,
            "states": {
                state: animation.to_dict()
                for state, animation in self.animations.items()
            },
        }


class PetPackLoader:
    """Load and validate user-owned packs without allowing path escape."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else pet_packs_root()

    def list_packs(self) -> list[PetPack]:
        if self.root.resolve() == pet_packs_root().resolve():
            ensure_default_pet_packs()
            ensure_default_pet_resources()
        if not self.root.is_dir():
            return []
        packs: list[PetPack] = []
        for path in sorted(self.root.iterdir(), key=lambda item: item.name.casefold()):
            if path.name == "template":
                continue
            if path.is_dir() and not path.is_symlink():
                packs.append(self.load(path.name))
        return packs

    def load(self, pack_id: str) -> PetPack:
        if not _PACK_ID.fullmatch(str(pack_id)):
            return _invalid_pack(str(pack_id), self.root / str(pack_id), "invalid pack id")
        pack_path = self.root / pack_id
        if not _is_within(pack_path, self.root) or not pack_path.is_dir():
            return _invalid_pack(pack_id, pack_path, "pack directory not found")
        manifest_path = pack_path / "pet.json"
        if not _is_within(manifest_path, pack_path) or not manifest_path.is_file():
            return _invalid_pack(pack_id, pack_path, "pet.json is missing")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return _invalid_pack(pack_id, pack_path, f"invalid pet.json: {exc}")
        if not isinstance(manifest, Mapping):
            return _invalid_pack(pack_id, pack_path, "pet.json must contain an object")
        if manifest.get("schemaVersion") != 1:
            return _invalid_pack(pack_id, pack_path, "schemaVersion must be 1")
        manifest_id = str(manifest.get("id") or "")
        if manifest_id != pack_id or not _PACK_ID.fullmatch(manifest_id):
            return _invalid_pack(pack_id, pack_path, "manifest id must match its directory")
        name = str(manifest.get("name") or "").strip()
        if not name:
            return _invalid_pack(pack_id, pack_path, "manifest name is required")
        states = manifest.get("states")
        if not isinstance(states, Mapping):
            return _invalid_pack(pack_id, pack_path, "manifest states must be an object")

        animations: dict[str, PetAnimation] = {}
        for state in PET_STATES:
            config = states.get(state)
            if not isinstance(config, Mapping):
                return _invalid_pack(pack_id, pack_path, f"state {state!r} is missing")
            fps = _finite_number(config.get("fps"))
            if fps is None or not 1 <= fps <= 60:
                return _invalid_pack(pack_id, pack_path, f"state {state!r} fps must be between 1 and 60")
            state_dir = pack_path / state
            if not _is_within(state_dir, pack_path) or not state_dir.is_dir():
                return _invalid_pack(pack_id, pack_path, f"state directory {state!r} is missing")
            frames = tuple(
                sorted(
                    (
                        item
                        for item in state_dir.iterdir()
                        if item.is_file() and not item.is_symlink() and item.suffix.casefold() in PET_IMAGE_SUFFIXES
                    ),
                    key=_natural_sort_key,
                )
            )
            if not frames:
                return _invalid_pack(pack_id, pack_path, f"state {state!r} has no PNG/WebP frames")
            if len(frames) > MAX_PACK_FRAMES:
                return _invalid_pack(pack_id, pack_path, f"state {state!r} exceeds {MAX_PACK_FRAMES} frames")
            for frame in frames:
                frame_error = _validate_image_frame(frame)
                if frame_error:
                    return _invalid_pack(pack_id, pack_path, f"state {state!r} frame {frame.name}: {frame_error}")
            animations[state] = PetAnimation(state=state, fps=fps, frames=frames)
        sprite_version = manifest.get("spriteVersionNumber", 1)
        if not isinstance(sprite_version, int) or sprite_version not in {1, 2}:
            return _invalid_pack(pack_id, pack_path, "spriteVersionNumber must be 1 or 2")
        atlas = manifest.get("atlas")
        if not isinstance(atlas, Mapping):
            atlas = {}
        return PetPack(
            id=pack_id,
            name=name,
            path=pack_path,
            sprite_version_number=sprite_version,
            atlas=dict(atlas),
            animations=animations,
        )


@dataclass(frozen=True)
class PetInteraction:
    id: str
    thread_id: str
    project_id: str = ""
    project_name: str = ""
    session_name: str = ""
    type: str = "ask_user"
    title: str = ""
    message: str = ""
    options: tuple[str, ...] = ()
    created_at: str = ""
    response_mode: str = "text"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "session_name": self.session_name,
            "type": self.type,
            "title": self.title,
            "message": self.message,
            "options": list(self.options),
            "created_at": self.created_at,
            "response_mode": self.response_mode,
        }


@dataclass(frozen=True)
class PetOverview:
    global_state: str = "idle"
    running_count: int = 0
    waiting_count: int = 0
    error_count: int = 0
    pending_interactions: tuple[PetInteraction, ...] = ()
    active_errors: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "global_state": self.global_state,
            "running_count": self.running_count,
            "waiting_count": self.waiting_count,
            "error_count": self.error_count,
            "pending_interactions": [item.to_dict() for item in self.pending_interactions],
            "active_errors": [dict(item) for item in self.active_errors],
        }


class PetOverviewReducer:
    """Reduce current runtime projections into the Pet's global status."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._errors: dict[str, dict[str, Any]] = {}

    def set_session(self, thread_id: str, projection: Mapping[str, Any]) -> None:
        normalized = dict(projection)
        normalized["thread_id"] = str(thread_id)
        self._sessions[str(thread_id)] = normalized

    def remove_session(self, thread_id: str) -> None:
        key = str(thread_id)
        self._sessions.pop(key, None)
        self._errors.pop(key, None)

    def set_error(self, thread_id: str, error: Mapping[str, Any] | str) -> None:
        value = dict(error) if isinstance(error, Mapping) else {"message": str(error)}
        value["thread_id"] = str(thread_id)
        self._errors[str(thread_id)] = value

    def clear_error(self, thread_id: str) -> None:
        self._errors.pop(str(thread_id), None)

    def build(self) -> PetOverview:
        interactions: list[PetInteraction] = []
        interaction_ids: set[tuple[str, str]] = set()
        running_count = 0
        for thread_id, projection in self._sessions.items():
            metadata = projection.get("metadata") if isinstance(projection.get("metadata"), Mapping) else {}
            pending = _project_interactions(thread_id, projection, metadata)
            for item in pending:
                key = (item.thread_id, item.id)
                if key in interaction_ids:
                    continue
                interaction_ids.add(key)
                interactions.append(item)
            status = str(projection.get("status") or "idle").casefold()
            if not pending and status in {"running", "interrupting"}:
                running_count += 1
        interactions.sort(key=lambda item: (item.created_at or "", item.id))
        errors = tuple(self._errors[key] for key in sorted(self._errors))
        waiting_count = len(interactions)
        error_count = len(errors)
        if waiting_count:
            state = "waiting"
        elif error_count:
            state = "error"
        elif running_count:
            state = "running"
        else:
            state = "idle"
        return PetOverview(
            global_state=state,
            running_count=running_count,
            waiting_count=waiting_count,
            error_count=error_count,
            pending_interactions=tuple(interactions),
            active_errors=errors,
        )


async def load_pet_overview_from_db(db: Any) -> PetOverview:
    """Build a restart-safe overview from the existing Core DB projections.

    Historical failed sessions are intentionally not restored as active Pet
    errors.  Runtime error tracking is live-only and is added by the event
    bridge in the next integration layer.
    """

    return await load_pet_overview_from_session_factory(db.session_factory)


async def load_pet_overview_from_session_factory(session_factory: Any) -> PetOverview:
    from sqlalchemy import select

    from lamtools_core.app.core_db import CoreRuntimeSession, CoreThreadSnapshot

    reducer = PetOverviewReducer()
    async with session_factory() as session:
        snapshots = (await session.execute(select(CoreThreadSnapshot))).scalars().all()
        runtime_rows = {
            row.thread_id: row
            for row in (await session.execute(select(CoreRuntimeSession))).scalars().all()
        }
    for row in snapshots:
        snapshot = dict(row.snapshot_json or {})
        session_info = snapshot.get("session") if isinstance(snapshot.get("session"), Mapping) else {}
        runtime = runtime_rows.get(row.thread_id)
        runtime_payload = dict(runtime.runtime_state_json or {}) if runtime is not None else {}
        metadata = dict(runtime_payload.get("metadata") or {})
        if runtime is not None:
            metadata.update(dict(runtime.pending_approval_json or {}))
        reducer.set_session(
            row.thread_id,
            {
                "status": runtime_payload.get("status") or snapshot.get("status") or "idle",
                "metadata": metadata,
                "title": session_info.get("title") or row.thread_id,
                "project_id": session_info.get("metadata", {}).get("project_id", "")
                if isinstance(session_info.get("metadata"), Mapping)
                else "",
            },
        )
    return reducer.build()


class PetOverviewService:
    """Keep one debounced global Pet projection beside the existing event hub."""

    def __init__(
        self,
        *,
        session_factory: Any,
        hub: "CoreAppEventHub",
        refresh_delay: float = 0.05,
    ) -> None:
        self.session_factory = session_factory
        self.hub = hub
        self.refresh_delay = max(0.0, float(refresh_delay))
        self._subscription: asyncio.Queue[Any | None] | None = None
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._stopped = False
        self._overview: PetOverview | None = None
        self._live_errors: dict[str, dict[str, Any]] = {}

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopped = False
        self._subscription = self.hub.subscribe_all()
        self._task = asyncio.create_task(self._run(), name="lamtools-pet-overview")
        await self._refresh(publish=True)

    async def stop(self) -> None:
        self._stopped = True
        if self._subscription is not None:
            self.hub.unsubscribe_all(self._subscription)
        self._subscription = None
        self._wake.set()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        subscription = self._subscription
        if subscription is None:
            return
        while not self._stopped:
            event = await subscription.get()
            from .live_hub import CoreAppEventGap

            if isinstance(event, CoreAppEventGap):
                self._subscription = self.hub.subscribe_all()
                subscription = self._subscription
                await self._refresh(publish=True)
                continue
            if isinstance(event, dict):
                self._record_live_error(event)
            if event is not None:
                self._wake.set()
            await self._wake.wait()
            self._wake.clear()
            if self._stopped:
                return
            if self.refresh_delay:
                await asyncio.sleep(self.refresh_delay)
            await self._refresh(publish=True)

    async def _refresh(self, *, publish: bool) -> None:
        try:
            overview = await load_pet_overview_from_session_factory(self.session_factory)
        except Exception:  # noqa: BLE001 - projection must not stop the Core server
            _logger.exception("Pet overview refresh failed")
            return
        if self._live_errors:
            overview = _overview_with_errors(overview, self._live_errors.values())
        if not publish and self._overview is not None:
            self._overview = overview
            return
        changed = self._overview is None or self._overview.to_dict() != overview.to_dict()
        self._overview = overview
        if changed:
            await self.hub.publish_global(
                {
                    "method": "pet/overviewChanged",
                    "thread_id": "",
                    "payload": {"overview": overview.to_dict()},
                }
            )

    def _record_live_error(self, event: Mapping[str, Any]) -> None:
        method = str(event.get("method") or "")
        if method == "pet/overviewChanged":
            return
        thread_id = str(event.get("thread_id") or "")
        if not thread_id:
            return
        payload = _event_payload(event)
        status = str(payload.get("status") or payload.get("state") or "").casefold()
        kind = str(payload.get("kind") or payload.get("type") or "").casefold()
        terminal_failure = method in {"runtime.failed", "turn.failed", "task.failed"}
        terminal_success = method in {
            "runtime.done",
            "runtime.cancelled",
            "turn.completed",
            "turn.cancelled",
            "task.completed",
            "task.cancelled",
        }
        if terminal_failure or status in {"failed", "error"} or kind == "error" or payload.get("error"):
            self._live_errors[thread_id] = {
                "thread_id": thread_id,
                "message": str(payload.get("error") or payload.get("message") or "Task failed"),
                "method": method,
            }
        elif terminal_success or status in {"completed", "cancelled", "done", "running", "waiting", "idle"}:
            self._live_errors.pop(thread_id, None)


def _overview_with_errors(overview: PetOverview, errors: Iterable[Mapping[str, Any]]) -> PetOverview:
    active_errors = tuple(dict(item) for item in errors)
    if overview.waiting_count:
        state = "waiting"
    elif active_errors:
        state = "error"
    elif overview.running_count:
        state = "running"
    else:
        state = "idle"
    return PetOverview(
        global_state=state,
        running_count=overview.running_count,
        waiting_count=overview.waiting_count,
        error_count=len(active_errors),
        pending_interactions=overview.pending_interactions,
        active_errors=active_errors,
    )


def _event_payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return {}
    nested = payload.get("payload")
    return nested if isinstance(nested, Mapping) else payload


def _project_interactions(
    thread_id: str,
    projection: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> list[PetInteraction]:
    result: list[PetInteraction] = []
    pending_approval = metadata.get("pending_approval")
    if isinstance(pending_approval, Mapping):
        request_id = str(pending_approval.get("request_id") or "")
        tool_call = pending_approval.get("tool_call") if isinstance(pending_approval.get("tool_call"), Mapping) else {}
        message = str(
            pending_approval.get("message")
            or tool_call.get("description")
            or tool_call.get("name")
            or "Approval required"
        )
        result.append(
            _interaction(
                thread_id,
                projection,
                pending_approval,
                request_id=request_id or f"{thread_id}:approval",
                type="approval",
                title="Approval required",
                message=message,
                options=("approve", "deny", "guide"),
                response_mode="approval",
            )
        )
    pending_waiting = metadata.get("pending_waiting_request")
    if isinstance(pending_waiting, Mapping):
        request_id = str(pending_waiting.get("request_id") or "")
        options = pending_waiting.get("options")
        if not isinstance(options, (list, tuple)):
            options = ()
        result.append(
            _interaction(
                thread_id,
                projection,
                pending_waiting,
                request_id=request_id or f"{thread_id}:ask-user",
                type="ask_user",
                title=str(pending_waiting.get("title") or "Input needed"),
                message=str(pending_waiting.get("message") or pending_waiting.get("prompt") or ""),
                options=tuple(str(item) for item in options),
                response_mode=str(pending_waiting.get("response_mode") or "text"),
            )
        )
    return result


def _interaction(
    thread_id: str,
    projection: Mapping[str, Any],
    pending: Mapping[str, Any],
    *,
    request_id: str,
    type: str,
    title: str,
    message: str,
    options: Iterable[str],
    response_mode: str,
) -> PetInteraction:
    return PetInteraction(
        id=request_id,
        thread_id=thread_id,
        project_id=str(projection.get("project_id") or ""),
        project_name=str(projection.get("project_name") or ""),
        session_name=str(projection.get("title") or thread_id),
        type=type,
        title=title,
        message=message,
        options=tuple(options),
        created_at=str(pending.get("created_at") or pending.get("createdAt") or ""),
        response_mode=response_mode,
    )


def _invalid_pack(pack_id: str, path: Path, error: str) -> PetPack:
    return PetPack(id=pack_id, name=pack_id, path=path, valid=False, error=error)


def _validate_image_frame(path: Path) -> str:
    """Validate that a frame is a decodable PNG/WebP, not just a matching name."""

    try:
        from PIL import Image
    except ImportError:
        Image = None  # type: ignore[assignment]
    if Image is not None:
        try:
            with Image.open(path) as image:
                expected = "PNG" if path.suffix.casefold() == ".png" else "WEBP"
                if image.format != expected:
                    return f"expected {expected}, got {image.format or 'unknown'}"
                image.verify()
            return ""
        except (OSError, ValueError) as exc:
            return f"cannot decode image ({exc})"

    # Pillow is optional in the packaged Core. Keep a conservative structural
    # check so invalid files are still rejected in minimal installations.
    try:
        with path.open("rb") as stream:
            header = stream.read(32)
            stream.seek(max(0, path.stat().st_size - 16))
            tail = stream.read(16)
    except OSError as exc:
        return f"cannot read image ({exc})"
    if path.suffix.casefold() == ".png":
        if not header.startswith(b"\x89PNG\r\n\x1a\n") or header[12:16] != b"IHDR":
            return "invalid PNG signature"
        width = int.from_bytes(header[16:20], "big")
        height = int.from_bytes(header[20:24], "big")
        if width < 1 or height < 1 or b"IEND" not in tail:
            return "invalid PNG dimensions or terminator"
    elif not (header[:4] == b"RIFF" and header[8:12] == b"WEBP"):
        return "invalid WebP signature"
    return ""


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _natural_sort_key(path: Path) -> tuple[Any, ...]:
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", path.name))


def _normalize_pet_id(value: Any, *, default: str) -> str:
    candidate = str(value or "").strip()
    return candidate if _PACK_ID.fullmatch(candidate) else default


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in {float("inf"), float("-inf")} else None


def _clamp_number(value: Any, low: float, high: float, default: float) -> float:
    number = _finite_number(value)
    return default if number is None else max(low, min(high, number))


__all__ = [
    "DEFAULT_PET_ID",
    "PET_NAMESPACE",
    "PET_STATES",
    "PetAnimation",
    "PetInteraction",
    "PetOverview",
    "PetOverviewReducer",
    "PetPack",
    "PetPackLoader",
    "PetPlacement",
    "PetSettings",
    "PetOverviewService",
    "load_pet_overview_from_db",
    "load_pet_overview_from_session_factory",
    "load_pet_settings",
    "pet_packs_root",
    "update_pet_settings",
]
