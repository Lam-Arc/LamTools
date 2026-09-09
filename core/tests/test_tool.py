"""Tests for lamtools_core.tool module."""

from lamtools_core.tool import (
    ToolArtifact,
    ToolCall,
    ToolContext,
    ToolError,
    ToolExecutor,
    ToolExecutorProtocol,
    ToolPermission,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)


class TestToolTypes:
    def test_tool_spec_construction(self):
        spec = ToolSpec(name="lookup_item", description="Lookup an item", permission="read")
        assert spec.name == "lookup_item"
        assert spec.permission == "read"

    def test_tool_spec_to_dict(self):
        spec = ToolSpec(name="search", description="Search")
        d = spec.to_dict()
        assert d["name"] == "search"

    def test_tool_call_construction(self):
        tc = ToolCall(id="c1", name="lookup_item", arguments={"item_id": "a"}, reason="user asked", goal="get content")
        assert tc.reason == "user asked"
        assert tc.goal == "get content"
        d = tc.to_dict()
        assert d["reason"] == "user asked"
        assert d["goal"] == "get content"

    def test_tool_artifact(self):
        a = ToolArtifact(kind="asset", uri="memory://asset-1", content="hello")
        d = a.to_dict()
        assert d["kind"] == "asset"
        assert d["uri"] == "memory://asset-1"

    def test_tool_result_ok(self):
        r = ToolResult(call_id="c1", name="lookup_item", content="item contents")
        assert r.status == "ok"
        d = r.to_dict()
        assert d["status"] == "ok"
        assert d["content"] == "item contents"

    def test_tool_result_error(self):
        r = ToolResult(
            call_id="c1",
            name="lookup_item",
            status="failed",
            error="not found",
            error_code="file_not_found",
        )
        d = r.to_dict()
        assert d["status"] == "failed"
        assert d["error"] == "not found"
        assert d["error_code"] == "file_not_found"

    def test_tool_result_with_artifacts(self):
        art = ToolArtifact(kind="asset", uri="memory://asset-1")
        r = ToolResult(call_id="c1", name="create_asset", artifacts=[art])
        d = r.to_dict()
        assert len(d["artifacts"]) == 1

    def test_tool_error(self):
        e = ToolError(call_id="c1", name="bad_tool", error="crashed", recoverable=True)
        d = e.to_dict()
        assert d["recoverable"] is True

    def test_tool_permission(self):
        p = ToolPermission(name="mutating_operation", level="restricted", auto_approve=False)
        assert p.level == "restricted"


class TestToolRegistry:
    def test_register_and_list(self):
        reg = ToolRegistry()
        spec = ToolSpec(name="lookup_item", description="Lookup an item")
        reg.register(spec)
        assert len(reg.list()) == 1
        assert reg.list()[0].name == "lookup_item"

    def test_get_existing(self):
        reg = ToolRegistry()
        spec = ToolSpec(name="search", description="Search")
        reg.register(spec)
        found = reg.get("search")
        assert found is not None
        assert found.name == "search"

    def test_get_missing(self):
        reg = ToolRegistry()
        assert reg.get("nonexistent") is None

    def test_has(self):
        reg = ToolRegistry()
        spec = ToolSpec(name="tool_a")
        reg.register(spec)
        assert reg.has("tool_a") is True
        assert reg.has("tool_b") is False

    def test_unregister(self):
        reg = ToolRegistry()
        spec = ToolSpec(name="temp_tool")
        reg.register(spec)
        assert reg.has("temp_tool")
        reg.unregister("temp_tool")
        assert not reg.has("temp_tool")

    def test_multiple_tools(self):
        reg = ToolRegistry()
        for name in ["a", "b", "c"]:
            reg.register(ToolSpec(name=name))
        assert len(reg.list()) == 3

    def test_executor_alias(self):
        assert ToolExecutor is ToolExecutorProtocol
