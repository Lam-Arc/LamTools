"""Best-effort wakeups for changes already committed to the sync journal."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def publish_committed_changes(journal: Any, publisher: Any, change_ids: list[str]) -> None:
    # user:“失败点是读取 sync 变更”+(提交后的通知失败不能把成功写入变成失败；变更保留供游标补拉)。
    if journal is None or publisher is None:
        return
    for change_id in change_ids:
        try:
            change = await journal.get_change(change_id)
            if change is not None:
                await publisher({"method": "sync/change", "params": change})
        except Exception:
            # Do not swallow task cancellation. The journal is the durable
            # delivery path; live notification is only a wakeup, never a commit.
            logger.warning("[sync] committed change notification failed change_id=%s; available for cursor replay",
                           change_id, exc_info=True)
