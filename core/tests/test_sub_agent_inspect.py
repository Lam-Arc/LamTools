"""sub_agent 的只读动作：list 看进度，get 看某一只的完整报告。

user:“sub Agent不是有message工具吗？这不就是主动问？不过 list 或者 get 确实也有必要添加”
+(message 是发指导，不是查状态；所以补两个只读动作：list 列这条会话派出去的所有子代理，
get 取一只的最终报告。两者都不触发执行、不改任何状态)。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import build_core_toolbox

LONG_REPORT = "做完了：" + ("验证细节。" * 5000)


class _Runner:
    def __init__(self, work_root: Path) -> None:
        self.work_root = work_root
        self.session_prefix = "thread-parent"

    async def run(self, **_kwargs):
        raise AssertionError("list/get must never start a turn")


class _Supervisor:
    def __init__(self) -> None:
        self.records = [
            {
                "name": "worker",
                "type": "execute",
                "status": "completed",
                "model_id": "model-a",
                "reasoning_level": "high",
                "elapsed_ms": 12345,
                "completed_at": 1.0,
                "execution_directory": "/tmp/project/worktrees/t1",
                "summary": LONG_REPORT,
            },
            {
                "name": "reader",
                "type": "consider",
                "status": "running",
                "model_id": "model-b",
                "reasoning_level": "light",
                "elapsed_ms": 800,
                "completed_at": None,
                "execution_directory": "",
                "summary": "",
            },
        ]
        self.calls: list[dict] = []

    async def list(self):
        return list(self.records)

    async def create_operation(self, **kwargs):
        self.calls.append(kwargs)
        raise AssertionError("list/get must not create anything")


def _toolbox(tmp_path: Path, supervisor: _Supervisor, monkeypatch: pytest.MonkeyPatch):
    async def fake_supervisor(**_kwargs):
        return supervisor

    monkeypatch.setattr(
        "lamtools_core.sub_agent_supervisor.get_sub_agent_supervisor", fake_supervisor
    )
    return build_core_toolbox(work_root=tmp_path, sub_agent_runner=_Runner(tmp_path))


@pytest.mark.asyncio
async def test_list_reports_every_sub_agent_with_a_short_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolbox = _toolbox(tmp_path, _Supervisor(), monkeypatch)

    result = await toolbox.execute(
        ToolCall(id="list", name="sub_agent", arguments={"action": "list"})
    )

    assert result.status == "ok", result.error
    items = result.metadata["sub_agents"]
    assert [item["name"] for item in items] == ["worker", "reader"]
    assert items[0]["status"] == "completed"
    assert items[0]["elapsed_ms"] == 12345
    # 列表里只给一眼能判断的长度，正文留给 get。
    assert len(items[0]["summary"]) == 501
    assert items[0]["summary"].endswith("…")
    assert items[1]["summary"] == ""


@pytest.mark.asyncio
async def test_get_returns_the_full_report_of_one_sub_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolbox = _toolbox(tmp_path, _Supervisor(), monkeypatch)

    result = await toolbox.execute(
        ToolCall(id="get", name="sub_agent", arguments={"action": "get", "name": "worker"})
    )

    assert result.status == "ok", result.error
    record = result.metadata["sub_agent"]
    assert record["name"] == "worker"
    # 默认只给一段，绝不整段回传。
    assert len(record["summary"]) == 2000
    assert record["summary"] == LONG_REPORT[:2000]
    assert record["summary_total_chars"] == len(LONG_REPORT)
    assert record["has_more"] is True
    assert record["next_offset"] == 2000
    assert record["execution_directory"] == "/tmp/project/worktrees/t1"


@pytest.mark.asyncio
async def test_get_pages_through_a_long_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolbox = _toolbox(tmp_path, _Supervisor(), monkeypatch)

    result = await toolbox.execute(
        ToolCall(
            id="get-page-2",
            name="sub_agent",
            arguments={"action": "get", "name": "worker", "offset": 2000, "max_chars": 1000},
        )
    )

    record = result.metadata["sub_agent"]
    assert record["summary"] == LONG_REPORT[2000:3000]
    assert record["summary_offset"] == 2000
    assert record["has_more"] is True


@pytest.mark.asyncio
async def test_get_caps_the_page_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolbox = _toolbox(tmp_path, _Supervisor(), monkeypatch)

    result = await toolbox.execute(
        ToolCall(
            id="get-huge-page",
            name="sub_agent",
            arguments={"action": "get", "name": "worker", "max_chars": 10_000_000},
        )
    )

    assert len(result.metadata["sub_agent"]["summary"]) == 20000


@pytest.mark.asyncio
async def test_get_names_the_available_sub_agents_when_the_name_is_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolbox = _toolbox(tmp_path, _Supervisor(), monkeypatch)

    result = await toolbox.execute(
        ToolCall(id="get-missing", name="sub_agent", arguments={"action": "get", "name": "nope"})
    )

    assert result.status == "failed"
    assert "nope" in (result.error or "")
    assert "worker" in (result.error or "")


@pytest.mark.asyncio
async def test_list_ignores_the_lifecycle_fields_the_schema_forces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolbox = _toolbox(tmp_path, _Supervisor(), monkeypatch)

    result = await toolbox.execute(
        ToolCall(
            id="list-nulls",
            name="sub_agent",
            arguments={
                "action": "list",
                "type": None,
                "name": None,
                "model": None,
                "reasoning_level": None,
                "work_root": None,
            },
        )
    )

    assert result.status == "ok", result.error


@pytest.mark.asyncio
async def test_lifecycle_actions_still_require_their_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolbox = _toolbox(tmp_path, _Supervisor(), monkeypatch)

    result = await toolbox.execute(
        ToolCall(
            id="create-incomplete",
            name="sub_agent",
            arguments={"action": "create", "type": "execute", "name": "worker", "model": "m"},
        )
    )

    assert result.status == "failed"
    assert "reasoning_level" in (result.error or "")


@pytest.mark.asyncio
async def test_an_unknown_argument_is_reported_instead_of_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolbox = _toolbox(tmp_path, _Supervisor(), monkeypatch)

    result = await toolbox.execute(
        ToolCall(
            id="typo",
            name="sub_agent",
            arguments={"action": "list", "workroot": "x"},
        )
    )

    assert result.status == "failed"
    assert "workroot" in (result.error or "")


@pytest.mark.asyncio
async def test_an_unknown_action_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolbox = _toolbox(tmp_path, _Supervisor(), monkeypatch)

    result = await toolbox.execute(
        ToolCall(id="bad-action", name="sub_agent", arguments={"action": "status"})
    )

    assert result.status == "failed"
    assert "create, close, delete, list, get" in (result.error or "")
