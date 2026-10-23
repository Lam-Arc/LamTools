"""Model-visible image payloads: one full-fidelity request, then a small copy.

Basis: a 2.31 MB reference PNG cost 20.8 s and 1011 prompt tokens per call, the
same picture as a 44 KB JPEG 3.7 s and 288 tokens — with an identical
description from the model.  These tests pin the three properties that make the
degradation safe: it shrinks, it is deterministic (a per-request changing prefix
would destroy the provider's prompt cache), and it never touches the stored
history or drops an image it cannot decode.
"""

from __future__ import annotations

import base64
import io
import os

import pytest
from PIL import Image

from lamtools_core.app.base_agent import _messages_with_degraded_stale_images
from lamtools_core.kernel.loop import _stamp_message_origin
from lamtools_core.llm import ChatMessage
from lamtools_core.llm.image_payload import (
    DEGRADED_IMAGE_MAX_LONG_SIDE,
    DEGRADED_IMAGE_MAX_SHORT_SIDE,
    DEGRADED_IMAGE_MIME,
    DEGRADED_IMAGE_NOTE,
    MESSAGE_ADDED_AT_STEP,
    degraded_content,
    degraded_data_url,
    has_images,
    image_step_allowance,
    split_data_url,
)


def _png_data_url(width: int = 1200, height: int = 900, *, noise: bool = True) -> str:
    if noise:
        payload = bytes(os.urandom(width * height * 3))
    else:
        payload = bytes([200, 40, 40] * (width * height))
    image = Image.frombytes("RGB", (width, height), payload)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


class TestDegradedDataUrl:
    def test_shrinks_to_a_small_bounded_8bit_png(self):
        original = _png_data_url()
        degraded = degraded_data_url(original)

        assert degraded is not None
        assert degraded.startswith(f"data:{DEGRADED_IMAGE_MIME};base64,")
        original_bytes = len(split_data_url(original)[1])
        degraded_bytes = len(split_data_url(degraded)[1])
        assert degraded_bytes < original_bytes / 2, (original_bytes, degraded_bytes)

        with Image.open(io.BytesIO(split_data_url(degraded)[1])) as result:
            assert max(result.size) <= DEGRADED_IMAGE_MAX_LONG_SIDE
            assert min(result.size) <= DEGRADED_IMAGE_MAX_SHORT_SIDE
            assert result.mode == "P"
            palette = result.getpalette() or []
            assert len(palette) <= 256 * 3

    def test_portrait_is_bounded_to_360p(self):
        degraded = degraded_data_url(_png_data_url(900, 1200))

        assert degraded is not None
        assert degraded.startswith(f"data:{DEGRADED_IMAGE_MIME};base64,")
        with Image.open(io.BytesIO(split_data_url(degraded)[1])) as result:
            assert result.size == (360, 480)
            assert result.mode == "P"

    def test_is_deterministic_for_the_same_input(self):
        original = _png_data_url(600, 400)
        assert degraded_data_url(original) == degraded_data_url(original)

    def test_fails_open_when_the_picture_cannot_be_decoded(self):
        # Undecodable payloads and non-image inputs keep their original bytes:
        # a missing shrink must never drop an image or break a model call.
        assert degraded_data_url("data:image/png;base64,bm90LWFuLWltYWdl") is None
        assert degraded_data_url("data:image/png;base64,%%%not-base64%%%") is None
        assert degraded_data_url("https://example.com/a.png") is None
        assert degraded_data_url("data:text/plain;base64,aGk=") is None

    def test_already_small_jpeg_is_returned_unchanged(self):
        image = Image.frombytes("RGB", (64, 64), bytes([10, 20, 30] * 64 * 64))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80)
        url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        assert degraded_data_url(url) == url


class TestPolicyHelpers:
    def test_step_allowance_keeps_exactly_one_full_request(self):
        assert image_step_allowance(None) == 0
        assert image_step_allowance({}) == 0
        assert image_step_allowance({MESSAGE_ADDED_AT_STEP: 0}) == 0
        assert image_step_allowance({MESSAGE_ADDED_AT_STEP: 7}) == 7
        assert image_step_allowance({MESSAGE_ADDED_AT_STEP: "junk"}) == 0

    def test_stamp_is_neutral_bookkeeping_and_does_not_overwrite(self):
        message = ChatMessage(role="tool", content="ok")
        _stamp_message_origin(message, 3)
        assert message.metadata[MESSAGE_ADDED_AT_STEP] == 3
        _stamp_message_origin(message, 9)
        assert message.metadata[MESSAGE_ADDED_AT_STEP] == 3

    def test_content_is_marked_only_when_something_was_replaced(self):
        text_only = [{"type": "text", "text": "no pictures"}]
        assert degraded_content(text_only) is None
        assert has_images(text_only) is False
        assert has_images([{"type": "image_url", "image_url": {"url": _png_data_url(400, 300)}}]) is True

    def test_degraded_content_appends_one_marker(self):
        url = _png_data_url(1200, 900)
        block = {"type": "image_url", "image_url": {"url": url}}
        result = degraded_content([{"type": "text", "text": "see"}, block])
        assert result is not None
        content, count = result
        assert count == 1
        assert content[-1] == {"type": "text", "text": DEGRADED_IMAGE_NOTE}
        assert content[1]["image_url"]["url"].startswith(
            f"data:{DEGRADED_IMAGE_MIME};base64,"
        )


class TestRequestAssemblyKeepsHistoryIntact:
    def test_fresh_image_kept_and_stale_image_degraded(self):
        url = _png_data_url(1200, 900)
        stale = ChatMessage(
            role="tool", content=[{"type": "image_url", "image_url": {"url": url}}],
            metadata={MESSAGE_ADDED_AT_STEP: 0},
        )
        fresh = ChatMessage(
            role="tool", content=[{"type": "image_url", "image_url": {"url": url}}],
            metadata={MESSAGE_ADDED_AT_STEP: 4},
        )

        # The message produced by this model call still gets its full request;
        # the one produced earlier is already degraded.
        built = _messages_with_degraded_stale_images([stale, fresh], current_step=4)
        assert built[0].content[0]["image_url"]["url"].startswith(
            f"data:{DEGRADED_IMAGE_MIME};base64,"
        )
        assert built[1].content[0]["image_url"]["url"] == url

        # The stored history keeps the original bytes: only the request is reduced.
        assert stale.content[0]["image_url"]["url"] == url
        assert fresh.content[0]["image_url"]["url"] == url

    def test_unstamped_user_attachment_is_full_for_the_first_request_only(self):
        url = _png_data_url(1200, 900)
        message = ChatMessage(role="user", content=[{"type": "image_url", "image_url": {"url": url}}])

        assert _messages_with_degraded_stale_images([message], current_step=0)[0].content[0][
            "image_url"
        ]["url"] == url
        assert _messages_with_degraded_stale_images([message], current_step=1)[0].content[0][
            "image_url"
        ]["url"].startswith(f"data:{DEGRADED_IMAGE_MIME};base64,")

    def test_messages_without_images_are_returned_as_is(self):
        message = ChatMessage(role="user", content="plain text")
        built = _messages_with_degraded_stale_images([message], current_step=9)
        assert built[0] is message
