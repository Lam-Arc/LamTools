"""Composition of independently registered command groups and plugin commands."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
from pathlib import Path


def build_parser(*, plugin_roots: list[Path | str] | tuple[Path | str, ...] | None = None, plugin_state_path: Path | str | None = None) -> argparse.ArgumentParser:
    from .config import _default_cli_plugin_roots, _default_cli_plugin_state_path
    from .parse_preferences import register_ask_auto_continue, register_command_shell, register_keep_awake, register_language, register_load_context, register_memory, register_memory_resume, register_network, register_onboarding
    from .parse_resources import register_artifact, register_attachment, register_command, register_office, register_plugin, register_skill
    from .parse_server import register_maintenance, register_migrate_projects, register_mobile, register_serve, register_setup, register_update
    from .parse_settings import register_context_compaction, register_imagegen, register_loadtools, register_models, register_permissions
    from .parse_turns import register_approval, register_cancel, register_pause, register_process, register_queue, register_resume, register_run, register_run_local, register_start, register_steer, register_terminate, register_watch
    from .parse_workspace import register_arrange, register_goal, register_plan_library, register_project, register_session, register_subagent
    parser = argparse.ArgumentParser(prog="core", description="Sunday AI software CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    # user:“通过 command 运行”+(提供与代理命令一致的真实 CLI 入口)。
    from .mcp import register_mcp
    register_mcp(sub)
    register_serve(sub)
    register_setup(sub)
    register_migrate_projects(sub)
    register_maintenance(sub)
    register_run(sub)
    register_run_local(sub)
    register_watch(sub)
    register_start(sub)
    register_resume(sub)
    register_pause(sub)
    register_terminate(sub)
    register_cancel(sub)
    register_steer(sub)
    register_queue(sub)
    register_process(sub)
    register_approval(sub)
    register_plugin(sub)
    register_skill(sub)
    register_command(sub)
    register_attachment(sub)
    register_imagegen(sub)
    register_update(sub)
    register_office(sub)
    register_mobile(sub)
    register_artifact(sub)
    register_session(sub)
    register_project(sub)
    register_goal(sub)
    register_plan_library(sub)
    register_arrange(sub)
    register_subagent(sub)
    register_models(sub)
    register_permissions(sub)
    register_context_compaction(sub)
    register_command_shell(sub)
    register_network(sub)
    register_language(sub)
    register_keep_awake(sub)
    register_ask_auto_continue(sub)
    register_memory_resume(sub)
    register_loadtools(sub)
    register_memory(sub)
    register_onboarding(sub)
    register_load_context(sub)
    from lamtools_core.plugin_system import PluginHost
    from lamtools_core.plugin_system.plugin_cli import load_plugin_cli_commands

    resolved_roots = (
        plugin_roots if plugin_roots is not None else _default_cli_plugin_roots()
    )
    resolved_state = (
        plugin_state_path
        if plugin_state_path is not None
        else _default_cli_plugin_state_path()
    )
    load_plugin_cli_commands(
        sub,
        host=PluginHost(roots=list(resolved_roots), state_path=resolved_state),
    )
    return parser
