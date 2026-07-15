from __future__ import annotations

import pytest

from lamtools_core.tool import ToolCall
from lamtools_core.tool.workspace_files import (
    WorkspaceReadOnlyTools,
    edit_file_tool,
    write_file_tool,
)


@pytest.mark.asyncio
async def test_read_file_returns_metadata_and_artifact(tmp_path):
    work_root = tmp_path / "project"
    work_root.mkdir()
    (work_root / "hello.py").write_text("print('hello')\n", encoding="utf-8")
    tools = WorkspaceReadOnlyTools(work_root)

    result = await tools.read_file(ToolCall(id="read-1", name="read_file", arguments={"path": "hello.py"}))

    assert result.status == "ok"
    assert "print('hello')" in result.content
    assert result.metadata["path"] == "hello.py"
    assert result.artifacts[0].kind == "file_read"


@pytest.mark.asyncio
async def test_read_file_can_use_registered_resource_root(tmp_path):
    work_root = tmp_path / "project"
    resource_root = tmp_path / "skill"
    work_root.mkdir()
    resource_root.mkdir()
    (resource_root / "guide.md").write_text("skill reference", encoding="utf-8")
    tools = WorkspaceReadOnlyTools(work_root)
    tools.add_resource_root(resource_root)

    result = await tools.read_file(ToolCall(id="read-resource", name="read_file", arguments={"path": "guide.md"}))

    assert result.status == "ok"
    assert "skill reference" in result.content
    assert result.metadata["path"] == "guide.md"


@pytest.mark.asyncio
async def test_search_files_and_content_respect_limits(tmp_path):
    work_root = tmp_path / "project"
    src = work_root / "src"
    src.mkdir(parents=True)
    for index in range(4):
        (src / f"file{index}.py").write_text(f"# TODO {index}\n", encoding="utf-8")
    tools = WorkspaceReadOnlyTools(work_root, max_search_results=2)

    files = await tools.search_files(ToolCall(id="search-files", name="search_files", arguments={"pattern": "*.py"}))
    content = await tools.search_content(ToolCall(id="search-content", name="search_content", arguments={"pattern": "TODO"}))

    assert files.status == "ok"
    assert "src/file0.py" in files.content
    assert "[... at least" in files.content
    assert content.status == "ok"
    assert content.content.count("TODO") == 2


@pytest.mark.asyncio
async def test_search_tools_treat_null_optional_path_as_workspace_root(tmp_path):
    work_root = tmp_path / "project"
    work_root.mkdir()
    (work_root / "note.md").write_text("searchable text\n", encoding="utf-8")
    tools = WorkspaceReadOnlyTools(work_root)

    files = await tools.search_files(
        ToolCall(
            id="search-files-null-path",
            name="search_files",
            arguments={"path": None, "pattern": "*.md"},
        )
    )
    content = await tools.search_content(
        ToolCall(
            id="search-content-null-path",
            name="search_content",
            arguments={"path": None, "pattern": "searchable"},
        )
    )

    assert files.status == "ok"
    assert files.content == "note.md"
    assert content.status == "ok"
    assert "note.md:1: searchable text" in content.content


@pytest.mark.asyncio
async def test_write_and_edit_file_are_bounded_to_workspace(tmp_path):
    work_root = tmp_path / "project"
    work_root.mkdir()

    created = await write_file_tool(
        ToolCall(id="write-1", name="write_file", arguments={"path": "note.txt", "content": "hello\n"}),
        work_root=work_root,
        max_write_length=100,
    )
    edited = await edit_file_tool(
        ToolCall(
            id="edit-1",
            name="edit_file",
            arguments={"path": "note.txt", "old_string": "hello", "new_string": "hello world"},
        ),
        work_root=work_root,
        max_write_length=100,
    )
    escaped = await write_file_tool(
        ToolCall(id="write-escape", name="write_file", arguments={"path": "../secret.txt", "content": "bad"}),
        work_root=work_root,
        max_write_length=100,
    )

    assert created.status == "ok"
    assert edited.status == "ok"
    diff_lines = str(edited.artifacts[0].content).splitlines()
    assert diff_lines[:3] == ["--- a/note.txt", "+++ b/note.txt", "@@ -1 +1 @@"]
    assert "-hello" in diff_lines
    assert "+hello world" in diff_lines
    assert (work_root / "note.txt").read_text(encoding="utf-8") == "hello world\n"
    assert escaped.status == "failed"
    assert "outside work_root" in escaped.error
