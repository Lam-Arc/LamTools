"""Host-owned agent presets.

An agent preset is a named bundle applied to a child-agent round: a mode, a
tool allow-list, an optional model, and extra prompt text.  The upstream DSH
host exposes ``agentPresets`` (``list`` / ``resolve`` / ``mount``); LamTools had
no equivalent, which forced ports to reimplement presets per plugin.  This
registry is the host contract:

* presets come from enabled plugin manifests (``agentPresets``) and from
  ``agent-presets.jsonc`` files in the project/global config;
* ``resolve`` validates the id;
* ``compose`` fills only values the caller did not set explicitly, so an
  explicit ``mode`` / ``allowed_tools`` / ``model`` always wins;
* the registry object is stable across turns; ``reload`` replaces its contents
  in place so plugin backends that hold a reference keep working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .jsonc import load_jsonc_text


@dataclass(frozen=True)
class AgentPreset:
    id: str
    title: str = ""
    description: str = ""
    mode: str = ""
    tools: tuple[str, ...] = ()
    model: str = ""
    prompt: str = ""
    plugin: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PresetComposition:
    preset_id: str = ""
    mode: str = ""
    allowed_tools: list[str] | None = None
    model: str = ""
    #: The caller's own request-local prompt (never mixed with the preset).
    prompt: str = ""
    #: The preset's prompt section, rendered in the leading system prompt.
    preset_prompt: str = ""


def _normalize_preset(raw: Any, *, plugin: str = "") -> AgentPreset | None:
    if not isinstance(raw, dict):
        return None
    preset_id = str(raw.get("id") or "").strip()
    if not preset_id:
        return None
    tools = raw.get("tools")
    if not isinstance(tools, list):
        tools = []
    return AgentPreset(
        id=preset_id,
        title=str(raw.get("title") or preset_id),
        description=str(raw.get("description") or ""),
        mode=str(raw.get("mode") or "").strip(),
        tools=tuple(str(item).strip() for item in tools if str(item).strip()),
        model=str(raw.get("model") or "").strip(),
        prompt=str(raw.get("prompt") or ""),
        plugin=plugin,
        metadata=dict(raw.get("metadata") or {}),
    )


def collect_manifest_presets(manifests: Iterable[Any]) -> list[AgentPreset]:
    presets: list[AgentPreset] = []
    for manifest in manifests:
        if not getattr(manifest, "enabled", False):
            continue
        raw = getattr(manifest, "raw", None)
        if not isinstance(raw, dict):
            continue
        items = raw.get("agentPresets")
        if not isinstance(items, list):
            continue
        for item in items:
            preset = _normalize_preset(item, plugin=str(getattr(manifest, "name", "")))
            if preset is not None:
                presets.append(preset)
    return presets


def collect_config_presets(data_dir: Path, work_root: Path | None) -> list[AgentPreset]:
    presets: list[AgentPreset] = []
    paths: list[Path] = []
    if work_root is not None:
        paths.append(Path(work_root) / ".lam" / "config" / "agent-presets.jsonc")
    paths.append(Path(data_dir) / "agent-presets.jsonc")
    for path in paths:
        try:
            raw = load_jsonc_text(path)
        except Exception:
            continue
        items = raw.get("presets") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            preset = _normalize_preset(item, plugin="config")
            if preset is not None:
                presets.append(preset)
    return presets


class AgentPresetRegistry:
    """Stable registry shared by the host, plugins and sub-agent runners."""

    def __init__(self, presets: Iterable[AgentPreset] | None = None, *, default_id: str = "default") -> None:
        self._presets: dict[str, AgentPreset] = {}
        self._default_id = str(default_id or "")
        # Runtime services scoped to a preset id.  They are not serialised:
        # a plugin registers the live object when its backend starts, and the
        # runner resolves it for the active preset (the DSH ``serviceFor``
        # contract without forcing every preset to be a full service scope).
        self._services: dict[tuple[str, str], Any] = {}
        self.reload(presets or [])

    def register_service(self, preset_id: str, name: str, service: Any) -> Callable[[], None]:
        key = (str(preset_id or ""), str(name or ""))
        self._services[key] = service

        def unregister() -> None:
            if self._services.get(key) is service:
                self._services.pop(key, None)

        return unregister

    def unregister_services(self, preset_id: str) -> None:
        preset_id = str(preset_id or "")
        for key in [key for key in self._services if key[0] == preset_id]:
            self._services.pop(key, None)

    def service_for(self, preset_id: str, name: str) -> Any | None:
        return self._services.get((str(preset_id or ""), str(name or "")))

    def reload(self, presets: Iterable[AgentPreset], *, default_id: str | None = None) -> None:
        self._presets = {preset.id: preset for preset in presets if preset.id}
        if default_id is not None:
            self._default_id = str(default_id or "")

    @property
    def default_id(self) -> str:
        if self._default_id and self._default_id in self._presets:
            return self._default_id
        if "default" in self._presets:
            return "default"
        return ""

    def list(self) -> list[AgentPreset]:
        return sorted(self._presets.values(), key=lambda preset: preset.id.casefold())

    def has(self, preset_id: str) -> bool:
        return str(preset_id or "") in self._presets

    def resolve(self, preset_id: str | None = None) -> AgentPreset:
        key = str(preset_id or self.default_id or "").strip()
        if not key:
            return AgentPreset(id="")
        preset = self._presets.get(key)
        if preset is None:
            raise KeyError(key)
        return preset

    def compose(
        self,
        preset_id: str | None,
        *,
        mode: str = "",
        allowed_tools: list[str] | None = None,
        model: str = "",
        prompt: str = "",
    ) -> PresetComposition:
        """Fill unset values from the preset; explicit caller values win."""
        preset = self.resolve(preset_id)
        if not preset.id:
            return PresetComposition(
                mode=str(mode or ""),
                allowed_tools=list(allowed_tools) if allowed_tools is not None else None,
                model=str(model or ""),
                prompt=str(prompt or ""),
            )
        tools = list(allowed_tools) if allowed_tools is not None else (list(preset.tools) or None)
        return PresetComposition(
            preset_id=preset.id,
            mode=str(mode or preset.mode or ""),
            allowed_tools=tools,
            model=str(model or preset.model or ""),
            prompt=str(prompt or ""),
            preset_prompt=str(preset.prompt or ""),
        )


def build_agent_preset_registry(
    manifests: Iterable[Any] = (),
    *,
    data_dir: Path,
    work_root: Path | None = None,
    default_id: str = "default",
) -> AgentPresetRegistry:
    presets = [*collect_manifest_presets(manifests), *collect_config_presets(Path(data_dir), work_root)]
    # Later sources (config) override plugin presets with the same id.
    deduped: dict[str, AgentPreset] = {}
    for preset in presets:
        deduped[preset.id] = preset
    resolved_default = str(default_id or "")
    for preset in deduped.values():
        if preset.metadata.get("default") is True:
            resolved_default = preset.id
            break
    return AgentPresetRegistry(deduped.values(), default_id=resolved_default)


__all__ = [
    "AgentPreset",
    "PresetComposition",
    "AgentPresetRegistry",
    "collect_manifest_presets",
    "collect_config_presets",
    "build_agent_preset_registry",
]
