from __future__ import annotations

from lamtools_core.runtime import RuntimeState
from lamtools_core.sub_session import (
    SubSessionManager,
    SubSessionRuntimeStateStore,
    filter_sub_agent_tools,
)


def test_sub_session_manager_reuses_same_agent_identity() -> None:
    state = RuntimeState(session_id="parent-session")
    manager = SubSessionManager()

    first = manager.get_or_create(state, "repo_reader")
    second = manager.get_or_create(state, "repo_reader")

    assert first == second
    assert first.agent_name == "repo_reader"
    assert first.agent_index == "001"
    assert first.session_id == "parent-session:sub:001:repo_reader"


def test_sub_session_manager_assigns_next_index_per_parent_session() -> None:
    state = RuntimeState(session_id="parent-session")
    manager = SubSessionManager()

    first = manager.get_or_create(state, "repo_reader")
    second = manager.get_or_create(state, "test_fixer")

    assert first.agent_index == "001"
    assert second.agent_index == "002"
    assert second.session_id == "parent-session:sub:002:test_fixer"


def test_sub_session_manager_defaults_empty_agent_name_to_sub() -> None:
    state = RuntimeState(session_id="parent-session")
    manager = SubSessionManager()

    ref = manager.get_or_create(state, "")

    assert ref.agent_name == "sub"
    assert ref.agent_index == "001"
    assert ref.session_id == "parent-session:sub:001:sub"


def test_filter_sub_agent_tools_removes_recursive_delegate_tool() -> None:
    tools = [
        {"type": "function", "function": {"name": "read_file"}},
        {"type": "function", "function": {"name": "sub_agent"}},
        {"name": "legacy_tool"},
    ]

    filtered = filter_sub_agent_tools(tools)

    assert filtered == [
        {"type": "function", "function": {"name": "read_file"}},
        {"name": "legacy_tool"},
    ]


def test_sub_session_runtime_state_store_persists_inside_parent_state() -> None:
    parent = RuntimeState(session_id="parent-session")
    child = RuntimeState(session_id="parent-session:sub:001:repo_reader", turn_count=3)
    child.metadata["note"] = "kept"
    store = SubSessionRuntimeStateStore(parent)

    import asyncio

    asyncio.run(store.save(child))
    loaded = asyncio.run(store.get("parent-session:sub:001:repo_reader"))

    assert loaded == child
    assert "_sub_session_runtime_states" in parent.metadata


def test_sub_session_runtime_state_store_preserves_full_checkpoint_history() -> None:
    parent = RuntimeState(session_id="parent-session")
    child = RuntimeState(session_id="parent-session:sub:001:repo_reader")
    history = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"message-{index}"}
        for index in range(30)
    ]
    store = SubSessionRuntimeStateStore(parent)

    import asyncio

    asyncio.run(store.save_checkpoint(child, history))
    loaded = asyncio.run(store.get_history(child.session_id))

    assert loaded == history


def test_sub_session_checkpoint_immediately_persists_parent_state() -> None:
    parent = RuntimeState(session_id="parent-session")
    child = RuntimeState(session_id="parent-session:sub:001:worker")

    class ParentStore:
        def __init__(self) -> None:
            self.saved = []

        async def save(self, state: RuntimeState) -> None:
            self.saved.append(state)

    parent_store = ParentStore()
    store = SubSessionRuntimeStateStore(parent, parent_state_store=parent_store)

    import asyncio

    asyncio.run(store.save_checkpoint(child, [{"role": "user", "content": "task"}]))

    assert parent_store.saved == [parent]
