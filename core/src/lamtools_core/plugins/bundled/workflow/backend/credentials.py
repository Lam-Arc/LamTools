"""Workflow credential references and the runtime resolution seam.

Persisted workflow documents may identify a credential, but they must never
contain the credential material.  The resolver is supplied by the host at
execution time (the first implementation can remain local and file-backed),
which keeps this package independent of a particular Vault or cloud service.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import inspect
import json
import re
from typing import Any, Protocol, runtime_checkable


class CredentialError(ValueError):
    """Raised when a credential reference or persisted payload is unsafe."""


CredentialSerializationError = CredentialError
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

# Key names are intentionally exact (after normalisation).  A config field
# such as ``tokenizer`` is not a credential, while ``api_key`` is.
SECRET_KEYS = frozenset(
    {
        "secret",
        "secrets",
        "password",
        "passwd",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "auth_token",
        "client_secret",
        "private_key",
        "secret_key",
        "credential_data",
        "credential_secret",
    }
)


def _identifier(value: Any, field_name: str, *, optional: bool = False) -> str:
    text = str(value or "").strip()
    if not text and optional:
        return ""
    if not text:
        raise CredentialError(f"{field_name} is required")
    if len(text) > 512 or _CONTROL_RE.search(text) or any(char.isspace() for char in text):
        raise CredentialError(f"{field_name} must be a non-whitespace identifier")
    return text


@dataclass(frozen=True, slots=True, init=False)
class CredentialRef:
    """A non-secret identifier resolved by the host at runtime.

    ``credential_id`` is canonical.  ``id`` and ``ref`` are accepted as
    constructor/parser aliases because older integrations use both spellings.
    ``scope`` defaults to ``workflow`` to make cross-workflow use explicit.
    """

    credential_id: str
    provider: str = ""
    scope: str = "workflow"

    def __init__(
        self,
        credential_id: str = "",
        provider: str = "",
        scope: str = "workflow",
        *,
        id: str | None = None,
        ref: str | None = None,
    ) -> None:
        aliases = [value for value in (id, ref) if value is not None]
        if aliases and credential_id and any(str(value) != str(credential_id) for value in aliases):
            raise CredentialError("credential id aliases disagree")
        if aliases:
            credential_id = str(aliases[0])
        object.__setattr__(self, "credential_id", _identifier(credential_id, "credential_id"))
        object.__setattr__(self, "provider", _identifier(provider, "provider", optional=True))
        object.__setattr__(self, "scope", _identifier(scope or "workflow", "scope"))

    @property
    def id(self) -> str:
        return self.credential_id

    @property
    def ref(self) -> str:
        return self.credential_id

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CredentialRef":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise CredentialError("credential must be a reference object")
        allowed = {"credential_id", "id", "ref", "provider", "provider_id", "scope"}
        unknown = sorted(str(key) for key in value if str(key) not in allowed)
        if unknown:
            raise CredentialError(f"unknown credential reference fields: {unknown}")
        return cls(
            credential_id=str(value.get("credential_id") or value.get("id") or value.get("ref") or ""),
            provider=str(value.get("provider") or value.get("provider_id") or ""),
            scope=str(value.get("scope") or "workflow"),
        )

    def to_dict(self) -> dict[str, str]:
        result = {"credential_id": self.credential_id, "scope": self.scope}
        if self.provider:
            result["provider"] = self.provider
        return result

    # A separate method makes the logging boundary obvious to callers.  It
    # intentionally returns the same non-secret reference representation.
    def to_redacted_dict(self) -> dict[str, str]:
        return self.to_dict()

    def resolve(self, resolver: Any, *, context: Any = None) -> Any:
        """Resolve through a host resolver, returning a value or awaitable."""

        if resolver is None:
            raise CredentialError("a credential resolver is required")
        call = getattr(resolver, "resolve", None)
        if call is None:
            call = getattr(resolver, "resolve_credential", None)
        if call is None and callable(resolver):
            call = resolver
        if call is None:
            raise TypeError("credential resolver must expose resolve() or be callable")
        kwargs = {"context": context, "credential": self, "ref": self}
        try:
            parameters = inspect.signature(call).parameters
        except (TypeError, ValueError):
            return call(self)
        accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
        selected = kwargs if accepts_kwargs else {name: value for name, value in kwargs.items() if name in parameters}
        positional = [
            parameter
            for parameter in parameters.values()
            if parameter.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
        ]
        if positional and positional[0].name not in selected:
            return call(self, **selected)
        return call(**selected)

    async def aresolve(self, resolver: Any, *, context: Any = None) -> Any:
        value = self.resolve(resolver, context=context)
        return await value if inspect.isawaitable(value) else value


@runtime_checkable
class CredentialResolver(Protocol):
    """Host-owned runtime credential lookup interface."""

    def resolve(self, credential: CredentialRef, *, context: Any = None) -> Any: ...


def is_credential_ref(value: object) -> bool:
    """Return true only for an explicit reference-shaped mapping."""

    return isinstance(value, Mapping) and bool(
        value.get("credential_id") or value.get("ref")
    ) and set(str(key) for key in value).issubset(
        {"credential_id", "id", "ref", "provider", "provider_id", "scope"}
    )


def credential_ref_from_dict(value: Mapping[str, Any]) -> CredentialRef:
    return CredentialRef.from_dict(value)


def serialize_credential_ref(value: CredentialRef | Mapping[str, Any]) -> dict[str, str]:
    ref = value if isinstance(value, CredentialRef) else CredentialRef.from_dict(value)
    return ref.to_redacted_dict()


def _normalise_secret_key(key: Any) -> str:
    return str(key).strip().lower().replace("-", "_")


def serialize_workflow_value(value: Any, *, path: str = "workflow") -> Any:
    """Serialize JSON data and refs while rejecting embedded secrets.

    This is the persistence boundary used by the V2 document serializer.  It
    raises instead of silently redacting, because silently dropping a secret
    would make a workflow appear valid while changing its behaviour.
    """

    if isinstance(value, CredentialRef):
        return value.to_dict()
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise CredentialError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise CredentialError(f"{path} has a non-string object key")
            if _normalise_secret_key(key) in SECRET_KEYS:
                if isinstance(nested, CredentialRef) or is_credential_ref(nested):
                    result[key] = serialize_credential_ref(nested)
                    continue
                raise CredentialError(f"{path}.{key} contains secret material; use CredentialRef")
            result[key] = serialize_workflow_value(nested, path=f"{path}.{key}")
        try:
            json.dumps(result, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise CredentialError(f"{path} must contain JSON values or CredentialRef") from exc
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, memoryview)):
        return [serialize_workflow_value(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    raise CredentialError(f"{path} must contain JSON values or CredentialRef")


def assert_no_secrets(value: Any, *, path: str = "workflow") -> None:
    """Validate a persisted value without changing it."""

    serialize_workflow_value(value, path=path)


def redact_workflow_value(value: Any, *, path: str = "workflow") -> Any:
    """Build a safe logging projection, replacing secret values in-place."""

    if isinstance(value, CredentialRef):
        return value.to_redacted_dict()
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, nested in value.items():
            if _normalise_secret_key(key) in SECRET_KEYS:
                result[str(key)] = "[REDACTED]" if nested is not None else None
            else:
                result[str(key)] = redact_workflow_value(nested, path=f"{path}.{key}")
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        return [redact_workflow_value(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    return deepcopy(value)


# Names used by host adapters and older design notes.
CredentialReference = CredentialRef
WorkflowCredentialRef = CredentialRef
WorkflowCredentialResolver = CredentialResolver
serialize_redacted = redact_workflow_value
serialize_workflow_credentials = serialize_workflow_value


__all__ = [
    "CredentialError",
    "CredentialSerializationError",
    "CredentialRef",
    "CredentialReference",
    "CredentialResolver",
    "WorkflowCredentialRef",
    "WorkflowCredentialResolver",
    "assert_no_secrets",
    "credential_ref_from_dict",
    "is_credential_ref",
    "redact_workflow_value",
    "serialize_credential_ref",
    "serialize_redacted",
    "serialize_workflow_credentials",
    "serialize_workflow_value",
]
