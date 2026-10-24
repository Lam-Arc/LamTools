"""Register RPC operations declared by v2 plugins.

user:“插件自己也提供操作”+插件目录里的 operations.jsonc 在启动时挂进同一个
操作目录，插件禁用后操作自动不可用；重名一律拒绝并记录，不做先装赢。

Handler contract::

    async def some_operation(request) -> OperationResult   # or a dict payload

Handlers that need the host paths may accept keyword-only ``work_root`` and
``data_dir``; the bridge only passes what the signature accepts.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from lamtools_core.app import OperationRequest, OperationResult

from .capabilities import CapabilityError
from .host import PluginHost
from .manifest import PluginManifest

OWNER = "plugin-system"
_MODULE_CACHE: dict[tuple[str, float, str], Any] = {}


@dataclass(frozen=True)
class PluginOperationSpec:
    name: str
    description: str
    handler: str
    plugin: str
    root: Path


@dataclass
class OperationAssembly:
    operations: list[PluginOperationSpec] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


def _resolve(manifest: PluginManifest, value: Any, *, key: str) -> Path:
    text = str(value or "").strip()
    if not text:
        raise CapabilityError(manifest.name, f"{key} is empty")
    if not text.startswith("./"):
        raise CapabilityError(manifest.name, f"{key} path must start with './': {text}")
    candidate = (manifest.root / text[2:]).resolve()
    if not candidate.is_relative_to(manifest.root):
        raise CapabilityError(manifest.name, f"{key} path is outside the plugin root: {text}")
    if not candidate.is_file():
        raise CapabilityError(manifest.name, f"{key} file is missing: {text}")
    return candidate


def read_operations(manifest: PluginManifest) -> list[PluginOperationSpec]:
    raw = manifest.raw.get("operations")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CapabilityError(manifest.name, "operations must be an array")
    specs: list[PluginOperationSpec] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if isinstance(item, str):
            path = _resolve(manifest, item, key=f"operations[{index}]")
            try:
                from lamtools_core.llm.profiles import strip_jsonc

                data = json.loads(strip_jsonc(path.read_text(encoding="utf-8-sig")))
            except (OSError, ValueError) as exc:
                raise CapabilityError(
                    manifest.name, f"{path.name} is not readable JSON: {exc}"
                ) from exc
            entries = data.get("operations") if isinstance(data, dict) else None
            if not isinstance(entries, list):
                raise CapabilityError(
                    manifest.name, f"{path.name} must contain an 'operations' array"
                )
            source_items = entries
        elif isinstance(item, dict):
            source_items = [item]
        else:
            raise CapabilityError(
                manifest.name, f"operations[{index}] must be a path or an object"
            )
        for entry in source_items:
            if not isinstance(entry, dict):
                raise CapabilityError(manifest.name, "operation entry must be an object")
            name = str(entry.get("name") or "").strip()
            handler = str(entry.get("handler") or "").strip()
            if not name:
                raise CapabilityError(manifest.name, "operation entry is missing name")
            if not handler or ":" not in handler:
                raise CapabilityError(
                    manifest.name, f"operation '{name}' needs a module:function handler"
                )
            if name in seen:
                raise CapabilityError(manifest.name, f"duplicate operation '{name}'")
            seen.add(name)
            specs.append(
                PluginOperationSpec(
                    name=name,
                    description=str(entry.get("description") or ""),
                    handler=handler,
                    plugin=manifest.name,
                    root=manifest.root,
                )
            )
    return specs


def assemble_operations(
    manifests: list[PluginManifest],
    *,
    include_disabled: bool = False,
) -> OperationAssembly:
    """Collect declarations; the catalog can mount disabled ones behind a guard."""
    assembly = OperationAssembly()
    seen: dict[str, str] = {}
    for manifest in manifests:
        if not manifest.enabled and not include_disabled:
            continue
        try:
            specs = read_operations(manifest)
        except CapabilityError as exc:
            assembly.errors.append({"plugin": manifest.name, "error": exc.message})
            continue
        for spec in specs:
            owner = seen.get(spec.name)
            if owner is not None:
                assembly.errors.append(
                    {
                        "plugin": manifest.name,
                        "error": f"operation '{spec.name}' is already declared by plugin '{owner}'",
                    }
                )
                continue
            seen[spec.name] = manifest.name
            assembly.operations.append(spec)
    return assembly


def _load_handler_module(spec: PluginOperationSpec, module_name: str) -> Any:
    if "." in module_name:
        # Bundled and packaged plugins declare a dotted module path.  Import it
        # normally after making the plugin root importable, like the legacy
        # operation loader does.
        root = str(spec.root)
        if root not in sys.path:
            sys.path.append(root)
        return importlib.import_module(module_name)
    path = (spec.root / f"{module_name}.py").resolve()
    if not path.is_file():
        raise ImportError(f"handler module is missing: {path}")
    mtime = path.stat().st_mtime
    cache_key = (str(path), mtime, module_name)
    cached = _MODULE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    unique_name = f"_lam_plugin_op_{abs(hash(str(path))):x}_{module_name}"
    module = sys.modules.get(unique_name)
    if module is None:
        module_spec = importlib.util.spec_from_file_location(unique_name, path)
        if module_spec is None or module_spec.loader is None:
            raise ImportError(f"cannot load plugin operation module: {path}")
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[unique_name] = module
        try:
            module_spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(unique_name, None)
            raise
    _MODULE_CACHE[cache_key] = module
    return module


def _accepted_kwargs(func: Callable[..., Any]) -> set[str]:
    try:
        parameters = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return set()
    return {
        name
        for name, parameter in parameters.items()
        if parameter.kind
        in (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    }


def _data_dir(host: PluginHost) -> Path:
    return Path(host.state.path).parent


def _work_root(request: OperationRequest) -> Path:
    payload = request.payload if isinstance(request.payload, dict) else {}
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    value = (
        payload.get("work_root")
        or payload.get("workRoot")
        or metadata.get("work_root")
        or metadata.get("workRoot")
    )
    return Path(value).expanduser().resolve() if value else Path.cwd()


def build_handler(spec: PluginOperationSpec, host: PluginHost):
    async def run(request: OperationRequest) -> OperationResult:
        module_name, _, function_name = spec.handler.partition(":")
        try:
            module = _load_handler_module(spec, module_name)
            func = getattr(module, function_name)
        except Exception as exc:  # noqa: BLE001 - a broken plugin must not kill the catalog
            return OperationResult(
                name=spec.name,
                status="error",
                payload={"error": f"plugin '{spec.plugin}' operation is unavailable: {exc}"},
            )
        kwargs: dict[str, Any] = {}
        accepted = _accepted_kwargs(func)
        if "work_root" in accepted:
            kwargs["work_root"] = _work_root(request)
        if "data_dir" in accepted:
            kwargs["data_dir"] = _data_dir(host)
        if "context" in accepted:
            from .backend_runtime import context_for

            context = context_for(spec.plugin)
            if context is not None:
                kwargs["context"] = context
        try:
            value = func(request, **kwargs)
            if inspect.isawaitable(value):
                value = await value
        except Exception as exc:  # noqa: BLE001
            return OperationResult(
                name=spec.name,
                status="error",
                payload={"error": f"{type(exc).__name__}: {exc}"},
            )
        if isinstance(value, OperationResult):
            return value
        if isinstance(value, dict):
            return OperationResult(name=spec.name, payload=value)
        return OperationResult(
            name=spec.name,
            payload={"result": value},
        )

    return run


def register_plugin_operations(catalog: Any, host: PluginHost) -> OperationAssembly:
    """Mount every enabled v2 plugin operation behind its own availability guard."""
    manifests = [item for item in host.discover() if item.assembly == "v2"]
    # Disabled plugins stay mounted behind the availability guard so a live
    # enable transition exposes them without rebuilding the catalog.
    assembly = assemble_operations(manifests, include_disabled=True)
    if assembly.errors:
        errors = getattr(catalog, "plugin_operation_errors", None)
        if isinstance(errors, list):
            errors.extend(assembly.errors)
    registered = set(catalog.registered()) if hasattr(catalog, "registered") else set()
    for spec in assembly.operations:
        # 外层目录会把内层已经挂过的操作原样搬过来，这里跳过，避免
        # 把“已注册”误记成插件错误。
        if spec.name in registered:
            continue

        def available(plugin_name: str = spec.plugin) -> bool:
            manifest = host.get(plugin_name)
            return manifest is not None and manifest.enabled

        try:
            catalog.register(
                spec.name,
                build_handler(spec, host),
                owner=OWNER,
                availability=available,
            )
        except ValueError as exc:
            errors = getattr(catalog, "plugin_operation_errors", None)
            if isinstance(errors, list):
                errors.append({"plugin": spec.plugin, "error": str(exc)})
    return assembly


__all__ = [
    "OperationAssembly",
    "PluginOperationSpec",
    "assemble_operations",
    "build_handler",
    "read_operations",
    "register_plugin_operations",
]
