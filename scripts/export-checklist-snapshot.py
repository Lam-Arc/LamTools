"""导出一个真实会话的完整快照，供 checklist 恢复回归测试使用。

user:“重启会导致 checklist 丢失”+(复现依赖重启后 UI 收到的真实快照数据；
本脚本用后端 snapshot_store.load() 重建该快照并存成 JSON，配合
core/ui/tests/checklist-restart-repro.test.ts（设 CHK_SNAPSHOT_PATH 环境变量）
回归验证恢复后的 checklist 卡片)。

用法（在仓库根目录）:
    python scripts/export-checklist-snapshot.py <thread_id> <输出.json> [data/core.db]
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core" / "src"))


async def export_snapshot(thread_id: str, output: str, db_path: str) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from lamtools_core.app.core_db import CoreAppEvent, CoreThreadSnapshot, CoreThreadSnapshotItem
    from lamtools_core.app.snapshot_store import (
        CoreAppSnapshotProjector,
        SqlAlchemyThreadSnapshotStore,
    )

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{Path(db_path).resolve()}",
        connect_args={"timeout": 30},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    store = SqlAlchemyThreadSnapshotStore(
        CoreThreadSnapshot,
        item_model=CoreThreadSnapshotItem,
        projector=CoreAppSnapshotProjector(),
        event_model=CoreAppEvent,
    )
    try:
        async with session_factory() as db:
            snapshot = await store.load(db, thread_id)
    finally:
        await engine.dispose()

    core = snapshot.get("core") or {}
    has_plan = isinstance(core.get("task_plan"), dict)
    Path(output).write_text(
        json.dumps(snapshot, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"items={len(core.get('items') or {})} task_plan={'present' if has_plan else 'absent'} -> {output}")


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    thread_id = sys.argv[1]
    output = sys.argv[2]
    db_path = sys.argv[3] if len(sys.argv) > 3 else str(ROOT / "data" / "core.db")
    asyncio.run(export_snapshot(thread_id, output, db_path))


if __name__ == "__main__":
    main()
