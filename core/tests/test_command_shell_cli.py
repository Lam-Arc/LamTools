from __future__ import annotations

import asyncio
import json

from lamtools_core.cli import build_parser
from lamtools_core.config.settings_store import get_setting


def test_command_shell_cli_get_and_set_persist_preference(capsys) -> None:
    parser = build_parser()
    set_args = parser.parse_args(["command-shell", "set", "git-bash"])
    assert asyncio.run(set_args.func(set_args)) == 0
    assert get_setting("core.commandShell") == {"preference": "git-bash"}
    assert json.loads(capsys.readouterr().out) == {"preference": "git-bash"}

    get_args = parser.parse_args(["command-shell", "get"])
    assert asyncio.run(get_args.func(get_args)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["preference"] == "git-bash"
    assert set(result["effective"]) == {"name", "kind", "executable"}
