from __future__ import annotations

from collections.abc import Mapping, Sequence

from .operation_catalog import OperationCatalog, OperationHandler


CORE_WORKBENCH_OPERATION_NAMES: tuple[str, ...] = (
    "thread.read",
    "thread.resume",
    "thread.start",
    "turn.start",
    "turn.steer",
    "turn.cancel",
    "approval.respond",
    "queue.create",
    "queue.update",
    "queue.delete",
    "queue.guide",
    "artifact.read",
    "artifact.open",
    "command.catalog",
    "command.execute",
    "attachment.list",
    "attachment.get",
    "attachment.preview",
    "attachment.open",
    "settings.get",
    "settings.update",
    "config.providers.list",
    "config.provider.create",
    "config.provider.update",
    "config.provider.delete",
    "config.models.list",
    "config.model.create",
    "config.model.update",
    "config.model.delete",
    "config.import_env",
    "config.resolved.get",
    "config.adapter_profiles.list",
    "config.runtime_capabilities.get",
    "plugin.list",
    "plugin.enable",
    "plugin.disable",
    "hook.list",
    "hook.trust",
    "hook.trust_all",
    "hook.untrust",
    "hook.delete",
    "hook.config.get",
    "hook.config.update",
    "skill.list",
    "skill.enable",
    "skill.disable",
    "project.list",
    "project.create",
    "project.get",
    "project.update",
    "project.delete",
    "project.sessions.create",
    "project.sessions.list",
    "project.agents_md.get",
    "project.agents_md.update",
    "session.rollback",
    "session.rollback.undo",
)


CORE_DURABLE_OPERATION_NAMES: tuple[str, ...] = (
    "goal.create",
    "goal.get",
    "goal.list",
    "goal.update",
    "arrange.create",
    "arrange.get",
    "arrange.list",
    "arrange.update",
    "arrange.pause",
    "arrange.resume",
    "arrange.cancel",
    "arrange.signal",
    "arrange.occurrence.get",
    "arrange.occurrence.list",
)


CORE_WORKFLOW_OPERATION_NAMES: tuple[str, ...] = (
    "workflow.create",
    "workflow.get",
    "workflow.list",
    "workflow.update",
    "workflow.delete",
    "workflow.run",
    "workflow.cancel",
    "workflow.expose",
    "workflow.unexpose",
    "workflow.tools.list",
)


def register_operation_handlers(
    catalog: OperationCatalog,
    names: Sequence[str],
    handlers: Mapping[str, OperationHandler],
) -> None:
    missing = [name for name in names if name not in handlers]
    if missing:
        raise KeyError(f"Missing operation handlers: {', '.join(missing)}")
    for name in names:
        catalog.register(name, handlers[name])


def build_member_operation_catalog(
    *,
    core_handlers: Mapping[str, OperationHandler],
    overlay_names: Sequence[str] = (),
    overlay_handlers: Mapping[str, OperationHandler] | None = None,
) -> OperationCatalog:
    core_names = set(CORE_WORKBENCH_OPERATION_NAMES)
    shadowed = [name for name in overlay_names if name in core_names]
    if shadowed:
        raise ValueError(f"Member overlay shadows core operations: {', '.join(shadowed)}")
    catalog = OperationCatalog()
    register_operation_handlers(catalog, CORE_WORKBENCH_OPERATION_NAMES, core_handlers)
    if overlay_names:
        register_operation_handlers(catalog, overlay_names, overlay_handlers or {})
    return catalog


__all__ = [
    "CORE_DURABLE_OPERATION_NAMES",
    "CORE_WORKBENCH_OPERATION_NAMES",
    "CORE_WORKFLOW_OPERATION_NAMES",
    "build_member_operation_catalog",
    "register_operation_handlers",
]
