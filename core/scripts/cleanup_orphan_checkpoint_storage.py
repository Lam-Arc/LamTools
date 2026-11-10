"""Remove checkpoint files and manifest rows with no remaining references."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import delete, exists, select

from lamtools_core.app.core_db import (
    CoreCheckpoint,
    CoreCheckpointBlob,
    CoreCheckpointBlobRef,
    CoreCheckpointV2,
    CoreWorkspaceManifest,
    open_core_app_db,
)


async def cleanup(path: Path, *, dry_run: bool = False) -> dict[str, object]:
    db = await open_core_app_db(path)
    try:
        async with db.session_factory() as session:
            blob_rows = list((await session.execute(
                select(CoreCheckpointBlob).where(~exists(
                    select(CoreCheckpointBlobRef.blob_hash).where(
                        CoreCheckpointBlobRef.blob_hash == CoreCheckpointBlob.hash
                    )
                ))
            )).scalars())
            manifest_rows = list((await session.execute(
                select(CoreWorkspaceManifest).where(
                    CoreWorkspaceManifest.hash != "",
                    ~exists(select(CoreCheckpoint.id).where(
                        CoreCheckpoint.manifest_hash == CoreWorkspaceManifest.hash
                    )),
                    ~exists(select(CoreCheckpointV2.id).where(
                        CoreCheckpointV2.workspace_manifest_id == CoreWorkspaceManifest.hash
                    )),
                )
            )).scalars())
        blob_paths = [Path(str(row.storage_path)) for row in blob_rows if row.storage_path]
        if not dry_run and (blob_rows or manifest_rows):
            blob_hashes = [row.hash for row in blob_rows]
            manifest_hashes = [row.hash for row in manifest_rows]

            async def write(session) -> None:
                if blob_hashes:
                    await session.execute(delete(CoreCheckpointBlob).where(
                        CoreCheckpointBlob.hash.in_(blob_hashes)
                    ))
                if manifest_hashes:
                    await session.execute(delete(CoreWorkspaceManifest).where(
                        CoreWorkspaceManifest.hash.in_(manifest_hashes)
                    ))

            await db.persistence.write(write)
            for path_item in blob_paths:
                path_item.unlink(missing_ok=True)
        async with db.session_factory() as session:
            remaining_blobs = len((await session.execute(
                select(CoreCheckpointBlob.hash).where(~exists(
                    select(CoreCheckpointBlobRef.blob_hash).where(
                        CoreCheckpointBlobRef.blob_hash == CoreCheckpointBlob.hash
                    )
                ))
            )).all())
            remaining_manifests = len((await session.execute(
                select(CoreWorkspaceManifest.hash).where(
                    CoreWorkspaceManifest.hash != "",
                    ~exists(select(CoreCheckpoint.id).where(
                        CoreCheckpoint.manifest_hash == CoreWorkspaceManifest.hash
                    )),
                    ~exists(select(CoreCheckpointV2.id).where(
                        CoreCheckpointV2.workspace_manifest_id == CoreWorkspaceManifest.hash
                    )),
                )
            )).all())
        return {
            "dry_run": dry_run,
            "orphan_blobs": len(blob_rows),
            "orphan_blob_bytes": sum(int(row.size or 0) for row in blob_rows),
            "orphan_blob_files": len(blob_paths),
            "orphan_manifests": len(manifest_rows),
            "remaining_orphan_manifests": remaining_manifests if not dry_run else len(manifest_rows),
            "remaining_orphan_blobs": remaining_blobs if not dry_run else len(blob_rows),
        }
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(cleanup(args.db, dry_run=args.dry_run)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
