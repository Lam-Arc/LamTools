import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.app_server.hub import hub
from app.app_server.member_adapter import WriterLiveMemberAdapter
from app.app_server.persistence import _PERSISTENCE_HOST
from app.app_server.snapshot import load_snapshot
from app.database import Base
from lamtools_core.app import CoreLiveContext, CoreLiveOperationHost, OperationCatalog, OperationResult
from lamtools_core.tool.approval_continuation import resolve_waiting_decision
from tests.test_writer_app_runtime_bridge import persist_projection_from_runtime_fact, runtime_fact


class ApprovalRuntime:
    def __init__(self):
        self.responses = []
        self.resolved = None

    async def respond(self, request):
        if self.resolved is None:
            decision = resolve_waiting_decision(
                str(request.payload.get("decision") or request.payload.get("action") or ""),
                str(request.payload.get("guidance") or request.payload.get("response") or ""),
            )
            self.resolved = {"decision": decision.action, "guidance": decision.guidance_text}
            self.responses.append(dict(request.payload))
        return OperationResult(name=request.name, payload=self.resolved)


def approval_context(session_factory, runtime):
    hooks = WriterLiveMemberAdapter(session_factory=session_factory, runtime=runtime)
    operations = OperationCatalog()
    operations.register("approval.respond", runtime.respond)
    return CoreLiveContext(
        operations=operations,
        host=CoreLiveOperationHost(
            session_factory=session_factory,
            persistence=_PERSISTENCE_HOST,
            hub=hub,
            member_hooks=hooks,
        ),
    )


@pytest.mark.asyncio
async def test_approval_decision_resolves_once_through_core_host(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'approval.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    runtime = ApprovalRuntime()

    try:
        async with session_factory() as db:
            await persist_projection_from_runtime_fact(db, runtime_fact(
                "runtime-approval", "runtime.approval_request",
                {"turn_id": "turn-1", "tool_call_id": "item-1", "request_id": "request-1"},
            ))
            await db.commit()
        context = approval_context(session_factory, runtime)
        first = await context.host.execute(
            "approval.respond",
            request_id=1,
            params={"request_id": "request-1", "decision": "approve_once"},
            context=context,
        )
        second = await context.host.execute(
            "approval.respond",
            request_id=2,
            params={"request_id": "request-1", "decision": "deny"},
            context=context,
        )

        assert first.response["result"]["decision"] == "approve"
        assert second.response["result"]["decision"] == "approve"
        assert len(runtime.responses) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_approval_uses_snapshot_without_writer_request_row(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime-approval.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            event = runtime_fact(
                "runtime-approval",
                "runtime.approval_request",
                {
                    "turn_id": "turn-1",
                    "tool_call_id": "call-1",
                    "tool_name": "shell",
                    "request_id": "request-1",
                    "message": "Allow?",
                },
            )
            await persist_projection_from_runtime_fact(db, event)
            await db.commit()

            snapshot = await load_snapshot(db, "thread-1")
            assert snapshot["core"]["requests"]["request-1"]["status"] == "open"
            assert snapshot["core"]["status"] == "waiting"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_other_guidance_is_canonicalized_by_core_host(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'guidance-approval.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    runtime = ApprovalRuntime()
    try:
        async with session_factory() as db:
            await persist_projection_from_runtime_fact(db, runtime_fact(
                "runtime-guidance", "runtime.approval_request",
                {"turn_id": "turn-1", "tool_call_id": "item-1", "request_id": "request-1"},
            ))
            await db.commit()
        context = approval_context(session_factory, runtime)
        outcome = await context.host.execute(
            "approval.respond",
            request_id=1,
            params={"request_id": "request-1", "action": "other_guidance", "response": "Use safer command"},
            context=context,
        )
        payload = outcome.response["result"]
        assert payload["decision"] == "guide"
        assert payload["guidance"] == "Use safer command"
    finally:
        await engine.dispose()
