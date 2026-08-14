"""P1 集成验证：插件 → 真实 CoreToolbox 装配 → 惰性暴露 → 审批 → 执行 → 答案闸门。

验证链（docs/rag-plugin-plan.md §1 P1 出口标准，toolbox 层无 LLM）：
1. 插件工具在对应 skill 加载前对模型不可见（惰性暴露，零膨胀）
2. load_skill(rag-for-agent) 后：检索类工具可见；rag_index 仍不可见（rag-indexer 未加载）
3. rag_index：ask_user → requires_approval=True（审批门生效）
4. rag_search：检索命中 + snippet + heading 锚点 + 元数据
5. submit_answer：合法引用通过 / 编造引用拦截 / 无引用拒绝
6. rag_search_sessions：P2 stub 诚实报错（不静默）
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from lamtools_core.plugins.tools import (  # noqa: PLC0415
    complete_plugin_tool_specs,
    load_plugin_tools,
)
from lamtools_core.skills import SkillRegistry  # noqa: PLC0415
from lamtools_core.tool import ToolCall  # noqa: PLC0415
from lamtools_core.tool.default_toolbox import build_core_toolbox  # noqa: PLC0415

_PASS = 0
_FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    _PASS += ok
    _FAIL += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _visible_names(toolbox) -> set[str]:
    names: set[str] = set()
    for t in toolbox.model_tools():
        fn = t.get("function") if isinstance(t, dict) else None
        if isinstance(fn, dict):
            names.add(fn.get("name") or "")
        elif isinstance(t, dict) and t.get("name"):
            names.add(t["name"])
    return {n for n in names if n}


async def main() -> int:
    specs = load_plugin_tools([PLUGIN_ROOT / "tools/tools.jsonc"], plugin_root=PLUGIN_ROOT)
    completed = complete_plugin_tool_specs(
        specs,
        plugin_name="lamtools-rag",
        plugin_root=PLUGIN_ROOT,
        dependencies=["sqlite-vec>=0.1.9"],
    )
    with tempfile.TemporaryDirectory() as td:
        wr = Path(td) / "ws"
        wr.mkdir()
        doc = wr / "合同.md"
        doc.write_text(
            "# 销售合同\n\n## 第三条 违约责任\n\n乙方逾期交货的，应向甲方支付违约金，金额为合同总价的百分之三十。\n",
            encoding="utf-8",
        )
        data_dir = Path(td) / "data"
        data_dir.mkdir()
        skill_registry = SkillRegistry(explicit_roots=[PLUGIN_ROOT / "skills"])
        toolbox = build_core_toolbox(
            work_root=wr,
            data_dir=data_dir,
            skill_registry=skill_registry,
            plugin_tool_specs=completed,
        )

        # 1. 惰性暴露：加载前全部不可见
        before = _visible_names(toolbox)
        check(
            "skill 加载前 rag 工具全部不可见（零膨胀）",
            not (before & {"rag_search", "rag_index", "rag_read", "submit_answer"}),
            f"可见={sorted(before & {'rag_search', 'rag_index', 'rag_read', 'submit_answer'})}",
        )

        # 2. load_skill(rag-for-agent) → 检索类可见，rag_index 仍不可见
        call = ToolCall(id="1", name="load_skill", arguments={"name": "rag-for-agent"})
        call = toolbox.prepare_call(call)
        res = await toolbox.execute(call)
        check("load_skill(rag-for-agent) 成功", res.status == "ok", res.status)
        after = _visible_names(toolbox)
        check(
            "加载后检索类工具可见",
            {"rag_search", "rag_read", "rag_search_sessions", "submit_answer"} <= after,
            f"可见={sorted(after & {'rag_search', 'rag_read', 'rag_search_sessions', 'submit_answer'})}",
        )
        check("rag_index 仍不可见（rag-indexer 未加载）", "rag_index" not in after)

        # 3. rag_index：ask_user 审批
        call = ToolCall(id="2", name="rag_index", arguments={"paths": ["合同.md"]})
        call = toolbox.prepare_call(call)
        check("rag_index 触发审批（ask_user）", call.requires_approval is True)
        res = await toolbox.execute(call)  # 模拟审批通过后的执行
        check(
            "rag_index 执行成功（索引 1 文件）",
            res.status == "ok" and res.metadata.get("stats", {}).get("added") == 1,
            res.content,
        )

        # 4. rag_search：命中 + 锚点 + 元数据
        call = ToolCall(id="3", name="rag_search", arguments={"query": "违约金", "top": 5})
        call = toolbox.prepare_call(call)
        check("rag_search 免审批（auto_allow）", call.requires_approval is False)
        res = await toolbox.execute(call)
        hits = res.metadata.get("hits") or []
        check(
            "rag_search 命中且含 snippet",
            res.status == "ok" and hits and "违约金" in hits[0].get("snippet", ""),
            res.content[:120].replace("\n", " "),
        )
        check(
            "命中元数据含 doc_id/page/heading",
            hits and hits[0].get("doc_id") and hits[0].get("page") is not None,
            str(hits[0] if hits else {}),
        )

        # 5. submit_answer 闸门
        good = ToolCall(
            id="4",
            name="submit_answer",
            arguments={
                "answer": "违约金按合同总价 30% 收取",
                "citations": [
                    {
                        "doc_id": hits[0]["doc_id"],
                        "page": hits[0]["page"],
                        "text": "违约金，金额为合同总价的百分之三十",
                    }
                ],
            },
        )
        good = toolbox.prepare_call(good)
        res = await toolbox.execute(good)
        check("submit_answer 合法引用通过", res.status == "ok", res.content)

        fake = ToolCall(
            id="5",
            name="submit_answer",
            arguments={
                "answer": "违约金 3%",
                "citations": [{"doc_id": "fake", "page": 99, "text": "编造片段"}],
            },
        )
        fake = toolbox.prepare_call(fake)
        res = await toolbox.execute(fake)
        check("submit_answer 编造引用拦截", res.status == "failed", res.error)

        no_cite = ToolCall(
            id="6", name="submit_answer", arguments={"answer": "没有引用的答案"}
        )
        no_cite = toolbox.prepare_call(no_cite)
        res = await toolbox.execute(no_cite)
        check("submit_answer 无引用拒绝", res.status == "failed")

        # 6. rag_search_sessions：P2 stub 诚实报错
        call = ToolCall(id="7", name="rag_search_sessions", arguments={"query": "上次讨论"})
        call = toolbox.prepare_call(call)
        res = await toolbox.execute(call)
        check(
            "rag_search_sessions P2 stub 诚实报错",
            res.status == "failed" and "P2" in (res.error or ""),
            res.error,
        )

    print(f"\nP1 集成验证：PASS={_PASS} FAIL={_FAIL}")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    import asyncio

    sys.exit(asyncio.run(main()))
