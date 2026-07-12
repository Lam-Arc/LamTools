from __future__ import annotations

from lamtools_core.app import CoreAppEventHub


WriterAppEventHub = CoreAppEventHub
hub = WriterAppEventHub()


__all__ = ["WriterAppEventHub", "hub"]
