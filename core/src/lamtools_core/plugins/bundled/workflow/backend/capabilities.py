"""Data-only node capability and resource-class declarations.

These declarations describe what a node may need; they do not grant a
permission and do not load an executor.  The host remains responsible for
checking the declaration against its execution policy before running a node.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
import json
import re
from typing import Any


class CapabilityError(ValueError):
    """Raised when a capability/resource declaration is malformed."""


_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")


def _token(value: Any, *, field_name: str, default: str = "") -> str:
    text = str(value or default).strip()
    if not text or not _TOKEN_RE.fullmatch(text):
        raise CapabilityError(f"{field_name} must be a safe token")
    return text


def _json_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CapabilityError(f"{field_name} must be an object")
    try:
        result = deepcopy(dict(value))
        json.dumps(result, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CapabilityError(f"{field_name} must contain JSON values only") from exc
    if any(not isinstance(key, str) for key in result):
        raise CapabilityError(f"{field_name} must use string keys")
    return result


@dataclass(frozen=True, slots=True)
class ResourceClass:
    """A named host resource class and optional data-only requirements."""

    name: str = "default"
    description: str = ""
    limits: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _token(self.name, field_name="resource_class", default="default"))
        object.__setattr__(self, "description", str(self.description or "").strip())
        object.__setattr__(self, "limits", _json_mapping(self.limits, field_name="resource limits"))

    @property
    def id(self) -> str:
        return self.name

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"name": self.name}
        if self.description:
            result["description"] = self.description
        if self.limits:
            result["limits"] = deepcopy(self.limits)
        return result


@dataclass(frozen=True, slots=True, init=False)
class WorkflowNodeCapabilities:
    """Capabilities and resource class declared by one node type."""

    capabilities: tuple[str, ...]
    resource_class: str
    resource_requirements: dict[str, Any] = field(default_factory=dict, compare=False)

    def __init__(
        self,
        capabilities: Iterable[str] = (),
        resource_class: str = "default",
        resource_requirements: Mapping[str, Any] | None = None,
        *,
        resources: Mapping[str, Any] | None = None,
    ) -> None:
        if resources is not None:
            if resource_requirements is not None and dict(resource_requirements) != dict(resources):
                raise CapabilityError("resource requirements aliases disagree")
            resource_requirements = resources
        if isinstance(capabilities, (str, bytes, bytearray)):
            capabilities = (capabilities.decode() if isinstance(capabilities, bytes) else str(capabilities),)
        normalized: list[str] = []
        seen: set[str] = set()
        for item in capabilities:
            capability = _token(item, field_name="capability")
            if capability not in seen:
                seen.add(capability)
                normalized.append(capability)
        object.__setattr__(self, "capabilities", tuple(normalized))
        object.__setattr__(self, "resource_class", _token(resource_class, field_name="resource_class", default="default"))
        object.__setattr__(self, "resource_requirements", _json_mapping(resource_requirements, field_name="resource_requirements"))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "WorkflowNodeCapabilities":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise CapabilityError("node capabilities must be an object")
        raw_caps = value.get("capabilities", value.get("requires", ()))
        if isinstance(raw_caps, Mapping):
            # A mapping is accepted only as a compact boolean declaration:
            # ``{"network": true}``; values are not permission grants.
            if any(not isinstance(enabled, bool) for enabled in raw_caps.values()):
                raise CapabilityError("capability mapping values must be booleans")
            raw_caps = [str(name) for name, enabled in raw_caps.items() if enabled]
        elif isinstance(raw_caps, str):
            raw_caps = [raw_caps]
        elif not isinstance(raw_caps, (list, tuple, set, frozenset)):
            raise CapabilityError("capabilities must be an array of names")
        resource_class = value.get("resource_class", value.get("resourceClass", "default"))
        requirements = value.get("resource_requirements", value.get("resources", {}))
        return cls(raw_caps, str(resource_class or "default"), requirements)

    def declares(self, capability: str) -> bool:
        return str(capability or "").strip() in self.capabilities

    # ``supports`` is deliberately an alias for declaration checks; actual
    # host grants are evaluated outside this package.
    supports = declares

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilities": list(self.capabilities),
            "resource_class": self.resource_class,
            "resource_requirements": deepcopy(self.resource_requirements),
        }


class WorkflowCapabilityRegistry:
    """Registry of data-only capability declarations keyed by node type."""

    def __init__(self) -> None:
        self._declarations: dict[str, WorkflowNodeCapabilities] = {}

    def register(
        self,
        type_id: str,
        declaration: WorkflowNodeCapabilities | Mapping[str, Any],
        *,
        replace: bool = False,
    ) -> WorkflowNodeCapabilities:
        clean_type = _token(type_id, field_name="node type")
        spec = declaration if isinstance(declaration, WorkflowNodeCapabilities) else WorkflowNodeCapabilities.from_dict(declaration)
        if clean_type in self._declarations and not replace:
            raise ValueError(f"workflow node capabilities already registered: {clean_type}")
        self._declarations[clean_type] = spec
        return spec

    def get(self, type_id: str) -> WorkflowNodeCapabilities | None:
        return self._declarations.get(str(type_id or "").strip())

    def require(self, type_id: str) -> WorkflowNodeCapabilities:
        result = self.get(type_id)
        if result is None:
            raise KeyError(type_id)
        return result

    def list(self) -> dict[str, WorkflowNodeCapabilities]:
        return dict(sorted(self._declarations.items()))

    def capabilities_for(self, type_id: str) -> tuple[str, ...]:
        return self.require(type_id).capabilities

    def resource_class_for(self, type_id: str) -> str:
        return self.require(type_id).resource_class


# Friendly names used by plugin authors.
NodeCapability = WorkflowNodeCapabilities
NodeCapabilities = WorkflowNodeCapabilities
CapabilityDeclaration = WorkflowNodeCapabilities
ResourceClassDeclaration = ResourceClass
NodeCapabilityRegistry = WorkflowCapabilityRegistry


__all__ = [
    "CapabilityDeclaration",
    "CapabilityError",
    "NodeCapability",
    "NodeCapabilityRegistry",
    "NodeCapabilities",
    "ResourceClass",
    "ResourceClassDeclaration",
    "WorkflowCapabilityRegistry",
    "WorkflowNodeCapabilities",
]
