from __future__ import annotations

import os
from pathlib import Path
from string import Template
from typing import Any

from .resource_dirs import appdata_writer_dir, writer_resource_roots


def _builtin_prompt_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "prompts" / "writer"


def _prompt_dirs() -> list[Path]:
    dirs: list[Path] = []
    env_dir = os.environ.get("LAMWRITER_PROMPT_DIR")
    if env_dir:
        root = Path(env_dir)
        dirs.extend([root / "writer", root])
    appdata = appdata_writer_dir()
    if appdata is not None:
        dirs.append(appdata / "prompts" / "writer")
    for root in writer_resource_roots():
        dirs.extend([
            root / "prompts" / "writer",
            root / "backend" / "app" / "prompts" / "writer",
        ])
    dirs.append(_builtin_prompt_dir())

    seen: set[str] = set()
    result: list[Path] = []
    for directory in dirs:
        key = os.path.normcase(str(directory.resolve()))
        if key in seen:
            continue
        seen.add(key)
        result.append(directory)
    return result


def load_writer_prompt(name: str, variables: dict[str, Any] | None = None) -> str:
    """Load a Writer prompt fragment from Markdown with optional overrides."""
    filename = name if name.endswith(".md") else f"{name}.md"
    for directory in _prompt_dirs():
        path = directory / filename
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").strip()
        if variables:
            return Template(text).safe_substitute(
                {key: str(value) for key, value in variables.items()}
            )
        return text
    raise FileNotFoundError(f"Writer prompt file not found: {filename}")
