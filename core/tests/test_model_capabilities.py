from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.llm.model_capabilities import (
    BUILTIN_CAPABILITIES,
    is_text_model,
    resolve_capability,
)


def test_resolve_capability_uses_jsonc_override_when_set():
    # A model_id known to be multimodal can be forced text via jsonc.
    assert resolve_capability("xopkimik26", "text") == "text"
    # A model_id known to be text can be forced multimodal via jsonc.
    assert resolve_capability("xopglm52", "multimodal") == "multimodal"


def test_resolve_capability_uses_builtin_exact_table():
    assert resolve_capability("xopkimik26") == "multimodal"
    assert resolve_capability("xopglm52") == "text"
    assert resolve_capability("xopdeepseekv4pro") == "text"
    assert resolve_capability("xminimaxm25") == "multimodal"
    assert resolve_capability("xopqwen35397b") == "multimodal"


def test_resolve_capability_uses_prefix_fallback_for_unknown_model():
    # A new Kimi variant not in the exact table still resolves multimodal.
    assert resolve_capability("xopkimik99") == "multimodal"
    # A new DeepSeek variant resolves text.
    assert resolve_capability("xopdeepseekv5") == "text"
    # A new Qwen variant resolves multimodal.
    assert resolve_capability("xopqwen99") == "multimodal"


def test_resolve_capability_defaults_to_text_for_truly_unknown():
    assert resolve_capability("totally-unknown-model") == "text"
    assert resolve_capability("") == "text"


def test_is_text_model_helper():
    assert is_text_model("xopglm52") is True
    assert is_text_model("xopkimik26") is False
    assert is_text_model("unknown") is True


def test_builtin_table_covers_all_known_xunfei_models():
    # The 19 known Xunfei model_ids should all be present or prefix-resolvable.
    known = [
        "xsparkx2", "xsparkx2agent", "xsparkx2flash", "auto",
        "xopglm5", "xopglm51", "xopglm52", "xopglmv47flash",
        "xopkimik26", "xopkimik25", "xminimaxm25",
        "xopdeepseekv32", "xopdeepseekv4pro", "xopdeepseekv4flash",
        "xopdeepseekv4flash0731",
        "xopqwen36v35b", "xopqwen35v35b", "xop3qwencodernext", "xopqwen35397b",
    ]
    multimodal = {"xopkimik26", "xopkimik25", "xminimaxm25",
                  "xop3qwencodernext", "xopqwen35v35b", "xopqwen35397b", "xopqwen36v35b"}
    for mid in known:
        expected = "multimodal" if mid in multimodal else "text"
        # Either exact table or prefix resolves it correctly.
        assert resolve_capability(mid) == expected, f"{mid} resolved wrong"
