"""Acceptance tests for Dreaming — asynchronous maintenance of memory.md.

PRD: 方案/Sunday-Memory-主动记忆与认知系统-PRD-V1.0.md（第 5、6、8 章）

What is proven here:

* only *new* turns are digested (a per-session cursor), never the whole history;
* short small talk is not turned into memory;
* one model call produces independent memory files plus the auto block of
  memory.md, and hand-written content always survives;
* a failed or disabled pass leaves the stored memory untouched;
* secrets are dropped instead of being stored as cognition;
* reserved files (INDEX.md, memory.md) cannot be written by the dream pass;
* "forgotten" entries reach the prompt so the model cannot silently restore
  what the user removed.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from lamtools_core import mem as memory
from lamtools_core.llm import LLMResponse
from lamtools_core.mem import dreaming
from lamtools_core.mem import settings as memory_settings


class StubLLM:
    """Minimal LLM client: records requests, returns one canned response."""

    def __init__(self, content: str = "", *, raises: Exception | None = None):
        self.content = content
        self.raises = raises
        self.requests: list[object] = []

    async def complete(self, request):
        self.requests.append(request)
        if self.raises is not None:
            raise self.raises
        return LLMResponse(content=self.content)

    async def stream(self, request):  # pragma: no cover - unused by dreaming
        yield None


@pytest.fixture()
def project_work(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    return work


def _output(**overrides) -> str:
    payload = {
        "global": {"core": "", "memories": []},
        "project": {"core": "", "memories": []},
        "notes": "",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def _turns(count: int = 2, *, text: str = None):
    # A pass needs DREAM_MIN_NEW_CHARS of new text; the default slice is a
    # realistic substantive conversation, not small talk.
    prompt = text or (
        "我们决定以后所有方案先写进方案目录再实现，并且在动手前先写验收测试；"
        "项目的后端是 Python 与 Rust 混合、前端是 Vue 与 TypeScript、桌面用 Tauri；"
        "数据放在 data/core.db，配置在 .lam/core/config，文档在 agent_docs；"
        "提交前先看一遍相关测试是否通过，涉及界面的改动要复用已有控件，"
        "不要新建重复的样式与组件。这些约定以后都按这个来，不需要每次再问。"
    )
    return [{"seq": index + 1, "prompt": prompt, "response": "了解，我会这样做。"} for index in range(count)]


def _run(work: Path, llm, turns=None, **kwargs):
    return dreaming.dream_session(
        llm_client=llm,
        model_id="test/model",
        work_root=work,
        scope="project",
        session_id="s1",
        turns=turns if turns is not None else _turns(),
        force=kwargs.pop("force", True),
        now=kwargs.pop("now", None),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Incremental selection
# ---------------------------------------------------------------------------


def test_only_turns_after_the_cursor_are_selected():
    outline = [
        {"seq": 1, "prompt": "早期问题", "response_excerpt": "早期回答"},
        {"seq": 2, "prompt": "新的决策", "response_excerpt": "新的回答"},
        {"seq": 5, "prompt": "更晚的决策", "response_excerpt": ""},
    ]
    turns, cursor = dreaming.select_undreamt_turns(outline, last_seq=1)
    assert [turn["seq"] for turn in turns] == [2, 5]
    assert cursor == 5


def test_cursor_never_moves_backwards():
    _, cursor = dreaming.select_undreamt_turns([{"seq": 3, "prompt": "x", "response_excerpt": "y"}], last_seq=9)
    assert cursor == 9


@pytest.mark.asyncio
async def test_a_short_turn_waits_but_is_never_dropped(project_work, monkeypatch):
    # Length only decides WHEN the turn-end trigger fires; the sweep digests the
    # short turn later instead of losing it.
    monkeypatch.setattr(dreaming, "_background_model_id", lambda: "test/model")
    llm = StubLLM(_output(project={"core": "- 用户在改用 Rust\n", "memories": []}))
    context = _FakeContext(_outline_snapshot("决定改用 Rust 重写。"), llm)

    deferred = await dreaming.maybe_dream_after_turn(
        context=context, thread_id="s1", work_root=str(project_work)
    )
    assert deferred["status"] == "skipped"
    assert deferred["reason"] == "waiting_for_more"
    assert llm.requests == []

    swept = await dreaming.maybe_dream_after_turn(
        context=context,
        thread_id="s1",
        work_root=str(project_work),
        ignore_size_gate=True,
    )
    assert swept["status"] == "applied"
    assert "用户在改用 Rust" in memory.read_core_document(memory.SCOPE_PROJECT, project_work)


# ---------------------------------------------------------------------------
# Applying a pass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dream_writes_memories_and_the_core_document(project_work):
    # Cognition evolves as a whole (contradictions get resolved), pinned text
    # survives, and the replaced version stays recoverable.
    memory.write_core_document(
        memory.SCOPE_PROJECT,
        project_work,
        "# 项目认知\n旧的手写内容。\n\n"
        f"{memory.CORE_PINNED_START}\n必须保留的一句。\n{memory.CORE_PINNED_END}\n",
    )
    llm = StubLLM(
        _output(
            **{
                "global": {"core_auto": "- 用户偏好直接给结论", "memories": []},
                "project": {
                    "core": "# 项目认知\n方案先落盘再实现。\n",
                    "memories": [
                        {
                            "path": "decisions/plan-first.md",
                            "mode": "write",
                            "content": "当要开始一个新需求时，读这条：先写方案再实现。\n",
                        }
                    ],
                },
            }
        )
    )

    result = await _run(project_work, llm)

    assert result["status"] == "applied"
    project_core = memory.read_core_document(memory.SCOPE_PROJECT, project_work)
    assert "方案先落盘再实现" in project_core
    assert "必须保留的一句。" in project_core
    assert "旧的手写内容。" not in project_core
    versions = memory.list_core_versions(memory.SCOPE_PROJECT, project_work)
    assert versions, "the replaced document must stay recoverable"
    snapshot = (
        memory.memory_root(memory.SCOPE_PROJECT, project_work)
        / memory.library.VERSIONS_DIRNAME
        / str(versions[0]["id"])
    )
    assert "旧的手写内容。" in snapshot.read_text(encoding="utf-8")
    assert memory.read_memory(
        memory.SCOPE_PROJECT, project_work, "decisions/plan-first.md"
    ).startswith("当要开始一个新需求时")

    global_core = memory.read_core_document(memory.SCOPE_GLOBAL, None)
    assert "用户偏好直接给结论" in global_core

    state = dreaming.load_state(memory.SCOPE_PROJECT, project_work)
    assert state["sessions"]["s1"]["last_seq"] == 2
    assert state["last_dream_at"]


@pytest.mark.asyncio
async def test_dream_appends_to_an_existing_memory_file(project_work):
    memory.write_memory(
        memory.SCOPE_PROJECT, project_work, "notes/stack.md", "first line\n"
    )
    llm = StubLLM(
        _output(
            project={
                "core_auto": "",
                "memories": [
                    {"path": "notes/stack.md", "mode": "append", "content": "second line\n"}
                ],
            }
        )
    )

    await _run(project_work, llm)

    content = memory.read_memory(memory.SCOPE_PROJECT, project_work, "notes/stack.md")
    assert "first line" in content and "second line" in content


@pytest.mark.asyncio
async def test_failure_keeps_existing_memory(project_work):
    memory.write_core_document(memory.SCOPE_PROJECT, project_work, "# 认知\n已存在。\n")
    llm = StubLLM(raises=RuntimeError("provider down"))

    result = await _run(project_work, llm)

    assert result["status"] == "failed"
    assert "provider down" in result["reason"]
    assert memory.read_core_document(memory.SCOPE_PROJECT, project_work) == "# 认知\n已存在。\n"
    state = dreaming.load_state(memory.SCOPE_PROJECT, project_work)
    assert "provider down" in state["last_error"]
    assert state["sessions"] == {}


@pytest.mark.asyncio
async def test_invalid_json_is_a_failed_pass(project_work):
    llm = StubLLM("这不是 JSON")
    result = await _run(project_work, llm)
    assert result["status"] == "failed"
    assert memory.read_core_document(memory.SCOPE_PROJECT, project_work) == ""


# ---------------------------------------------------------------------------
# Safety rails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_secrets_are_dropped_instead_of_stored(project_work):
    llm = StubLLM(
        _output(
            project={
                "core_auto": "- 用户常用 OpenAI\n- api_key: sk-abcdef0123456789abcdef",
                "memories": [
                    {
                        "path": "ops/secrets.md",
                        "mode": "write",
                        "content": "密码: hunter2hunter2\n正常内容一行。\n",
                    }
                ],
            }
        )
    )

    await _run(project_work, llm)

    core = memory.read_core_document(memory.SCOPE_PROJECT, project_work)
    assert "用户常用 OpenAI" in core
    assert "sk-abcdef0123456789abcdef" not in core
    stored = memory.read_memory(memory.SCOPE_PROJECT, project_work, "ops/secrets.md")
    assert "hunter2hunter2" not in stored
    assert "正常内容一行。" in stored


@pytest.mark.asyncio
async def test_reserved_files_cannot_be_written_by_dreaming(project_work):
    llm = StubLLM(
        _output(
            project={
                "core_auto": "",
                "memories": [
                    {"path": "INDEX.md", "mode": "write", "content": "伪造索引"},
                    {"path": "memory.md", "mode": "write", "content": "伪造认知"},
                    {"path": "../escape.md", "mode": "write", "content": "逃逸"},
                    {"path": "notes/ok.md", "mode": "write", "content": "正常"},
                ],
            }
        )
    )

    result = await _run(project_work, llm)

    assert "notes/ok.md" in [item["path"] for item in result["written"]]
    assert memory.read_core_document(memory.SCOPE_PROJECT, project_work) != "伪造认知"
    assert not (project_work / ".lam" / "memory" / "INDEX.md").read_text(
        encoding="utf-8"
    ).startswith("伪造索引")


@pytest.mark.asyncio
async def test_disabled_switch_stops_the_pass(project_work):
    memory_settings.set_memory_enabled(False)
    llm = StubLLM(_output(project={"core_auto": "- 不应写入", "memories": []}))

    result = await _run(project_work, llm)

    assert result["status"] == "skipped"
    assert result["reason"] == "disabled"
    assert llm.requests == []
    assert "不应写入" not in memory.read_core_document(memory.SCOPE_PROJECT, project_work)
    memory_settings.set_memory_enabled(True)


@pytest.mark.asyncio
async def test_disabled_while_the_model_runs_discards_the_result(project_work):
    class DisablingLLM(StubLLM):
        async def complete(self, request):
            memory_settings.set_memory_enabled(False)
            return await super().complete(request)

    llm = DisablingLLM(_output(project={"core_auto": "- 关闭后不应落盘", "memories": []}))
    result = await _run(project_work, llm)

    assert result["status"] == "skipped"
    assert result["reason"] == "disabled"
    assert "关闭后不应落盘" not in memory.read_core_document(memory.SCOPE_PROJECT, project_work)
    memory_settings.set_memory_enabled(True)


@pytest.mark.asyncio
async def test_concurrent_pass_is_refused_not_merged(project_work):
    handle = dreaming.acquire_dream_lock(memory.SCOPE_PROJECT, project_work)
    assert handle is not None
    try:
        llm = StubLLM(_output(project={"core_auto": "- 并发", "memories": []}))
        result = await _run(project_work, llm)
        assert result["status"] == "skipped"
        assert result["reason"] == "busy"
        assert llm.requests == []
    finally:
        dreaming.release_dream_lock(handle)


@pytest.mark.asyncio
async def test_cooldown_blocks_a_second_automatic_pass(project_work):
    llm = StubLLM(_output(project={"core_auto": "", "memories": []}))

    first = await dreaming.dream_session(
        llm_client=llm,
        model_id="test/model",
        work_root=project_work,
        scope="project",
        session_id="s1",
        turns=_turns(),
        now=time.time(),
    )
    assert first["status"] == "applied"

    second = await dreaming.dream_session(
        llm_client=llm,
        model_id="test/model",
        work_root=project_work,
        scope="project",
        session_id="s2",
        turns=_turns(),
        now=time.time(),
    )
    assert second["status"] == "skipped"
    assert second["reason"] == "cooldown"

    forced = await dreaming.dream_session(
        llm_client=llm,
        model_id="test/model",
        work_root=project_work,
        scope="project",
        session_id="s2",
        turns=_turns(),
        force=True,
        now=time.time(),
    )
    assert forced["status"] == "applied"


# ---------------------------------------------------------------------------
# Forgotten entries
# ---------------------------------------------------------------------------


def test_forgotten_entries_are_persisted_with_the_tier(project_work):
    dreaming.record_forgotten(memory.SCOPE_PROJECT, project_work, "notes/old.md", title="旧结论")

    state = dreaming.load_state(memory.SCOPE_PROJECT, project_work)
    assert state["forgotten"][0]["path"] == "notes/old.md"
    assert state["forgotten"][0]["title"] == "旧结论"


@pytest.mark.asyncio
async def test_forgotten_entries_reach_the_prompt(project_work):
    dreaming.record_forgotten(memory.SCOPE_PROJECT, project_work, "notes/old.md", title="旧结论")
    llm = StubLLM(_output())

    await _run(project_work, llm)

    assert llm.requests, "the model must have been called"
    prompt = "\n".join(str(message.content) for message in llm.requests[0].messages)
    assert "notes/old.md" in prompt
    assert "忘记" in prompt or "forgotten" in prompt.lower()


# ---------------------------------------------------------------------------
# Turn-end trigger (what `_run_core_turn` actually calls)
# ---------------------------------------------------------------------------


class _AsyncCM:
    def __init__(self, value=None):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *exc):
        return False


class _FakePersistence:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    async def load_items_by_kind(self, db, thread_id, *, text_marker):
        return self.snapshot


class _FakeHost:
    def __init__(self, llm_client, session_store=None):
        self.llm_client = llm_client
        self.session_store = session_store


class _FakeContext:
    def __init__(self, snapshot, llm_client, session_store=None):
        self.persistence = _FakePersistence(snapshot)
        self.host = _FakeHost(llm_client, session_store)

    def session_factory(self):
        return _AsyncCM(None)


def _outline_snapshot(prompt: str, response: str = "了解。") -> dict:
    return {
        "thread_id": "s1",
        "items": {
            "u1": {"type": "userMessage", "content": prompt, "seq": 1, "status": "completed"},
            "a1": {"type": "agentMessage", "content": response, "seq": 2, "status": "completed"},
        },
        "item_order": ["u1", "a1"],
    }


@pytest.mark.asyncio
async def test_turn_end_pass_dreams_only_the_new_turns(project_work, monkeypatch):
    monkeypatch.setattr(dreaming, "_background_model_id", lambda: "test/model")
    llm = StubLLM(_output(project={"core_auto": "- 用户偏好方案先行", "memories": []}))
    prompt = (
        "我们约定：以后先写方案再实现，方案放进方案目录；改代码前先写验收测试，"
        "只跑本次新增的相关测试；界面改动优先复用已有控件。" * 5
    )
    # 必须够得上整理门槛，否则这条用例证明的是「闲聊不记忆」而不是触发链路。
    assert len(prompt) >= dreaming.DREAM_MIN_NEW_CHARS

    context = _FakeContext(_outline_snapshot(prompt), llm)

    result = await dreaming.maybe_dream_after_turn(
        context=context, thread_id="s1", work_root=str(project_work), force=True
    )

    assert result["status"] == "applied"
    assert "用户偏好方案先行" in memory.read_core_document(memory.SCOPE_PROJECT, project_work)
    state = dreaming.load_state(memory.SCOPE_PROJECT, project_work)
    # 游标记的是「这一轮」的序号（用户条目的 seq），下一轮从它之后继续。
    assert state["sessions"]["s1"]["last_seq"] == 1

    # 同一段对话不会被反复整理：游标之后没有新回合就不再调用模型。
    calls_before = len(llm.requests)
    again = await dreaming.maybe_dream_after_turn(
        context=context, thread_id="s1", work_root=str(project_work), force=True
    )
    assert again["status"] == "skipped"
    assert again["reason"] == "no_new_turns"
    assert len(llm.requests) == calls_before


@pytest.mark.asyncio
async def test_turn_end_pass_skips_without_a_model(project_work):
    context = _FakeContext(_outline_snapshot("随便聊聊。"), None)
    result = await dreaming.maybe_dream_after_turn(
        context=context, thread_id="s1", work_root=str(project_work), force=True
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "no_model"


@pytest.mark.asyncio
@pytest.mark.parametrize("edited", ["用户刚保存的普通编辑。", ""])
async def test_an_inflight_dream_preserves_edits_and_clears(project_work, edited):
    scope = memory.SCOPE_PROJECT
    memory.write_core_document(scope, project_work, "旧的核心认知。")

    class EditingModel(StubLLM):
        async def complete(self, request):
            assert "旧的核心认知。" in request.messages[-1].content
            memory.write_core_document(scope, project_work, edited)
            return await super().complete(request)

    result = await _run(project_work, EditingModel(_output(project={"core": "旧版本的整理结果。"})))

    assert result["status"] == "applied"
    assert not result["written"]
    assert memory.read_core_document(scope, project_work) == edited


@pytest.mark.asyncio
async def test_an_inflight_dream_cannot_recreate_a_deleted_memory(project_work):
    scope = memory.SCOPE_PROJECT
    path = "notes/old.md"
    memory.write_memory(scope, project_work, path, "用户要忘记的内容。")

    class DeletingModel(StubLLM):
        async def complete(self, request):
            memory.delete_memory(scope, project_work, path)
            dreaming.record_forgotten(scope, project_work, path)
            return await super().complete(request)

    llm = DeletingModel(_output(project={"memories": [
        {"path": "notes/./old.md", "content": "用户要忘记的内容。"},
        {"path": "notes/new.md", "content": "应保留的另一条记忆。"},
    ]}))
    result = await _run(project_work, llm)

    assert result["written"] == [{"scope": scope, "path": "notes/new.md"}]
    assert not (memory.memory_root(scope, project_work) / path).exists()


@pytest.mark.asyncio
async def test_only_one_pass_runs_at_a_time(project_work, monkeypatch):
    # A pass in another project can still write the shared global tier; the
    # process therefore serializes passes instead of letting them interleave.
    monkeypatch.setattr(dreaming, "_PASS_ACTIVE", True)
    llm = StubLLM(_output(project={"core_auto": "- 不应写入", "memories": []}))

    result = await _run(project_work, llm)

    assert result["status"] == "skipped"
    assert result["reason"] == "busy"
    assert llm.requests == []
    assert "不应写入" not in memory.read_core_document(memory.SCOPE_PROJECT, project_work)


def test_a_stale_lock_is_reclaimed(project_work):
    import os
    import time

    root = memory.memory_root(memory.SCOPE_PROJECT, project_work)
    lock = root / dreaming.STATE_DIRNAME / dreaming.LOCK_FILENAME
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("999999 0", encoding="utf-8")
    stale = time.time() - dreaming.DREAM_LOCK_STALE_SECONDS - 60
    os.utime(lock, (stale, stale))

    acquired = dreaming.acquire_dream_lock(memory.SCOPE_PROJECT, project_work)
    try:
        assert acquired is not None, "a dead pass must not block later passes"
    finally:
        dreaming.release_dream_lock(acquired)
    assert not lock.exists()


def test_a_corrupt_state_file_falls_back_to_defaults(project_work):
    state_path = dreaming._state_path(memory.SCOPE_PROJECT, project_work)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{ not json", encoding="utf-8")

    state = dreaming.load_state(memory.SCOPE_PROJECT, project_work)

    assert state["version"] == 1
    assert state["sessions"] == {}
    assert state["last_error"] == ""
