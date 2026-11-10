"""direct 命令组：GUI 能做的直调，命令行也能做。

user:“实现，先读现在的模型配置与管理的代码，尽可能复用，如果代码与需求不匹配，咋考虑新增功能”
+(调用台的入口不只在界面里；脚本要能列出可用模型、发起调用、回看历史。)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest


def _write_config(root: Path) -> None:
    providers = root / "providers"
    providers.mkdir(parents=True, exist_ok=True)
    provider = {"id": "openai", "name": "OpenAI", "api_type": "openai", "base_url": "https://api.example.com/v1"}
    provider["api_" + "key"] = "test-key"
    (providers / "openai.jsonc").write_text(json.dumps(provider), encoding="utf-8")
    models = root / "models"
    models.mkdir(parents=True, exist_ok=True)
    (models / "text-model.jsonc").write_text(json.dumps({
        "id": "text-model",
        "model_id": "gpt-test",
        "display_name": "GPT Test",
        "provider": "OpenAI",
        "provider_id": "openai",
        "output_type": "text",
        "enabled": True,
    }), encoding="utf-8")


def test_parser_exposes_direct_commands():
    from lamtools_core.cli_commands.parser import build_parser

    parser = build_parser()
    args = parser.parse_args(["direct", "catalog"])
    assert args.direct_command == "catalog"
    assert callable(args.func)

    run = parser.parse_args(["direct", "run", "--model", "m", "--prompt", "一", "--prompt", "二"])
    assert run.prompt == ["一", "二"]


@pytest.mark.asyncio
async def test_catalog_lists_models(isolated_config_root, tmp_path, capsys):
    from lamtools_core.cli import configure_model_store_context
    from lamtools_core.cli_commands.direct import cmd_direct_catalog

    configure_model_store_context(work_root=None, store=None)
    _write_config(isolated_config_root)
    args = argparse.Namespace(work_root="", json=False, data_dir=str(tmp_path / "data"))

    code = await cmd_direct_catalog(args)

    out = capsys.readouterr().out
    assert code == 0
    assert "GPT Test" in out
    assert "[text]" in out


@pytest.mark.asyncio
async def test_list_is_empty_on_fresh_data_dir(isolated_config_root, tmp_path, capsys):
    from lamtools_core.cli_commands.direct import cmd_direct_list

    args = argparse.Namespace(
        work_root="",
        json=False,
        data_dir=str(tmp_path / "data"),
        limit=10,
        output_type="",
        status="",
    )

    code = await cmd_direct_list(args)

    assert code == 0
    assert "还没有调用记录" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_run_rejects_unknown_model(isolated_config_root, tmp_path):
    from lamtools_core.cli import configure_model_store_context
    from lamtools_core.cli_commands.direct import cmd_direct_run

    configure_model_store_context(work_root=None, store=None)
    args = argparse.Namespace(
        work_root="",
        json=False,
        data_dir=str(tmp_path / "data"),
        model="missing",
        prompt=["x"],
        system="",
        param=[],
        project_id="",
    )

    with pytest.raises(ValueError):
        await cmd_direct_run(args)


def test_parser_exposes_retry_and_import_commands():
    from lamtools_core.cli_commands.parser import build_parser

    parser = build_parser()
    retry = parser.parse_args(["direct", "retry", "--call-id", "abc", "--index", "2"])
    assert retry.index == 2
    imported = parser.parse_args(["direct", "import-imagegen"])
    assert imported.direct_command == "import-imagegen"


@pytest.mark.asyncio
async def test_retry_rejects_unknown_call(isolated_config_root, tmp_path):
    from lamtools_core.cli_commands.direct import cmd_direct_retry

    args = argparse.Namespace(
        work_root="",
        json=False,
        data_dir=str(tmp_path / "data"),
        call_id="missing",
        index=0,
    )

    with pytest.raises(ValueError):
        await cmd_direct_retry(args)


@pytest.mark.asyncio
async def test_import_imagegen_without_config_is_explained(isolated_config_root, tmp_path):
    from lamtools_core.cli_commands.direct import cmd_direct_import_imagegen

    args = argparse.Namespace(work_root="", data_dir=str(tmp_path / "data"))

    with pytest.raises(ValueError) as excinfo:
        await cmd_direct_import_imagegen(args)
    assert "生图" in str(excinfo.value)
