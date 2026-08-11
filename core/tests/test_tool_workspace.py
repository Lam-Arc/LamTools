from __future__ import annotations

import pytest

from lamtools_core.tool.workspace import (
    format_file_size,
    is_within_path,
    line_count,
    relative_workspace_uri,
    validate_workspace_path,
)


def test_validate_workspace_path_accepts_child_path(tmp_path):
    work_root = tmp_path / "project"
    work_root.mkdir()

    resolved = validate_workspace_path("src/main.py", work_root)

    assert resolved == (work_root / "src" / "main.py").resolve()


def test_validate_workspace_path_rejects_escape(tmp_path):
    work_root = tmp_path / "project"
    work_root.mkdir()

    with pytest.raises(ValueError, match="outside work_root"):
        validate_workspace_path("../secret.txt", work_root)


def test_validate_workspace_path_allow_outside_allows_escape(tmp_path):
    work_root = tmp_path / "project"
    work_root.mkdir()

    resolved = validate_workspace_path("../secret.txt", work_root, allow_outside=True)

    assert resolved == (tmp_path / "secret.txt").resolve()


def test_validate_workspace_path_allow_outside_keeps_workspace_paths(tmp_path):
    work_root = tmp_path / "project"
    work_root.mkdir()

    resolved = validate_workspace_path("src/main.py", work_root, allow_outside=True)

    assert resolved == (work_root / "src" / "main.py").resolve()


def test_is_within_path_and_relative_uri(tmp_path):
    work_root = tmp_path / "project"
    child = work_root / "src" / "main.py"
    child.parent.mkdir(parents=True)
    child.write_text("print('ok')\n", encoding="utf-8")

    assert is_within_path(child, work_root)
    assert relative_workspace_uri(child, work_root) == "src/main.py"


def test_file_format_helpers():
    assert format_file_size(12) == "12B"
    assert format_file_size(1536) == "1.5KB"
    assert line_count("a\nb") == 2
    assert line_count("a\nb\n") == 2
