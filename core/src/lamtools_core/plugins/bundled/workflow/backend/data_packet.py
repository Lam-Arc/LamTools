"""The canonical item envelope used at Workflow node boundaries.

Workflow values historically crossed the runner as an arbitrary Python value.
That is convenient for the first-party nodes, but it makes a value carrying a
file, a pairing relationship, or provenance impossible to describe without
serialising the file itself.  This module is deliberately small: the packet
contains JSON values and *references* to Core-owned attachments; it never
owns binary bytes.

The legacy adapter is intentionally explicit.  A random mapping containing an
``items`` key is still an ordinary JSON value until a caller asks for
``WorkflowDataPacket.coerce`` (or ``from_legacy``), while a canonical packet
must carry the format/version envelope.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
import json
import math
import re
from typing import Any


DATA_PACKET_FORMAT = "lamtools.workflow.data-packet"
DATA_PACKET_VERSION = 1


class WorkflowDataPacketError(ValueError):
    """Raised when a data packet or reference is malformed."""


_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_URI_RE = re.compile(r"^(?:attachment|workspace|https?)://[^\s]+$", re.IGNORECASE)
_BINARY_FIELDS = frozenset(
    {
        "content",
        "data",
        "bytes",
        "blob",
        "body",
        "payload",
        "base64",
        "data_url",
        "data_uri",
        "inline",
        "raw_bytes",
        "storage_path",
        "local_path",
    }
)


def _copy_json(value: Any, *, path: str = "value") -> Any:
    """Validate and copy a JSON-compatible value.

    ``json.dumps`` alone accepts NaN and silently stringifies non-string map
    keys in a few call paths.  Both behaviours make a persisted packet
    ambiguous, so recurse first and reject them explicitly.
    """

    def walk(item: Any, location: str) -> Any:
        if item is None or isinstance(item, (str, bool, int)):
            return deepcopy(item)
        if isinstance(item, float):
            if not math.isfinite(item):
                raise WorkflowDataPacketError(f"{location} contains a non-finite number")
            return item
        if isinstance(item, Mapping):
            result: dict[str, Any] = {}
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise WorkflowDataPacketError(f"{location} has a non-string object key")
                result[key] = walk(nested, f"{location}.{key}")
            return result
        if isinstance(item, (list, tuple)):
            return [walk(nested, f"{location}[{index}]") for index, nested in enumerate(item)]
        raise WorkflowDataPacketError(
            f"{location} must contain JSON values only (got {type(item).__name__})"
        )

    result = walk(value, path)
    # Keep this as a final guard for unusual ``int`` subclasses and future
    # changes to the recursive validator.
    try:
        json.dumps(result, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise WorkflowDataPacketError(f"{path} must contain JSON values only") from exc
    return result


def _safe_identifier(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise WorkflowDataPacketError(f"{field_name} is required")
    if len(text) > 512 or _CONTROL_RE.search(text) or any(char.isspace() for char in text):
        raise WorkflowDataPacketError(f"{field_name} must be a non-whitespace identifier")
    return text


def _validate_reference_mapping(value: Mapping[str, Any], *, kind: str) -> None:
    for key, nested in value.items():
        lowered = str(key).strip().lower()
        if lowered in _BINARY_FIELDS:
            raise WorkflowDataPacketError(
                f"{kind} references cannot embed binary field {key!r}"
            )
        if isinstance(nested, (bytes, bytearray, memoryview)):
            raise WorkflowDataPacketError(f"{kind} references cannot contain bytes")
    # Reject data URLs even when a producer hides them in an otherwise valid
    # ``uri`` field.  A URI is a locator, not an inline transport.
    for key in ("uri", "url", "ref", "path"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.lower().startswith("data:"):
            raise WorkflowDataPacketError(f"{kind} references cannot contain data URLs")


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    """A reference to a Core attachment, never the attachment bytes."""

    id: str
    filename: str = ""
    mime_type: str = ""
    size: int | None = None
    checksum: str = ""
    uri: str = ""
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _safe_identifier(self.id, field_name="attachment id"))
        if self.filename:
            filename = str(self.filename).strip()
            if not filename or _CONTROL_RE.search(filename):
                raise WorkflowDataPacketError("attachment filename is invalid")
            object.__setattr__(self, "filename", filename)
        if self.mime_type:
            mime = str(self.mime_type).strip()
            if not mime or _CONTROL_RE.search(mime) or any(char.isspace() for char in mime):
                raise WorkflowDataPacketError("attachment mime_type is invalid")
            object.__setattr__(self, "mime_type", mime)
        if self.size is not None:
            if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
                raise WorkflowDataPacketError("attachment size must be a non-negative integer")
        if self.checksum:
            checksum = str(self.checksum).strip()
            if not checksum or _CONTROL_RE.search(checksum) or any(char.isspace() for char in checksum):
                raise WorkflowDataPacketError("attachment checksum is invalid")
            object.__setattr__(self, "checksum", checksum)
        if self.uri:
            uri = str(self.uri).strip()
            if not _URI_RE.match(uri) or uri.lower().startswith("workspace://"):
                raise WorkflowDataPacketError(
                    "attachment uri must be an attachment:// or http(s):// reference"
                )
            if uri.lower().startswith("attachment://"):
                target_id = uri[len("attachment://") :].strip()
                if target_id != self.id:
                    raise WorkflowDataPacketError("attachment uri id does not match attachment id")
            object.__setattr__(self, "uri", uri)
        metadata = _copy_json(self.metadata, path="attachment metadata")
        object.__setattr__(self, "metadata", metadata)

    @property
    def attachment_id(self) -> str:
        """Compatibility spelling used by the Core attachment service."""

        return self.id

    @classmethod
    def from_id(cls, attachment_id: str, **kwargs: Any) -> "AttachmentRef":
        return cls(id=attachment_id, **kwargs)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AttachmentRef":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise WorkflowDataPacketError("attachment must be a reference object")
        _validate_reference_mapping(value, kind="attachment")
        allowed = {
            "id",
            "attachment_id",
            "filename",
            "name",
            "mime_type",
            "mime",
            "size",
            "checksum",
            "sha256",
            "uri",
            "ref",
            "metadata",
        }
        unknown = sorted(str(key) for key in value if str(key) not in allowed)
        if unknown:
            raise WorkflowDataPacketError(f"unknown attachment reference fields: {unknown}")
        raw_id = value.get("id", value.get("attachment_id"))
        if raw_id in (None, ""):
            raw_uri = value.get("uri", value.get("ref"))
            if isinstance(raw_uri, str) and raw_uri.lower().startswith("attachment://"):
                raw_id = raw_uri[len("attachment://") :]
        uri = value.get("uri", value.get("ref", ""))
        return cls(
            id=raw_id or "",
            filename=str(value.get("filename") or value.get("name") or ""),
            mime_type=str(value.get("mime_type") or value.get("mime") or ""),
            size=value.get("size"),
            checksum=str(value.get("checksum") or value.get("sha256") or ""),
            uri=str(uri or ""),
            metadata=dict(value.get("metadata") or {}) if isinstance(value.get("metadata"), Mapping) else {},
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"id": self.id}
        if self.filename:
            result["filename"] = self.filename
        if self.mime_type:
            result["mime_type"] = self.mime_type
        if self.size is not None:
            result["size"] = self.size
        if self.checksum:
            result["checksum"] = self.checksum
        if self.uri:
            result["uri"] = self.uri
        if self.metadata:
            result["metadata"] = deepcopy(self.metadata)
        return result


@dataclass(frozen=True, slots=True, init=False)
class ArtifactRef:
    """A reference to an artifact manifest or locator.

    Artifact records may point at a workspace file or an attachment.  The
    reference accepts those URI schemes (and remote HTTP(S) locators), but it
    intentionally has no ``content``/``bytes`` field.
    """

    artifact_id: str
    uri: str = ""
    kind: str = ""
    mime_type: str = ""
    name: str = ""
    size: int | None = None
    checksum: str = ""
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def __init__(
        self,
        artifact_id: str = "",
        uri: str = "",
        kind: str = "",
        mime_type: str = "",
        name: str = "",
        size: int | None = None,
        checksum: str = "",
        metadata: Mapping[str, Any] | None = None,
        *,
        id: str | None = None,
    ) -> None:
        if id is not None:
            if artifact_id and artifact_id != id:
                raise WorkflowDataPacketError("artifact id aliases disagree")
            artifact_id = id
        object.__setattr__(self, "artifact_id", artifact_id)
        object.__setattr__(self, "uri", uri)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "mime_type", mime_type)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "size", size)
        object.__setattr__(self, "checksum", checksum)
        object.__setattr__(self, "metadata", dict(metadata or {}))
        self._validate()

    def _validate(self) -> None:
        object.__setattr__(self, "artifact_id", _safe_identifier(self.artifact_id, field_name="artifact id"))
        uri = str(self.uri or "").strip()
        if uri and not _URI_RE.match(uri):
            raise WorkflowDataPacketError(
                "artifact uri must use workspace://, attachment://, or http(s)://"
            )
        object.__setattr__(self, "uri", uri)
        for name in ("kind", "mime_type", "name", "checksum"):
            raw = str(getattr(self, name) or "").strip()
            if _CONTROL_RE.search(raw):
                raise WorkflowDataPacketError(f"artifact {name} is invalid")
            object.__setattr__(self, name, raw)
        if self.size is not None and (
            isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0
        ):
            raise WorkflowDataPacketError("artifact size must be a non-negative integer")
        object.__setattr__(self, "metadata", _copy_json(self.metadata, path="artifact metadata"))

    @property
    def id(self) -> str:
        return self.artifact_id

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactRef":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise WorkflowDataPacketError("artifact must be a reference object")
        _validate_reference_mapping(value, kind="artifact")
        allowed = {
            "artifact_id",
            "id",
            "uri",
            "ref",
            "path",
            "kind",
            "mime_type",
            "name",
            "filename",
            "size",
            "checksum",
            "sha256",
            "metadata",
        }
        unknown = sorted(str(key) for key in value if str(key) not in allowed)
        if unknown:
            raise WorkflowDataPacketError(f"unknown artifact reference fields: {unknown}")
        uri = str(value.get("uri", value.get("ref", value.get("path", ""))) or "")
        return cls(
            artifact_id=str(value.get("artifact_id") or value.get("id") or uri or ""),
            uri=uri,
            kind=str(value.get("kind") or ""),
            mime_type=str(value.get("mime_type") or ""),
            name=str(value.get("name") or value.get("filename") or ""),
            size=value.get("size"),
            checksum=str(value.get("checksum") or value.get("sha256") or ""),
            metadata=value.get("metadata") if isinstance(value.get("metadata"), Mapping) else {},
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"artifact_id": self.artifact_id}
        for key in ("uri", "kind", "mime_type", "name", "size", "checksum"):
            value = getattr(self, key)
            if value not in ("", None):
                result[key] = value
        if self.metadata:
            result["metadata"] = deepcopy(self.metadata)
        return result


@dataclass(frozen=True, slots=True)
class WorkflowDataItem:
    """One JSON item plus optional binary, pair, and provenance references."""

    json: Any = field(default_factory=dict)
    binary: AttachmentRef | None = None
    paired: tuple[Any, ...] = ()
    lineage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "json", _copy_json(self.json, path="item.json"))
        binary = self.binary
        if binary is not None and not isinstance(binary, AttachmentRef):
            binary = AttachmentRef.from_dict(binary) if isinstance(binary, Mapping) else None
            if binary is None:
                raise WorkflowDataPacketError("item.binary must be an AttachmentRef")
        object.__setattr__(self, "binary", binary)
        paired = self.paired
        if paired is None:
            normalized_paired: list[Any] = []
        elif isinstance(paired, Mapping) or isinstance(paired, (str, bytes, bytearray)):
            normalized_paired = [_copy_json(paired, path="item.paired")]
        elif isinstance(paired, Sequence):
            normalized_paired = [_copy_json(value, path=f"item.paired[{index}]") for index, value in enumerate(paired)]
        else:
            raise WorkflowDataPacketError("item.paired must be a JSON value or array")
        object.__setattr__(self, "paired", tuple(normalized_paired))
        lineage = self.lineage
        if lineage is None:
            normalized_lineage: list[str] = []
        elif isinstance(lineage, str):
            normalized_lineage = [lineage]
        elif isinstance(lineage, Sequence) and not isinstance(lineage, (bytes, bytearray)):
            normalized_lineage = [str(value).strip() for value in lineage]
        else:
            raise WorkflowDataPacketError("item.lineage must be a string or array")
        if any(not value or _CONTROL_RE.search(value) for value in normalized_lineage):
            raise WorkflowDataPacketError("item.lineage entries must be non-empty identifiers")
        object.__setattr__(self, "lineage", tuple(normalized_lineage))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowDataItem":
        if not isinstance(value, Mapping):
            raise WorkflowDataPacketError("packet items must be objects")
        allowed = {"json", "binary", "paired", "paired_item", "pairedItem", "lineage"}
        unknown = sorted(str(key) for key in value if str(key) not in allowed)
        if unknown:
            raise WorkflowDataPacketError(f"unknown data item fields: {unknown}")
        if "json" not in value:
            raise WorkflowDataPacketError("packet item requires json")
        raw_binary = value.get("binary")
        binary = None if raw_binary is None else AttachmentRef.from_dict(raw_binary)
        paired = value.get("paired", value.get("paired_item", value.get("pairedItem", ())))
        return cls(
            json=value["json"],
            binary=binary,
            paired=paired,
            lineage=value.get("lineage", ()),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "json": deepcopy(self.json),
            "paired": [deepcopy(value) for value in self.paired],
            "lineage": list(self.lineage),
        }
        if self.binary is not None:
            result["binary"] = self.binary.to_dict()
        return result


@dataclass
class WorkflowDataPacket:
    """Canonical ``items[]`` packet.

    ``from_legacy`` wraps a legacy scalar/object/array as one item so the
    operation is lossless.  ``from_legacy_items`` is available for integrations
    whose legacy array already means “multiple workflow items”.
    """

    items: list[WorkflowDataItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.items, Mapping) or isinstance(self.items, (str, bytes, bytearray)):
            raise WorkflowDataPacketError("packet items must be an array")
        if not isinstance(self.items, Sequence):
            raise WorkflowDataPacketError("packet items must be an array")
        normalized: list[WorkflowDataItem] = []
        for index, item in enumerate(self.items):
            if isinstance(item, WorkflowDataItem):
                normalized.append(item)
            elif isinstance(item, Mapping):
                normalized.append(WorkflowDataItem.from_dict(item))
            else:
                raise WorkflowDataPacketError(f"packet item {index} must be an object")
        self.items = normalized

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowDataPacket":
        if not isinstance(value, Mapping):
            raise WorkflowDataPacketError("data packet must be an object")
        if value.get("format") != DATA_PACKET_FORMAT:
            raise WorkflowDataPacketError(
                f"expected {DATA_PACKET_FORMAT!r} packet format"
            )
        version = value.get("version")
        if isinstance(version, bool) or not isinstance(version, int) or version != DATA_PACKET_VERSION:
            raise WorkflowDataPacketError(f"unsupported data packet version: {version!r}")
        raw_items = value.get("items")
        if not isinstance(raw_items, list):
            raise WorkflowDataPacketError("data packet items must be an array")
        return cls([WorkflowDataItem.from_dict(item) for item in raw_items])

    @classmethod
    def from_legacy(cls, value: Any) -> "WorkflowDataPacket":
        """Explicitly wrap one legacy scalar, object, or array as one item."""

        if isinstance(value, cls):
            return cls(list(value.items))
        # A canonical envelope is only accepted when its marker is present;
        # arbitrary old dictionaries therefore remain ordinary item JSON.
        if is_data_packet(value):
            return cls.from_dict(value)
        return cls([WorkflowDataItem(json=value)])

    @classmethod
    def from_legacy_items(cls, value: Sequence[Any]) -> "WorkflowDataPacket":
        """Adapt a legacy array whose elements represent separate items."""

        if isinstance(value, (str, bytes, bytearray, Mapping)):
            raise WorkflowDataPacketError("legacy item sequence must be an array")
        return cls([WorkflowDataItem(json=item) for item in value])

    @classmethod
    def coerce(cls, value: Any) -> "WorkflowDataPacket":
        """Read a canonical packet or explicitly adapt a legacy value."""

        return cls.from_dict(value) if is_data_packet(value) else cls.from_legacy(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": DATA_PACKET_FORMAT,
            "version": DATA_PACKET_VERSION,
            "items": [item.to_dict() for item in self.items],
        }

    def to_legacy(self) -> Any:
        """Project back to the old scalar/object/array value shape."""

        values = [deepcopy(item.json) for item in self.items]
        if len(values) == 1:
            return values[0]
        return values


def is_data_packet(value: object) -> bool:
    """Return true only for a marked, structurally canonical packet."""

    if not isinstance(value, Mapping):
        return False
    if value.get("format") != DATA_PACKET_FORMAT or value.get("version") != DATA_PACKET_VERSION:
        return False
    items = value.get("items")
    return isinstance(items, list) and all(isinstance(item, Mapping) and "json" in item for item in items)


def adapt_legacy_value(value: Any) -> WorkflowDataPacket:
    """Named compatibility helper for callers that prefer a function API."""

    return WorkflowDataPacket.from_legacy(value)


def adapt_data_packet(value: Any) -> WorkflowDataPacket:
    """Normalize either a canonical packet or a legacy value to a packet."""

    if isinstance(value, WorkflowDataPacket):
        return value
    if is_data_packet(value):
        return WorkflowDataPacket.from_dict(value)
    return WorkflowDataPacket.from_legacy(value)


def packet_to_legacy(value: WorkflowDataPacket | Mapping[str, Any]) -> Any:
    packet = value if isinstance(value, WorkflowDataPacket) else WorkflowDataPacket.from_dict(value)
    return packet.to_legacy()


# Friendly aliases used by host integrations and earlier design notes.
DataPacket = WorkflowDataPacket
DataPacketItem = WorkflowDataItem
WorkflowItem = WorkflowDataItem
BinaryAttachmentRef = AttachmentRef


__all__ = [
    "DATA_PACKET_FORMAT",
    "DATA_PACKET_VERSION",
    "ArtifactRef",
    "AttachmentRef",
    "BinaryAttachmentRef",
    "DataPacket",
    "DataPacketItem",
    "WorkflowDataItem",
    "WorkflowDataPacket",
    "WorkflowDataPacketError",
    "WorkflowItem",
    "adapt_data_packet",
    "adapt_legacy_value",
    "is_data_packet",
    "packet_to_legacy",
]
