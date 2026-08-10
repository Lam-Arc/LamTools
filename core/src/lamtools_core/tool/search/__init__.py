"""Search index public API: protocol types + provider registry."""

from __future__ import annotations

from .protocol import SearchProvider, SearchResult
from .factory import (
    build_web_search_handler,
    get_provider,
    list_providers,
)

__all__ = [
    "SearchProvider",
    "SearchResult",
    "build_web_search_handler",
    "get_provider",
    "list_providers",
]