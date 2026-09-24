"""Persistent user-defined model groups.

Groups are configuration, not runtime state: the authoritative file lives in
the unified Core config directory beside provider/model JSONC definitions.
Memberships reference the authoritative ``model_id`` and never duplicate model
or provider connection data.
"""

from __future__ import annotations

import copy
import json
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from lamtools_core.config.root import atomic_write_text, core_config_file
from lamtools_core.llm.profiles import load_jsonc

from .id_validation import validate_config_id

MODEL_GROUPS_FILENAME = "model_groups.jsonc"
_LOCK = threading.RLock()


class ModelGroupRevisionConflict(RuntimeError):
    """Raised when a caller updates an out-of-date group catalog."""


@dataclass(frozen=True)
class ModelGroup:
    id: str
    name: str
    order: int = 0


@dataclass(frozen=True)
class ModelGroupMembership:
    group_id: str
    model_id: str
    order: int = 0


class ModelGroupStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else core_config_file(MODEL_GROUPS_FILENAME)

    def snapshot(self, *, available_model_ids: Iterable[str] | None = None) -> dict[str, Any]:
        with _LOCK:
            data = self._read()
        available = None if available_model_ids is None else {str(item) for item in available_model_ids}
        groups = sorted(data["groups"], key=lambda item: (item["order"], item["id"]))
        memberships = sorted(
            data["memberships"], key=lambda item: (item["group_id"], item["order"], item["model_id"])
        )
        payload_memberships: list[dict[str, Any]] = []
        for item in memberships:
            rendered = copy.deepcopy(item)
            if available is not None:
                rendered["available"] = item["model_id"] in available
            payload_memberships.append(rendered)
        members_by_group: dict[str, list[str]] = {}
        dangling_by_group: dict[str, list[str]] = {}
        for item in memberships:
            if available is not None and item["model_id"] not in available:
                dangling_by_group.setdefault(item["group_id"], []).append(item["model_id"])
            else:
                members_by_group.setdefault(item["group_id"], []).append(item["model_id"])
        payload_groups = []
        for group in groups:
            rendered = copy.deepcopy(group)
            rendered["model_ids"] = members_by_group.get(group["id"], [])
            rendered["dangling_model_ids"] = dangling_by_group.get(group["id"], [])
            payload_groups.append(rendered)
        return {
            "version": 1,
            "revision": data["revision"],
            "groups": payload_groups,
            "memberships": payload_memberships,
        }

    def create(
        self,
        name: str,
        *,
        model_ids: Iterable[str] = (),
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        clean_name = _validate_name(name)
        with _LOCK:
            data = self._read()
            self._check_revision(data, expected_revision)
            _ensure_unique_name(data, clean_name)
            group_id = f"mg-{uuid.uuid4().hex}"
            data["groups"].append({"id": group_id, "name": clean_name, "order": len(data["groups"])})
            for order, model_id in enumerate(_unique_model_ids(model_ids)):
                data["memberships"].append({"group_id": group_id, "model_id": model_id, "order": order})
            self._commit(data)
            return {"group_id": group_id, **self.snapshot()}

    def update(
        self,
        group_id: str,
        *,
        name: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        group_id = validate_config_id("model group", group_id)
        clean_name = _validate_name(name)
        with _LOCK:
            data = self._read()
            self._check_revision(data, expected_revision)
            group = _find_group(data, group_id)
            _ensure_unique_name(data, clean_name, except_id=group_id)
            group["name"] = clean_name
            self._commit(data)
            return self.snapshot()

    def delete(self, group_id: str, *, expected_revision: int | None = None) -> dict[str, Any]:
        group_id = validate_config_id("model group", group_id)
        with _LOCK:
            data = self._read()
            self._check_revision(data, expected_revision)
            _find_group(data, group_id)
            data["groups"] = [item for item in data["groups"] if item["id"] != group_id]
            data["memberships"] = [item for item in data["memberships"] if item["group_id"] != group_id]
            _normalize_group_order(data)
            self._commit(data)
            return self.snapshot()

    def set_members(
        self,
        group_id: str,
        model_ids: Iterable[str],
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        group_id = validate_config_id("model group", group_id)
        model_ids = _unique_model_ids(model_ids)
        with _LOCK:
            data = self._read()
            self._check_revision(data, expected_revision)
            _find_group(data, group_id)
            data["memberships"] = [item for item in data["memberships"] if item["group_id"] != group_id]
            data["memberships"].extend(
                {"group_id": group_id, "model_id": model_id, "order": order}
                for order, model_id in enumerate(model_ids)
            )
            self._commit(data)
            return self.snapshot()

    def reorder(self, group_ids: Iterable[str], *, expected_revision: int | None = None) -> dict[str, Any]:
        requested = [validate_config_id("model group", item) for item in group_ids]
        if len(requested) != len(set(requested)):
            raise ValueError("group_ids must not contain duplicates")
        with _LOCK:
            data = self._read()
            self._check_revision(data, expected_revision)
            existing = {item["id"] for item in data["groups"]}
            if set(requested) != existing:
                raise ValueError("group_ids must contain every model group exactly once")
            order_by_id = {group_id: order for order, group_id in enumerate(requested)}
            for group in data["groups"]:
                group["order"] = order_by_id[group["id"]]
            self._commit(data)
            return self.snapshot()

    def remove_model_ids(self, model_ids: Iterable[str]) -> dict[str, Any]:
        removed = {str(item).strip() for item in model_ids if str(item).strip()}
        if not removed:
            return self.snapshot()
        with _LOCK:
            data = self._read()
            before = len(data["memberships"])
            data["memberships"] = [item for item in data["memberships"] if item["model_id"] not in removed]
            if len(data["memberships"]) != before:
                _normalize_membership_order(data)
                self._commit(data)
            return self.snapshot()

    def rename_model_id(self, old_id: str, new_id: str) -> dict[str, Any]:
        old_id = validate_config_id("model", old_id)
        new_id = validate_config_id("model", new_id)
        with _LOCK:
            data = self._read()
            changed = False
            for item in data["memberships"]:
                if item["model_id"] == old_id:
                    item["model_id"] = new_id
                    changed = True
            if changed:
                # A renamed model may collide with an existing membership.
                seen: set[tuple[str, str]] = set()
                unique: list[dict[str, Any]] = []
                for item in sorted(data["memberships"], key=lambda value: (value["group_id"], value["order"])):
                    key = (item["group_id"], item["model_id"])
                    if key not in seen:
                        seen.add(key)
                        unique.append(item)
                data["memberships"] = unique
                _normalize_membership_order(data)
                self._commit(data)
            return self.snapshot()

    def _read(self) -> dict[str, Any]:
        try:
            raw = load_jsonc(self.path)
        except FileNotFoundError:
            return {"version": 1, "revision": 0, "groups": [], "memberships": []}
        if not isinstance(raw, dict):
            raise ValueError("model group catalog must be an object")
        if int(raw.get("version") or 1) != 1:
            raise ValueError("unsupported model group catalog version")
        groups_raw = raw.get("groups")
        memberships_raw = raw.get("memberships")
        if not isinstance(groups_raw, list) or not isinstance(memberships_raw, list):
            raise ValueError("model group catalog groups/memberships must be arrays")
        groups: list[dict[str, Any]] = []
        names: set[str] = set()
        ids: set[str] = set()
        for index, item in enumerate(groups_raw):
            if not isinstance(item, dict):
                raise ValueError("model group must be an object")
            group_id = validate_config_id("model group", item.get("id"))
            name = _validate_name(item.get("name"))
            if group_id in ids or name.casefold() in names:
                raise ValueError("duplicate model group id or name")
            ids.add(group_id)
            names.add(name.casefold())
            groups.append({"id": group_id, "name": name, "order": _order(item.get("order"), index)})
        memberships: list[dict[str, Any]] = []
        membership_keys: set[tuple[str, str]] = set()
        for index, item in enumerate(memberships_raw):
            if not isinstance(item, dict):
                raise ValueError("model group membership must be an object")
            group_id = validate_config_id("model group", item.get("group_id"))
            model_id = validate_config_id("model", item.get("model_id"))
            if group_id not in ids:
                raise ValueError(f"membership references unknown group: {group_id}")
            key = (group_id, model_id)
            if key in membership_keys:
                raise ValueError("duplicate model group membership")
            membership_keys.add(key)
            memberships.append({"group_id": group_id, "model_id": model_id, "order": _order(item.get("order"), index)})
        data = {
            "version": 1,
            "revision": max(0, int(raw.get("revision") or 0)),
            "groups": groups,
            "memberships": memberships,
        }
        _normalize_group_order(data)
        _normalize_membership_order(data)
        return data

    def _commit(self, data: dict[str, Any]) -> None:
        data["revision"] = int(data.get("revision") or 0) + 1
        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    @staticmethod
    def _check_revision(data: dict[str, Any], expected: int | None) -> None:
        if expected is not None and int(expected) != int(data["revision"]):
            raise ModelGroupRevisionConflict(
                f"model group revision conflict: expected {expected}, current {data['revision']}"
            )


def _validate_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("model group name is required")
    if len(name) > 100:
        raise ValueError("model group name must be at most 100 characters")
    return name


def _unique_model_ids(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        model_id = validate_config_id("model", value)
        if model_id not in seen:
            result.append(model_id)
            seen.add(model_id)
    return result


def _find_group(data: dict[str, Any], group_id: str) -> dict[str, Any]:
    for group in data["groups"]:
        if group["id"] == group_id:
            return group
    raise LookupError(f"model group not found: {group_id}")


def _ensure_unique_name(data: dict[str, Any], name: str, *, except_id: str = "") -> None:
    folded = name.casefold()
    if any(item["id"] != except_id and item["name"].casefold() == folded for item in data["groups"]):
        raise ValueError(f"model group name already exists: {name}")


def _order(value: Any, fallback: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return fallback


def _normalize_group_order(data: dict[str, Any]) -> None:
    data["groups"].sort(key=lambda item: (item["order"], item["id"]))
    for order, item in enumerate(data["groups"]):
        item["order"] = order


def _normalize_membership_order(data: dict[str, Any]) -> None:
    data["memberships"].sort(key=lambda item: (item["group_id"], item["order"], item["model_id"]))
    next_order: dict[str, int] = {}
    for item in data["memberships"]:
        order = next_order.get(item["group_id"], 0)
        item["order"] = order
        next_order[item["group_id"]] = order + 1


__all__ = [
    "MODEL_GROUPS_FILENAME",
    "ModelGroup",
    "ModelGroupMembership",
    "ModelGroupRevisionConflict",
    "ModelGroupStore",
]
