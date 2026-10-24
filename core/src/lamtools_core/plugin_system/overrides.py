"""Parse module overrides from a plugin manifest.

user:“双键族”+``lamtools_core.*`` 键走后端 boot 查找器；``@/...`` 键是
前端模块（import map 替换，Core 返回页面时注入）。同一目标只能一个插件
接管，安全模式跳过全部覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .capabilities import CapabilityError
from .manifest import PluginManifest

HOST_MODULE_PREFIX = "lamtools_core."
#: 前端覆盖键：应用源码内的裸模块说明符（构建后由 import map 解析）。
FRONTEND_KEY_PREFIX = "@/"
FRONTEND_SUFFIXES = (".js", ".mjs")


@dataclass(frozen=True)
class PluginOverrideSpec:
    plugin: str
    target: str
    path: Path
    root: Path

    @property
    def is_frontend(self) -> bool:
        return self.target.startswith(FRONTEND_KEY_PREFIX)


@dataclass
class OverrideAssembly:
    overrides: dict[str, PluginOverrideSpec] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    skipped: bool = False

    def frontend_overrides(self) -> dict[str, PluginOverrideSpec]:
        return {k: v for k, v in self.overrides.items() if v.is_frontend}

    def backend_overrides(self) -> dict[str, PluginOverrideSpec]:
        return {k: v for k, v in self.overrides.items() if not v.is_frontend}


def _validate_target(plugin: str, value: Any) -> str:
    target = str(value or "").strip()
    if target.startswith(FRONTEND_KEY_PREFIX):
        return target
    if not target.startswith(HOST_MODULE_PREFIX):
        raise CapabilityError(
            plugin,
            f"override target must start with '{HOST_MODULE_PREFIX}' or '{FRONTEND_KEY_PREFIX}': {target or '(missing)'}",
        )
    if any(not part.isidentifier() for part in target.split(".")):
        raise CapabilityError(plugin, f"override target is not a module name: {target}")
    return target


def read_overrides(manifest: PluginManifest) -> list[PluginOverrideSpec]:
    raw = manifest.raw.get("overrides")
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise CapabilityError(manifest.name, "overrides must be an object")
    specs: list[PluginOverrideSpec] = []
    seen: set[str] = set()
    for raw_target, raw_path in raw.items():
        target = _validate_target(manifest.name, raw_target)
        if target in seen:
            raise CapabilityError(manifest.name, f"duplicate override target '{target}'")
        seen.add(target)
        text = str(raw_path or "").strip()
        if not text:
            raise CapabilityError(manifest.name, f"override '{target}' has no file")
        if not text.startswith("./"):
            raise CapabilityError(
                manifest.name, f"override path must start with './': {text}"
            )
        candidate = (manifest.root / text[2:]).resolve()
        if not candidate.is_relative_to(manifest.root):
            raise CapabilityError(
                manifest.name, f"override path is outside the plugin root: {text}"
            )
        allowed = FRONTEND_SUFFIXES if target.startswith(FRONTEND_KEY_PREFIX) else (".py",)
        if candidate.suffix.lower() not in allowed:
            raise CapabilityError(
                manifest.name,
                f"override path must end with {' or '.join(allowed)}: {text}",
            )
        if not candidate.is_file():
            raise CapabilityError(manifest.name, f"override file is missing: {text}")
        specs.append(
            PluginOverrideSpec(
                plugin=manifest.name,
                target=target,
                path=candidate,
                root=manifest.root,
            )
        )
    return specs


def assemble_overrides(
    manifests: list[PluginManifest],
    *,
    safe_mode: bool = False,
) -> OverrideAssembly:
    """Build the target-to-file map, reporting conflicts explicitly."""
    assembly = OverrideAssembly(skipped=safe_mode)
    if safe_mode:
        return assembly
    for manifest in manifests:
        if not manifest.enabled:
            continue
        try:
            specs = read_overrides(manifest)
        except CapabilityError as exc:
            assembly.errors.append({"plugin": manifest.name, "error": exc.message})
            continue
        for spec in specs:
            existing = assembly.overrides.get(spec.target)
            if existing is not None:
                assembly.errors.append(
                    {
                        "plugin": manifest.name,
                        "error": (
                            f"module '{spec.target}' is already overridden by "
                            f"plugin '{existing.plugin}'"
                        ),
                    }
                )
                continue
            assembly.overrides[spec.target] = spec
    return assembly


def override_paths(assembly: OverrideAssembly) -> dict[str, Path]:
    return {target: spec.path for target, spec in assembly.overrides.items()}


__all__ = [
    "HOST_MODULE_PREFIX",
    "OverrideAssembly",
    "PluginOverrideSpec",
    "assemble_overrides",
    "override_paths",
    "read_overrides",
]
