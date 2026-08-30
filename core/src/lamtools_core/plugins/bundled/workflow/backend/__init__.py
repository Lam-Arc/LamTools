"""Runtime contributions for the bundled Workflow plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lamtools_core.plugins.context import PluginContext

from .build_tools import workflow_build_tool_handlers, workflow_build_tool_specs
from .runtime import WorkflowManager, WorkflowRunner
from .store import WorkflowStore
from .tools import WorkflowToolBundle, workflow_tool_provider
from .watcher import WorkflowFileWatcher


@dataclass
class WorkflowPluginRuntime:
    context: PluginContext
    store: WorkflowStore
    manager: WorkflowManager
    runner: WorkflowRunner
    watcher: WorkflowFileWatcher | None = None
    _pending_work_roots: set[str] = field(default_factory=set, repr=False)
    _enabled: bool = field(default=True, init=False, repr=False)

    @property
    def tool_providers(self) -> list[Any]:
        return [self.workflow_tool_provider]

    @property
    def tool_handlers(self) -> dict[str, Any]:
        if not self._enabled:
            return {}
        return self.build_tool_handlers

    @property
    def build_tool_handlers(self) -> dict[str, Any]:
        executor = self.context.operation_executor()
        # Handlers resolve the active project from ToolCall.metadata. Do not
        # capture the project that happened to be open when the plugin loaded.
        return workflow_build_tool_handlers(executor)

    @property
    def tool_specs(self) -> list[Any]:
        if not self._enabled:
            return []
        return workflow_build_tool_specs()

    def workflow_tool_provider(self, work_root: str | None = None) -> Any:
        if not self._enabled:
            return WorkflowToolBundle(specs=[], handlers={}, names={})
        # Rebuild the provider with the active work root so project switching
        # never reuses the root captured at application startup.
        scoped_context = self.context.for_work_root(work_root or self.context.work_root)
        return workflow_tool_provider(
            self.store,
            scoped_context.operation_executor(),
            work_root=scoped_context.work_root,
        )()

    async def start(self, context: PluginContext | None = None) -> None:
        context = context or self.context
        self._enabled = True
        if self.watcher is None and context.event_bus is not None:
            roots = [str(context.work_root), *sorted(self._pending_work_roots)]
            self.watcher = WorkflowFileWatcher(
                self.store,
                context.event_bus,
                poll_interval=2.0,
                work_roots=roots,
            )
        if self.watcher is not None:
            await self.watcher.start()

    async def stop(self) -> None:
        self._enabled = False
        if self.watcher is not None:
            await self.watcher.stop()
            self.watcher = None
        shutdown = getattr(self.runner, "shutdown", None)
        if callable(shutdown):
            result = shutdown()
            if hasattr(result, "__await__"):
                await result

    def watch_work_root(self, work_root: str | None) -> None:
        if not work_root:
            return
        from pathlib import Path

        root = str(Path(work_root).expanduser().resolve())
        self._pending_work_roots.add(root)
        if self.watcher is not None:
            self.watcher.add_work_root(root)


def create_plugin(context: PluginContext) -> WorkflowPluginRuntime:
    # Hosts may provide a store-compatible object for embedded/legacy local
    # runs.  Normal HTTP/GUI hosts leave this unset and the plugin owns its
    # durable WorkflowStore instance.
    store = context.service("workflow_store") or WorkflowStore()
    runtime = WorkflowPluginRuntime(
        context=context,
        store=store,
        manager=WorkflowManager(store),
        runner=WorkflowRunner(
            llm_client=context.llm_client,
            sub_agent_runner=context.service("sub_agent_runner"),
            emit=context.emit,
            runtime_task_registry=context.runtime_task_registry,
            workflow_store=store,
            permission_service=context.permission_service,
        ),
    )
    return runtime


__all__ = ["WorkflowPluginRuntime", "create_plugin"]
