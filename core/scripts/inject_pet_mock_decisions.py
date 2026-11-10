"""往一个真实会话里注入 mock 审批/提问，验证桌宠的转发链路。

user:"现在用climock一下审批和询问，包括子代理发的，看看桌宠能不能正常转发"+
"从上游mock，不要直接调显示的API，比如你可以mock某个会话发某个事件"+
(本脚本不碰任何显示接口：它做的是运行时本来就会做的事——往会话事件流写
 `approval_request` run item，并在决策池 `core_turn_interactions` 里落一条
 pending 记录。桌宠/主界面都是通过正常的快照与决策池读到它们的。)

用法（在 core/ 目录、后端未启动或已启动都可以，写入后重启桌宠覆盖层生效）：

    py -3.14 -m scripts.inject_pet_mock_decisions \
        --thread core-cli-7993f1df \
        --project 70035a5bc64e447596daa239222633ff \
        --pet-config ..\\.lam-petdev\\pet\\config.json \
        --pet-id blocky-1

清理：

    py -3.14 -m scripts.inject_pet_mock_decisions --thread core-cli-7993f1df --cleanup
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from lamtools_core.app.core_db import open_core_app_db, persist_core_run_items
from lamtools_core.event.run_item import RunItemEvent
from lamtools_core.turn.model import Interaction, InteractionOption
from lamtools_core.turn.store import TurnStore

#: 仓库根目录下的开发库（`<repo>/data/core.db`），与 `serve` 的 `_resolve_core_db`
#: 一致。不能用相对 cwd 的 `data/core.db`：从 core/ 运行会写到 core/data/ 的另一份库。
DEFAULT_DB = str(Path(__file__).resolve().parents[2] / "data" / "core.db")

#: 四个展示用例：主 Agent 审批 / 主 Agent 提问 / 子代理审批 / 子代理提问。
SPECS: list[dict[str, object]] = [
    {
        "slug": "approval-main",
        "kind": "approval",
        "agent": "",
        "title": "需要授权：整理下载目录里的临时文件（mock 审批）",
        "context": "桌宠应该弹出审批气泡，带上“允许 / 拒绝”和自由回复框。",
        "options": [
            ("approve", "允许执行", "approve"),
            ("deny", "拒绝执行", "deny"),
        ],
    },
    {
        "slug": "question-main",
        "kind": "question",
        "agent": "",
        "title": "主 Agent 提问：桌宠气泡里的问题和选项看清了吗？（mock 提问）",
        "context": "这是主 Agent 发的提问，回答会走 other_guidance 回到原请求。",
        "options": [
            ("option-1", "看清了", "看清了"),
            ("option-2", "没看清", "没看清"),
        ],
    },
    {
        "slug": "approval-sub",
        "kind": "approval",
        "agent": "Reviewer",
        "title": "子代理 Reviewer 请求授权：检查构建产物（mock 子代理审批）",
        "context": "来源应显示为“子代理 · Reviewer”，不能算到主 Agent 头上。",
        "options": [
            ("approve", "允许执行", "approve"),
            ("deny", "拒绝执行", "deny"),
        ],
    },
    {
        "slug": "question-sub",
        "kind": "question",
        "agent": "Researcher",
        "title": "子代理 Researcher 提问：报告要按什么口径汇总？（mock 子代理提问）",
        "context": "子代理的提问同样应该在桌宠上弹出，并带来源标签。",
        "options": [
            ("option-1", "按项目汇总", "按项目汇总"),
            ("option-2", "按时间汇总", "按时间汇总"),
        ],
    },
]


def _options(raw: list[tuple[str, str, str]]) -> list[InteractionOption]:
    return [
        InteractionOption(id=item_id, label=label, response=response or label)
        for item_id, label, response in raw
    ]


async def inject(args: argparse.Namespace) -> int:
    app_db = await open_core_app_db(args.db)
    try:
        store = TurnStore(app_db.session_factory, app_db.persistence.write_coordinator)
        stamp = int(time.time() * 1000)
        created: list[dict[str, str]] = []
        events: list[RunItemEvent] = []
        for spec in SPECS:
            slug = str(spec["slug"])
            kind = str(spec["kind"])
            agent = str(spec["agent"] or "")
            request_id = f"mock-pet-{slug}-{stamp}"
            turn_id = f"{args.thread}:turn:mock-pet-{slug}-{stamp}"
            scope = "main" if not agent else f"agent:{agent}"
            options = _options(spec["options"])  # type: ignore[arg-type]
            interaction = Interaction(
                interaction_id=request_id,
                turn_id=turn_id,
                thread_id=args.thread,
                run_id=turn_id,
                scope=scope,
                kind=kind,  # type: ignore[arg-type]
                status="open",
                tool_call_id=request_id,
                title=str(spec["title"]),
                context=str(spec["context"]),
                options=options,
                expires_at_ms=(stamp + 30 * 60 * 1000) if kind == "question" else 0,
                legacy_request_id=request_id,
                project_id=args.project,
                agent_name=agent,
                agent_session_id=f"mock-sub-{agent.lower()}" if agent else "",
                delivered_by="main" if not agent else f"agent:{agent}",
                metadata={"mock": True, "slug": slug},
            )
            await store.create_interaction(interaction)
            sub_agent = (
                {
                    "agent": agent,
                    "sub_session_id": interaction.agent_session_id,
                    "parent_session_id": args.thread,
                    "parent_turn_id": turn_id,
                }
                if agent
                else None
            )
            events.append(
                RunItemEvent(
                    kind="approval_request",
                    thread_id=args.thread,
                    event_id=f"{request_id}:event",
                    run_id=turn_id,
                    turn_id=turn_id,
                    item_id=request_id,
                    status="waiting",
                    payload={
                        "type": "serverRequest",
                        "request_id": request_id,
                        "tool_call_id": request_id,
                        "kind": kind,
                        "tool_name": "question" if kind == "question" else "command",
                        "message": str(spec["title"]),
                        "context": str(spec["context"]),
                        "options": [
                            {
                                "id": option.id,
                                "label": option.label,
                                "description": option.description,
                                "response": option.response,
                            }
                            for option in options
                        ],
                        "project_id": args.project,
                        **({"sub_agent": sub_agent} if sub_agent else {}),
                    },
                )
            )
            created.append({"request_id": request_id, "kind": kind, "agent": agent})
        # 与运行时一致：事件流 + 快照投影。桌宠随后通过普通快照读到决策池。
        await persist_core_run_items(app_db, events)
        print(json.dumps({"thread": args.thread, "created": created}, ensure_ascii=False, indent=2))
        if args.pet_config and args.pet_id:
            _bind_pet(Path(args.pet_config), args.pet_id, args.project, args.thread)
            print(f"pet binding written: {args.pet_config} -> {args.pet_id} = {args.thread}")
        return 0
    finally:
        await app_db.close()


def _bind_pet(path: Path, pet_id: str, project_id: str, session_id: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    bindings = data.setdefault("bindings", {})
    pets = bindings.setdefault("pets", {})
    pets[pet_id] = {"projectId": project_id, "sessionId": session_id}
    for record in data.get("pets", []) or []:
        if isinstance(record, dict) and record.get("id") == pet_id:
            record["projectId"] = project_id
            record["sessionId"] = session_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def cleanup(args: argparse.Namespace) -> int:
    app_db = await open_core_app_db(args.db)
    try:
        from sqlalchemy import delete

        from lamtools_core.app.core_db import CoreTurnInteraction

        async def write(db):
            result = await db.execute(
                delete(CoreTurnInteraction).where(
                    CoreTurnInteraction.thread_id == args.thread,
                    CoreTurnInteraction.interaction_id.like("mock-pet-%"),
                )
            )
            return result.rowcount or 0

        removed = await app_db.persistence.write(write)
        print(f"removed {removed} mock interaction(s) from {args.thread}")
        return 0
    finally:
        await app_db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject mock pet decisions into a session")
    parser.add_argument("--thread", required=True, help="Existing thread/session id")
    parser.add_argument("--project", default="", help="Project id recorded on the interactions")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"Core DB path (default: {DEFAULT_DB})")
    parser.add_argument("--pet-config", default="", help="Pet config.json to bind the pet to this session")
    parser.add_argument("--pet-id", default="", help="Pet id inside that config")
    parser.add_argument("--cleanup", action="store_true", help="Delete previously injected mock rows")
    args = parser.parse_args()
    asyncio.run(cleanup(args) if args.cleanup else inject(args))


if __name__ == "__main__":
    main()
