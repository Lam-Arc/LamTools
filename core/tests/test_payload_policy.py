"""Acceptance tests for the persisted payload policy.

user:“不应该有任何一个信息大于 4 兆 ... 一旦涉及到其他的附件，应该用的是指针
或者说是地址来表示，而不是直接放什么 base64 或者源文件”+(落盘时剥掉内联
data URL，保留 image_ref 地址；4MB 只告警，不硬拒绝)。
"""

from __future__ import annotations

import json
import logging

import pytest

from lamtools_core.runtime.payload_policy import (
    MAX_NORMAL_PAYLOAD_BYTES,
    payload_size_bytes,
    persistable_message,
    warn_if_oversized,
)

BIG_IMAGE = "data:image/png;base64," + ("A" * (5 * 1024 * 1024))


def _message_with_image(data_url: str = BIG_IMAGE) -> dict:
    return {
        "role": "tool",
        "name": "read_file",
        "tool_call_id": "call-1",
        "content": [
            {"type": "text", "text": "图片文件: shot.png"},
            {"type": "image_url", "image_url": {"url": data_url, "detail": "auto"}},
        ],
        "metadata": {
            "image_ref": {
                "path": "shot.png",
                "mime": "image/png",
                "sha256": "abc123",
            }
        },
    }


def test_persisted_tool_message_drops_inline_image_but_keeps_reference():
    row = persistable_message(_message_with_image())

    assert [block["type"] for block in row["content"]] == ["text"]
    assert row["metadata"]["image_ref"]["path"] == "shot.png"
    assert "data:image" not in json.dumps(row)
    assert payload_size_bytes(row) < MAX_NORMAL_PAYLOAD_BYTES


def test_live_message_is_not_mutated():
    message = _message_with_image()

    persistable_message(message)

    assert message["content"][1]["type"] == "image_url"
    assert message["content"][1]["image_url"]["url"] == BIG_IMAGE


def test_small_inline_image_is_still_externalized():
    row = persistable_message(_message_with_image("data:image/png;base64,iVBORw0KGgo="))

    assert [block["type"] for block in row["content"]] == ["text"]


def test_non_data_image_address_is_kept():
    message = {
        "role": "tool",
        "content": [
            {"type": "text", "text": "see attachment"},
            {"type": "image_url", "image_url": {"url": "attachment://abc", "detail": "auto"}},
        ],
    }

    row = persistable_message(message)

    assert row["content"][1]["image_url"]["url"] == "attachment://abc"


def test_oversized_text_is_kept_and_warned(caplog):
    message = {"role": "tool", "content": "x" * (MAX_NORMAL_PAYLOAD_BYTES + 1024)}
    row = persistable_message(message)

    with caplog.at_level(logging.WARNING, logger="lamtools_core.runtime.payload_policy"):
        size = warn_if_oversized("history", "thread-1:tool", row)

    # Soft limit: the row is still persisted, but the exception is visible.
    assert row["content"] == message["content"]
    assert size > MAX_NORMAL_PAYLOAD_BYTES
    assert any("normal limit" in record.getMessage() for record in caplog.records)


def test_normal_text_does_not_warn(caplog):
    row = persistable_message({"role": "user", "content": "hello"})

    with caplog.at_level(logging.WARNING, logger="lamtools_core.runtime.payload_policy"):
        size = warn_if_oversized("history", "thread-1:user", row)

    assert size < MAX_NORMAL_PAYLOAD_BYTES
    assert not caplog.records


def _kernel_with(store):
    from lamtools_core.kernel.loop import CoreLoopKernel

    kernel = CoreLoopKernel.__new__(CoreLoopKernel)
    kernel.state_store = store
    return kernel


@pytest.mark.asyncio
async def test_kernel_incremental_append_externalizes_inline_image():
    from lamtools_core.llm import ChatMessage
    from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState

    store = InMemoryRuntimeStateStore()
    kernel = _kernel_with(store)
    message = ChatMessage(
        role="tool",
        name="read_file",
        tool_call_id="call-1",
        content=[
            {"type": "text", "text": "图片文件: shot.png"},
            {"type": "image_url", "image_url": {"url": BIG_IMAGE, "detail": "auto"}},
        ],
        metadata={"image_ref": {"path": "shot.png", "mime": "image/png", "sha256": "abc"}},
    )

    await kernel._append_durable_messages(RuntimeState(session_id="s"), [message])

    rows = await store.get_history("s")
    assert len(rows) == 1
    row = rows[0]
    assert "data:image" not in json.dumps(row)
    assert row["metadata"]["image_ref"]["path"] == "shot.png"
    # The live message keeps the pixels for the immediately following request.
    assert message.content[1]["type"] == "image_url"
    assert message.content[1]["image_url"]["url"] == BIG_IMAGE


@pytest.mark.asyncio
async def test_kernel_full_replace_externalizes_inline_image():
    from lamtools_core.llm import ChatMessage
    from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState

    store = InMemoryRuntimeStateStore()
    kernel = _kernel_with(store)
    message = ChatMessage(
        role="tool",
        content=[
            {"type": "text", "text": "图片文件: shot.png"},
            {"type": "image_url", "image_url": {"url": BIG_IMAGE, "detail": "auto"}},
        ],
        metadata={"image_ref": {"path": "shot.png", "mime": "image/png", "sha256": "abc"}},
    )

    await kernel._replace_history_checkpoint(RuntimeState(session_id="s"), [message])

    rows = await store.get_history("s")
    assert len(rows) == 1
    row = rows[0]
    assert "data:image" not in json.dumps(row)
    assert row["metadata"]["image_ref"]["path"] == "shot.png"
    assert (await store.get("s")) is not None
