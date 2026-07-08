# Agent Plugin Hooks Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first runnable plugin/hook foundation: plugin scanning, hook JSON configuration, hook trust, `PreToolUse` command hooks, and shared operation entries for CLI/app-server use.

**Architecture:** Add Core-owned plugin and hook modules under `lamtools_core.plugins`. Keep `CoreLoopKernel + RuntimeKit` as the runtime mainline; HookEngine attaches to lifecycle events and returns decisions without becoming a second business injection layer. Writer only wires Core operations and CLI commands to the shared plugin/hook operations.

**Tech Stack:** Python 3.14, pytest, existing LamTools Core runtime, existing Writer app-server OperationCatalog, JSON hook/plugin manifests, Windows PowerShell with UTF-8.

## Global Constraints

- PowerShell involving Chinese must use UTF-8.
- Core must not contain Writer/Artist product names.
- Plugin discovery, hook configuration, trust, loading, and execution belong to Core. Writer may only bridge Core operations into app-server/CLI surfaces.
- Do not restore `HookSet` or create a parallel business hook layer.
- Do not add a dedicated plugin installer; Agent self-install is an acceptance scenario that uses existing file/command ability to place a plugin package in a scanned plugin directory.
- Phase 1 does not build a settings page; users customize hooks through JSON files.
- Phase 1 custom hook paths are `<project_root>/.lamtools/hooks.json`, `%APPDATA%/LamTools/hooks.json`, and `<plugin_root>/hooks/hooks.json` or `plugin.json.hooks`.
- Non-managed hooks must not execute until trusted by hash.
- Hooks can tighten permissions, block, request approval, or add context; non-managed hooks cannot loosen existing tool permissions.
- GUI capability must have an equivalent CLI/app-server operation entry.
- TDD is required for production changes.
- Do not revert unrelated dirty files.

---

## Scope Check

The spec covers multiple subsystems: plugin registry, hooks, trust, MCP, skills, agents, GUI, CLI, and runtime lifecycle events. This plan intentionally implements the first independently testable slice:

- plugin scanning and manifest parsing
- project/user/plugin hook JSON parsing
- hash-based trust store
- command hook execution
- `PreToolUse` runtime enforcement
- shared Core operations plus Writer CLI/app-server bridge

The plan does not implement settings UI, plugin marketplace download, MCP hook handlers, prompt hook handlers, HTTP hook handlers, `PostToolUse`, `Stop`, compaction hooks, or plugin MCP/skill loading. Those become later plans after this slice passes.

## File Structure

- Create: `core/src/lamtools_core/plugins/__init__.py`
  - Public exports for plugin and hook modules.
- Create: `core/src/lamtools_core/plugins/models.py`
  - Dataclasses and type aliases shared by plugin registry, hook registry, trust store, and engine.
- Create: `core/src/lamtools_core/plugins/registry.py`
  - Plugin directory discovery, manifest parsing, resource path validation, state file enable/disable.
- Create: `core/src/lamtools_core/plugins/hook_config.py`
  - User/project/plugin hook config loading and normalization into executable hook definitions.
- Create: `core/src/lamtools_core/plugins/trust.py`
  - JSON trust store keyed by hook definition hash.
- Create: `core/src/lamtools_core/plugins/engine.py`
  - `PreToolUse` command hook execution and decision merge.
- Create: `core/src/lamtools_core/plugins/operations.py`
  - Shared OperationCatalog entries for plugin/hook list, enable, disable, and trust.
- Modify: `core/src/lamtools_core/kernel/loop.py`
  - Add optional HookEngine and apply `PreToolUse` before approval/tool execution.
- Modify: `core/src/lamtools_core/__init__.py`
  - Export plugin/hook public types if this package already exports comparable Core app types.
- Test: `core/tests/test_plugin_registry.py`
- Test: `core/tests/test_hook_registry.py`
- Test: `core/tests/test_hook_trust.py`
- Test: `core/tests/test_hook_engine.py`
- Test: `core/tests/test_kernel_pre_tool_hooks.py`
- Test: `core/tests/test_plugin_operations.py`
- Modify: `members/writer/backend/app/app_server/operations.py`
  - Register plugin/hook bridge operations in Writer app-server.
- Modify: `members/writer/backend/app/app_server/connection.py`
  - Bind app-server request handlers for new plugin/hook operations.
- Modify: `members/writer/backend/writer_cli/__main__.py`
  - Add `writer plugin ...` and `writer hook ...` CLI commands routed through app-server to Core operations.
- Modify: `members/writer/backend/writer_cli/app_server_client.py`
  - Add thin request helpers if existing generic request is insufficient.
- Test: `members/writer/backend/tests/test_writer_app_server_protocol.py`
- Test: `members/writer/backend/tests/test_writer_cli.py`

## Task 0: Working Tree Guard

**Files:**
- Read only: existing dirty files shown by `git status --short`.

**Interfaces:**
- Consumes: current dirty tree.
- Produces: an execution decision before touching code.

- [ ] **Step 1: Inspect current status**

Run:

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
git status --short
```

Expected: unrelated dirty files may remain, including Core Agent default runtime work. Do not revert them.

- [ ] **Step 2: Decide execution base**

If `core/src/lamtools_core/app/__init__.py` or other Core Agent files remain dirty, either:

```powershell
git diff -- core/src/lamtools_core/app/__init__.py
```

Expected: confirm whether the dirty change is compatible with adding `lamtools_core.plugins`. If incompatible, stop and ask for the Core Agent runtime work to be committed or moved to a worktree.

- [ ] **Step 3: Commit discipline**

For every later task, stage only the files listed in that task:

```powershell
git diff --cached --name-status
```

Expected: staged paths match the task's file list.

## Task 1: Plugin Manifest Registry

**Files:**
- Create: `core/src/lamtools_core/plugins/__init__.py`
- Create: `core/src/lamtools_core/plugins/models.py`
- Create: `core/src/lamtools_core/plugins/registry.py`
- Test: `core/tests/test_plugin_registry.py`

**Interfaces:**
- Produces:
  - `PluginManifest`
  - `PluginResource`
  - `PluginStateStore`
  - `PluginRegistry`
  - `default_user_plugin_root() -> Path`
  - `default_project_plugin_root(project_root: Path | str) -> Path`
- Consumes: plugin directories containing `plugin.json`.

- [ ] **Step 1: Write failing plugin registry tests**

Create `core/tests/test_plugin_registry.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugins import PluginRegistry, PluginStateStore


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_registry_discovers_plugin_resources(tmp_path: Path):
    plugin = tmp_path / "plugins" / "repo-policy"
    write_json(plugin / "plugin.json", {
        "name": "repo-policy",
        "version": "0.1.0",
        "description": "Repo policy",
        "skills": ["./skills"],
        "hooks": ["./hooks/hooks.json"],
        "mcpServers": "./mcp/mcp.json",
        "agents": ["./agents"],
        "permissions": {"commands": "ask_user"},
    })

    registry = PluginRegistry(plugin_roots=[tmp_path / "plugins"])
    plugins = registry.discover()

    assert [item.name for item in plugins] == ["repo-policy"]
    assert plugins[0].version == "0.1.0"
    assert plugins[0].root == plugin.resolve()
    assert plugins[0].hook_files == [plugin.resolve() / "hooks" / "hooks.json"]
    assert plugins[0].skill_roots == [plugin.resolve() / "skills"]
    assert plugins[0].mcp_files == [plugin.resolve() / "mcp" / "mcp.json"]
    assert plugins[0].agent_roots == [plugin.resolve() / "agents"]


def test_registry_uses_default_hook_and_mcp_paths(tmp_path: Path):
    plugin = tmp_path / "plugins" / "defaulted"
    write_json(plugin / "plugin.json", {"name": "defaulted", "version": "1.0.0"})
    write_json(plugin / "hooks" / "hooks.json", {"hooks": {}})
    write_json(plugin / ".mcp.json", {"mcpServers": {}})

    registry = PluginRegistry(plugin_roots=[tmp_path / "plugins"])
    item = registry.discover()[0]

    assert item.hook_files == [plugin.resolve() / "hooks" / "hooks.json"]
    assert item.mcp_files == [plugin.resolve() / ".mcp.json"]


def test_registry_rejects_paths_outside_plugin_root(tmp_path: Path):
    plugin = tmp_path / "plugins" / "bad"
    write_json(plugin / "plugin.json", {
        "name": "bad",
        "version": "1.0.0",
        "hooks": ["../outside.json"],
    })

    registry = PluginRegistry(plugin_roots=[tmp_path / "plugins"])

    with pytest.raises(ValueError, match="outside plugin root"):
        registry.discover()


def test_plugin_state_store_controls_enabled_flag(tmp_path: Path):
    state = PluginStateStore(tmp_path / "plugin-state.json")
    state.set_enabled("repo-policy", False)
    state.set_enabled("other", True)

    registry = PluginRegistry(
        plugin_roots=[tmp_path / "plugins"],
        state_store=state,
    )
    plugin = tmp_path / "plugins" / "repo-policy"
    write_json(plugin / "plugin.json", {"name": "repo-policy", "version": "0.1.0"})

    discovered = registry.discover()[0]

    assert discovered.enabled is False
    assert state.is_enabled("other") is True
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.14 -m pytest core/tests/test_plugin_registry.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'lamtools_core.plugins'`.

- [ ] **Step 3: Implement manifest models**

Create `core/src/lamtools_core/plugins/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


HookSource = Literal["user", "project", "plugin", "managed"]
HookHandlerType = Literal["command", "http", "mcp", "prompt"]
HookDecisionKind = Literal["allow", "block"]


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: str
    description: str = ""
    root: Path = Path()
    enabled: bool = True
    skill_roots: list[Path] = field(default_factory=list)
    hook_files: list[Path] = field(default_factory=list)
    mcp_files: list[Path] = field(default_factory=list)
    agent_roots: list[Path] = field(default_factory=list)
    permissions: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookHandler:
    type: HookHandlerType
    command: str = ""
    url: str = ""
    tool: str = ""
    prompt: str = ""
    timeout: float = 10.0
    required: bool = False
    status_message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookDefinition:
    id: str
    event: str
    matcher: str
    source: HookSource
    source_name: str
    config_path: Path
    plugin_name: str = ""
    plugin_root: Path | None = None
    handler: HookHandler = field(default_factory=lambda: HookHandler(type="command"))
    definition_hash: str = ""
    trusted: bool = False
    status: str = "pending_review"


@dataclass(frozen=True)
class HookEvent:
    event_name: str
    session_id: str = ""
    run_id: str = ""
    turn_id: str = ""
    cwd: str = ""
    project_root: str = ""
    plugin_name: str = ""
    plugin_root: str = ""
    plugin_data: str = ""
    transcript_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookDecision:
    decision: HookDecisionKind = "allow"
    reason: str = ""
    additional_context: str = ""
    updated_input: dict[str, Any] | None = None
    permission_decision: str = ""
    permission_decision_reason: str = ""
    audit_events: list[dict[str, Any]] = field(default_factory=list)
```

- [ ] **Step 4: Implement registry**

Create `core/src/lamtools_core/plugins/registry.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import PluginManifest


def _appdata_root() -> Path:
    raw = os.environ.get("APPDATA")
    if raw:
        return Path(raw)
    return Path.home() / "AppData" / "Roaming"


def default_user_plugin_root() -> Path:
    return _appdata_root() / "LamTools" / "plugins"


def default_project_plugin_root(project_root: Path | str) -> Path:
    return Path(project_root).resolve() / ".lamtools" / "plugins"


class PluginStateStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"plugins": {}}
        return json.loads(self.path.read_text(encoding="utf-8-sig"))

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_enabled(self, name: str) -> bool:
        plugins = self._load().get("plugins", {})
        if not isinstance(plugins, dict):
            return True
        raw = plugins.get(name, {})
        return bool(raw.get("enabled", True)) if isinstance(raw, dict) else True

    def set_enabled(self, name: str, enabled: bool) -> None:
        data = self._load()
        plugins = data.setdefault("plugins", {})
        if not isinstance(plugins, dict):
            plugins = {}
            data["plugins"] = plugins
        entry = plugins.setdefault(name, {})
        if not isinstance(entry, dict):
            entry = {}
            plugins[name] = entry
        entry["enabled"] = bool(enabled)
        self._save(data)


class PluginRegistry:
    def __init__(
        self,
        *,
        plugin_roots: list[Path | str],
        state_store: PluginStateStore | None = None,
    ) -> None:
        self.plugin_roots = [Path(root).resolve() for root in plugin_roots]
        self.state_store = state_store

    def discover(self) -> list[PluginManifest]:
        items: list[PluginManifest] = []
        for root in self.plugin_roots:
            if not root.exists():
                continue
            for manifest_path in sorted(root.glob("*/plugin.json")):
                items.append(self._read_manifest(manifest_path))
        return sorted(items, key=lambda item: item.name)

    def _read_manifest(self, manifest_path: Path) -> PluginManifest:
        raw = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError(f"plugin manifest must be an object: {manifest_path}")
        name = str(raw.get("name") or manifest_path.parent.name).strip()
        if not name:
            raise ValueError(f"plugin name is required: {manifest_path}")
        root = manifest_path.parent.resolve()
        hook_files = self._paths(root, raw.get("hooks"))
        if not hook_files and (root / "hooks" / "hooks.json").exists():
            hook_files = [root / "hooks" / "hooks.json"]
        mcp_files = self._paths(root, raw.get("mcpServers"))
        if not mcp_files:
            if (root / ".mcp.json").exists():
                mcp_files = [root / ".mcp.json"]
            elif (root / "mcp" / "mcp.json").exists():
                mcp_files = [root / "mcp" / "mcp.json"]
        enabled = self.state_store.is_enabled(name) if self.state_store else True
        return PluginManifest(
            name=name,
            version=str(raw.get("version") or "0.0.0"),
            description=str(raw.get("description") or ""),
            root=root,
            enabled=enabled,
            skill_roots=self._paths(root, raw.get("skills")),
            hook_files=hook_files,
            mcp_files=mcp_files,
            agent_roots=self._paths(root, raw.get("agents")),
            permissions=raw.get("permissions") if isinstance(raw.get("permissions"), dict) else {},
            raw=dict(raw),
        )

    def _paths(self, root: Path, value: object) -> list[Path]:
        values = value if isinstance(value, list) else [value] if isinstance(value, str) else []
        paths: list[Path] = []
        for raw in values:
            text = str(raw or "").strip()
            if not text:
                continue
            if not text.startswith("./"):
                raise ValueError(f"plugin resource path must start with './': {text}")
            path = (root / text[2:]).resolve()
            if not path.is_relative_to(root):
                raise ValueError(f"plugin resource path is outside plugin root: {text}")
            paths.append(path)
        return paths
```

- [ ] **Step 5: Export package API**

Create `core/src/lamtools_core/plugins/__init__.py`:

```python
from .models import HookDecision, HookDefinition, HookEvent, HookHandler, PluginManifest
from .registry import PluginRegistry, PluginStateStore, default_project_plugin_root, default_user_plugin_root

__all__ = [
    "HookDecision",
    "HookDefinition",
    "HookEvent",
    "HookHandler",
    "PluginManifest",
    "PluginRegistry",
    "PluginStateStore",
    "default_project_plugin_root",
    "default_user_plugin_root",
]
```

- [ ] **Step 6: Verify GREEN**

Run:

```powershell
py -3.14 -m pytest core/tests/test_plugin_registry.py -q
```

Expected: `4 passed`.

- [ ] **Step 7: Commit Task 1**

```powershell
git add core/src/lamtools_core/plugins/__init__.py core/src/lamtools_core/plugins/models.py core/src/lamtools_core/plugins/registry.py core/tests/test_plugin_registry.py
git commit -m "feat: add core plugin registry"
```

## Task 2: Hook Config Registry and Trust Store

**Files:**
- Modify: `core/src/lamtools_core/plugins/__init__.py`
- Modify: `core/src/lamtools_core/plugins/models.py`
- Create: `core/src/lamtools_core/plugins/hook_config.py`
- Create: `core/src/lamtools_core/plugins/trust.py`
- Test: `core/tests/test_hook_registry.py`
- Test: `core/tests/test_hook_trust.py`

**Interfaces:**
- Consumes: `PluginManifest`.
- Produces:
  - `HookRegistry.load(...) -> list[HookDefinition]`
  - `HookTrustStore.trust(hash: str) -> None`
  - `HookTrustStore.is_trusted(hash: str) -> bool`

- [ ] **Step 1: Write failing hook registry tests**

Create `core/tests/test_hook_registry.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from lamtools_core.plugins import HookRegistry, HookTrustStore, PluginManifest


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_hook_registry_loads_project_user_and_plugin_hooks(tmp_path: Path):
    project = tmp_path / "project"
    user = tmp_path / "user" / "hooks.json"
    plugin_root = tmp_path / "plugins" / "repo-policy"
    plugin_hooks = plugin_root / "hooks" / "hooks.json"
    hook_body = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "run_command", "hooks": [{"type": "command", "command": "python check.py"}]}
            ]
        }
    }
    write_json(project / ".lamtools" / "hooks.json", hook_body)
    write_json(user, hook_body)
    write_json(plugin_hooks, hook_body)

    registry = HookRegistry(
        project_root=project,
        user_hooks_path=user,
        plugins=[
            PluginManifest(
                name="repo-policy",
                version="0.1.0",
                root=plugin_root,
                hook_files=[plugin_hooks],
            )
        ],
        trust_store=HookTrustStore(tmp_path / "trust.json"),
    )

    hooks = registry.load()

    assert [hook.source for hook in hooks] == ["project", "user", "plugin"]
    assert {hook.event for hook in hooks} == {"PreToolUse"}
    assert {hook.matcher for hook in hooks} == {"run_command"}
    assert all(hook.definition_hash for hook in hooks)
    assert all(hook.trusted is False for hook in hooks)
    assert all(hook.status == "pending_review" for hook in hooks)


def test_hook_registry_marks_trusted_hooks(tmp_path: Path):
    project = tmp_path / "project"
    write_json(project / ".lamtools" / "hooks.json", {
        "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "python ok.py"}]}]}
    })
    trust = HookTrustStore(tmp_path / "trust.json")
    first = HookRegistry(project_root=project, trust_store=trust).load()[0]
    trust.trust(first.definition_hash)

    second = HookRegistry(project_root=project, trust_store=trust).load()[0]

    assert second.trusted is True
    assert second.status == "trusted"


def test_hook_registry_rejects_unsupported_handler_type(tmp_path: Path):
    project = tmp_path / "project"
    write_json(project / ".lamtools" / "hooks.json", {
        "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "socket", "command": "x"}]}]}
    })

    registry = HookRegistry(project_root=project)

    try:
        registry.load()
    except ValueError as exc:
        assert "unsupported hook handler type" in str(exc)
    else:
        raise AssertionError("unsupported handler type should fail")
```

Create `core/tests/test_hook_trust.py`:

```python
from __future__ import annotations

from lamtools_core.plugins import HookTrustStore


def test_hook_trust_store_persists_hashes(tmp_path):
    path = tmp_path / "trust.json"
    store = HookTrustStore(path)
    store.trust("abc123")

    assert HookTrustStore(path).is_trusted("abc123") is True
    assert HookTrustStore(path).is_trusted("missing") is False


def test_hook_trust_store_can_untrust_hash(tmp_path):
    store = HookTrustStore(tmp_path / "trust.json")
    store.trust("abc123")
    store.untrust("abc123")

    assert store.is_trusted("abc123") is False
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.14 -m pytest core/tests/test_hook_registry.py core/tests/test_hook_trust.py -q
```

Expected: FAIL because `HookRegistry` and `HookTrustStore` are not exported.

- [ ] **Step 3: Implement trust store**

Create `core/src/lamtools_core/plugins/trust.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class HookTrustStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"trusted_hashes": []}
        return json.loads(self.path.read_text(encoding="utf-8-sig"))

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def trusted_hashes(self) -> set[str]:
        values = self._load().get("trusted_hashes", [])
        return {str(item) for item in values if str(item).strip()} if isinstance(values, list) else set()

    def is_trusted(self, value: str) -> bool:
        return str(value or "") in self.trusted_hashes()

    def trust(self, value: str) -> None:
        hashes = self.trusted_hashes()
        hashes.add(str(value))
        self._save({"trusted_hashes": sorted(hashes)})

    def untrust(self, value: str) -> None:
        hashes = self.trusted_hashes()
        hashes.discard(str(value))
        self._save({"trusted_hashes": sorted(hashes)})
```

- [ ] **Step 4: Implement hook config registry**

Create `core/src/lamtools_core/plugins/hook_config.py`:

```python
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .models import HookDefinition, HookHandler, PluginManifest
from .trust import HookTrustStore

SUPPORTED_HANDLER_TYPES = {"command", "http", "mcp", "prompt"}


def default_user_hooks_path() -> Path:
    appdata = os.environ.get("APPDATA")
    root = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return root / "LamTools" / "hooks.json"


def default_project_hooks_path(project_root: Path | str) -> Path:
    return Path(project_root).resolve() / ".lamtools" / "hooks.json"


class HookRegistry:
    def __init__(
        self,
        *,
        project_root: Path | str | None = None,
        user_hooks_path: Path | str | None = None,
        plugins: list[PluginManifest] | None = None,
        trust_store: HookTrustStore | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve() if project_root else None
        self.user_hooks_path = Path(user_hooks_path).resolve() if user_hooks_path else default_user_hooks_path()
        self.plugins = list(plugins or [])
        self.trust_store = trust_store

    def load(self) -> list[HookDefinition]:
        hooks: list[HookDefinition] = []
        if self.project_root is not None:
            hooks.extend(self._load_file(default_project_hooks_path(self.project_root), source="project", source_name="project"))
        hooks.extend(self._load_file(self.user_hooks_path, source="user", source_name="user"))
        for plugin in self.plugins:
            if not plugin.enabled:
                continue
            for path in plugin.hook_files:
                hooks.extend(self._load_file(path, source="plugin", source_name=plugin.name, plugin=plugin))
        return hooks

    def _load_file(
        self,
        path: Path,
        *,
        source: str,
        source_name: str,
        plugin: PluginManifest | None = None,
    ) -> list[HookDefinition]:
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        hooks_section = raw.get("hooks", {}) if isinstance(raw, dict) else {}
        if not isinstance(hooks_section, dict):
            raise ValueError(f"hooks must be an object: {path}")
        loaded: list[HookDefinition] = []
        for event, groups in hooks_section.items():
            if not isinstance(groups, list):
                raise ValueError(f"hook event groups must be a list: {path}:{event}")
            for group_index, group in enumerate(groups):
                if not isinstance(group, dict):
                    raise ValueError(f"hook group must be an object: {path}:{event}:{group_index}")
                matcher = str(group.get("matcher") or "*")
                handlers = group.get("hooks", [])
                if not isinstance(handlers, list):
                    raise ValueError(f"hook handlers must be a list: {path}:{event}:{group_index}")
                for handler_index, raw_handler in enumerate(handlers):
                    handler = self._handler(raw_handler)
                    stable = {
                        "event": event,
                        "matcher": matcher,
                        "source": source,
                        "source_name": source_name,
                        "config_path": str(path),
                        "plugin_name": plugin.name if plugin else "",
                        "handler": handler.raw,
                    }
                    digest = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
                    trusted = self.trust_store.is_trusted(digest) if self.trust_store else False
                    loaded.append(HookDefinition(
                        id=f"{source}:{source_name}:{event}:{group_index}:{handler_index}:{digest[:12]}",
                        event=str(event),
                        matcher=matcher,
                        source=source,  # type: ignore[arg-type]
                        source_name=source_name,
                        config_path=path,
                        plugin_name=plugin.name if plugin else "",
                        plugin_root=plugin.root if plugin else None,
                        handler=handler,
                        definition_hash=digest,
                        trusted=trusted,
                        status="trusted" if trusted else "pending_review",
                    ))
        return loaded

    def _handler(self, raw: object) -> HookHandler:
        if not isinstance(raw, dict):
            raise ValueError("hook handler must be an object")
        handler_type = str(raw.get("type") or "command")
        if handler_type not in SUPPORTED_HANDLER_TYPES:
            raise ValueError(f"unsupported hook handler type: {handler_type}")
        return HookHandler(
            type=handler_type,  # type: ignore[arg-type]
            command=str(raw.get("command") or ""),
            url=str(raw.get("url") or ""),
            tool=str(raw.get("tool") or ""),
            prompt=str(raw.get("prompt") or ""),
            timeout=float(raw.get("timeout") or 10),
            required=bool(raw.get("required") or False),
            status_message=str(raw.get("statusMessage") or raw.get("status_message") or ""),
            raw=dict(raw),
        )
```

- [ ] **Step 5: Export hook registry and trust store**

Update `core/src/lamtools_core/plugins/__init__.py`:

```python
from .hook_config import HookRegistry, default_project_hooks_path, default_user_hooks_path
from .models import HookDecision, HookDefinition, HookEvent, HookHandler, PluginManifest
from .registry import PluginRegistry, PluginStateStore, default_project_plugin_root, default_user_plugin_root
from .trust import HookTrustStore

__all__ = [
    "HookDecision",
    "HookDefinition",
    "HookEvent",
    "HookHandler",
    "HookRegistry",
    "HookTrustStore",
    "PluginManifest",
    "PluginRegistry",
    "PluginStateStore",
    "default_project_hooks_path",
    "default_project_plugin_root",
    "default_user_hooks_path",
    "default_user_plugin_root",
]
```

- [ ] **Step 6: Verify GREEN**

Run:

```powershell
py -3.14 -m pytest core/tests/test_hook_registry.py core/tests/test_hook_trust.py -q
```

Expected: `5 passed`.

- [ ] **Step 7: Commit Task 2**

```powershell
git add core/src/lamtools_core/plugins/__init__.py core/src/lamtools_core/plugins/models.py core/src/lamtools_core/plugins/hook_config.py core/src/lamtools_core/plugins/trust.py core/tests/test_hook_registry.py core/tests/test_hook_trust.py
git commit -m "feat: add hook registry and trust store"
```

## Task 3: Command Hook Engine

**Files:**
- Modify: `core/src/lamtools_core/plugins/__init__.py`
- Create: `core/src/lamtools_core/plugins/engine.py`
- Test: `core/tests/test_hook_engine.py`

**Interfaces:**
- Consumes: `HookDefinition`, `HookEvent`, `HookTrustStore`.
- Produces: `HookEngine.run(event: HookEvent) -> HookDecision`.

- [ ] **Step 1: Write failing command hook tests**

Create `core/tests/test_hook_engine.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugins import HookDefinition, HookEngine, HookEvent, HookHandler


def make_script(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


@pytest.mark.asyncio
async def test_command_hook_can_block_tool(tmp_path: Path):
    script = tmp_path / "block.py"
    make_script(script, """
import json, sys
_payload = json.load(sys.stdin)
print(json.dumps({"decision": "block", "reason": "blocked by policy"}))
""".strip())
    hook = HookDefinition(
        id="hook-1",
        event="PreToolUse",
        matcher="run_command",
        source="project",
        source_name="project",
        config_path=tmp_path / "hooks.json",
        handler=HookHandler(type="command", command=f"python {script}", timeout=5),
        trusted=True,
        status="trusted",
    )

    decision = await HookEngine([hook]).run(HookEvent(
        event_name="PreToolUse",
        project_root=str(tmp_path),
        tool_name="run_command",
        tool_input={"command": "pytest"},
    ))

    assert decision.decision == "block"
    assert decision.reason == "blocked by policy"
    assert decision.audit_events[0]["hook_id"] == "hook-1"


@pytest.mark.asyncio
async def test_command_hook_can_update_tool_input(tmp_path: Path):
    script = tmp_path / "rewrite.py"
    make_script(script, """
import json, sys
payload = json.load(sys.stdin)
tool_input = payload["tool_input"]
tool_input["command"] = "py -3.14 -m pytest"
print(json.dumps({"updatedInput": tool_input}))
""".strip())
    hook = HookDefinition(
        id="hook-1",
        event="PreToolUse",
        matcher="run_command",
        source="project",
        source_name="project",
        config_path=tmp_path / "hooks.json",
        handler=HookHandler(type="command", command=f"python {script}", timeout=5),
        trusted=True,
        status="trusted",
    )

    decision = await HookEngine([hook]).run(HookEvent(
        event_name="PreToolUse",
        project_root=str(tmp_path),
        tool_name="run_command",
        tool_input={"command": "pytest"},
    ))

    assert decision.updated_input == {"command": "py -3.14 -m pytest"}


@pytest.mark.asyncio
async def test_untrusted_hook_does_not_execute(tmp_path: Path):
    script = tmp_path / "block.py"
    make_script(script, "print('should not run')")
    hook = HookDefinition(
        id="hook-1",
        event="PreToolUse",
        matcher="*",
        source="project",
        source_name="project",
        config_path=tmp_path / "hooks.json",
        handler=HookHandler(type="command", command=f"python {script}", timeout=5),
        trusted=False,
        status="pending_review",
    )

    decision = await HookEngine([hook]).run(HookEvent(event_name="PreToolUse", tool_name="run_command"))

    assert decision.decision == "allow"
    assert decision.audit_events[0]["status"] == "skipped_untrusted"
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.14 -m pytest core/tests/test_hook_engine.py -q
```

Expected: FAIL because `HookEngine` is not exported.

- [ ] **Step 3: Implement command hook engine**

Create `core/src/lamtools_core/plugins/engine.py`:

```python
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import HookDecision, HookDefinition, HookEvent


class HookEngine:
    def __init__(self, hooks: list[HookDefinition]) -> None:
        self.hooks = list(hooks)

    async def run(self, event: HookEvent) -> HookDecision:
        decision = HookDecision()
        audit_events: list[dict[str, Any]] = []
        current_input = dict(event.tool_input)
        for hook in self._matching_hooks(event):
            if not hook.trusted:
                audit_events.append({"hook_id": hook.id, "status": "skipped_untrusted"})
                continue
            result, audit = await self._run_hook(hook, replace(event, tool_input=current_input))
            audit_events.append(audit)
            if result.updated_input is not None:
                current_input.update(result.updated_input)
                decision = replace(decision, updated_input=dict(current_input))
            if result.additional_context:
                joined = "\n".join(item for item in [decision.additional_context, result.additional_context] if item)
                decision = replace(decision, additional_context=joined)
            if result.permission_decision:
                decision = replace(
                    decision,
                    permission_decision=result.permission_decision,
                    permission_decision_reason=result.permission_decision_reason,
                )
            if result.decision == "block":
                decision = replace(decision, decision="block", reason=result.reason)
                break
        return replace(decision, audit_events=[*decision.audit_events, *audit_events])

    def _matching_hooks(self, event: HookEvent) -> list[HookDefinition]:
        return [
            hook
            for hook in self.hooks
            if hook.event == event.event_name
            and (hook.matcher in {"", "*"} or hook.matcher == event.tool_name)
        ]

    async def _run_hook(self, hook: HookDefinition, event: HookEvent) -> tuple[HookDecision, dict[str, Any]]:
        if hook.handler.type != "command":
            return HookDecision(), {"hook_id": hook.id, "status": "skipped_unsupported"}
        payload = self._payload(hook, event)
        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.update({
            "LAMTOOLS_HOOK_EVENT": event.event_name,
            "LAMTOOLS_PLUGIN_ROOT": str(hook.plugin_root or ""),
        })
        proc = await asyncio.create_subprocess_shell(
            self._expanded_command(hook, event),
            cwd=event.project_root or event.cwd or None,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(body), timeout=hook.handler.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            if hook.handler.required:
                return HookDecision(decision="block", reason="required hook timed out"), {
                    "hook_id": hook.id,
                    "status": "timeout",
                }
            return HookDecision(), {"hook_id": hook.id, "status": "timeout"}
        audit = {
            "hook_id": hook.id,
            "status": "completed" if proc.returncode == 0 else "failed",
            "exit_code": proc.returncode,
            "stderr": stderr.decode("utf-8", errors="replace").splitlines()[:1],
        }
        if proc.returncode != 0:
            if hook.handler.required:
                return HookDecision(decision="block", reason="required hook failed"), audit
            return HookDecision(), audit
        text = stdout.decode("utf-8", errors="replace").strip()
        if not text:
            return HookDecision(), audit
        data = json.loads(text)
        return HookDecision(
            decision="block" if data.get("decision") == "block" else "allow",
            reason=str(data.get("reason") or ""),
            additional_context=str(data.get("additionalContext") or data.get("additional_context") or ""),
            updated_input=data.get("updatedInput") if isinstance(data.get("updatedInput"), dict) else None,
            permission_decision=str(data.get("permissionDecision") or data.get("permission_decision") or ""),
            permission_decision_reason=str(data.get("permissionDecisionReason") or data.get("permission_decision_reason") or ""),
        ), audit

    def _payload(self, hook: HookDefinition, event: HookEvent) -> dict[str, Any]:
        return {
            "event_name": event.event_name,
            "session_id": event.session_id,
            "run_id": event.run_id,
            "turn_id": event.turn_id,
            "cwd": event.cwd,
            "project_root": event.project_root,
            "plugin_name": hook.plugin_name or event.plugin_name,
            "plugin_root": str(hook.plugin_root or event.plugin_root or ""),
            "plugin_data": event.plugin_data,
            "transcript_path": event.transcript_path,
            "metadata": event.metadata,
            "tool_name": event.tool_name,
            "tool_input": event.tool_input,
        }

    def _expanded_command(self, hook: HookDefinition, event: HookEvent) -> str:
        command = hook.handler.command
        plugin_root = str(hook.plugin_root or event.plugin_root or "")
        plugin_data = event.plugin_data
        project_root = event.project_root
        return (
            command
            .replace("${PLUGIN_ROOT}", plugin_root)
            .replace("${PLUGIN_DATA}", plugin_data)
            .replace("${PROJECT_ROOT}", project_root)
        )
```

- [ ] **Step 4: Export engine**

Update `core/src/lamtools_core/plugins/__init__.py`:

```python
from .engine import HookEngine
from .hook_config import HookRegistry, default_project_hooks_path, default_user_hooks_path
from .models import HookDecision, HookDefinition, HookEvent, HookHandler, PluginManifest
from .registry import PluginRegistry, PluginStateStore, default_project_plugin_root, default_user_plugin_root
from .trust import HookTrustStore

__all__ = [
    "HookDecision",
    "HookDefinition",
    "HookEngine",
    "HookEvent",
    "HookHandler",
    "HookRegistry",
    "HookTrustStore",
    "PluginManifest",
    "PluginRegistry",
    "PluginStateStore",
    "default_project_hooks_path",
    "default_project_plugin_root",
    "default_user_hooks_path",
    "default_user_plugin_root",
]
```

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
py -3.14 -m pytest core/tests/test_hook_engine.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit Task 3**

```powershell
git add core/src/lamtools_core/plugins/__init__.py core/src/lamtools_core/plugins/engine.py core/tests/test_hook_engine.py
git commit -m "feat: add command hook engine"
```

## Task 4: Wire PreToolUse Hooks Into CoreLoopKernel

**Files:**
- Modify: `core/src/lamtools_core/kernel/loop.py`
- Test: `core/tests/test_kernel_pre_tool_hooks.py`

**Interfaces:**
- Consumes: `HookEngine.run(HookEvent(...))`.
- Produces: optional `CoreLoopKernel.hook_engine` behavior before approval and tool execution.

- [ ] **Step 1: Write failing kernel hook tests**

Create `core/tests/test_kernel_pre_tool_hooks.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

import pytest

from lamtools_core.kernel.loop import CoreLoopKernel
from lamtools_core.kernel.policy import LoopPolicy
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState, RuntimeTurnInput
from lamtools_core.tool import ToolCall, ToolResult
from lamtools_core.plugins import HookDecision, HookEvent

from core.tests.test_kernel import MockEventSink, MockLLMClient, MockRuntimeKit, MockKitStep


@dataclass
class BlockingHookEngine:
    async def run(self, event: HookEvent) -> HookDecision:
        assert event.event_name == "PreToolUse"
        assert event.tool_name == "run_command"
        return HookDecision(decision="block", reason="blocked by hook")


@dataclass
class RewritingHookEngine:
    async def run(self, event: HookEvent) -> HookDecision:
        return HookDecision(updated_input={"command": "py -3.14 -m pytest"})


@pytest.mark.asyncio
async def test_pre_tool_use_hook_blocks_tool_execution():
    executor_calls = []

    class ToolKit(MockRuntimeKit):
        async def execute_tool(self, state: RuntimeState, call: ToolCall) -> ToolResult:
            executor_calls.append(call.name)
            return ToolResult(call_id=call.id, name=call.name, status="ok", content="ran")

    kit = ToolKit(steps=[MockKitStep(tool_calls=[ToolCall(id="call-1", name="run_command", arguments={"command": "pytest"})])])
    kernel = CoreLoopKernel(
        kit=kit,
        llm_client=MockLLMClient(),
        state_store=InMemoryRuntimeStateStore(),
        event_sink=MockEventSink(),
        policy=LoopPolicy(),
        hook_engine=BlockingHookEngine(),
    )

    result = await kernel.run(RuntimeTurnInput(user_message="run tests", metadata={"session_id": "s1"}))

    assert executor_calls == []
    assert result.steps[0].tool_steps[0].result.status == "blocked"
    assert result.steps[0].tool_steps[0].result.error == "blocked by hook"


@pytest.mark.asyncio
async def test_pre_tool_use_hook_rewrites_tool_input_before_execution():
    seen_arguments = []

    class ToolKit(MockRuntimeKit):
        async def execute_tool(self, state: RuntimeState, call: ToolCall) -> ToolResult:
            seen_arguments.append(dict(call.arguments))
            return ToolResult(call_id=call.id, name=call.name, status="ok", content="ran")

    kit = ToolKit(steps=[MockKitStep(tool_calls=[ToolCall(id="call-1", name="run_command", arguments={"command": "pytest"})])])
    kernel = CoreLoopKernel(
        kit=kit,
        llm_client=MockLLMClient(),
        state_store=InMemoryRuntimeStateStore(),
        event_sink=MockEventSink(),
        policy=LoopPolicy(),
        hook_engine=RewritingHookEngine(),
    )

    await kernel.run(RuntimeTurnInput(user_message="run tests", metadata={"session_id": "s1"}))

    assert seen_arguments == [{"command": "py -3.14 -m pytest"}]
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.14 -m pytest core/tests/test_kernel_pre_tool_hooks.py -q
```

Expected: FAIL because `CoreLoopKernel.__init__` does not accept `hook_engine`.

- [ ] **Step 3: Add optional hook engine to kernel dataclass**

In `core/src/lamtools_core/kernel/loop.py`, add:

```python
from lamtools_core.plugins import HookEvent
```

and add a dataclass field:

```python
    hook_engine: Any | None = None
```

Use `Any` because tests can pass a small adapter object and Core does not need a hard dependency on one concrete engine implementation.

- [ ] **Step 4: Add pre-tool helper methods**

In `CoreLoopKernel`, add:

```python
    async def _apply_pre_tool_hook(
        self,
        state: RuntimeState,
        call: ToolCall,
    ) -> ToolResult | None:
        if self.hook_engine is None:
            return None
        decision = await self.hook_engine.run(HookEvent(
            event_name="PreToolUse",
            session_id=state.session_id,
            run_id=state.run_id,
            cwd=str(call.metadata.get("cwd") or ""),
            project_root=str(call.metadata.get("work_root") or call.metadata.get("project_root") or ""),
            metadata=dict(call.metadata),
            tool_name=call.name,
            tool_input=dict(call.arguments if isinstance(call.arguments, dict) else {}),
        ))
        if decision.updated_input is not None:
            call.arguments = dict(decision.updated_input)
        if decision.additional_context:
            call.metadata["hook_additional_context"] = decision.additional_context
        if decision.permission_decision == "ask_user":
            call.requires_approval = True
            call.metadata["hook_permission_reason"] = decision.permission_decision_reason
        if decision.permission_decision == "deny" or decision.decision == "block":
            reason = decision.permission_decision_reason or decision.reason or "blocked by hook"
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="blocked",
                error=reason,
                content=reason,
                metadata={"hook_decision": "blocked", "hook_audit": decision.audit_events},
            )
        if decision.audit_events:
            call.metadata["hook_audit"] = decision.audit_events
        return None
```

- [ ] **Step 5: Call pre hooks before approval check**

In `CoreLoopKernel.run`, directly before:

```python
approval_calls = [call for call in turn.tool_calls if call.requires_approval]
```

insert:

```python
blocked_results: dict[str, ToolResult] = {}
for call in turn.tool_calls:
    blocked = await self._apply_pre_tool_hook(state, call)
    if blocked is not None:
        blocked_results[call.id] = blocked
```

Then change approval collection to:

```python
approval_calls = [
    call
    for call in turn.tool_calls
    if call.id not in blocked_results and call.requires_approval
]
```

In sequential execution, before calling `_execute_tool`, check:

```python
if call.id in blocked_results:
    result = blocked_results[call.id]
else:
    result = await self._execute_tool(state, call)
```

In the parallel path, merge the new `blocked_results` with any kit preflight result. Use the existing `blocked_results` variable instead of redeclaring a second local map.

- [ ] **Step 6: Verify GREEN**

Run:

```powershell
py -3.14 -m pytest core/tests/test_kernel_pre_tool_hooks.py core/tests/test_kernel.py -q
```

Expected: pass.

- [ ] **Step 7: Commit Task 4**

```powershell
git add core/src/lamtools_core/kernel/loop.py core/tests/test_kernel_pre_tool_hooks.py
git commit -m "feat: run pre tool hooks in core kernel"
```

## Task 5: Shared Plugin/Hook Operations

**Files:**
- Modify: `core/src/lamtools_core/plugins/__init__.py`
- Create: `core/src/lamtools_core/plugins/operations.py`
- Test: `core/tests/test_plugin_operations.py`

**Interfaces:**
- Consumes: `PluginRegistry`, `PluginStateStore`, `HookRegistry`, `HookTrustStore`.
- Produces: `build_plugin_operation_catalog(...) -> OperationCatalog`.

- [ ] **Step 1: Write failing operation tests**

Create `core/tests/test_plugin_operations.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugins import (
    HookRegistry,
    HookTrustStore,
    PluginRegistry,
    PluginStateStore,
    build_plugin_operation_catalog,
)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.mark.asyncio
async def test_plugin_operations_list_enable_disable_and_trust(tmp_path: Path):
    plugin_root = tmp_path / "plugins" / "repo-policy"
    write_json(plugin_root / "plugin.json", {"name": "repo-policy", "version": "0.1.0"})
    write_json(plugin_root / "hooks" / "hooks.json", {
        "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "python ok.py"}]}]}
    })
    state = PluginStateStore(tmp_path / "plugin-state.json")
    trust = HookTrustStore(tmp_path / "hook-trust.json")
    registry = PluginRegistry(plugin_roots=[tmp_path / "plugins"], state_store=state)

    def hook_registry_factory():
        return HookRegistry(plugins=registry.discover(), trust_store=trust)

    catalog = build_plugin_operation_catalog(
        plugin_registry=registry,
        plugin_state_store=state,
        hook_registry_factory=hook_registry_factory,
        hook_trust_store=trust,
    )

    plugins = await catalog.execute("plugin.list")
    assert plugins.payload["plugins"][0]["name"] == "repo-policy"
    assert plugins.payload["plugins"][0]["enabled"] is True

    await catalog.execute("plugin.disable", {"name": "repo-policy"})
    assert state.is_enabled("repo-policy") is False

    hooks = await catalog.execute("hook.list")
    hook_id = hooks.payload["hooks"][0]["id"]
    hook_hash = hooks.payload["hooks"][0]["definition_hash"]

    await catalog.execute("hook.trust", {"hook_id": hook_id})
    assert trust.is_trusted(hook_hash) is True
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
py -3.14 -m pytest core/tests/test_plugin_operations.py -q
```

Expected: FAIL because `build_plugin_operation_catalog` is not exported.

- [ ] **Step 3: Implement operations**

Create `core/src/lamtools_core/plugins/operations.py`:

```python
from __future__ import annotations

from collections.abc import Callable

from lamtools_core.app import OperationCatalog, OperationRequest, OperationResult

from .hook_config import HookRegistry
from .registry import PluginRegistry, PluginStateStore
from .trust import HookTrustStore


def build_plugin_operation_catalog(
    *,
    plugin_registry: PluginRegistry,
    plugin_state_store: PluginStateStore,
    hook_registry_factory: Callable[[], HookRegistry],
    hook_trust_store: HookTrustStore,
) -> OperationCatalog:
    catalog = OperationCatalog()

    async def plugin_list(request: OperationRequest) -> OperationResult:
        _ = request
        plugins = [
            {
                "name": item.name,
                "version": item.version,
                "description": item.description,
                "root": str(item.root),
                "enabled": item.enabled,
                "skills": [str(path) for path in item.skill_roots],
                "hooks": [str(path) for path in item.hook_files],
                "mcp": [str(path) for path in item.mcp_files],
                "agents": [str(path) for path in item.agent_roots],
            }
            for item in plugin_registry.discover()
        ]
        return OperationResult(name=request.name, payload={"plugins": plugins})

    async def plugin_enable(request: OperationRequest) -> OperationResult:
        name = str(request.payload.get("name") or "").strip()
        if not name:
            return OperationResult(name=request.name, status="error", payload={"error": "name is required"})
        plugin_state_store.set_enabled(name, True)
        return OperationResult(name=request.name, payload={"name": name, "enabled": True})

    async def plugin_disable(request: OperationRequest) -> OperationResult:
        name = str(request.payload.get("name") or "").strip()
        if not name:
            return OperationResult(name=request.name, status="error", payload={"error": "name is required"})
        plugin_state_store.set_enabled(name, False)
        return OperationResult(name=request.name, payload={"name": name, "enabled": False})

    async def hook_list(request: OperationRequest) -> OperationResult:
        _ = request
        hooks = [
            {
                "id": hook.id,
                "event": hook.event,
                "matcher": hook.matcher,
                "source": hook.source,
                "source_name": hook.source_name,
                "plugin_name": hook.plugin_name,
                "config_path": str(hook.config_path),
                "handler_type": hook.handler.type,
                "command": hook.handler.command,
                "definition_hash": hook.definition_hash,
                "trusted": hook.trusted,
                "status": hook.status,
            }
            for hook in hook_registry_factory().load()
        ]
        return OperationResult(name=request.name, payload={"hooks": hooks})

    async def hook_trust(request: OperationRequest) -> OperationResult:
        hook_id = str(request.payload.get("hook_id") or request.payload.get("hookId") or "").strip()
        hooks = hook_registry_factory().load()
        hook = next((item for item in hooks if item.id == hook_id), None)
        if hook is None:
            return OperationResult(name=request.name, status="error", payload={"error": "hook_id not found"})
        hook_trust_store.trust(hook.definition_hash)
        return OperationResult(name=request.name, payload={"hook_id": hook_id, "trusted": True})

    catalog.register("plugin.list", plugin_list)
    catalog.register("plugin.enable", plugin_enable)
    catalog.register("plugin.disable", plugin_disable)
    catalog.register("hook.list", hook_list)
    catalog.register("hook.trust", hook_trust)
    return catalog
```

- [ ] **Step 4: Export operations**

Update `core/src/lamtools_core/plugins/__init__.py`:

```python
from .engine import HookEngine
from .hook_config import HookRegistry, default_project_hooks_path, default_user_hooks_path
from .models import HookDecision, HookDefinition, HookEvent, HookHandler, PluginManifest
from .operations import build_plugin_operation_catalog
from .registry import PluginRegistry, PluginStateStore, default_project_plugin_root, default_user_plugin_root
from .trust import HookTrustStore

__all__ = [
    "HookDecision",
    "HookDefinition",
    "HookEngine",
    "HookEvent",
    "HookHandler",
    "HookRegistry",
    "HookTrustStore",
    "PluginManifest",
    "PluginRegistry",
    "PluginStateStore",
    "build_plugin_operation_catalog",
    "default_project_hooks_path",
    "default_project_plugin_root",
    "default_user_hooks_path",
    "default_user_plugin_root",
]
```

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
py -3.14 -m pytest core/tests/test_plugin_operations.py -q
```

Expected: `1 passed`.

- [ ] **Step 6: Commit Task 5**

```powershell
git add core/src/lamtools_core/plugins/__init__.py core/src/lamtools_core/plugins/operations.py core/tests/test_plugin_operations.py
git commit -m "feat: add plugin hook operations"
```

## Task 6: Writer App-Server and CLI Bridge

This task is exposure only. Do not implement plugin scanning, hook config parsing, trust storage, or hook execution in Writer; every operation must route to Core-owned plugin/hook logic.

**Files:**
- Modify: `members/writer/backend/app/app_server/operations.py`
- Modify: `members/writer/backend/app/app_server/connection.py`
- Modify: `members/writer/backend/writer_cli/__main__.py`
- Modify: `members/writer/backend/writer_cli/app_server_client.py`
- Test: `members/writer/backend/tests/test_writer_app_server_protocol.py`
- Test: `members/writer/backend/tests/test_writer_cli.py`

**Interfaces:**
- Consumes: Core `build_plugin_operation_catalog`.
- Produces: Writer app-server operations and CLI commands:
  - `plugin.list`
  - `plugin.enable`
  - `plugin.disable`
  - `hook.list`
  - `hook.trust`

- [ ] **Step 1: Write failing Writer app-server test**

Append to `members/writer/backend/tests/test_writer_app_server_protocol.py`:

```python
@pytest.mark.asyncio
async def test_plugin_operations_are_registered_in_writer_catalog(tmp_path):
    from app.app_server.operations import build_writer_operation_catalog

    async def noop(request):
        return None

    catalog = build_writer_operation_catalog(
        thread_read=noop,
        thread_resume=noop,
        thread_start=noop,
        turn_start=noop,
        turn_steer=noop,
        turn_cancel=noop,
        approval_respond=noop,
        queue_create=noop,
        queue_update=noop,
        queue_delete=noop,
        project_create=noop,
        project_directory_pick=noop,
        project_get=noop,
        project_list=noop,
        project_update=noop,
        project_delete=noop,
        project_agents_md_get=noop,
        project_agents_md_update=noop,
        project_sessions_list=noop,
        attachment_list=noop,
        attachment_get=noop,
        attachment_preview=noop,
        attachment_open=noop,
        artifact_read=noop,
        artifact_open=noop,
        command_catalog=noop,
        command_execute=noop,
        session_create=noop,
        session_get=noop,
        session_list=noop,
        session_update=noop,
        session_delete=noop,
        session_fork=noop,
        session_git_graph=noop,
        session_changes_get=noop,
        session_checkpoints_list=noop,
        session_checkpoint_create=noop,
        session_checkpoint_restore=noop,
        session_commit_review_get=noop,
        session_commit_review_decide=noop,
        session_agent_branches_list=noop,
        session_agent_branch_diff=noop,
        session_agent_branch_merge=noop,
        session_agent_branch_abandon=noop,
        session_rollback_turn=noop,
        session_changes_undo=noop,
        session_change_file_open=noop,
        session_change_file_undo=noop,
        settings_get=noop,
        settings_update=noop,
        config_providers_list=noop,
        config_provider_create=noop,
        config_provider_update=noop,
        config_provider_delete=noop,
        config_models_list=noop,
        config_model_create=noop,
        config_model_update=noop,
        config_model_delete=noop,
        config_import_env=noop,
        config_resolved_get=noop,
        config_adapter_profiles_list=noop,
        config_runtime_capabilities_get=noop,
        config_subagent_upsert=noop,
        config_subagent_delete=noop,
        plugin_list=noop,
        plugin_enable=noop,
        plugin_disable=noop,
        hook_list=noop,
        hook_trust=noop,
    )

    assert catalog.has("plugin.list")
    assert catalog.has("plugin.enable")
    assert catalog.has("plugin.disable")
    assert catalog.has("hook.list")
    assert catalog.has("hook.trust")
```

- [ ] **Step 2: Write failing CLI tests**

Append to `members/writer/backend/tests/test_writer_cli.py`:

```python
def test_cli_plugin_list_uses_app_server(monkeypatch, capsys):
    calls = []

    class FakeClient:
        def __init__(self, base_url):
            self.base_url = base_url
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def connect(self, thread_id=None):
            return None
        async def request(self, method, params=None):
            calls.append((method, params or {}))
            return {"plugins": [{"name": "repo-policy", "enabled": True}]}

    monkeypatch.setattr("writer_cli.__main__.AppServerClient", FakeClient)
    from writer_cli.__main__ import main

    assert main(["plugin", "list"]) == 0
    assert calls == [("plugin.list", {})]
    assert "repo-policy" in capsys.readouterr().out


def test_cli_hook_trust_uses_app_server(monkeypatch, capsys):
    calls = []

    class FakeClient:
        def __init__(self, base_url):
            self.base_url = base_url
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def connect(self, thread_id=None):
            return None
        async def request(self, method, params=None):
            calls.append((method, params or {}))
            return {"hook_id": "hook-1", "trusted": True}

    monkeypatch.setattr("writer_cli.__main__.AppServerClient", FakeClient)
    from writer_cli.__main__ import main

    assert main(["hook", "trust", "hook-1"]) == 0
    assert calls == [("hook.trust", {"hook_id": "hook-1"})]
    assert "trusted" in capsys.readouterr().out
```

- [ ] **Step 3: Verify RED**

Run:

```powershell
py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py::test_plugin_operations_are_registered_in_writer_catalog members/writer/backend/tests/test_writer_cli.py::test_cli_plugin_list_uses_app_server members/writer/backend/tests/test_writer_cli.py::test_cli_hook_trust_uses_app_server -q
```

Expected: FAIL because operations and CLI commands are missing.

- [ ] **Step 4: Register Writer app-server operations**

In `members/writer/backend/app/app_server/operations.py`, add function parameters to `build_writer_operation_catalog`:

```python
    plugin_list: OperationRpcHandler,
    plugin_enable: OperationRpcHandler,
    plugin_disable: OperationRpcHandler,
    hook_list: OperationRpcHandler,
    hook_trust: OperationRpcHandler,
```

Register:

```python
    catalog.register("plugin.list", _handler(plugin_list))
    catalog.register("plugin.enable", _handler(plugin_enable))
    catalog.register("plugin.disable", _handler(plugin_disable))
    catalog.register("hook.list", _handler(hook_list))
    catalog.register("hook.trust", _handler(hook_trust))
```

In `members/writer/backend/app/app_server/connection.py`, add methods that call Core operation catalog. The connection method must build paths from the active project/work root when available and from settings data dir for state/trust. The callable shape:

```python
    async def _plugin_list(self, request: JsonRpcRequest) -> None:
        outcome = await handle_plugin_catalog_operation(request_id=request.id, params=request.params or {}, operation="plugin.list")
        await self._send_response(outcome.response)
```

Implement `handle_plugin_catalog_operation` in `operations.py` as a small adapter around Core's `build_plugin_operation_catalog`.

- [ ] **Step 5: Add CLI command wrappers**

In `members/writer/backend/writer_cli/__main__.py`, add:

```python
async def cmd_plugin_list(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect()
        result = await client.request("plugin.list", {})
    for plugin in result.get("plugins", []):
        print(f"{plugin.get('name')} enabled={plugin.get('enabled')}")
    return 0


async def cmd_plugin_enable(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect()
        result = await client.request("plugin.enable", {"name": args.name})
    print(f"{result.get('name')} enabled")
    return 0


async def cmd_plugin_disable(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect()
        result = await client.request("plugin.disable", {"name": args.name})
    print(f"{result.get('name')} disabled")
    return 0


async def cmd_hook_list(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect()
        result = await client.request("hook.list", {})
    for hook in result.get("hooks", []):
        print(f"{hook.get('id')} {hook.get('event')} {hook.get('matcher')} trusted={hook.get('trusted')}")
    return 0


async def cmd_hook_trust(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect()
        result = await client.request("hook.trust", {"hook_id": args.hook_id})
    print(f"{result.get('hook_id')} trusted")
    return 0
```

In `build_parser()`, add `plugin` and `hook` subcommands:

```python
    plugin_parser = sub.add_parser("plugin", help="Plugin utilities")
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_command", required=True)
    plugin_sub.add_parser("list", help="List plugins").set_defaults(func=cmd_plugin_list)
    plugin_enable = plugin_sub.add_parser("enable", help="Enable plugin")
    plugin_enable.add_argument("name")
    plugin_enable.set_defaults(func=cmd_plugin_enable)
    plugin_disable = plugin_sub.add_parser("disable", help="Disable plugin")
    plugin_disable.add_argument("name")
    plugin_disable.set_defaults(func=cmd_plugin_disable)

    hook_parser = sub.add_parser("hook", help="Hook utilities")
    hook_sub = hook_parser.add_subparsers(dest="hook_command", required=True)
    hook_sub.add_parser("list", help="List hooks").set_defaults(func=cmd_hook_list)
    hook_trust = hook_sub.add_parser("trust", help="Trust hook by id")
    hook_trust.add_argument("hook_id")
    hook_trust.set_defaults(func=cmd_hook_trust)
```

- [ ] **Step 6: Verify GREEN**

Run:

```powershell
py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py::test_plugin_operations_are_registered_in_writer_catalog members/writer/backend/tests/test_writer_cli.py::test_cli_plugin_list_uses_app_server members/writer/backend/tests/test_writer_cli.py::test_cli_hook_trust_uses_app_server -q
```

Expected: pass.

- [ ] **Step 7: Commit Task 6**

```powershell
git add members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/connection.py members/writer/backend/writer_cli/__main__.py members/writer/backend/writer_cli/app_server_client.py members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_cli.py
git commit -m "feat: expose plugin hook operations in writer"
```

## Task 7: Phase 1 Verification

**Files:**
- Modify only if verification exposes missing exports or narrow integration bugs.

**Interfaces:**
- Consumes all previous tasks.
- Produces a verified Phase 1 slice.

- [ ] **Step 1: Run Core plugin/hook tests**

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
py -3.14 -m pytest core/tests/test_plugin_registry.py core/tests/test_hook_registry.py core/tests/test_hook_trust.py core/tests/test_hook_engine.py core/tests/test_kernel_pre_tool_hooks.py core/tests/test_plugin_operations.py -q
```

Expected: pass.

- [ ] **Step 2: Run existing Core regression tests around touched areas**

```powershell
py -3.14 -m pytest core/tests/test_kernel.py core/tests/test_tool.py core/tests/test_tool_approval.py -q
```

Expected: pass.

- [ ] **Step 3: Run Writer bridge tests**

```powershell
py -3.14 -m pytest members/writer/backend/tests/test_writer_app_server_protocol.py members/writer/backend/tests/test_writer_cli.py -q
```

Expected: pass or existing unrelated failures only if they are already documented before this task starts. New plugin/hook assertions must pass.

- [ ] **Step 4: Run whitespace and product-name checks**

```powershell
git diff --check -- core members/writer docs/superpowers
rg -n "Writer|Artist|LamWriter|LamArtist" core/src/lamtools_core/plugins core/src/lamtools_core/kernel/loop.py
```

Expected: no whitespace errors and no product names in Core plugin/kernel code.

- [ ] **Step 5: Manual acceptance fixture**

Create a temporary plugin outside tracked source:

```powershell
$root = Join-Path $env:TEMP "lamtools-plugin-acceptance"
Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path "$root\plugins\repo-policy\hooks" | Out-Null
@'
{"name":"repo-policy","version":"0.1.0"}
'@ | Set-Content -LiteralPath "$root\plugins\repo-policy\plugin.json" -Encoding UTF8
@'
{"hooks":{"PreToolUse":[{"matcher":"run_command","hooks":[{"type":"command","command":"python ${PLUGIN_ROOT}/hooks/block.py"}]}]}}
'@ | Set-Content -LiteralPath "$root\plugins\repo-policy\hooks\hooks.json" -Encoding UTF8
@'
import json, sys
payload = json.load(sys.stdin)
command = payload.get("tool_input", {}).get("command", "")
if "Remove-Item" in command:
    print(json.dumps({"decision":"block","reason":"blocked destructive command"}))
else:
    print(json.dumps({}))
'@ | Set-Content -LiteralPath "$root\plugins\repo-policy\hooks\block.py" -Encoding UTF8
```

Use the new Core registry and hook operations in a short Python smoke script:

```powershell
@'
from pathlib import Path
from lamtools_core.plugins import PluginRegistry
root = Path(__import__("os").environ["TEMP"]) / "lamtools-plugin-acceptance"
plugins = PluginRegistry(plugin_roots=[root / "plugins"]).discover()
print([(p.name, len(p.hook_files)) for p in plugins])
'@ | py -3.14 -
```

Expected output includes:

```text
[('repo-policy', 1)]
```

- [ ] **Step 6: Commit verification fixes**

If Step 1-5 required small fixes:

```powershell
git add <only-fixed-files>
git commit -m "fix: stabilize plugin hook phase one"
```

Expected: no commit if no fixes were needed.

## Self-Review

- Spec coverage: plugin package discovery, JSON hook customization, trust, `PreToolUse`, no dedicated installer, CLI/app-server operations, and Kernel/Kit separation are covered.
- Scope gaps intentionally deferred: settings UI, marketplace, HTTP/MCP/prompt handlers, `PostToolUse`, `Stop`, compaction hooks, plugin MCP loading, plugin skill loading, and plugin agents.
- Placeholder scan: no `TBD`, `TODO`, `implement later`, or vague edge-case steps.
- Type consistency: `PluginRegistry`, `HookRegistry`, `HookTrustStore`, `HookEngine`, `HookEvent`, and `HookDecision` are defined before any later task consumes them.
