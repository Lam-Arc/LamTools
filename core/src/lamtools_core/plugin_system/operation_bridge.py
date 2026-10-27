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
    permission: str = "auto_allow"
    impact: str = ""
    approval_fields: tuple[str, ...] = ()


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
    from .process_runtime import process_runtime_spec

    process_runtime = process_runtime_spec(manifest) is not None
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
                if process_runtime:
                    # user:“外部进程插件运行时”+(进程插件在 operations.jsonc 里
                    # 只声明名字，处理函数在子进程里，不需要 Python 模块路径)。
                    handler = f"process:{name}"
                else:
                    raise CapabilityError(
                        manifest.name, f"operation '{name}' needs a module:function handler"
                    )
            if name in seen:
                raise CapabilityError(manifest.name, f"duplicate operation '{name}'")
            seen.add(name)
            permission = entry.get("permission", "auto_allow")
            if permission not in {"auto_allow", "ask_user", "hard_block"}:
                raise CapabilityError(manifest.name, f"invalid operation permission: {permission}")
            approval_fields = entry.get("approvalFields", [])
            if not isinstance(approval_fields, list) or len(approval_fields) > 12 or any(not isinstance(key, str) or not key or len(key) > 80 for key in approval_fields):
                raise CapabilityError(manifest.name, "approvalFields must contain at most 12 field names")
            specs.append(
                PluginOperationSpec(
                    name=name,
                    description=str(entry.get("description") or ""),
                    handler=handler,
                    plugin=manifest.name,
                    root=manifest.root,
                    permission=permission,
                    impact=str(entry.get("impact") or entry.get("description") or name),
                    approval_fields=tuple(approval_fields),
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
    # user:“该重建就重建”+(工具、操作和后端共享同一模块空间与卸载时机)。
    from .loading import load_module
    return load_module(spec.root, module_name)


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


def _process_backend(host: PluginHost, plugin: str) -> Any | None:
    """Return the live process backend for a plugin, if it declares one.

    user:“外部进程插件运行时”+(Node 等插件由宿主托管，操作也走同一条进程，
    不再要求操作实现必须是 Python 模块)。
    """
    from .process_runtime import ProcessBackend, process_runtime_spec

    manifest = host.get(plugin)
    if manifest is None or process_runtime_spec(manifest) is None:
        return None
    manager = getattr(host, "backend_manager", None)
    handle = manager.get(plugin) if manager is not None else None
    if handle is None or not getattr(handle, "started", False):
        return None
    value = getattr(handle, "value", None)
    return value if isinstance(value, ProcessBackend) else None


def build_handler(spec: PluginOperationSpec, host: PluginHost, consent: Any = None):
    async def run(request: OperationRequest) -> OperationResult:
        # user:“继续”+(审批在宿主后台先于导入和执行；自绘面板也不能绕过)。
        if spec.permission != "auto_allow":
            if consent is None:
                return OperationResult(name=spec.name, status="blocked", payload={"error": "操作审批服务不可用"})
            denied = consent.check(spec, request)
            if denied is not None:
                return denied
        backend = _process_backend(host, spec.plugin)
        if backend is not None:
            try:
                value = await backend.call_operation(spec.name, request.payload or {}, request.metadata or {})
            except Exception as exc:  # noqa: BLE001 - a dead process must not kill the catalog
                return OperationResult(
                    name=spec.name,
                    status="error",
                    payload={"error": f"{type(exc).__name__}: {exc}"},
                )
            if isinstance(value, OperationResult):
                return value
            status = str(value.get("status") or "ok")
            payload = value.get("payload")
            return OperationResult(
                name=spec.name,
                status=status,
                payload=dict(payload) if isinstance(payload, dict) else {"result": payload},
            )
        from .process_runtime import process_runtime_spec

        manifest = host.get(spec.plugin)
        if manifest is not None and process_runtime_spec(manifest) is not None:
            # A declared process plugin must not silently fall back to importing
            # a Python module that does not exist.
            return OperationResult(
                name=spec.name,
                status="error",
                payload={"error": f"plugin '{spec.plugin}' process backend is not running"},
            )
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

            context = context_for(spec.plugin, host)
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

    async def leased(request):
        manager = getattr(host, "backend_manager", None)
        if manager is None:
            return await run(request)
        async with manager.lease(spec.plugin):
            return await run(request)
    return leased


def register_plugin_operations(catalog: Any, host: PluginHost, *, refresh: bool = False) -> OperationAssembly:
    """Mount every enabled plugin operation behind its own availability guard."""
    import weakref
    if not hasattr(host, "operation_catalogs"):
        host.operation_catalogs = weakref.WeakSet()
    host.operation_catalogs.add(catalog)
    if refresh:
        for name in catalog.registered():
            owner = catalog.owner_of(name)
            if owner.startswith("plugin:"):
                catalog.unregister_owner(owner)
    manifests = host.discover()
    # Disabled plugins stay mounted behind the availability guard so a live
    # enable transition exposes them without rebuilding the catalog.
    assembly = assemble_operations(manifests, include_disabled=True)
    if assembly.errors:
        errors = getattr(catalog, "plugin_operation_errors", None)
        if isinstance(errors, list):
            errors.extend(assembly.errors)
    registered = set(catalog.registered()) if hasattr(catalog, "registered") else set()
    from .operation_consent import OperationConsent

    consent = getattr(host, "operation_consent", None)
    if consent is None:
        consent = host.operation_consent = OperationConsent(host)
    if "plugin.system.operation.respond" not in registered:
        catalog.register("plugin.system.operation.respond", consent.respond, owner=OWNER)
    for spec in assembly.operations:
        # 外层目录会把内层已经挂过的操作原样搬过来，这里跳过，避免
        # 把“已注册”误记成插件错误。
        if spec.name in registered:
            continue

        def available(plugin_name: str = spec.plugin) -> bool:
            manifest = host.get(plugin_name)
            return host.available(plugin_name)

        try:
            catalog.register(
                spec.name,
                build_handler(spec, host, consent),
                owner=f"plugin:{spec.plugin}",
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
