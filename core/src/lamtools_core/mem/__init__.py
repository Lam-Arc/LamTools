"""Long-term memory: a directory-backed, tool-driven memory library.

The old structured store was removed (product decision 2026-10-01).  Memory is
now plain files under two tiers — ``global`` (``.lam/core/config/memory/``) and
``project`` (``<work_root>/.lam/memory/``) — managed through the ``memory``
tool, the ``memory.*`` RPCs and the ``core memory`` CLI group.  See
:mod:`lamtools_core.mem.library`.

On top of that knowledge store, each tier keeps one ``memory.md`` root document
(the L1 core cognition injected into every request) and a ``.dreaming`` state
directory maintained by :mod:`lamtools_core.mem.dreaming`.
"""

from __future__ import annotations

from lamtools_core.mem import library
from lamtools_core.mem.library import (
    CORE_FILENAME,
    CORE_PINNED_END,
    CORE_PINNED_START,
    INDEX_FILENAME,
    MAX_CORE_PROMPT_CHARS,
    MAX_CORE_READ_CHARS,
    MAX_CORE_VERSIONS,
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
    clear_core_document,
    core_file_path,
    core_text_for_prompt,
    delete_memory,
    edit_memory,
    has_content,
    index_text_for_prompt,
    list_core_versions,
    list_entries,
    make_directory,
    memory_root,
    merge_core_document,
    normalize_scope,
    pinned_blocks,
    read_core_document,
    read_memory,
    refresh_index,
    rename_memory,
    render_index,
    resolve_memory_path,
    restore_core_version,
    reveal_memory,
    write_core_document,
    write_memory,
)

__all__ = [
    "library",
    "CORE_FILENAME",
    "CORE_PINNED_END",
    "CORE_PINNED_START",
    "INDEX_FILENAME",
    "MAX_CORE_PROMPT_CHARS",
    "MAX_CORE_READ_CHARS",
    "MAX_CORE_VERSIONS",
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
    "clear_core_document",
    "core_file_path",
    "core_text_for_prompt",
    "delete_memory",
    "edit_memory",
    "index_text_for_prompt",
    "list_core_versions",
    "list_entries",
    "make_directory",
    "memory_root",
    "merge_core_document",
    "normalize_scope",
    "pinned_blocks",
    "read_core_document",
    "read_memory",
    "refresh_index",
    "rename_memory",
    "render_index",
    "resolve_memory_path",
    "restore_core_version",
    "reveal_memory",
    "write_core_document",
    "write_memory",
]
