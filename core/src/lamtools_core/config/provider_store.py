"""File-backed provider definitions (jsonc).

Provider connection info (base_url, api_key, api_type) lives as one jsonc
file per provider under:

* Project:  ``{work_root}/.lam/config/providers/<id>.jsonc``
* Global:   ``~/.lam/config/providers/<id>.jsonc``
* Built-in: the app-shipped ``core/config/resources/providers/`` directory.

Resolution merges all scopes with **project overriding global overriding
built-in** on a per-``id`` basis. Models reference their provider by the
``provider`` name (or the optional ``provider_id`` pointing at a provider
file's ``id``).

This is the jsonc-only replacement for the former ``llm_providers`` table —
there is no database, no migration, no fallback parsing.
"""

from __future__ import annotations

import asyncio
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lamtools_core.config.root import core_config_dir, legacy_user_config_dir
from lamtools_core.llm.profiles import load_jsonc

PROVIDERS_SUBDIR = "providers"
PROVIDER_FILENAME_SUFFIX = ".jsonc"

# Sentinel used when serialising api keys for display / round-tripping.
MASKED_API_KEY = "********"


def slugify(value: str) -> str:
    """Turn an arbitrary provider name into a safe file-name stem.

    Keeps ASCII letters/digits, CJK characters and ``-``/``_``; everything
    else collapses to ``-``. Empty results fall back to ``provider``.
    """
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", str(value or "").strip(), flags=re.UNICODE).strip("-")
    return cleaned or "provider"


def mask_api_key(api_key: str) -> str:
    return MASKED_API_KEY if (api_key or "").strip() else ""


@dataclass
class ProviderConfig:
    """A single provider definition loaded from jsonc."""

    id: str = ""                 # stable id (defaults to the file stem)
    name: str = ""               # display name; what model files reference
    api_type: str = "openai"     # openai | anthropic | ... (adapter protocol)
    base_url: str = ""
    api_key: str = ""
    is_default: bool = False
    adapter_profile_id: str = ""  # reference to a shared adapter profile
    extra: dict[str, Any] = field(default_factory=dict)  # free-form extension
    notes: str = ""               # free-form notes/remarks (optional, user-facing)
    source_path: str = ""         # which file this came from (for debugging/UI)

    def masked(self) -> "ProviderConfig":
        """Return a copy with the api key masked for display/listing."""
        return replace_for_mask(self)


def replace_for_mask(config: "ProviderConfig") -> "ProviderConfig":
    from dataclasses import replace

    return replace(config, api_key=mask_api_key(config.api_key))


def _repo_resource_providers_dir() -> Path:
    """Built-in shipped providers dir: <repo>/core/config/resources/providers.

    Resolved relative to this file in dev; from ``_MEIPASS/config/resources``
    when frozen (PyInstaller).
    """
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return meipass / "config" / "resources" / PROVIDERS_SUBDIR
    return Path(__file__).resolve().parent.parent.parent.parent / "config" / "resources" / PROVIDERS_SUBDIR


class ProviderStore:
    """Discovers, parses, and writes per-provider jsonc definition files."""

    def __init__(self, *, explicit_roots: Iterable[str | Path] = ()) -> None:
        self._explicit_roots = tuple(Path(item).resolve() for item in explicit_roots)
        self._cached_signature: tuple[tuple[str, int, int], ...] | None = None
        self._cached_providers: dict[str, ProviderConfig] | None = None

    # -- discovery --------------------------------------------------------

    def _candidate_dirs(self, work_root: str | None) -> list[Path]:
        """Return provider dirs in ascending precedence (built-in → legacy → unified → project).

        The unified config directory is where new writes land, so it must
        override the legacy ``{lam_home}/config/providers`` read fallback.
        """
        dirs: list[Path] = []
        builtin = _repo_resource_providers_dir()
        if builtin.is_dir():
            dirs.append(builtin)
        legacy = legacy_user_config_dir() / PROVIDERS_SUBDIR
        if legacy.is_dir() and legacy != core_config_dir() / PROVIDERS_SUBDIR:
            dirs.append(legacy)
        unified = core_config_dir() / PROVIDERS_SUBDIR
        if unified.is_dir():
            dirs.append(unified)
        for root in self._explicit_roots:
            candidate = root / "config" / PROVIDERS_SUBDIR
            if candidate.is_dir():
                dirs.append(candidate)
        if work_root:
            project_dir = Path(work_root).resolve() / ".lam" / "config" / PROVIDERS_SUBDIR
            if project_dir.is_dir():
                dirs.append(project_dir)
        return dirs

    def _candidate_files(self, work_root: str | None) -> list[Path]:
        seen: set[Path] = set()
        results: list[Path] = []
        for directory in self._candidate_dirs(work_root):
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.jsonc")):
                resolved = path.resolve()
                if resolved not in seen and resolved.is_file():
                    seen.add(resolved)
                    results.append(resolved)
        return results

    def _signature(self, work_root: str | None) -> tuple[tuple[str, int, int], ...]:
        entries: list[tuple[str, int, int]] = []
        for path in self._candidate_files(work_root):
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((str(path), stat.st_mtime_ns, stat.st_size))
        return tuple(entries)

    # -- parse -----------------------------------------------------------

    @staticmethod
    def _parse(path: Path) -> ProviderConfig | None:
        try:
            data = load_jsonc(path)
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        provider_id = str(data.get("id") or path.stem).strip()
        if not provider_id:
            return None
        extra = data.get("extra")
        if not isinstance(extra, dict):
            extra = {}
        return ProviderConfig(
            id=provider_id,
            name=str(data.get("name") or provider_id).strip(),
            api_type=str(data.get("api_type") or "openai").strip(),
            base_url=str(data.get("base_url") or "").strip(),
            api_key=str(data.get("api_key") or "").strip(),
            is_default=bool(data.get("is_default") or False),
            adapter_profile_id=str(data.get("adapter_profile_id") or "").strip(),
            extra=extra,
            notes=str(data.get("notes") or "").strip(),
            source_path=str(path),
        )

    # -- async API -------------------------------------------------------

    async def list(self, *, work_root: str | None = None) -> list[ProviderConfig]:
        return await asyncio.to_thread(self.list_sync, work_root=work_root)

    def list_sync(self, *, work_root: str | None = None) -> list[ProviderConfig]:
        providers = self._load_map(work_root)
        return sorted(providers.values(), key=lambda p: (p.name or p.id).lower())

    async def get(self, provider_ref: str, *, work_root: str | None = None) -> ProviderConfig | None:
        return await asyncio.to_thread(self.get_sync, provider_ref, work_root=work_root)

    def get_sync(self, provider_ref: str, *, work_root: str | None = None) -> ProviderConfig | None:
        if not provider_ref:
            return None
        ref = provider_ref.strip()
        providers = self._load_map(work_root)
        if ref in providers:
            return providers[ref]
        lowered = ref.lower()
        for provider in providers.values():
            if provider.name.lower() == lowered:
                return provider
        return None

    def default_sync(self, *, work_root: str | None = None) -> ProviderConfig | None:
        """Return the is_default provider, else the single configured one."""
        providers = self.list_sync(work_root=work_root)
        for provider in providers:
            if provider.is_default:
                return provider
        if len(providers) == 1:
            return providers[0]
        return None

    # -- internal: cached load ------------------------------------------

    def _load_map(self, work_root: str | None) -> dict[str, ProviderConfig]:
        sig = self._signature(work_root)
        if self._cached_signature == sig and self._cached_providers is not None:
            return self._cached_providers
        # Candidate files are ordered built-in → global → explicit → project,
        # so later entries override earlier ones on a per-id basis.
        providers: dict[str, ProviderConfig] = {}
        for path in self._candidate_files(work_root):
            provider = self._parse(path)
            if provider is None:
                continue
            providers[provider.id] = provider
        self._cached_signature = sig
        self._cached_providers = providers
        return providers

    # -- write -----------------------------------------------------------

    @staticmethod
    def write_path(provider_id: str, *, scope: str, work_root: str | None) -> Path:
        if scope == "project" and work_root:
            return Path(work_root).resolve() / ".lam" / "config" / PROVIDERS_SUBDIR / f"{provider_id}{PROVIDER_FILENAME_SUFFIX}"
        return core_config_dir() / PROVIDERS_SUBDIR / f"{provider_id}{PROVIDER_FILENAME_SUFFIX}"

    def write(self, provider: ProviderConfig, *, scope: str, work_root: str | None) -> Path:
        path = self.write_path(provider.id, scope=scope, work_root=work_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._serialize(provider), encoding="utf-8")
        self._cached_signature = None  # invalidate cache
        self._cached_providers = None
        return path

    @staticmethod
    def _serialize(provider: ProviderConfig) -> str:
        import json

        data: dict[str, Any] = {
            "id": provider.id,
            "name": provider.name,
            "api_type": provider.api_type,
            "base_url": provider.base_url,
            "api_key": provider.api_key,
            "is_default": provider.is_default,
            "notes": provider.notes,
        }
        if provider.adapter_profile_id:
            data["adapter_profile_id"] = provider.adapter_profile_id
        if provider.extra:
            data["extra"] = dict(provider.extra)
        return json.dumps(data, ensure_ascii=False, indent=2)


__all__ = [
    "PROVIDERS_SUBDIR",
    "PROVIDER_FILENAME_SUFFIX",
    "MASKED_API_KEY",
    "ProviderConfig",
    "ProviderStore",
    "mask_api_key",
    "slugify",
]
