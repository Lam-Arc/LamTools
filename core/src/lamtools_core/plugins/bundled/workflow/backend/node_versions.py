"""Explicit, host-registered Workflow node schema migrations.

Node versions are data-contract versions, not package versions.  A migration
is installed explicitly by a trusted host/plugin and is applied in a
contiguous directed chain; no module or callable is ever imported from a
workflow document.  Documents that have no requested upgrade remain readable
at their stored version.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
import inspect
from typing import Any


class NodeVersionError(ValueError):
    """Raised when a node version or migration chain is invalid."""


MigrationCallable = Callable[[dict[str, Any]], Mapping[str, Any] | dict[str, Any]]


def parse_node_version(value: Any, *, default: int = 1) -> int:
    """Parse a positive integer node version while retaining legacy defaults."""

    if value is None or value == "":
        value = default
    if isinstance(value, bool):
        raise NodeVersionError("node type_version must be a positive integer")
    if isinstance(value, int):
        version = value
    elif isinstance(value, str) and value.strip().isdigit():
        version = int(value.strip())
    else:
        raise NodeVersionError("node type_version must be a positive integer")
    if version < 1:
        raise NodeVersionError("node type_version must be a positive integer")
    return version


@dataclass(frozen=True, slots=True)
class NodeMigration:
    type_id: str
    from_version: int
    to_version: int
    migrate: MigrationCallable

    def __post_init__(self) -> None:
        if not str(self.type_id or "").strip():
            raise NodeVersionError("migration type_id is required")
        source = parse_node_version(self.from_version)
        target = parse_node_version(self.to_version)
        if target <= source:
            raise NodeVersionError("node migrations must move to a higher version")
        if not callable(self.migrate) or inspect.iscoroutinefunction(self.migrate):
            raise NodeVersionError("node migration must be a synchronous callable")
        object.__setattr__(self, "type_id", str(self.type_id).strip())
        object.__setattr__(self, "from_version", source)
        object.__setattr__(self, "to_version", target)


class NodeMigrationRegistry:
    """Explicit migration graph keyed by node type and source version."""

    def __init__(self, *, current_versions: Mapping[str, int] | None = None) -> None:
        self._migrations: dict[tuple[str, int], NodeMigration] = {}
        self._current_versions: dict[str, int] = {}
        for type_id, version in (current_versions or {}).items():
            self.set_current_version(type_id, version)

    @staticmethod
    def _type_id(type_id: Any) -> str:
        clean = str(type_id or "").strip()
        if not clean or any(char.isspace() for char in clean) or ":" in clean:
            raise NodeVersionError("node type_id must be a safe token")
        return clean

    def set_current_version(self, type_id: str, version: int) -> int:
        clean = self._type_id(type_id)
        parsed = parse_node_version(version)
        self._current_versions[clean] = parsed
        return parsed

    # Short alias used by registry adapters.
    set_target_version = set_current_version

    def register(
        self,
        type_id: str,
        from_version: int,
        to_version: int,
        migrate: MigrationCallable,
        *,
        replace: bool = False,
    ) -> NodeMigration:
        clean = self._type_id(type_id)
        migration = NodeMigration(clean, parse_node_version(from_version), parse_node_version(to_version), migrate)
        key = (clean, migration.from_version)
        if key in self._migrations and not replace:
            raise ValueError(
                f"workflow node migration already registered: {clean} {migration.from_version}"
            )
        self._migrations[key] = migration
        self._current_versions[clean] = max(
            self._current_versions.get(clean, 1), migration.to_version
        )
        return migration

    register_migration = register

    def get(self, type_id: str, from_version: int) -> NodeMigration | None:
        return self._migrations.get((self._type_id(type_id), parse_node_version(from_version)))

    def list(self, type_id: str | None = None) -> list[NodeMigration]:
        values = list(self._migrations.values())
        if type_id is not None:
            clean = self._type_id(type_id)
            values = [item for item in values if item.type_id == clean]
        return sorted(values, key=lambda item: (item.type_id, item.from_version, item.to_version))

    def current_version(self, type_id: str, *, default: int = 1) -> int:
        clean = self._type_id(type_id)
        return self._current_versions.get(clean, parse_node_version(default))

    latest_version = current_version

    def resolve_chain(
        self,
        type_id: str,
        from_version: int,
        to_version: int | None = None,
    ) -> tuple[NodeMigration, ...]:
        clean = self._type_id(type_id)
        source = parse_node_version(from_version)
        target = self.current_version(clean) if to_version is None else parse_node_version(to_version)
        if target < source:
            raise NodeVersionError(
                f"cannot downgrade node {clean!r} from version {source} to {target}"
            )
        if target == source:
            return ()
        # Each source version has at most one explicit next migration.  Walk
        # it directly to make missing steps and cycles visible to callers.
        chain: list[NodeMigration] = []
        cursor = source
        seen: set[int] = set()
        while cursor < target:
            if cursor in seen:
                raise NodeVersionError(f"cycle in node migration chain for {clean!r}")
            seen.add(cursor)
            migration = self._migrations.get((clean, cursor))
            if migration is None or migration.to_version > target:
                raise NodeVersionError(
                    f"no explicit migration chain for node {clean!r}: {cursor} -> {target}"
                )
            chain.append(migration)
            cursor = migration.to_version
        if cursor != target:
            raise NodeVersionError(
                f"no explicit migration chain for node {clean!r}: {source} -> {target}"
            )
        return tuple(chain)

    resolve = resolve_chain

    def migrate_node(
        self,
        node: Mapping[str, Any],
        *,
        target_version: int | None = None,
        type_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(node, Mapping):
            raise NodeVersionError("node definition must be an object")
        result = deepcopy(dict(node))
        raw_type = type_id or result.get("type_id") or result.get("typeId") or result.get("kind")
        clean = self._type_id(raw_type)
        nested_type = result.get("type") if isinstance(result.get("type"), Mapping) else {}
        raw_version = result.get(
            "type_version",
            result.get("typeVersion", nested_type.get("version", 1)),
        )
        source = parse_node_version(raw_version)
        chain = self.resolve_chain(clean, source, target_version)
        for migration in chain:
            migrated = migration.migrate(deepcopy(result))
            if inspect.isawaitable(migrated) or not isinstance(migrated, Mapping):
                raise NodeVersionError(
                    f"migration {clean} {migration.from_version}->{migration.to_version} must return an object"
                )
            result = deepcopy(dict(migrated))
            # A migration may rewrite type_id only to the same node type; a
            # cross-type replacement would bypass registry trust boundaries.
            migrated_type = self._type_id(
                result.get("type_id") or result.get("typeId") or result.get("kind") or clean
            )
            if migrated_type != clean:
                raise NodeVersionError("node migration cannot change type_id")
            result["type_id"] = clean
            result["type_version"] = migration.to_version
            if isinstance(result.get("type"), Mapping):
                nested = deepcopy(dict(result["type"]))
                nested["id"] = clean
                nested["version"] = migration.to_version
                result["type"] = nested
        return result

    migrate = migrate_node
    apply = migrate_node


def resolve_node_version(value: Any, *, default: int = 1) -> int:
    """Public parsing helper retained for old node readers."""

    return parse_node_version(value, default=default)


__all__ = [
    "MigrationCallable",
    "NodeMigration",
    "NodeMigrationRegistry",
    "NodeVersionError",
    "parse_node_version",
    "resolve_node_version",
]
