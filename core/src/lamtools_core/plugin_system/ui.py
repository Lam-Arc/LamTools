"""UI declarations: styles, regions and the optional script entry.

user:“界面四档全开”+第 3 步只处理声明式的部分：样式文件、区域里的块和
按钮、可选的脚本入口。自绘入口和模块替换留到后面的步骤。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .capabilities import CapabilityError
from .manifest import PluginManifest

VALID_REGIONS = (
    "appRail",
    "left",
    "titlebar",
    "main",
    "right",
    "composer",
    "composerSide",
    "message",
    "settings",
)

VALID_BLOCK_TYPES = ("text", "status", "metric", "list", "progress")


@dataclass(frozen=True)
class PluginUIAction:
    id: str
    title: str
    operation: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    dangerous: bool = False
    mutates: bool = False
    plugin: str = ""


@dataclass(frozen=True)
class PluginUIBlock:
    type: str
    label: str = ""
    value: Any = None
    text: str = ""
    state: str = ""
    items: tuple[Any, ...] = ()
    detail: str = ""
    max: float | None = None


@dataclass(frozen=True)
class PluginUIRegion:
    region: str
    order: int = 50
    mode: str = ""
    replace: bool = False
    blocks: tuple[PluginUIBlock, ...] = ()
    actions: tuple[PluginUIAction, ...] = ()
    entry: Path | None = None
    plugin: str = ""


@dataclass(frozen=True)
class PluginWindowSpec:
    id: str
    title: str
    entry: Path
    width: int = 420
    height: int = 620
    plugin: str = ""
    root: Path | None = None


@dataclass(frozen=True)
class PluginUISpec:
    plugin: str
    styles: list["PluginAssetSpec"] = field(default_factory=list)
    regions: list[PluginUIRegion] = field(default_factory=list)
    script: "PluginAssetSpec | None" = None
    windows: list[PluginWindowSpec] = field(default_factory=list)


@dataclass(frozen=True)
class PluginAssetSpec:
    plugin: str
    root: Path
    path: Path


@dataclass
class UIAssembly:
    specs: dict[str, PluginUISpec] = field(default_factory=dict)
    regions: list[PluginUIRegion] = field(default_factory=list)
    styles: list[PluginAssetSpec] = field(default_factory=list)
    scripts: list[PluginAssetSpec] = field(default_factory=list)
    windows: list[PluginWindowSpec] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


def _asset(
    manifest: PluginManifest,
    value: Any,
    *,
    key: str,
    suffixes: tuple[str, ...],
) -> PluginAssetSpec:
    text = str(value or "").strip()
    if not text:
        raise CapabilityError(manifest.name, f"{key} path is empty")
    if not text.startswith("./"):
        raise CapabilityError(manifest.name, f"{key} path must start with './': {text}")
    candidate = (manifest.root / text[2:]).resolve()
    if not candidate.is_relative_to(manifest.root):
        raise CapabilityError(manifest.name, f"{key} path is outside the plugin root: {text}")
    if candidate.suffix.lower() not in suffixes:
        raise CapabilityError(
            manifest.name,
            f"{key} path must end with {' or '.join(suffixes)}: {text}",
        )
    if not candidate.is_file():
        raise CapabilityError(manifest.name, f"{key} file is missing: {text}")
    return PluginAssetSpec(plugin=manifest.name, root=manifest.root, path=candidate)


def _parse_block(raw: Any, plugin: str) -> PluginUIBlock:
    if not isinstance(raw, dict):
        raise CapabilityError(plugin, "ui block must be an object")
    block_type = str(raw.get("type") or "").strip()
    if block_type not in VALID_BLOCK_TYPES:
        raise CapabilityError(plugin, f"ui block type is not supported: {block_type or '(missing)'}")
    items_raw = raw.get("items")
    items: tuple[Any, ...] = ()
    if isinstance(items_raw, list):
        items = tuple(
            item
            for item in items_raw
            if isinstance(item, str) or isinstance(item, dict)
        )
    max_raw = raw.get("max")
    maximum: float | None = None
    if isinstance(max_raw, (int, float)) and not isinstance(max_raw, bool):
        maximum = float(max_raw)
    return PluginUIBlock(
        type=block_type,
        label=str(raw.get("label") or ""),
        value=raw.get("value"),
        text=str(raw.get("text") or ""),
        state=str(raw.get("state") or ""),
        items=items,
        detail=str(raw.get("detail") or ""),
        max=maximum,
    )


def _parse_action(raw: Any, plugin: str) -> PluginUIAction:
    if not isinstance(raw, dict):
        raise CapabilityError(plugin, "ui action must be an object")
    action_id = str(raw.get("id") or "").strip()
    operation = str(raw.get("operation") or "").strip()
    if not action_id:
        raise CapabilityError(plugin, "ui action is missing id")
    if not operation:
        raise CapabilityError(plugin, f"ui action '{action_id}' is missing operation")
    return PluginUIAction(
        id=action_id,
        title=str(raw.get("title") or action_id),
        operation=operation,
        input_schema=(
            raw.get("inputSchema")
            if isinstance(raw.get("inputSchema"), dict)
            else raw.get("input_schema")
            if isinstance(raw.get("input_schema"), dict)
            else {}
        ),
        dangerous=bool(raw.get("dangerous", False)),
        mutates=bool(raw.get("mutates", False)),
        plugin=plugin,
    )


def _parse_region(manifest: PluginManifest, raw: Any) -> PluginUIRegion:
    if not isinstance(raw, dict):
        raise CapabilityError(manifest.name, "ui region must be an object")
    region = str(raw.get("region") or "").strip()
    if region not in VALID_REGIONS:
        raise CapabilityError(
            manifest.name,
            f"ui region is not supported: {region or '(missing)'}",
        )
    order_raw = raw.get("order", 50)
    if isinstance(order_raw, bool) or not isinstance(order_raw, int):
        raise CapabilityError(manifest.name, f"ui region '{region}' order must be an integer")
    blocks_raw = raw.get("blocks")
    if blocks_raw is not None and not isinstance(blocks_raw, list):
        raise CapabilityError(manifest.name, f"ui region '{region}' blocks must be an array")
    actions_raw = raw.get("actions")
    if actions_raw is not None and not isinstance(actions_raw, list):
        raise CapabilityError(manifest.name, f"ui region '{region}' actions must be an array")
    entry: Path | None = None
    entry_raw = raw.get("entry")
    if entry_raw is not None:
        entry = _asset(
            manifest,
            entry_raw,
            key="ui region entry",
            suffixes=(".js", ".mjs", ".html"),
        ).path
    return PluginUIRegion(
        region=region,
        order=order_raw,
        mode=str(raw.get("mode") or "").strip(),
        replace=bool(raw.get("replace", False)),
        blocks=tuple(_parse_block(item, manifest.name) for item in (blocks_raw or [])),
        actions=tuple(_parse_action(item, manifest.name) for item in (actions_raw or [])),
        entry=entry,
        plugin=manifest.name,
    )


def _positive_int(plugin: str, value: Any, *, key: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CapabilityError(plugin, f"ui window {key} must be a positive integer")
    return value


def _parse_window(manifest: PluginManifest, raw: Any) -> PluginWindowSpec:
    if not isinstance(raw, dict):
        raise CapabilityError(manifest.name, "ui window must be an object")
    window_id = str(raw.get("id") or "").strip()
    if not window_id or any(character.isspace() for character in window_id):
        raise CapabilityError(manifest.name, "ui window id must be one token")
    entry = _asset(
        manifest,
        raw.get("entry"),
        key="ui window entry",
        suffixes=(".html",),
    ).path
    return PluginWindowSpec(
        id=window_id,
        title=str(raw.get("title") or window_id),
        entry=entry,
        width=_positive_int(manifest.name, raw.get("width"), key="width", default=420),
        height=_positive_int(manifest.name, raw.get("height"), key="height", default=620),
        plugin=manifest.name,
        root=manifest.root,
    )


def read_ui(manifest: PluginManifest) -> PluginUISpec:
    """Read the optional ``ui`` declaration; a missing section is an empty spec."""
    raw = manifest.raw.get("ui")
    if raw is None:
        return PluginUISpec(plugin=manifest.name)
    if not isinstance(raw, dict):
        raise CapabilityError(manifest.name, "ui must be an object")

    styles_raw = raw.get("styles")
    if styles_raw is not None and not isinstance(styles_raw, list):
        raise CapabilityError(manifest.name, "ui.styles must be an array")
    styles = [
        _asset(manifest, item, key="ui style", suffixes=(".css",))
        for item in (styles_raw or [])
    ]

    script: PluginAssetSpec | None = None
    if raw.get("script") is not None:
        script = _asset(
            manifest,
            raw.get("script"),
            key="ui script",
            suffixes=(".js", ".mjs"),
        )

    regions_raw = raw.get("regions")
    if regions_raw is not None and not isinstance(regions_raw, list):
        raise CapabilityError(manifest.name, "ui.regions must be an array")
    regions = [_parse_region(manifest, item) for item in (regions_raw or [])]

    windows_raw = raw.get("windows")
    if windows_raw is not None and not isinstance(windows_raw, list):
        raise CapabilityError(manifest.name, "ui.windows must be an array")
    windows = [_parse_window(manifest, item) for item in (windows_raw or [])]

    return PluginUISpec(
        plugin=manifest.name,
        styles=styles,
        regions=regions,
        script=script,
        windows=windows,
    )


def assemble_ui(manifests: list[PluginManifest]) -> UIAssembly:
    """Flatten enabled plugins' UI declarations with explicit errors."""
    assembly = UIAssembly()
    replaced: dict[str, str] = {}
    window_owners: dict[str, str] = {}
    for manifest in manifests:
        if not manifest.enabled:
            continue
        try:
            spec = read_ui(manifest)
        except CapabilityError as exc:
            assembly.errors.append({"plugin": manifest.name, "error": exc.message})
            continue
        assembly.specs[manifest.name] = spec
        assembly.styles.extend(spec.styles)
        if spec.script is not None:
            assembly.scripts.append(spec.script)
        for region in spec.regions:
            if region.replace:
                owner = replaced.get(region.region)
                if owner is not None:
                    assembly.errors.append(
                        {
                            "plugin": manifest.name,
                            "error": f"region '{region.region}' is already replaced by plugin '{owner}'",
                        }
                    )
                    continue
                replaced[region.region] = manifest.name
            assembly.regions.append(region)
        for window in spec.windows:
            owner = window_owners.get(window.id)
            if owner is not None:
                assembly.errors.append(
                    {
                        "plugin": manifest.name,
                        "error": f"window '{window.id}' is already declared by plugin '{owner}'",
                    }
                )
                continue
            window_owners[window.id] = manifest.name
            assembly.windows.append(window)
    assembly.regions.sort(key=lambda item: (item.order, item.plugin, item.region))
    return assembly


__all__ = [
    "VALID_BLOCK_TYPES",
    "VALID_REGIONS",
    "PluginAssetSpec",
    "PluginUIAction",
    "PluginUIBlock",
    "PluginUIRegion",
    "PluginUISpec",
    "PluginWindowSpec",
    "UIAssembly",
    "assemble_ui",
    "read_ui",
]
