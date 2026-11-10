"""取用回路端到端：按素材需求检索、按星级排序、取到用法、落地后回写。

user:“再利用是 agent 来再利用，人只做观测和选用……用低透玻璃材质和 ping 环的
环形交互样式，质量按照星级就行”+(一句话里出现多个素材，Agent 要能一次查到、
按星级挑、拿到怎么用，落完代码把这次使用记在素材上)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import LIBRARY_TOOL_NAME
from lamtools_core.tool.library_tools import make_library_handler


def _call(**arguments):
    return ToolCall(id="call-1", name=LIBRARY_TOOL_NAME, arguments=arguments)


async def _seed(tmp_path: Path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    db = await open_core_app_db(tmp_path / "core.db")
    project, _ = await db.project_store.create(work_root)
    store = db.artifact_store

    files = {
        "glass.css": "低透玻璃",
        "ring.vue": "ping 环",
        "card.css": "卡片",
    }
    for name, _label in files.items():
        (work_root / name).write_text("/* x */", encoding="utf-8")

    async def register(name: str) -> str:
        record = await store.register(
            project_id=project.id,
            work_root=work_root,
            path=name,
            kind="file_change",
            mime_type="text/css" if name.endswith(".css") else "text/plain",
            name=name,
            source="agent_generated",
            role="deliverable",
        )
        return record.artifact_id

    glass = await register("glass.css")
    ring = await register("ring.vue")
    card = await register("card.css")

    await store.set_tags(glass, ["material", "glass", "low-trans", "surface"])
    await store.set_usage(
        glass,
        {
            "entry": ".optical-glass--low-trans",
            "requires": "父级要有可见底色",
            "example": '<div class="optical-glass optical-glass--low-trans">面板</div>',
        },
    )
    await store.set_rating(glass, 5)

    await store.set_tags(ring, ["control", "ring", "ping-ring", "interaction"])
    await store.set_usage(
        ring,
        {"entry": "import PingRing from '@/pet/ui/PingRing.vue'", "requires": "props.ping: PingRuntime"},
    )
    await store.set_rating(ring, 4)

    await store.set_tags(card, ["control", "card", "surface"])
    await store.set_rating(card, 3)

    handler = make_library_handler(store, work_root)
    return db, store, handler, glass, ring, card


@pytest.mark.asyncio
async def test_two_intents_are_found_and_ranked_by_rating(tmp_path):
    db, _store, library, glass, ring, _card = await _seed(tmp_path)

    # 材质：低透玻璃
    material = await library(_call(action="list", tag=["material", "low-trans"]))
    assert material.status == "ok"
    assert glass in material.content

    # 交互：环形
    interaction = await library(_call(action="list", tag="ring"))
    assert interaction.status == "ok"
    assert ring in interaction.content

    # 两条都要能按星级挑：5 分的玻璃排在 4 分的环前面
    ranked = await library(_call(action="list", sort="rating"))
    assert ranked.status == "ok"
    assert ranked.content.index("glass.css") < ranked.content.index("card.css")

    await db.close()


@pytest.mark.asyncio
async def test_list_carries_how_to_use_it(tmp_path):
    db, _store, library, glass, _ring, _card = await _seed(tmp_path)

    result = await library(_call(action="list", tag=["material", "glass"]))

    assert result.status == "ok"
    # 只有路径不算取用：输出里必须带着从哪进。
    assert "entry=.optical-glass--low-trans" in result.content
    assert f"used=0" in result.content
    assert glass in result.content

    await db.close()


@pytest.mark.asyncio
async def test_use_writes_the_trace_back_onto_the_material(tmp_path):
    db, store, library, glass, ring, _card = await _seed(tmp_path)

    landed = await library(
        _call(
            action="use",
            artifact_ids=[glass, ring],
            used_in="会话 悬浮面板 / core/ui/src/components/FloatingPanel.vue",
        )
    )
    assert landed.status == "ok"

    glass_record = await store.get(glass)
    ring_record = await store.get(ring)
    assert glass_record.usage_count == 1
    assert ring_record.usage_count == 1
    assert "FloatingPanel.vue" in (glass_record.used_in[0]["where"] if glass_record.used_in else "")
    assert glass_record.last_used_at

    # 再列一次，取用次数要出现在给 Agent 看的那一行里
    listed = await library(_call(action="list", tag="glass"))
    assert "used=1" in listed.content

    # 顺序也要跟着变：同分时用得多的靠前
    used_first = await library(_call(action="list", sort="used"))
    assert used_first.content.index("glass.css") <= used_first.content.index("ring.vue")

    await db.close()


@pytest.mark.asyncio
async def test_use_requires_somewhere_to_point_at(tmp_path):
    db, _store, library, glass, _ring, _card = await _seed(tmp_path)

    result = await library(_call(action="use", artifact_ids=[glass], used_in="   "))

    assert result.status == "failed"
    assert result.error_code == "missing_argument"

    await db.close()


@pytest.mark.asyncio
async def test_tagging_replaces_class_name_fragments(tmp_path):
    db, store, library, glass, _ring, _card = await _seed(tmp_path)

    await library(_call(action="tag", artifact_ids=[glass], tags=["head", "row"], mode="add"))
    replaced = await library(
        _call(action="tag", artifact_ids=[glass], tags=["material", "glass", "low-trans"], mode="set")
    )
    assert replaced.status == "ok"

    record = await store.get(glass)
    assert record.tags == ["material", "glass", "low-trans"]

    await db.close()
