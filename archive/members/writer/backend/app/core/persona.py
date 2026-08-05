from __future__ import annotations

from typing import Any

from .prompt_files import load_writer_prompt


def get_writer_system_prompt() -> str:
    """Writer system prompt with durable reply-safety constraints."""
    return load_writer_prompt("persona")


def get_writer_persona() -> dict[str, Any]:
    """Get the Writer persona definition (placeholder)."""
    return {}
