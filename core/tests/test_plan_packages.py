"""Plan packages: the shared contract, the store, and the RPC surface.

`core/protocol/plan-package-v1-fixtures.json` is the contract of record. The
phone runs the same cases through its own implementation, so this file is where
a field, a default or a refusal wording stops being a desktop-only decision.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lamtools_core import cli as core_cli
from lamtools_core.app import open_core_app_db
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.app.plan_operations import register_plan_operations
from lamtools_core.cli import build_parser
from lamtools_core.runtime.plan_package import (
    InMemoryPlanStore,
    PlanExecution,
    PlanManager,
)

FIXTURES = Path(__file__).resolve().parents[1] / "protocol" / "plan-package-v1-fixtures.json"
CONTRACT = json.loads(FIXTURES.read_text(encoding="utf-8"))
COMPARED_FIELDS: list[str] = CONTRACT["contract"]["compared_fields"]
CASES: list[dict[str, Any]] = CONTRACT["cases"]


def _project(plan: dict[str, Any]) -> dict[str, Any]:
    """Only the fields both hosts must agree on."""

    return {field: plan.get(field) for field in COMPARED_FIELDS}


async def _apply(manager: PlanManager, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """One fixture step, in the vocabulary the fixtures expect."""

    result: dict[str, Any] = {"ok": True, "error": None, "plan": None, "listed": [], "revisions": []}
    try:
        if action == "save":
            plan = await manager.save(payload, source="desktop", expected_revision=payload.get("expected_revision"))
        elif action == "revert":
            plan = await manager.revert(payload["plan_id"], int(payload["revision"]), source="desktop")
        elif action == "delete":
            plan = await manager.delete(payload["plan_id"])
        elif action == "restore":
            plan = await manager.restore(payload["plan_id"])
        elif action == "list":
            listed = await manager.list(
                project_id=payload.get("project_id"),
                status=payload.get("status"),
                include_deleted=bool(payload.get("include_deleted")),
            )
            result["listed"] = [plan.id for plan in listed]
            return result
        elif action == "revisions":
            history = await manager.revisions(payload["plan_id"])
            result["revisions"] = [{"revision": item.revision, "title": item.title} for item in history]
            return result
        else:  # pragma: no cover - the fixture set is checked below
            raise AssertionError(f"unknown fixture action: {action}")
        result["plan"] = plan.to_dict()
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        result["ok"] = False
        result["error"] = str(exc)
    result["listed"] = [plan.id for plan in await manager.list()]
    return result


def _assert_expectation(case: dict[str, Any], result: dict[str, Any]) -> None:
    expect = case["expect"]
    name = case["name"]

    assert result["ok"] is expect["ok"], f"{name}: ok mismatch ({result['error']})"
    if not expect["ok"]:
        assert result["error"] == expect["error"], f"{name}: refusal wording drifted"
        return

    if "revision" in expect:
        assert result["plan"]["revision"] == expect["revision"], f"{name}: revision"
    if "status" in expect:
        assert result["plan"]["status"] == expect["status"], f"{name}: status"
    if "plan_id_prefix" in expect:
        assert result["plan"]["plan_id"].startswith(expect["plan_id_prefix"]), f"{name}: id"
    if "plan" in expect:
        assert _project(result["plan"]) == expect["plan"], f"{name}: package drifted"
    if "listed" in expect:
        assert result["listed"] == expect["listed"], f"{name}: list"
    if "revisions" in expect:
        assert result["revisions"] == expect["revisions"], f"{name}: revision history"


async def _run_case(manager: PlanManager, case: dict[str, Any]) -> None:
    for step in case.get("given", []):
        replayed = await _apply(manager, step.get("action", "save"), step["payload"])
        assert replayed["ok"], f"{case['name']}: given step failed: {replayed['error']}"
    _assert_expectation(case, await _apply(manager, case["action"], case.get("payload", {})))


async def test_shared_fixtures_hold_for_the_in_memory_store() -> None:
    # Every case is self-contained: its `given` steps build the state it needs,
    # so a fresh store per case keeps one case's plans out of another's list.
    for case in CASES:
        await _run_case(PlanManager(InMemoryPlanStore()), case)


async def test_shared_fixtures_hold_through_the_sqlite_store(tmp_path: Path) -> None:
    """The persisted store answers the contract exactly like the in-memory one."""

    for index, case in enumerate(CASES):
        db = await open_core_app_db(tmp_path / f"case-{index}.db")
        try:
            await _run_case(PlanManager(db.plan_store), case)
        finally:
            await db.close()


async def test_every_fixture_case_is_unique_and_known() -> None:
    names = [case["name"] for case in CASES]
    assert len(names) == len(set(names)), "duplicate fixture case names"
    assert {"save", "revert", "delete", "restore", "list", "revisions"} <= {
        case["action"] for case in CASES
    }


async def test_a_stored_plan_survives_a_reopen_with_its_history(tmp_path: Path) -> None:
    """Kill-and-restart durability, which is the whole point of Stage 1."""

    path = tmp_path / "core.db"
    first = await open_core_app_db(path)
    try:
        manager = PlanManager(first.plan_store)
        created = await manager.save(
            {
                "plan_id": "plan_reopen",
                "project_id": "proj-1",
                "title": "存了再开",
                "requirement": {"restatement": "重启不丢"},
                "approach": {"chosen": "落库"},
                "checklist": {"steps": [{"id": "s1", "description": "写下去"}]},
            },
            source="desktop",
        )
        assert created.revision == 1
        await manager.save(
            {"plan_id": "plan_reopen", "expected_revision": 1, "status": "ready"},
            source="desktop",
        )
    finally:
        await first.close()

    second = await open_core_app_db(path)
    try:
        reopened = PlanManager(second.plan_store)
        plan = await reopened.require("plan_reopen")
        assert plan.title == "存了再开"
        assert plan.status == "ready"
        assert plan.revision == 2
        history = await reopened.revisions("plan_reopen")
        assert [(item.revision, item.status) for item in history] == [(1, "draft"), (2, "ready")]
    finally:
        await second.close()


async def test_execution_bookkeeping_does_not_spend_a_revision(tmp_path: Path) -> None:
    """An imported plan keeps the revision the phone knows after it starts here."""

    db = await open_core_app_db(tmp_path / "core.db")
    try:
        manager = PlanManager(db.plan_store)
        created = await manager.save(
            {
                "plan_id": "plan_exec",
                "project_id": "proj-1",
                "title": "要开工的方案",
                "requirement": {"restatement": "开工"},
                "approach": {"chosen": "开会话"},
            },
            source="mobile",
        )
        executed = await manager.record_execution(
            created.id,
            PlanExecution(thread_id="thread-9", revision=created.revision, started_at="2026-09-28T10:00:00+00:00"),
        )
        assert executed.revision == created.revision
        assert executed.execution is not None
        assert executed.execution.thread_id == "thread-9"
        assert (await manager.require(created.id)).execution.thread_id == "thread-9"
    finally:
        await db.close()


async def test_revert_restores_a_status_the_state_machine_would_not_allow_forward() -> None:
    """Reverting is an explicit move on history, so `done -> ready` is allowed."""

    manager = PlanManager(InMemoryPlanStore())
    await manager.save(
        {
            "plan_id": "plan_rev",
            "project_id": "proj-1",
            "title": "回到了定稿",
            "requirement": {"restatement": "x"},
            "approach": {"chosen": "y"},
            "checklist": {"steps": [{"id": "s1", "description": "第一步"}]},
        },
        source="desktop",
    )
    await manager.save({"plan_id": "plan_rev", "expected_revision": 1, "status": "ready"}, source="desktop")
    await manager.save({"plan_id": "plan_rev", "expected_revision": 2, "status": "executing"}, source="desktop")
    done = await manager.save({"plan_id": "plan_rev", "expected_revision": 3, "status": "done"}, source="desktop")
    assert done.status == "done"

    reverted = await manager.revert("plan_rev", 2, source="desktop")
    assert reverted.status == "ready"
    assert reverted.revision == 5
    assert reverted.execution is None


async def test_deleted_plans_are_listed_only_on_request() -> None:
    manager = PlanManager(InMemoryPlanStore())
    await manager.save(
        {
            "plan_id": "plan_del",
            "project_id": "proj-1",
            "title": "软删除",
            "requirement": {"restatement": "x"},
            "approach": {"chosen": "y"},
        },
        source="desktop",
    )
    await manager.delete("plan_del")

    assert await manager.list() == []
    with_deleted = await manager.list(include_deleted=True)
    assert [plan.id for plan in with_deleted] == ["plan_del"]
    assert with_deleted[0].deleted_at is not None
    assert (await manager.restore("plan_del")).deleted_at is None


async def test_operations_expose_the_plan_lifecycle() -> None:
    catalog = OperationCatalog()
    register_plan_operations(catalog, plan_manager=PlanManager(InMemoryPlanStore()))

    created = await catalog.execute(
        "plan.save",
        {
            "plan_id": "plan_op",
            "project_id": "proj-1",
            "title": "接口形状",
            "requirement": {"restatement": "x"},
            "approach": {"chosen": "y"},
            "checklist": {"steps": [{"id": "s1", "description": "一步"}]},
        },
    )
    assert created.status == "ok"
    assert created.payload["plan"]["plan_id"] == "plan_op"

    listed = await catalog.execute("plan.list", {"project_id": "proj-1"})
    assert [plan["plan_id"] for plan in listed.payload["plans"]] == ["plan_op"]

    fetched = await catalog.execute("plan.get", {"plan_id": "plan_op"})
    assert fetched.payload["plan"]["title"] == "接口形状"

    readied = await catalog.execute(
        "plan.save",
        {"plan_id": "plan_op", "expected_revision": 1, "status": "ready"},
    )
    assert readied.payload["plan"]["status"] == "ready"

    history = await catalog.execute("plan.revisions", {"plan_id": "plan_op"})
    assert [item["revision"] for item in history.payload["revisions"]] == [1, 2]

    deleted = await catalog.execute("plan.delete", {"plan_id": "plan_op"})
    assert deleted.payload["plan"]["deleted_at"] is not None
    assert (await catalog.execute("plan.list", {"project_id": "proj-1"})).payload["plans"] == []

    restored = await catalog.execute("plan.restore", {"plan_id": "plan_op"})
    assert restored.payload["plan"]["deleted_at"] is None

    reverted = await catalog.execute("plan.revert", {"plan_id": "plan_op", "revision": 1})
    assert reverted.payload["plan"]["status"] == "draft"


async def test_operations_report_refusals_as_errors_not_exceptions() -> None:
    catalog = OperationCatalog()
    register_plan_operations(catalog, plan_manager=PlanManager(InMemoryPlanStore()))

    refused = await catalog.execute("plan.save", {"plan_id": "plan_x", "title": "只有标题"})
    assert refused.status == "error"
    assert refused.payload["error"] == "plan project is required"

    missing = await catalog.execute("plan.get", {"plan_id": "plan_missing"})
    assert missing.status == "error"
    assert missing.payload["error"] == "Plan not found: plan_missing"

    bad_status = await catalog.execute("plan.list", {"status": "approved"})
    assert bad_status.status == "error"
    assert bad_status.payload["error"] == "invalid plan status: approved"

    bad_revision = await catalog.execute("plan.revert", {"plan_id": "plan_op", "revision": "abc"})
    assert bad_revision.status == "error"
    assert bad_revision.payload["error"] == "plan revision must be a number"


class _FakeLiveClient:
    """Records the RPC a CLI command would send, and answers it."""

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None, calls: list[tuple[str, dict]] | None = None) -> None:
        self.responses = responses or {}
        self.calls = calls if calls is not None else []

    async def request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, payload))
        return self.responses.get(method, {})


def _patch_live(monkeypatch: Any, client: _FakeLiveClient) -> None:
    async def fake_invoke_live(args: argparse.Namespace, operation: Any) -> dict[str, Any]:
        return await operation(client)

    monkeypatch.setattr(core_cli, "_invoke_live", fake_invoke_live)


async def test_cli_lists_and_filters_plans(monkeypatch: Any, capsys: Any) -> None:
    client = _FakeLiveClient(
        {
            "plan.list": {
                "plans": [
                    {
                        "plan_id": "plan_1",
                        "title": "手机做方案",
                        "status": "draft",
                        "source": "mobile",
                        "checklist": {"steps": [{"id": "s1", "description": "一步"}]},
                    }
                ]
            }
        }
    )
    _patch_live(monkeypatch, client)

    args = build_parser().parse_args(["plan", "ls", "--project", "proj-1", "--status", "draft"])
    assert await args.func(args) == 0

    assert client.calls == [("plan.list", {"project_id": "proj-1", "status": "draft"})]
    assert "plan_1" in capsys.readouterr().out


async def test_cli_save_takes_a_package_file_and_lets_flags_override_it(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    package = {
        "plan_id": "plan_from_phone",
        "project_id": "proj-1",
        "title": "手机导出的方案",
        "source": "mobile",
        "requirement": {"restatement": "原始需求", "non_goals": ["不做多人协作"]},
        "approach": {"chosen": "原始做法"},
    }
    source = tmp_path / "package.json"
    source.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")

    client = _FakeLiveClient({"plan.save": {"plan": {"plan_id": "plan_from_phone", "revision": 1, "status": "draft"}}})
    _patch_live(monkeypatch, client)

    args = build_parser().parse_args(
        ["plan", "save", "--from-file", str(source), "--project", "proj-2", "--approach", "本地改过的做法"]
    )
    assert await args.func(args) == 0

    assert len(client.calls) == 1
    method, payload = client.calls[0]
    assert method == "plan.save"
    # The file's host-local `source` is dropped; the store decides that field.
    assert "source" not in payload
    assert payload["project_id"] == "proj-2"
    assert payload["approach"] == {"chosen": "本地改过的做法"}
    # Untouched nested values survive the override.
    assert payload["requirement"] == {"restatement": "原始需求", "non_goals": ["不做多人协作"]}
    assert "plan_from_phone" in capsys.readouterr().out


async def test_cli_save_refuses_an_unusable_file_without_calling_the_server(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    client = _FakeLiveClient()
    _patch_live(monkeypatch, client)

    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    args = build_parser().parse_args(["plan", "save", "--from-file", str(broken)])
    assert await args.func(args) == 1
    assert client.calls == []
    assert "not valid JSON" in capsys.readouterr().err

    empty = build_parser().parse_args(["plan", "save"])
    assert await empty.func(empty) == 1
    assert client.calls == []
    assert "nothing to save" in capsys.readouterr().err


async def test_cli_export_writes_the_package(monkeypatch: Any, tmp_path: Path) -> None:
    client = _FakeLiveClient({"plan.get": {"plan": {"plan_id": "plan_1", "title": "导出我"}}})
    _patch_live(monkeypatch, client)

    destination = tmp_path / "out" / "plan.json"
    args = build_parser().parse_args(["plan", "export", "plan_1", "--out", str(destination)])
    assert await args.func(args) == 0

    assert json.loads(destination.read_text(encoding="utf-8"))["title"] == "导出我"


async def test_cli_delete_points_at_restore(monkeypatch: Any, capsys: Any) -> None:
    client = _FakeLiveClient({"plan.delete": {"plan": {"plan_id": "plan_1"}}})
    _patch_live(monkeypatch, client)

    args = build_parser().parse_args(["plan", "delete", "plan_1"])
    assert await args.func(args) == 0

    assert client.calls == [("plan.delete", {"plan_id": "plan_1"})]
    assert "plan restore plan_1" in capsys.readouterr().out
