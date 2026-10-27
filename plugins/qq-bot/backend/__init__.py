"""QQ bot backend entry."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from qqbot.runtime import QQBotRuntime  # noqa: E402
from qqbot.state import set_runtime  # noqa: E402


class Runtime(QQBotRuntime):
    async def start(self, context=None):
        set_runtime(self)
        await super().start(context)

    async def stop(self):
        try:
            await super().stop()
        finally:
            set_runtime(None)


def create_plugin(context):
    return Runtime(context)


__all__ = ["Runtime", "create_plugin"]
