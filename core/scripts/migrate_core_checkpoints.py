"""Run the resumable legacy checkpoint -> V2 metadata migration.

This command only creates/populates V2 rows.  It never clears legacy payloads
and never runs VACUUM.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.checkpoint_v2 import migrate_legacy_checkpoints


async def run(path: Path) -> dict[str, int]:
    db = await open_core_app_db(path)
    try:
        first = await migrate_legacy_checkpoints(db.session_factory, write_coordinator=db.persistence.write_coordinator, batch_size=1)
        second = await migrate_legacy_checkpoints(db.session_factory, write_coordinator=db.persistence.write_coordinator, batch_size=1)
        return {
            "scanned": first.scanned,
            "migrated": first.migrated,
            "skipped_first_run": first.skipped,
            "second_run_migrated": second.migrated,
            "second_run_skipped": second.skipped,
            "repaired": first.repaired,
            "second_run_repaired": second.repaired,
            "materialized_first_run": first.materialized,
            "materialized_second_run": second.materialized,
        }
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.db)), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
