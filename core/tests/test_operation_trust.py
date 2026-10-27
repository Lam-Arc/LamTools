"""user:“一次性处理干净 不要留尾巴”+(权限信任持久化、精确匹配并可撤销)。"""
from pathlib import Path
import pytest


def test_trust_persists_one_level_at_a_time_and_revokes(tmp_path):
    from lamtools_core.tool.operation_trust import OperationTrustStore
    from lamtools_core.tool.approval import ApprovalGate
    from lamtools_core.tool.permission import ASK_USER
    store = OperationTrustStore(tmp_path / "trust.json")
    params = {"command": "git reset --hard"}
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={"run_command": ASK_USER}, permission_preset="auto", trust_store=store)
    assert gate.check("run_command", params).requires_approval
    gate.trust_operation("run_command", params)
    reloaded = ApprovalGate(work_root=tmp_path, tool_permissions={"run_command": ASK_USER}, permission_preset="auto", trust_store=OperationTrustStore(store.path))
    assert reloaded.check("run_command", params).level == 2
    assert reloaded.check("run_command", params).allowed
    assert reloaded.check("run_command", {"command": "git reset --hard HEAD~1"}).level == 3
    reloaded.trust_operation("run_command", params)
    reloaded.trust_operation("run_command", params)
    assert reloaded.check("run_command", params).level == 1
    row = store.list()[0]
    store.revoke(row["key"])
    assert gate.check("run_command", params).level == 3


def test_hard_block_cannot_be_trusted(tmp_path):
    from lamtools_core.tool.operation_trust import OperationTrustStore
    from lamtools_core.tool.approval import ApprovalGate
    from lamtools_core.tool.permission import HARD_BLOCK, ASK_USER
    gate = ApprovalGate(work_root=tmp_path, tool_permissions={"disabled": HARD_BLOCK, "write_file": ASK_USER},
                        permission_preset="full_access", trust_store=OperationTrustStore(tmp_path / "trust.json"))
    with pytest.raises(ValueError): gate.trust_operation("disabled", {})
    with pytest.raises(ValueError): gate.trust_operation("write_file", {"path": ".env"})


def test_trust_is_scoped_to_the_exact_project(tmp_path):
    from lamtools_core.tool.operation_trust import OperationTrustStore
    store = OperationTrustStore(tmp_path / "trust.json")
    first = store.selector(tmp_path / "a", "run_command", {"command": "git reset --hard"})
    other = store.selector(tmp_path / "b", "run_command", {"command": "git reset --hard"})
    assert first != other


def test_trust_decision_retains_user_intent():
    from lamtools_core.tool.approval_continuation import resolve_waiting_decision
    decision = resolve_waiting_decision("trust")
    assert decision.action == "approve" and decision.trust


@pytest.mark.asyncio
async def test_real_approval_persists_trust_for_the_next_chat(tmp_path, monkeypatch, instant_model_retry_sleep):
    from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
    from lamtools_core.runtime import InMemoryRuntimeStateStore
    from lamtools_core.llm import LLMStreamEvent, LLMToolCall
    from lamtools_core.tool.operation_trust import OperationTrustStore
    monkeypatch.setattr("lamtools_core.config.root.core_config_file", lambda name: tmp_path / name)
    class Model:
        calls = 0
        async def complete(self, request): raise AssertionError("streaming expected")
        async def stream(self, request):
            self.calls += 1
            if self.calls % 2:
                yield LLMStreamEvent(kind="done", tool_calls=[LLMToolCall(id=f"write-{self.calls}", name="write_file",
                    arguments={"path": "first.txt" if self.calls == 1 else "second.txt", "content": "saved"})])
            else:
                yield LLMStreamEvent(kind="content_delta", content="done")
                yield LLMStreamEvent(kind="done")
    store = InMemoryRuntimeStateStore()
    catalog = create_core_agent_operations(spec=CoreAgentSpec(), paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=Model(), plugin_roots=[], runtime_state_store=store)
    await catalog.execute("turn.start", {"thread_id": "first", "message": "save"})
    state = await store.get("first")
    pending = state.metadata["pending_approval"]
    result = await catalog.execute("approval.respond", {"thread_id": "first", "request_id": pending["request_id"], "decision": "trust"})
    assert result.status == "ok"
    assert (tmp_path / "work/first.txt").read_text(encoding="utf8") == "saved"
    assert OperationTrustStore().list()[0]["level"] == 1
    result = await catalog.execute("turn.start", {"thread_id": "second", "message": "save"})
    assert result.status == "ok"
    assert (tmp_path / "work/second.txt").read_text(encoding="utf8") == "saved"
    rows = (await catalog.execute("permissions.trust.list", {})).payload["entries"]
    assert rows
    await catalog.execute("permissions.trust.revoke", {"key": rows[0]["key"]})
    assert not OperationTrustStore().list()
