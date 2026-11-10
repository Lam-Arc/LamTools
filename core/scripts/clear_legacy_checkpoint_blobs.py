"""Clear legacy checkpoint payloads in small, verified batches.

This command never deletes checkpoint rows.  It requires both the V2 row and
the migrated materialized recovery row to exist before changing a blob, and it
orders automatic batches by payload size so the largest storage consumers are
handled first.  Run the V2 validator after each batch.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update

from lamtools_core.app.core_db import (
    CoreCheckpoint,
    CoreCheckpointV2,
    CoreCheckpointV2Materialized,
    open_core_app_db,
)


async def clear_batch(
    path: Path,
    *,
    limit: int,
    checkpoint_ids: list[str] | None = None,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be positive")
    db = await open_core_app_db(path)
    try:
        async with db.session_factory() as connection:
            if checkpoint_ids:
                rows = list((await connection.execute(
                    select(CoreCheckpoint.id, func.length(CoreCheckpoint.conversation_json))
                    .where(CoreCheckpoint.id.in_(checkpoint_ids))
                )).all())
                by_id = {str(row[0]): int(row[1] or 0) for row in rows}
                missing = [checkpoint_id for checkpoint_id in checkpoint_ids if checkpoint_id not in by_id]
                if missing:
                    raise LookupError(f"Checkpoint not found: {', '.join(missing)}")
                selected = [(checkpoint_id, by_id[checkpoint_id]) for checkpoint_id in checkpoint_ids]
            else:
                selected = [
                    (str(row[0]), int(row[1] or 0))
                    for row in (await connection.execute(
                        select(CoreCheckpoint.id, func.length(CoreCheckpoint.conversation_json))
                        .where(CoreCheckpoint.conversation_json.is_not(None))
                        .where(func.length(CoreCheckpoint.conversation_json) > 2)
                        .order_by(func.length(CoreCheckpoint.conversation_json).desc(), CoreCheckpoint.id.asc())
                        .limit(limit)
                    )).all()
                ]
            if len(selected) > limit:
                raise ValueError(f"Refusing to clear {len(selected)} rows; limit is {limit}")
            if not selected:
                return {"cleared": 0, "checkpoint_ids": [], "bytes_before": 0, "bytes_after": 0}

            ids = [checkpoint_id for checkpoint_id, _ in selected]
            for checkpoint_id, size in selected:
                if size <= 2:
                    raise ValueError(f"Checkpoint blob is already empty: {checkpoint_id}")
                if await connection.get(CoreCheckpointV2, checkpoint_id) is None:
                    raise LookupError(f"V2 checkpoint is missing: {checkpoint_id}")
                if await connection.get(CoreCheckpointV2Materialized, checkpoint_id) is None:
                    raise LookupError(f"V2 recovery material is missing: {checkpoint_id}")

            result = await connection.execute(
                update(CoreCheckpoint)
                .where(CoreCheckpoint.id.in_(ids))
                .values(conversation_json={})
            )
            if result.rowcount != len(ids):
                raise RuntimeError(f"Only cleared {result.rowcount} of {len(ids)} checkpoint blobs")
            await connection.commit()
            return {
                "cleared": len(ids),
                "checkpoint_ids": ids,
                "bytes_before": sum(size for _, size in selected),
                "bytes_after": len(ids) * 2,
            }
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("checkpoint", nargs="*")
    args = parser.parse_args()
    result = asyncio.run(clear_batch(
        args.db,
        limit=args.limit,
        checkpoint_ids=list(args.checkpoint) or None,
    ))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
