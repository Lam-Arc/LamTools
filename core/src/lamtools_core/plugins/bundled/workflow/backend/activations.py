"""Workflow activation contracts backed by Core Arrange.

This module deliberately contains no scheduler.  It translates a workflow
trigger declaration into the stable ``arrange.create`` operation so Core has
one durable timer/event implementation and one lease/recovery path.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Mapping


ACTIVATION_MARKER = "lamtools.workflow.activation"
SUPPORTED_TRIGGER_TYPES = frozenset({"manual", "once", "interval", "calendar", "event"})


class WorkflowActivationError(ValueError):
    """Raised when a workflow trigger cannot be activated safely."""


def normalize_workflow_trigger(value: Mapping[str, Any], *, index: int = 0) -> dict[str, Any]:
    """Return one canonical, JSON-serializable trigger declaration."""
    if not isinstance(value, Mapping):
        raise WorkflowActivationError("workflow trigger must be an object")
    trigger_type = str(value.get("type") or "manual").strip().lower()
    if trigger_type == "cron":
        trigger_type = "calendar"
    if trigger_type not in SUPPORTED_TRIGGER_TYPES:
        raise WorkflowActivationError(f"unsupported workflow trigger type: {trigger_type or '-'}")
    trigger_id = str(value.get("id") or f"trigger_{index + 1}").strip()
    if not trigger_id:
        raise WorkflowActivationError("workflow trigger id is required")
    result: dict[str, Any] = {
        "id": trigger_id,
        "type": trigger_type,
        "enabled": bool(value.get("enabled", True)),
        "name": str(value.get("name") or "").strip(),
        "inputs": deepcopy(dict(value.get("inputs") or {})),
    }
    raw_max_runs = value.get("max_runs", value.get("maxRuns"))
    if raw_max_runs not in (None, ""):
        try:
            max_runs = int(raw_max_runs)
        except (TypeError, ValueError) as exc:
            raise WorkflowActivationError("trigger max_runs must be an integer") from exc
        if max_runs <= 0:
            raise WorkflowActivationError("trigger max_runs must be positive")
        result["max_runs"] = max_runs

    if trigger_type == "manual":
        return result
    if trigger_type == "once":
        raw_at = value.get("at", value.get("run_at", value.get("runAt")))
        at = str(raw_at or "").strip()
        if not at:
            raise WorkflowActivationError("once trigger requires at")
        try:
            datetime.fromisoformat(at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise WorkflowActivationError("once trigger at must be an ISO datetime") from exc
        result["at"] = at
        result["max_runs"] = 1
        return result
    if trigger_type == "interval":
        raw_seconds = value.get("every_seconds", value.get("everySeconds"))
        try:
            every_seconds = float(raw_seconds)
        except (TypeError, ValueError) as exc:
            raise WorkflowActivationError("interval trigger requires every_seconds") from exc
        if every_seconds <= 0:
            raise WorkflowActivationError("interval every_seconds must be positive")
        result["every_seconds"] = every_seconds
        start_at = str(value.get("start_at", value.get("startAt")) or "").strip()
        if start_at:
            try:
                datetime.fromisoformat(start_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise WorkflowActivationError("interval start_at must be an ISO datetime") from exc
            result["start_at"] = start_at
        return result
    if trigger_type == "event":
        event_type = str(value.get("event_type", value.get("eventType")) or "").strip()
        if not event_type:
            raise WorkflowActivationError("event trigger requires event_type")
        result["event_type"] = event_type
        return result

    frequency = str(value.get("frequency") or "daily").strip().lower()
    if frequency not in {"daily", "monthly"}:
        raise WorkflowActivationError("calendar frequency must be daily or monthly")
    wall_time = str(value.get("time") or "").strip()
    if not wall_time:
        raise WorkflowActivationError("calendar trigger requires time")
    result.update({
        "frequency": frequency,
        "time": wall_time,
        "timezone": str(value.get("timezone") or "Asia/Shanghai").strip(),
    })
    if frequency == "monthly":
        try:
            day = int(value.get("day"))
        except (TypeError, ValueError) as exc:
            raise WorkflowActivationError("monthly calendar trigger requires day") from exc
        if not 1 <= day <= 31:
            raise WorkflowActivationError("monthly calendar day must be between 1 and 31")
        result["day"] = day
    return result


def arrange_trigger(trigger: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a canonical workflow trigger into Core Arrange syntax."""
    normalized = normalize_workflow_trigger(trigger)
    trigger_type = normalized["type"]
    if trigger_type == "manual":
        raise WorkflowActivationError("manual triggers are not activatable")
    if trigger_type == "once":
        return {"type": "once", "at": normalized["at"]}
    if trigger_type == "interval":
        result = {"type": "interval", "every_seconds": normalized["every_seconds"]}
        if normalized.get("start_at"):
            result["start_at"] = normalized["start_at"]
        return result
    if trigger_type == "event":
        return {"type": "event", "event_type": normalized["event_type"]}
    return {
        key: normalized[key]
        for key in ("type", "frequency", "time", "timezone", "day")
        if key in normalized
    }


def build_arrange_activation_payload(
    *,
    workflow_id: str,
    workflow_name: str,
    workflow_revision: int,
    work_root: str,
    trigger: Mapping[str, Any],
    source_thread_id: str = "",
) -> dict[str, Any]:
    """Build an ``arrange.create`` payload for one workflow trigger."""
    normalized = normalize_workflow_trigger(trigger)
    if not normalized["enabled"]:
        raise WorkflowActivationError("disabled workflow triggers cannot be activated")
    schedule = arrange_trigger(normalized)
    clean_id = str(workflow_id or "").strip()
    clean_name = str(workflow_name or "").strip()
    clean_root = str(work_root or "").strip()
    if not clean_id or not clean_name or not clean_root:
        raise WorkflowActivationError("workflow id, name and work_root are required")
    marker = {
        "format": ACTIVATION_MARKER,
        "workflow_id": clean_id,
        "workflow_name": clean_name,
        "workflow_revision": max(1, int(workflow_revision or 1)),
        "trigger_id": normalized["id"],
        "trigger_type": normalized["type"],
    }
    run_payload = {
        "name": clean_name,
        "workflow_id": clean_id,
        "workflow_revision": marker["workflow_revision"],
        "work_root": clean_root,
        "inputs": deepcopy(normalized.get("inputs") or {}),
        "activation": marker,
    }
    payload: dict[str, Any] = {
        "work_root": clean_root,
        "thread_id": str(source_thread_id or f"workflow:{clean_id}"),
        "source_thread_id": str(source_thread_id or f"workflow:{clean_id}"),
        "session_strategy": "fixed",
        "kind": "routine",
        "operation": "workflow.run",
        "payload": run_payload,
        "trigger": schedule,
        "title": normalized["name"] or f"{clean_name} · {normalized['id']}",
        "max_runs": normalized.get("max_runs"),
    }
    return payload


def is_workflow_activation_job(value: Mapping[str, Any]) -> bool:
    if not isinstance(value, Mapping) or value.get("operation") != "workflow.run":
        return False
    payload = value.get("payload")
    marker = payload.get("activation") if isinstance(payload, Mapping) else None
    return isinstance(marker, Mapping) and marker.get("format") == ACTIVATION_MARKER


def activation_view(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a stable, secret-free view of an Arrange activation job."""
    if not is_workflow_activation_job(value):
        raise WorkflowActivationError("arrange job is not a workflow activation")
    payload = value.get("payload") if isinstance(value.get("payload"), Mapping) else {}
    marker = payload.get("activation") if isinstance(payload.get("activation"), Mapping) else {}
    return {
        "id": str(value.get("id") or ""),
        "workflow_id": str(marker.get("workflow_id") or ""),
        "workflow_name": str(marker.get("workflow_name") or ""),
        "workflow_revision": int(marker.get("workflow_revision") or 0),
        "trigger_id": str(marker.get("trigger_id") or ""),
        "trigger_type": str(marker.get("trigger_type") or ""),
        "status": str(value.get("status") or ""),
        "next_run_at": value.get("next_run_at"),
        "run_count": int(value.get("run_count") or 0),
        "max_runs": value.get("max_runs"),
        "last_error": str(value.get("last_error") or ""),
        "revision": int(value.get("revision") or 0),
    }


__all__ = [
    "ACTIVATION_MARKER",
    "SUPPORTED_TRIGGER_TYPES",
    "WorkflowActivationError",
    "activation_view",
    "arrange_trigger",
    "build_arrange_activation_payload",
    "is_workflow_activation_job",
    "normalize_workflow_trigger",
]
