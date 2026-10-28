"""QQ bot backend entry."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from qqbot.manager import QQBotManager  # noqa: E402
from qqbot.state import set_manager  # noqa: E402


class Runtime(QQBotManager):
    async def start(self, context=None):
        set_manager(self)
        await super().start(context)

    async def stop(self):
        try:
            await super().stop()
        finally:
            set_manager(None)


def create_plugin(context):
    return Runtime(context)


__all__ = ["Runtime", "create_plugin"]
