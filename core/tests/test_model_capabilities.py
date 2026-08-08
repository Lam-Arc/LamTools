from __future__ import annotations

from lamtools_core.llm.model_capabilities import is_text_model, resolve_capability


def test_resolve_capability_uses_jsonc_value():
    assert resolve_capability("xopkimik26", "multimodal") == "multimodal"
    assert resolve_capability("mimo-v2.5-free", "multimodal") == "multimodal"
    assert resolve_capability("xopkimik26", "text") == "text"
    assert resolve_capability("xopglm52", "text") == "text"


def test_resolve_capability_ignores_model_id():
    # jsonc is the single source of truth: model_id alone must NOT decide.
    # Previously xopkimik26 resolved multimodal via the builtin table; now it
    # defaults to text without a jsonc capability value.
    assert resolve_capability("xopkimik26") == "text"
    assert resolve_capability("mimo-v2.5-free") == "text"
    assert resolve_capability("xopdeepseekv4pro", "text") == "text"
    assert resolve_capability("totally-unknown-model", "multimodal") == "multimodal"


def test_resolve_capability_defaults_to_text_for_unknown_value():
    assert resolve_capability("mimo-v2.5-free", "") == "text"
    assert resolve_capability("", "") == "text"
    assert resolve_capability("", " vision ") == "text"
    assert resolve_capability("", "MULTIMODAL") == "multimodal"


def test_is_text_model_helper():
    assert is_text_model("xopglm52", "text") is True
    assert is_text_model("xopkimik26", "multimodal") is False
    assert is_text_model("unknown") is True


def test_no_builtin_capability_table_remains():
    # Plan: jsonc is the ONLY source of truth — the hardcoded tables must be gone.
    import lamtools_core.llm.model_capabilities as mod

    assert not hasattr(mod, "BUILTIN_CAPABILITIES")
    assert not hasattr(mod, "_CAPABILITY_PREFIXES")


def _write_project_model(tmp_path, model_id: str, capability: str) -> None:
    models_dir = tmp_path / ".lam" / "config" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / f"{model_id}.jsonc").write_text(
        "{\n"
        f'  "model_id": "{model_id}",\n'
        f'  "provider": "test",\n'
        f'  "capability": "{capability}",\n'
        '  "is_default": false\n'
        "}\n",
        encoding="utf-8",
    )


def test_resolve_model_capability_reads_jsonc(tmp_path):
    from lamtools_core.config.model_store import resolve_model_capability

    _write_project_model(tmp_path, "mm-model", "multimodal")
    _write_project_model(tmp_path, "txt-model", "text")

    assert resolve_model_capability("mm-model", work_root=str(tmp_path)) == "multimodal"
    assert resolve_model_capability("txt-model", work_root=str(tmp_path)) == "text"
    # A model with no jsonc definition defaults to text (safe).
    assert resolve_model_capability("no-such-model", work_root=str(tmp_path)) == "text"


def test_resolve_model_capability_defaults_text_without_jsonc_field(tmp_path):
    from lamtools_core.config.model_store import resolve_model_capability

    models_dir = tmp_path / ".lam" / "config" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / "undeclared.jsonc").write_text(
        '{\n  "model_id": "undeclared",\n  "provider": "test",\n  "is_default": false\n}\n',
        encoding="utf-8",
    )
    assert resolve_model_capability("undeclared", work_root=str(tmp_path)) == "text"