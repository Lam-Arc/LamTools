from __future__ import annotations

import asyncio
import json

import pytest

from lamtools_core.cli import build_parser
from lamtools_core.config.language import LANGUAGE_NAMESPACE, UI_LANGUAGES, language_status, merge_language
from lamtools_core.config.settings_store import get_setting, set_setting


def test_default_language(isolated_config_root):
    assert language_status() == {"locale": "zh-CN"}


@pytest.mark.parametrize("locale", UI_LANGUAGES)
def test_cli_persists_language(locale, isolated_config_root, capsys):
    parser = build_parser()
    args = parser.parse_args(["language", "set", locale])
    assert asyncio.run(args.func(args)) == 0
    assert get_setting(LANGUAGE_NAMESPACE) == {"locale": locale}
    assert json.loads(capsys.readouterr().out) == {"locale": locale}
    args = parser.parse_args(["language", "get"])
    assert asyncio.run(args.func(args)) == 0
    assert json.loads(capsys.readouterr().out) == {"locale": locale}


@pytest.mark.parametrize("value", [None, True, 1, "", "fr", "zh-cn", [], {}])
def test_invalid_language_rejected(value):
    with pytest.raises(ValueError):
        merge_language({"locale": "en"}, {"locale": value})


def test_unknown_fields_rejected():
    with pytest.raises(ValueError):
        merge_language({}, {"locale": "en", "model_language": "en"})


def test_corrupt_saved_value_falls_back(isolated_config_root):
    set_setting(LANGUAGE_NAMESPACE, {"locale": "fr"})
    assert language_status() == {"locale": "zh-CN"}


@pytest.mark.asyncio
async def test_rpc_round_trip_and_failed_write_keeps_setting(isolated_config_root):
    from lamtools_core.config.operations import build_config_operation_catalog

    catalog = build_config_operation_catalog()
    for locale in UI_LANGUAGES:
        result = await catalog.execute("settings.update", {"namespace": LANGUAGE_NAMESPACE, "value": {"locale": locale}}, metadata={})
        assert result.status == "ok"
        fetched = await catalog.execute("settings.get", {"namespace": LANGUAGE_NAMESPACE}, metadata={})
        assert fetched.payload["value"] == {"locale": locale}
    rejected = await catalog.execute("settings.update", {"namespace": LANGUAGE_NAMESPACE, "value": {"locale": "fr"}}, metadata={})
    assert rejected.status == "error"
    assert language_status() == {"locale": "en"}
