"""Long-term memory: a directory-backed, tool-driven memory library.

The old structured store and dreaming pipeline were removed (product decision
2026-10-01).  Memory is now plain files under two tiers — ``global``
(``.lam/core/config/memory/``) and ``project`` (``<work_root>/.lam/memory/``) —
managed through the ``memory`` tool, the ``memory.*`` RPCs and the
``core memory`` CLI group.  See :mod:`lamtools_core.mem.library`.
"""

from __future__ import annotations

from lamtools_core.mem import library
from lamtools_core.mem.library import (
    INDEX_FILENAME,
    MAX_INDEX_CHARS,
    MAX_READ_CHARS,
    RESERVED_NAMES,
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
    MemoryConflictError,
    MemoryEntry,
    MemoryError,
    MemoryNotFoundError,
    MemoryPathError,
    MemoryReservedError,
    append_memory,
    delete_memory,
    edit_memory,
    has_content,
    index_text_for_prompt,
    list_entries,
    make_directory,
    memory_root,
    normalize_scope,
    read_memory,
    refresh_index,
    rename_memory,
    render_index,
    resolve_memory_path,
    reveal_memory,
    write_memory,
)

__all__ = [
    "library",
    "INDEX_FILENAME",
    "MAX_INDEX_CHARS",
    "MAX_READ_CHARS",
    "RESERVED_NAMES",
    "SCOPE_GLOBAL",
    "SCOPE_PROJECT",
    "MemoryConflictError",
    "MemoryEntry",
    "MemoryError",
    "MemoryNotFoundError",
    "MemoryPathError",
    "MemoryReservedError",
    "append_memory",
    "delete_memory",
    "edit_memory",
    "index_text_for_prompt",
    "list_entries",
    "make_directory",
    "memory_root",
    "normalize_scope",
    "read_memory",
    "refresh_index",
    "rename_memory",
    "render_index",
    "resolve_memory_path",
    "reveal_memory",
    "write_memory",
]
