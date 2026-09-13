from __future__ import annotations

import pytest

from lamtools_core.plugins.bundled.workflow.backend.activations import (
    WorkflowActivationError,
    activation_view,
    arrange_trigger,
    build_arrange_activation_payload,
    is_workflow_activation_job,
    normalize_workflow_trigger,
)


def test_trigger_normalization_and_arrange_translation() -> None:
    trigger = normalize_workflow_trigger({
        "id": "daily",
        "type": "calendar",
        "frequency": "daily",
        "time": "08:00",
        "timezone": "Asia/Shanghai",
        "inputs": {"window": "24h"},
    })
    assert arrange_trigger(trigger) == {
        "type": "calendar",
        "frequency": "daily",
        "time": "08:00",
        "timezone": "Asia/Shanghai",
    }


def test_activation_payload_routes_through_arrange_and_pins_revision() -> None:
    payload = build_arrange_activation_payload(
        workflow_id="wf_1",
        workflow_name="refund-report",
        workflow_revision=7,
        work_root="E:/workspace",
        trigger={"id": "refund", "type": "event", "event_type": "refund.created"},
    )
    assert payload["operation"] == "workflow.run"
    assert payload["session_strategy"] == "fixed"
    assert payload["trigger"] == {"type": "event", "event_type": "refund.created"}
    assert payload["payload"]["workflow_id"] == "wf_1"
    assert payload["payload"]["workflow_revision"] == 7
    assert payload["payload"]["activation"]["workflow_revision"] == 7
    job = {
        **payload,
        "id": "arrange_1",
        "status": "waiting",
        "run_count": 0,
        "next_run_at": None,
        "revision": 2,
    }
    assert is_workflow_activation_job(job)
    assert activation_view(job)["trigger_id"] == "refund"


@pytest.mark.parametrize(
    "trigger",
    [
        {"type": "manual"},
        {"type": "interval", "every_seconds": 0},
        {"type": "event", "event_type": ""},
        {"type": "calendar", "frequency": "monthly", "time": "08:00", "day": 32},
        {"type": "unknown"},
    ],
)
def test_invalid_or_manual_triggers_cannot_be_scheduled(trigger: dict[str, object]) -> None:
    with pytest.raises(WorkflowActivationError):
        arrange_trigger(trigger)


def test_activation_view_rejects_unrelated_arrange_job() -> None:
    with pytest.raises(WorkflowActivationError):
        activation_view({"operation": "turn.start", "payload": {}})
