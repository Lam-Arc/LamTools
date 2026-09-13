"""Controlled project icon and color metadata used by every public surface."""

from __future__ import annotations

from typing import Any


PROJECT_ICON_KEYS = (
    "folder",
    "code",
    "idea",
    "design",
    "docs",
    "work",
    "rocket",
    "sparkles",
)
PROJECT_SOLID_COLOR_KEYS = (
    "gray",
    "blue",
    "violet",
    "pink",
    "red",
    "orange",
    "green",
    "cyan",
)
PROJECT_GRADIENT_COLOR_KEYS = (
    "sunrise",
    "aurora",
    "ocean",
    "violet-sky",
    "berry",
    "ember",
    "forest",
    "prism",
)
PROJECT_COLOR_KEYS = PROJECT_SOLID_COLOR_KEYS + PROJECT_GRADIENT_COLOR_KEYS

DEFAULT_PROJECT_ICON_KEY = "folder"
DEFAULT_PROJECT_COLOR_KEY = "gray"


def validate_project_icon_key(value: Any) -> str:
    key = str(value or "").strip().lower()
    if key not in PROJECT_ICON_KEYS:
        raise ValueError(f"Unsupported project icon_key: {key or '<empty>'}")
    return key


def validate_project_color_key(value: Any) -> str:
    key = str(value or "").strip().lower()
    if key not in PROJECT_COLOR_KEYS:
        raise ValueError(f"Unsupported project color_key: {key or '<empty>'}")
    return key


__all__ = [
    "DEFAULT_PROJECT_COLOR_KEY",
    "DEFAULT_PROJECT_ICON_KEY",
    "PROJECT_COLOR_KEYS",
    "PROJECT_GRADIENT_COLOR_KEYS",
    "PROJECT_ICON_KEYS",
    "PROJECT_SOLID_COLOR_KEYS",
    "validate_project_color_key",
    "validate_project_icon_key",
]
