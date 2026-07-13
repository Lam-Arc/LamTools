from __future__ import annotations

from lamtools_core.tool.sub_agent import (
    AgentWriteScope,
    SubAgentDefinition,
    delete_project_sub_agent_definition,
    parse_sub_agent_definition,
    render_sub_agent_definition,
    normalize_scope_path,
    project_sub_agent_definition_path,
    scope_allows_path,
    scopes_conflict,
    validate_project_sub_agent_name,
    write_project_sub_agent_definition,
    write_scope_error,
    write_scope_from_options,
)


def test_write_scope_from_options_accepts_alias_shapes():
    assert write_scope_from_options({"write_scope": "src/app.py"}) == AgentWriteScope(("src/app.py",))
    assert write_scope_from_options({"allowed_paths": {"files": ["src/a.py"]}}) == AgentWriteScope(("src/a.py",))


def test_normalize_scope_path_rejects_escape():
    assert normalize_scope_path("./src\\app.py") == "src/app.py"
    assert normalize_scope_path("../secret.txt") == ""
    assert normalize_scope_path("src/../secret.txt") == ""


def test_scope_allows_path_supports_directory_and_glob():
    assert scope_allows_path(AgentWriteScope(("src/",)), "src/app.py") is True
    assert scope_allows_path(AgentWriteScope(("tests/*.py",)), "tests/test_app.py") is True
    assert scope_allows_path(AgentWriteScope(("src/",)), "docs/readme.md") is False


def test_scopes_conflict_detects_overlapping_paths():
    assert scopes_conflict(AgentWriteScope(("src/",)), AgentWriteScope(("src/auth/login.py",))) is True
    assert scopes_conflict(AgentWriteScope(("src/a.py",)), AgentWriteScope(("docs/readme.md",))) is False


def test_write_scope_error_only_for_write_capable_agents():
    assert write_scope_error(agent_name="explorer", tools=("read_file",), scope=None) == ""
    assert "write_scope" in write_scope_error(agent_name="worker", tools=("write_file",), scope=None)
    assert write_scope_error(
        agent_name="worker",
        tools=("write_file",),
        scope=AgentWriteScope(("src/",)),
    ) == ""


def test_parse_sub_agent_definition_frontmatter(tmp_path):
    path = tmp_path / "explorer.md"
    path.write_text(
        "\n".join([
            "---",
            "name: explorer",
            "description: Project explorer",
            "tools:",
            "  - read_file",
            "model: fast-model",
            "maxTurns: 2",
            "---",
            "Only inspect files.",
        ]),
        encoding="utf-8",
    )

    definition = parse_sub_agent_definition(path, "project")

    assert definition is not None
    assert definition.name == "explorer"
    assert definition.description == "Project explorer"
    assert definition.tools == ("read_file",)
    assert definition.model == "fast-model"
    assert not hasattr(definition, "max_tool_rounds")
    assert definition.developer_instructions == "Only inspect files."


def test_project_sub_agent_definition_write_delete_roundtrip(tmp_path):
    saved = write_project_sub_agent_definition(
        tmp_path,
        SubAgentDefinition(
            name="Project Worker",
            description="Project worker",
            role="implementation",
            developer_instructions="Only handle project work.",
            tools=("read_file", "write_file"),
            model="fast-model",
            aliases=("pw",),
        ),
    )

    assert saved.name == "project_worker"
    path = project_sub_agent_definition_path(tmp_path, "project_worker")
    assert path.is_file()
    definition_text = path.read_text(encoding="utf-8")
    assert "Only handle project work." in definition_text
    assert "maxTurns" not in definition_text
    assert delete_project_sub_agent_definition(tmp_path, "project_worker") is True
    assert not path.exists()


def test_validate_and_render_sub_agent_definition():
    assert validate_project_sub_agent_name("Project Worker") == "project_worker"
    rendered = render_sub_agent_definition(
        SubAgentDefinition(
            name="reviewer",
            description="Review: code",
            role="review",
            developer_instructions="Review carefully.",
            tools=("read_file",),
        )
    )

    assert 'description: "Review: code"' in rendered
    assert "  - read_file" in rendered
