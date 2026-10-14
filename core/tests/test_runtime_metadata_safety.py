"""Live callbacks must never leak into serialized runtime metadata.

The app layer hands the continuation a callback through operation metadata
(``approval_decision_durable``). Spreading that metadata into a turn input put
a Python function into the runtime metadata, and the first plugin hook or
provider request then failed the whole run with "Object of type function is not
JSON serializable" before the first model call (reported 2026-10-14 as one of
three quick tests failing outright).
"""
from __future__ import annotations

import json

import pytest

from lamtools_core.app.default_agent import _runtime_metadata
from lamtools_core.kernel.loop import _json_safe_metadata


def test_runtime_metadata_drops_callbacks_and_private_keys():
    async def decision_durable(info: dict) -> None:
        return None

    filtered = _runtime_metadata({
        "approval_decision_durable": decision_durable,
        "_core_operation": lambda payload: payload,
        "source": "core_live",
        "nested": {"keep": 1},
    })

    assert filtered == {"source": "core_live", "nested": {"keep": 1}}
    assert json.dumps(filtered) == '{"source": "core_live", "nested": {"keep": 1}}'


def test_runtime_metadata_accepts_missing_metadata():
    assert _runtime_metadata(None) == {}
    assert _runtime_metadata("core_live") == {}


def test_hook_metadata_stays_serializable():
    async def decision_durable(info: dict) -> None:
        return None

    hook_metadata = _json_safe_metadata({
        "approval_decision_durable": decision_durable,
        "work_root": "E:\\LamTools",
        "nested": {"keep": True, "drop": decision_durable},
        "items": [1, "two", decision_durable],
    })

    assert hook_metadata == {
        "work_root": "E:\\LamTools",
        "nested": {"keep": True},
        "items": [1, "two"],
    }
    json.dumps(hook_metadata, ensure_ascii=False)


def test_hook_metadata_keeps_plain_payloads_untouched():
    payload = {"a": 1, "b": ["x", {"c": None}], "d": True}
    assert _json_safe_metadata(payload) == payload


@pytest.mark.asyncio
async def test_hook_metadata_sanitizes_the_live_history_object():
    # Any non-serializable value in the turn metadata would fail a hook or a
    # provider call; the sanitizer must survive the object shapes the kernel
    # actually carries.
    class Weird:
        pass

    sanitized = _json_safe_metadata({
        "session_id": "thread-1",
        "object": Weird(),
        "asyncio_event": __import__("asyncio").Event(),
    })

    assert sanitized["session_id"] == "thread-1"
    # Unknown objects stay for the caller's own serializer to report; only
    # live callbacks (which are certainly unserializable) are dropped here.
    assert "object" in sanitized
