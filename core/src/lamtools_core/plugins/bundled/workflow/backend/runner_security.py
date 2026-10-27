"""Host grants, credential resolution and runtime secret redaction."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from .credentials import CredentialError, CredentialRef, is_credential_ref
from .runner_context import WorkflowExecutionContext


@dataclass(frozen=True, slots=True)
class _WorkflowAuthorizationGrants:
    capabilities: frozenset[str] = frozenset()
    resources: dict[str, Any] = field(default_factory=dict, compare=False)


def _grant_names(value: Any) -> set[str]:
    """Collect explicit names from a host grant value."""

    result: set[str] = set()
    if isinstance(value, str):
        name = value.strip()
        if name:
            result.add(name)
    elif isinstance(value, Mapping):
        for key, nested in value.items():
            name = str(key).strip()
            if isinstance(nested, bool):
                if nested and name:
                    result.add(name)
            elif isinstance(nested, (list, tuple, set, frozenset)):
                result.update(_grant_names(nested))
            elif isinstance(nested, Mapping):
                # ``{"network": {"allowed": true}}`` is a common host shape.
                enabled = nested.get("allowed", nested.get("granted", nested.get("enabled")))
                if enabled is True and name:
                    result.add(name)
        # A mapping may itself be one compact declaration, e.g.
        # ``{"allowed": ["network"]}``.
        for key in ("allowed", "granted", "capabilities", "requires", "names"):
            if key in value:
                result.update(_grant_names(value[key]))
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            result.update(_grant_names(item))
    return result


def _workflow_authorization_grants(
    context: WorkflowExecutionContext,
) -> _WorkflowAuthorizationGrants:
    """Read only explicit capability/resource grants from host context."""

    capability_names: set[str] = set()
    resource_names: set[str] = set()
    resource_specs: dict[str, Any] = {}
    containers = (
        context.capabilities if isinstance(context.capabilities, Mapping) else {},
        context.permissions if isinstance(context.permissions, Mapping) else {},
    )
    capability_keys = {
        "capabilities", "allowed_capabilities", "allow_capabilities", "grants",
        "allowed", "enabled_capabilities", "requires",
    }
    resource_keys = {
        "resources", "resource", "resource_classes", "allowed_resources",
        "allowed_resource_classes", "resource_class", "allowed_resource_class",
    }
    for container in containers:
        # Direct boolean maps (``{"network": true}``) are explicit grants.
        capability_names.update(
            name for name, value in container.items()
            if isinstance(value, bool) and value and str(name).strip()
        )
        for key, value in container.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in capability_keys:
                capability_names.update(_grant_names(value))
            if normalized in resource_keys:
                if normalized in {"resource_class", "allowed_resource_class"} and isinstance(value, str):
                    resource_names.add(value.strip())
                elif isinstance(value, Mapping):
                    for resource_name, resource_value in value.items():
                        clean_name = str(resource_name).strip()
                        if not clean_name:
                            continue
                        resource_names.add(clean_name)
                        resource_specs[clean_name] = resource_value
                else:
                    resource_names.update(_grant_names(value))
        # Some hosts expose the resource grant as a nested capability map.
        nested_resources = container.get("resource_capabilities")
        if isinstance(nested_resources, Mapping):
            for resource_name, resource_value in nested_resources.items():
                clean_name = str(resource_name).strip()
                if clean_name:
                    resource_names.add(clean_name)
                    resource_specs[clean_name] = resource_value
    return _WorkflowAuthorizationGrants(
        capabilities=frozenset(capability_names),
        resources={name: resource_specs.get(name, True) for name in resource_names},
    )


def _workflow_resource_authorized(
    resource_class: str,
    requirements: Any,
    resources: Mapping[str, Any],
) -> bool:
    """Check class and declared data-only limits against host grants."""

    available = resources.get(resource_class)
    if available is None:
        return False
    if not requirements:
        return True
    if not isinstance(requirements, Mapping) or not isinstance(available, Mapping):
        return False
    for key, required in requirements.items():
        if key not in available:
            return False
        actual = available[key]
        if isinstance(required, (int, float)) and not isinstance(required, bool):
            if not isinstance(actual, (int, float)) or isinstance(actual, bool) or actual < required:
                return False
        elif actual != required:
            return False
    return True


def _credential_ref(value: Any) -> CredentialRef | None:
    if isinstance(value, CredentialRef):
        return value
    if isinstance(value, Mapping) and is_credential_ref(value):
        return CredentialRef.from_dict(value)
    return None


async def _resolve_workflow_credentials(
    value: Any,
    resolver: Any,
    context: WorkflowExecutionContext | None,
    resolved: dict[str, Any],
    secrets: list[Any],
    *,
    path: str = "workflow",
) -> Any:
    """Resolve explicit credential references without mutating source data."""

    ref = _credential_ref(value)
    if ref is not None:
        # The transient context is intentionally keyed by the public
        # credential identifier; provider/scope remain part of the ref sent to
        # the resolver, but are never exposed as a persistence key.
        cache_key = ref.credential_id
        if cache_key not in resolved:
            if resolver is None:
                raise CredentialError(
                    f"credential reference at {path} requires a credential resolver"
                )
            if isinstance(resolver, Mapping):
                if ref.credential_id not in resolver:
                    raise CredentialError(f"credential not found: {ref.credential_id}")
                result = resolver[ref.credential_id]
            else:
                result = await ref.aresolve(resolver, context=context)
            resolved[cache_key] = result
            secrets.append(result)
        return resolved[cache_key]
    if isinstance(value, Mapping):
        return {
            key: await _resolve_workflow_credentials(
                nested, resolver, context, resolved, secrets, path=f"{path}.{key}"
            )
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [
            await _resolve_workflow_credentials(
                nested, resolver, context, resolved, secrets, path=f"{path}[{index}]"
            )
            for index, nested in enumerate(value)
        ]
    if isinstance(value, tuple):
        return tuple(
            [
                await _resolve_workflow_credentials(
                    nested, resolver, context, resolved, secrets, path=f"{path}[{index}]"
                )
                for index, nested in enumerate(value)
            ]
        )
    return value


def _contains_credential_ref(value: Any) -> bool:
    if _credential_ref(value) is not None:
        return True
    if isinstance(value, Mapping):
        return any(_contains_credential_ref(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_credential_ref(item) for item in value)
    return False


def _redact_runtime_secrets(value: Any, secrets: list[Any]) -> Any:
    """Prevent resolved values from crossing result/event/snapshot boundaries."""

    if not secrets:
        return value
    for secret in secrets:
        if secret is None:
            continue
        try:
            if type(value) is type(secret) and value == secret:
                return "[REDACTED]"
        except Exception:  # noqa: BLE001 - hostile host value comparison
            pass
        if isinstance(value, str) and isinstance(secret, str) and secret:
            if secret in value:
                return value.replace(secret, "[REDACTED]")
    if isinstance(value, Mapping):
        return {
            key: _redact_runtime_secrets(nested, secrets)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [_redact_runtime_secrets(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_runtime_secrets(item, secrets) for item in value)
    return value


def _redact_exception_text(exc: BaseException, secrets: list[Any]) -> str:
    return str(_redact_runtime_secrets(str(exc), secrets)) or type(exc).__name__
