"""Parse resources responsibilities."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse


def register_plugin(sub: argparse._SubParsersAction) -> None:
    from .connection import _add_live_connection_arguments
    from .plugins import cmd_plugin_config_get, cmd_plugin_config_set, cmd_plugin_deps, cmd_plugin_disable, cmd_plugin_enable, cmd_plugin_install, cmd_plugin_list, cmd_plugin_operations_list, cmd_plugin_uninstall, cmd_plugin_widget_action, cmd_plugin_widget_list, cmd_plugin_widget_show
    plugin = sub.add_parser("plugin", help="Manage LamTools plugins (list/install/uninstall/enable/disable/deps/config)")
    plugin_sub = plugin.add_subparsers(dest="plugin_command", required=True)
    # user:“插件页再加上插件市场的界面”+(同一市场功能也提供命令行入口)。
    from .plugins import cmd_plugin_market
    market = plugin_sub.add_parser("market", help="Browse or install verified GitHub plugins")
    market.add_argument("action", choices=("list", "install"))
    market.add_argument("name", nargs="?", default="")
    _add_live_connection_arguments(market)
    market.add_argument("--raw", action="store_true")
    market.set_defaults(func=cmd_plugin_market)
    plugin_list = plugin_sub.add_parser("list", help="List plugins")
    _add_live_connection_arguments(plugin_list)
    plugin_list.add_argument("--raw", action="store_true")
    plugin_list.set_defaults(func=cmd_plugin_list)
    plugin_enable = plugin_sub.add_parser("enable", help="Enable a plugin")
    plugin_enable.add_argument("name")
    _add_live_connection_arguments(plugin_enable)
    plugin_enable.add_argument("--raw", action="store_true")
    plugin_enable.set_defaults(func=cmd_plugin_enable)
    plugin_disable = plugin_sub.add_parser("disable", help="Disable a plugin (tools disappear next turn)")
    plugin_disable.add_argument("name")
    _add_live_connection_arguments(plugin_disable)
    plugin_disable.add_argument("--raw", action="store_true")
    plugin_disable.set_defaults(func=cmd_plugin_disable)
    plugin_install = plugin_sub.add_parser("install", help="Install a plugin from local directory / zip / GitHub Release URL")
    plugin_install.add_argument("source", choices=("local", "zip", "url", "cc", "claude-code", "codex"),
                         help="local dir / zip / GitHub Release URL / Claude Code plugin / Codex plugin")
    plugin_install.add_argument("path_or_url", help="Local dir/zip path, GitHub Release .zip asset URL, or community plugin directory")
    plugin_install.add_argument("--target", choices=("user", "project"), default="user")
    plugin_install.add_argument("--sha256", default="", help="Expected sha256 of a URL-downloaded asset")
    plugin_install.add_argument("--no-deps", action="store_true", help="Skip installing declared pip dependencies")
    plugin_install.add_argument("-y", "--yes", action="store_true", help="Skip the interactive confirmation")
    _add_live_connection_arguments(plugin_install)
    plugin_install.add_argument("--raw", action="store_true")
    plugin_install.set_defaults(func=cmd_plugin_install)
    plugin_uninstall = plugin_sub.add_parser("uninstall", help="Uninstall a plugin (removes its directory)")
    plugin_uninstall.add_argument("name")
    plugin_uninstall.add_argument("--deps", action="store_true", help="Also uninstall its recorded dependencies (shared deps kept)")
    _add_live_connection_arguments(plugin_uninstall)
    plugin_uninstall.add_argument("--raw", action="store_true")
    plugin_uninstall.set_defaults(func=cmd_plugin_uninstall)
    plugin_deps = plugin_sub.add_parser("deps-status", help="Check a plugin's pip dependency status")
    plugin_deps.add_argument("name")
    _add_live_connection_arguments(plugin_deps)
    plugin_deps.add_argument("--raw", action="store_true")
    plugin_deps.set_defaults(func=cmd_plugin_deps)
    plugin_config = plugin_sub.add_parser("config", help="Read/write plugin configuration")
    plugin_config_sub = plugin_config.add_subparsers(dest="plugin_config_command", required=True)
    plugin_config_get = plugin_config_sub.add_parser("get", help="Get plugin configuration")
    plugin_config_get.add_argument("name")
    _add_live_connection_arguments(plugin_config_get)
    plugin_config_get.add_argument("--raw", action="store_true")
    plugin_config_get.set_defaults(func=cmd_plugin_config_get)
    plugin_config_set = plugin_config_sub.add_parser("set", help="Set plugin configuration (JSON object)")
    plugin_config_set.add_argument("name")
    plugin_config_set.add_argument("value", help="JSON object, e.g. '{\"embeddingSource\": \"api\"}'")
    _add_live_connection_arguments(plugin_config_set)
    plugin_config_set.add_argument("--raw", action="store_true")
    plugin_config_set.set_defaults(func=cmd_plugin_config_set)
    plugin_operations = plugin_sub.add_parser(
        "operations", help="Inspect plugin-declared operations (RPC surface, G 组)"
    )
    plugin_operations_sub = plugin_operations.add_subparsers(
        dest="plugin_operations_command", required=True
    )
    plugin_operations_list = plugin_operations_sub.add_parser(
        "list", help="List plugin-declared operations (optionally filtered by plugin name)"
    )
    plugin_operations_list.add_argument("name", nargs="?", default="", help="Plugin name filter")
    _add_live_connection_arguments(plugin_operations_list)
    plugin_operations_list.add_argument("--raw", action="store_true")
    plugin_operations_list.set_defaults(func=cmd_plugin_operations_list)
    plugin_widget = plugin_sub.add_parser("widget", help="Inspect and invoke plugin sidebar widgets")
    plugin_widget_sub = plugin_widget.add_subparsers(dest="plugin_widget_command", required=True)
    plugin_widget_list = plugin_widget_sub.add_parser("list", help="List enabled sidebar widgets")
    _add_live_connection_arguments(plugin_widget_list)
    plugin_widget_list.add_argument("--raw", action="store_true")
    plugin_widget_list.set_defaults(func=cmd_plugin_widget_list)
    plugin_widget_show = plugin_widget_sub.add_parser("show", help="Show a widget snapshot")
    plugin_widget_show.add_argument("id")
    plugin_widget_show.add_argument("--work-root", default="")
    plugin_widget_show.add_argument("--thread-id", default="")
    _add_live_connection_arguments(plugin_widget_show)
    plugin_widget_show.add_argument("--raw", action="store_true")
    plugin_widget_show.set_defaults(func=cmd_plugin_widget_show)
    plugin_widget_action = plugin_widget_sub.add_parser("action", help="Invoke a declared widget action")
    plugin_widget_action.add_argument("id")
    plugin_widget_action.add_argument("action")
    plugin_widget_action.add_argument("--input", default="{}", help="Action input JSON object")
    plugin_widget_action.add_argument("--work-root", default="")
    plugin_widget_action.add_argument("--thread-id", default="")
    plugin_widget_action.add_argument("--idempotency-key", default="")
    plugin_widget_action.add_argument("-y", "--yes", action="store_true", help="Confirm a dangerous action")
    _add_live_connection_arguments(plugin_widget_action)
    plugin_widget_action.add_argument("--raw", action="store_true")
    plugin_widget_action.set_defaults(func=cmd_plugin_widget_action)


def register_skill(sub: argparse._SubParsersAction) -> None:
    from .connection import _add_live_connection_arguments
    from .plugins import cmd_skill_create, cmd_skill_delete, cmd_skill_disable, cmd_skill_enable, cmd_skill_list
    skill = sub.add_parser("skill", help="Manage Core skills (list/create/enable/disable/delete)")
    skill_sub = skill.add_subparsers(dest="skill_command", required=True)
    skill_list = skill_sub.add_parser("list", help="List discovered skills")
    _add_live_connection_arguments(skill_list)
    skill_list.add_argument("--raw", action="store_true")
    skill_list.set_defaults(func=cmd_skill_list)
    skill_create = skill_sub.add_parser("create", help="Create a user skill")
    skill_create.add_argument("name")
    skill_create.add_argument("--description", required=True)
    skill_create.add_argument("--content", required=True)
    _add_live_connection_arguments(skill_create)
    skill_create.add_argument("--raw", action="store_true")
    skill_create.set_defaults(func=cmd_skill_create)
    skill_enable = skill_sub.add_parser("enable", help="Enable a skill")
    skill_enable.add_argument("name")
    _add_live_connection_arguments(skill_enable)
    skill_enable.add_argument("--raw", action="store_true")
    skill_enable.set_defaults(func=cmd_skill_enable)
    skill_disable = skill_sub.add_parser("disable", help="Disable a skill")
    skill_disable.add_argument("name")
    _add_live_connection_arguments(skill_disable)
    skill_disable.add_argument("--raw", action="store_true")
    skill_disable.set_defaults(func=cmd_skill_disable)
    skill_delete = skill_sub.add_parser("delete", help="Delete a writable project or user skill")
    skill_delete.add_argument("name")
    skill_delete.add_argument("-y", "--yes", action="store_true", help="Skip the interactive confirmation")
    _add_live_connection_arguments(skill_delete)
    skill_delete.add_argument("--raw", action="store_true")
    skill_delete.set_defaults(func=cmd_skill_delete)


def register_command(sub: argparse._SubParsersAction) -> None:
    from .connection import _add_live_connection_arguments
    from .turns import cmd_command_catalog, cmd_command_execute
    command = sub.add_parser("command", help="Use the Core command system")
    command_sub = command.add_subparsers(dest="command_action", required=True)
    command_catalog = command_sub.add_parser("catalog", help="List commands and skills")
    command_catalog.add_argument("--work-root", default="")
    _add_live_connection_arguments(command_catalog)
    command_catalog.add_argument("--raw", action="store_true")
    command_catalog.set_defaults(func=cmd_command_catalog)
    command_execute = command_sub.add_parser("execute", help="Execute a Core command action")
    command_execute.add_argument("thread_id")
    command_execute.add_argument("name")
    command_execute.add_argument("arguments", nargs="*", help="Command arguments")
    command_execute.add_argument("--work-root", default="")
    _add_live_connection_arguments(command_execute)
    command_execute.add_argument("--raw", action="store_true")
    command_execute.set_defaults(func=cmd_command_execute)


def register_attachment(sub: argparse._SubParsersAction) -> None:
    from .connection import _add_live_connection_arguments
    from .resources import cmd_attachment_upload
    attachment = sub.add_parser("attachment", help="Use Core attachment upload and storage")
    attachment_sub = attachment.add_subparsers(dest="attachment_action", required=True)
    attachment_upload = attachment_sub.add_parser("upload", help="Upload an attachment to a Core session")
    attachment_upload.add_argument("thread_id")
    attachment_upload.add_argument("file")
    _add_live_connection_arguments(attachment_upload)
    attachment_upload.add_argument("--raw", action="store_true")
    attachment_upload.set_defaults(func=cmd_attachment_upload)


def register_office(sub: argparse._SubParsersAction) -> None:
    from .connection import _office_positive_float, _office_positive_int
    from .office import cmd_office_check, cmd_office_render, cmd_office_validate
    office = sub.add_parser("office", help="Validate and render Office documents")
    office_sub = office.add_subparsers(dest="office_command", required=True)

    office_check = office_sub.add_parser("check", help="Run one bounded Office readiness check")
    office_check.add_argument(
        "--backend",
        choices=("auto", "microsoft", "libreoffice"),
        default="auto",
        help="Office backend (defaults to auto)",
    )
    office_check.add_argument(
        "--timeout",
        type=_office_positive_float,
        default=15.0,
        help="Maximum seconds for each format conversion",
    )
    office_check.add_argument(
        "--report",
        "--report-path",
        dest="report_path",
        default=None,
        help="Optional path for the JSON readiness report",
    )
    office_check.set_defaults(func=cmd_office_check)

    def _add_office_arguments(command: argparse.ArgumentParser, *, render: bool) -> None:
        # Positional paths keep the command convenient for shell scripts;
        # option aliases cover callers that need self-documenting invocations.
        command.add_argument("source_pos", nargs="?", help="Office input/source path")
        command.add_argument("manifest_pos", nargs="?", help="Canonical data manifest path")
        if render:
            command.add_argument("output_pos", nargs="?", help="Directory for rendered PDF/PNG output")
        command.add_argument(
            "--input",
            "--source",
            "--input-path",
            "--source-path",
            dest="source_path",
            default=None,
            help="Office input/source path (can replace the first positional path)",
        )
        command.add_argument(
            "--manifest",
            "--manifest-path",
            dest="manifest_path",
            default=None,
            help="Canonical data manifest path (can replace the second positional path)",
        )
        command.add_argument(
            "--output-dir",
            "--output",
            "--out-dir",
            dest="output_dir_path",
            default=None,
            help="Directory for rendered PDF/PNG output",
        )
        command.add_argument(
            "--backend",
            choices=("auto", "microsoft", "libreoffice"),
            default="auto",
            help="Renderer backend (render defaults to auto)",
        )
        command.add_argument(
            "--timeout",
            type=_office_positive_float,
            default=120.0,
            help="Renderer process timeout in seconds",
        )
        command.add_argument(
            "--dpi",
            type=_office_positive_int,
            default=144,
            help="PNG preview resolution",
        )
        command.add_argument(
            "--report",
            "--report-path",
            dest="report_path",
            default=None,
            help="Optional path for the JSON report",
        )

    office_validate = office_sub.add_parser("validate", help="Validate manifest and source data without rendering")
    _add_office_arguments(office_validate, render=False)
    office_validate.set_defaults(func=cmd_office_validate)

    office_render = office_sub.add_parser("render", help="Validate then render Office/PDF previews")
    _add_office_arguments(office_render, render=True)
    office_render.set_defaults(func=cmd_office_render)


def register_artifact(sub: argparse._SubParsersAction) -> None:
    from .resources import cmd_artifact_delete, cmd_artifact_list, cmd_artifact_open, cmd_artifact_preview, cmd_artifact_restore, cmd_artifact_show
    artifact = sub.add_parser("artifact", help="Manage project artifacts")
    artifact_sub = artifact.add_subparsers(dest="artifact_command", required=True)
    artifact_list = artifact_sub.add_parser("list", help="List artifacts of a project workspace")
    artifact_list.add_argument("--work-root", default="", help="Project work_root (default: current directory)")
    artifact_list.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    artifact_list.add_argument("--include-deleted", action="store_true", help="Also list soft-deleted tombstones")
    artifact_list.set_defaults(func=cmd_artifact_list)
    artifact_show = artifact_sub.add_parser("show", help="Show a single artifact record")
    artifact_show.add_argument("artifact_id")
    artifact_show.add_argument("--work-root", default="", help="Project work_root (default: current directory)")
    artifact_show.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    artifact_show.set_defaults(func=cmd_artifact_show)
    artifact_open = artifact_sub.add_parser("open", help="Open an artifact with the system default application")
    artifact_open.add_argument("artifact_id")
    artifact_open.add_argument("--work-root", default="", help="Project work_root (default: current directory)")
    artifact_open.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    artifact_open.set_defaults(func=cmd_artifact_open)
    artifact_preview = artifact_sub.add_parser("preview", help="Print an artifact as UTF-8 plain text")
    artifact_preview.add_argument("artifact_id")
    artifact_preview.add_argument("--work-root", default="", help="Project work_root (default: current directory)")
    artifact_preview.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    artifact_preview.add_argument("--max-chars", type=int, default=200000, help="Maximum text characters to print")
    artifact_preview.set_defaults(func=cmd_artifact_preview)
    artifact_delete = artifact_sub.add_parser("delete", help="Soft-remove artifacts while retaining identity")
    artifact_delete.add_argument("artifact_ids", nargs="+")
    artifact_delete.add_argument("--work-root", default="", help="Project work_root (default: current directory)")
    artifact_delete.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    artifact_delete.set_defaults(func=cmd_artifact_delete)
    artifact_restore = artifact_sub.add_parser("restore", help="Restore soft-removed artifacts")
    artifact_restore.add_argument("artifact_ids", nargs="+")
    artifact_restore.add_argument("--work-root", default="")
    artifact_restore.add_argument("--core-db", default="")
    artifact_restore.set_defaults(func=cmd_artifact_restore)
