"""Parse workspace responsibilities."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
import os
from lamtools_core.app.project_visuals import PROJECT_COLOR_KEYS, PROJECT_ICON_KEYS


def register_session(sub: argparse._SubParsersAction) -> None:
    from .connection import _add_live_connection_arguments
    from .sessions import cmd_session_checkpoints, cmd_session_export, cmd_session_fork, cmd_session_list, cmd_session_outline, cmd_session_permissions, cmd_session_rollback, cmd_session_show
    session = sub.add_parser("session", help="Query Sunday sessions")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    session_list = session_sub.add_parser("list", help="List Sunday sessions")
    session_list.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    session_list.add_argument("--raw", action="store_true")
    session_list.set_defaults(func=cmd_session_list)
    session_ls = session_sub.add_parser("ls", help="List Sunday sessions")
    session_ls.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    session_ls.add_argument("--raw", action="store_true")
    session_ls.set_defaults(session_command="list", func=cmd_session_list)
    session_show = session_sub.add_parser("show", help="Show a Sunday session")
    session_show.add_argument("thread_id")
    session_show.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    session_show.add_argument("--raw", action="store_true")
    session_show.set_defaults(func=cmd_session_show)
    session_outline = session_sub.add_parser(
        "outline", help="Show a compact conversation outline"
    )
    session_outline.add_argument("thread_id")
    _add_live_connection_arguments(session_outline)
    session_outline.add_argument("--raw", action="store_true")
    session_outline.set_defaults(func=cmd_session_outline)
    session_export = session_sub.add_parser("export", help="Export a Sunday session")
    session_export.add_argument("thread_id")
    session_export.add_argument(
        "--mode",
        choices=("transcript", "handoff", "full"),
        default="",
        help="Export tier: transcript, handoff, or full",
    )
    session_export.add_argument(
        "--format",
        choices=("markdown", "md", "txt", "jsonl", "json", "zip"),
        default="",
        help="Transcript format; handoff and full choose JSON/ZIP automatically",
    )
    session_export.add_argument("--output", default="", help="Destination file; omit for text stdout")
    session_export.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    session_export.set_defaults(func=cmd_session_export)
    session_checkpoints = session_sub.add_parser("checkpoints", help="List session rollback checkpoints")
    session_checkpoints.add_argument("thread_id")
    _add_live_connection_arguments(session_checkpoints)
    session_checkpoints.add_argument("--raw", action="store_true")
    session_checkpoints.set_defaults(func=cmd_session_checkpoints)
    session_rollback = session_sub.add_parser("rollback", help="Rollback to a turn, or restore a checkpoint")
    session_rollback.add_argument("thread_id")
    session_rollback.add_argument("checkpoint_id", nargs="?", default="", help="Legacy checkpoint id")
    session_rollback.add_argument(
        "--turn-id",
        default="",
        help="Clear this turn and later conversation; restore files when a boundary checkpoint exists",
    )
    _add_live_connection_arguments(session_rollback)
    session_rollback.add_argument("--raw", action="store_true")
    session_rollback.set_defaults(func=cmd_session_rollback)
    session_fork = session_sub.add_parser("fork", help="Fork at a turn, or from a checkpoint")
    session_fork.add_argument("thread_id")
    session_fork.add_argument("checkpoint_id", nargs="?", default="", help="Legacy checkpoint id")
    session_fork.add_argument(
        "--turn-id",
        default="",
        help="Fork the history through this turn (this message and earlier only)",
    )
    _add_live_connection_arguments(session_fork)
    session_fork.add_argument("--raw", action="store_true")
    session_fork.set_defaults(func=cmd_session_fork)
    session_permissions = session_sub.add_parser(
        "permissions", help="Set the live permission state for a session"
    )
    session_permissions.add_argument("thread_id")
    session_permissions.add_argument(
        "--approval",
        required=True,
        choices=("ask", "auto", "full_access"),
        help="Live session approval state",
    )
    _add_live_connection_arguments(session_permissions)
    session_permissions.add_argument("--raw", action="store_true")
    session_permissions.set_defaults(func=cmd_session_permissions)


def register_project(sub: argparse._SubParsersAction) -> None:
    from .library import cmd_project_agents_get, cmd_project_agents_set, cmd_project_create, cmd_project_delete, cmd_project_list, cmd_project_rename, cmd_project_show, cmd_project_update
    project = sub.add_parser("project", help="Manage Core project workspaces")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_list = project_sub.add_parser("list", help="List project workspaces")
    project_list.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    project_list.set_defaults(func=cmd_project_list)
    project_create = project_sub.add_parser("create", help="Create or reuse a project workspace")
    project_create.add_argument("work_root")
    project_create.add_argument("--name", default=None)
    project_create.add_argument("--icon", "--icon-key", dest="icon_key", choices=PROJECT_ICON_KEYS, default="folder")
    project_create.add_argument("--color", "--color-key", dest="color_key", choices=PROJECT_COLOR_KEYS, default="gray")
    project_create.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    project_create.set_defaults(func=cmd_project_create)
    project_show = project_sub.add_parser("show", help="Show a project workspace")
    project_show.add_argument("project_id")
    project_show.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    project_show.set_defaults(func=cmd_project_show)
    project_rename = project_sub.add_parser("rename", help="Rename a project workspace")
    project_rename.add_argument("project_id")
    project_rename.add_argument("name")
    project_rename.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    project_rename.set_defaults(func=cmd_project_rename)
    project_update = project_sub.add_parser("update", help="Update project name, icon, or color")
    project_update.add_argument("project_id")
    project_update.add_argument("--name", default=None)
    project_update.add_argument("--icon", "--icon-key", dest="icon_key", choices=PROJECT_ICON_KEYS, default=None)
    project_update.add_argument("--color", "--color-key", dest="color_key", choices=PROJECT_COLOR_KEYS, default=None)
    project_update.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    project_update.set_defaults(func=cmd_project_update)
    project_delete = project_sub.add_parser("delete", help="Delete a project record")
    project_delete.add_argument("project_id")
    project_delete.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    project_delete.set_defaults(func=cmd_project_delete)
    project_agents = project_sub.add_parser("agents", help="Manage project AGENTS.md")
    project_agents_sub = project_agents.add_subparsers(dest="project_agents_command", required=True)
    project_agents_get = project_agents_sub.add_parser("get", help="Read project AGENTS.md")
    project_agents_get.add_argument("project_id")
    project_agents_get.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    project_agents_get.set_defaults(func=cmd_project_agents_get)
    project_agents_set = project_agents_sub.add_parser("set", help="Set project AGENTS.md from a UTF-8 file")
    project_agents_set.add_argument("project_id")
    project_agents_set.add_argument("source_file")
    project_agents_set.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    project_agents_set.set_defaults(func=cmd_project_agents_set)


def register_goal(sub: argparse._SubParsersAction) -> None:
    from .library import cmd_goal_create, cmd_goal_list, cmd_goal_show, cmd_goal_update
    goal = sub.add_parser("goal", help="Manage durable goals")
    goal_sub = goal.add_subparsers(dest="goal_command", required=True)
    goal_create = goal_sub.add_parser("new", help="Create a new goal")
    goal_create.add_argument("thread_id", help="Thread ID")
    goal_create.add_argument("objective", nargs="+", help="Goal objective text")
    goal_create.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    goal_create.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    goal_create.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    goal_create.set_defaults(func=cmd_goal_create, raw=False)
    goal_list = goal_sub.add_parser("ls", help="List goals")
    goal_list.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    goal_list.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    goal_list.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    goal_list.set_defaults(func=cmd_goal_list, thread_id="", raw=False)
    goal_show = goal_sub.add_parser("describe", help="Show a goal")
    goal_show.add_argument("goal_id", help="Goal ID")
    goal_show.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    goal_show.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    goal_show.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    goal_show.set_defaults(func=cmd_goal_show, thread_id="", raw=False)
    goal_update = goal_sub.add_parser("set", help="Set goal status")
    goal_update.add_argument("goal_id", help="Goal ID")
    goal_update.add_argument("--status", default="", help="New status: active/blocked/archived")
    goal_update.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    goal_update.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    goal_update.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    goal_update.set_defaults(func=cmd_goal_update, thread_id="", raw=False)


def register_plan_library(sub: argparse._SubParsersAction) -> None:
    from .library import cmd_plan_library_create, cmd_plan_library_delete, cmd_plan_library_favorite, cmd_plan_library_folder, cmd_plan_library_list, cmd_plan_library_move, cmd_plan_library_rename, cmd_plan_library_show
    plan_library = sub.add_parser("plan-library", help="Manage the plan library (方案/ folder)")
    plan_library_sub = plan_library.add_subparsers(dest="plan_library_command", required=True)
    plan_library_list = plan_library_sub.add_parser("list", help="List the plans in a project's 方案/ folder")
    plan_library_list.add_argument("--work-root", required=True, help="Project work root (the folder holding 方案/)")
    plan_library_list.set_defaults(func=cmd_plan_library_list, raw=False)
    plan_library_show = plan_library_sub.add_parser("show", help="Print one plan document")
    plan_library_show.add_argument("name", help="Plan inside 方案/ (e.g. 导出显示进度.md or 归档/导出显示进度.md)")
    plan_library_show.add_argument("--work-root", required=True, help="Project work root")
    plan_library_show.set_defaults(func=cmd_plan_library_show, raw=False)
    plan_library_delete = plan_library_sub.add_parser("delete", help="Delete one plan document")
    plan_library_delete.add_argument("name", help="Plan inside 方案/ (e.g. 导出显示进度.md or 归档/导出显示进度.md)")
    plan_library_delete.add_argument("--work-root", required=True, help="Project work root")
    plan_library_delete.set_defaults(func=cmd_plan_library_delete, raw=False)
    plan_library_create = plan_library_sub.add_parser("create", help="Create a new skeleton plan document")
    plan_library_create.add_argument("name", help="New plan name (e.g. 新方案 or 新方案.md)")
    plan_library_create.add_argument("--work-root", required=True, help="Project work root")
    plan_library_create.add_argument("--folder", default="", help="Target folder inside 方案/, nested paths allowed (optional)")
    plan_library_create.set_defaults(func=cmd_plan_library_create, raw=False)
    plan_library_folder = plan_library_sub.add_parser("folder", help="Create an empty folder inside 方案/")
    plan_library_folder.add_argument("path", help="New folder path inside 方案/ (e.g. 归档 or 归档/这一期)")
    plan_library_folder.add_argument("--work-root", required=True, help="Project work root")
    plan_library_folder.set_defaults(func=cmd_plan_library_folder, raw=False)
    plan_library_rename = plan_library_sub.add_parser("rename", help="Rename one plan document in place")
    plan_library_rename.add_argument("path", help="Plan path inside the project (e.g. 方案/旧名.md)")
    plan_library_rename.add_argument("new_name", help="New plan name")
    plan_library_rename.add_argument("--work-root", required=True, help="Project work root")
    plan_library_rename.set_defaults(func=cmd_plan_library_rename, raw=False)
    plan_library_move = plan_library_sub.add_parser("move", help="Move one plan to the library root or a folder")
    plan_library_move.add_argument("path", help="Plan path inside the project (e.g. 方案/方案.md)")
    plan_library_move.add_argument("--folder", default="", help="Target folder inside 方案/, nested paths allowed (empty = root)")
    plan_library_move.add_argument("--work-root", required=True, help="Project work root")
    plan_library_move.set_defaults(func=cmd_plan_library_move, raw=False)
    plan_library_favorite = plan_library_sub.add_parser("favorite", help="Star (or unstar) one plan")
    plan_library_favorite.add_argument("path", help="Plan path inside the project (e.g. 方案/方案.md)")
    plan_library_favorite.add_argument("--off", action="store_true", help="Remove the star instead of adding it")
    plan_library_favorite.add_argument("--work-root", required=True, help="Project work root")
    plan_library_favorite.set_defaults(func=cmd_plan_library_favorite, raw=False)


def register_arrange(sub: argparse._SubParsersAction) -> None:
    from .agents import cmd_arrange_create, cmd_arrange_edit, cmd_arrange_list, cmd_arrange_show, cmd_arrange_update
    arrange = sub.add_parser("arrange", help="Manage durable arrangements")
    arrange_sub = arrange.add_subparsers(dest="arrange_command", required=True)
    arrange_create = arrange_sub.add_parser("new", help="Create a new arrangement")
    arrange_create.add_argument("message", nargs="+", help="Arrangement instruction text")
    arrange_create.add_argument("--work-root", required=True, default="", help="Project work root absolute path (required)")
    arrange_create.add_argument("--thread-id", default="", help="Target thread ID (uses source thread if omitted)")
    arrange_create.add_argument("--title", default="", help="Card title (defaults to first 40 chars of message)")
    arrange_create.add_argument("--session-strategy", choices=["fixed", "new"], default="new", help="Session strategy: fixed or new (default: new)")
    arrange_create.add_argument("--kind", choices=["routine", "focus"], default="routine", help="Arrangement kind (default: routine)")
    arrange_create.add_argument("--trigger-once", default="", help="One-time run at local datetime (e.g. 2026-12-31T08:00)")
    arrange_create.add_argument("--trigger-daily", default="", help="Daily at wall-clock time HH:MM (e.g. 09:00)")
    arrange_create.add_argument("--trigger-monthly", default="", help="Monthly at DAY:HH:MM (e.g. 5:09:00)")
    arrange_create.add_argument("--trigger-event", default="", help="Event-triggered by event type name")
    arrange_create.add_argument("--timezone", default="Asia/Shanghai", help="Timezone for calendar triggers")
    arrange_create.add_argument("--model-id", default="", help="Default model for new sessions (strategy=new)")
    arrange_create.add_argument("--max-runs", type=int, default=None, help="Maximum run count")
    arrange_create.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    arrange_create.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    arrange_create.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    arrange_create.set_defaults(func=cmd_arrange_create, raw=False)
    arrange_list = arrange_sub.add_parser("ls", help="List arrangements")
    arrange_list.add_argument("--work-root", default="", help="Filter by project work_root")
    arrange_list.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    arrange_list.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    arrange_list.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    arrange_list.set_defaults(func=cmd_arrange_list, thread_id="", raw=False)
    arrange_show = arrange_sub.add_parser("describe", help="Show an arrangement")
    arrange_show.add_argument("job_id", help="Job ID")
    arrange_show.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    arrange_show.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    arrange_show.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    arrange_show.set_defaults(func=cmd_arrange_show, thread_id="", raw=False)
    arrange_update = arrange_sub.add_parser("set", help="Set arrangement status")
    arrange_update.add_argument("job_id", help="Job ID")
    arrange_update.add_argument("--status", default="", help="New status: scheduled/paused/cancelled")
    arrange_update.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    arrange_update.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    arrange_update.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    arrange_update.set_defaults(func=cmd_arrange_update, thread_id="", raw=False)
    arrange_edit = arrange_sub.add_parser("edit", help="Edit arrangement fields")
    arrange_edit.add_argument("job_id", help="Job ID")
    arrange_edit.add_argument("--title", default="", help="New title")
    arrange_edit.add_argument("--instruction", default="", help="New instruction text")
    arrange_edit.add_argument("--session-strategy", choices=["fixed", "new"], default="", help="Session strategy")
    arrange_edit.add_argument("--model-id", default="", help="Default model for new sessions")
    arrange_edit.add_argument("--trigger-once", default="", help="New one-time trigger")
    arrange_edit.add_argument("--trigger-daily", default="", help="New daily trigger HH:MM")
    arrange_edit.add_argument("--trigger-monthly", default="", help="New monthly trigger DAY:HH:MM")
    arrange_edit.add_argument("--trigger-event", default="", help="New event type")
    arrange_edit.add_argument("--timezone", default="Asia/Shanghai", help="Timezone for calendar triggers")
    arrange_edit.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    arrange_edit.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    arrange_edit.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    arrange_edit.set_defaults(func=cmd_arrange_edit, raw=False)


def register_subagent(sub: argparse._SubParsersAction) -> None:
    from .agents import cmd_subagent_guide_edit, cmd_subagent_guide_set, cmd_subagent_guide_show, cmd_subagent_lifecycle, cmd_subagent_roles_delete, cmd_subagent_roles_set, cmd_subagent_roles_show, cmd_subagent_strategy_set, cmd_subagent_strategy_show, cmd_subagent_strategy_unset
    from .connection import _add_live_connection_arguments
    subagent = sub.add_parser("subagent", help="Manage sub-agent delegation guide")
    subagent_sub = subagent.add_subparsers(dest="subagent_command", required=True)
    for command in ("list", "create", "close", "delete", "message", "interrupt", "pause", "resume"):
        lifecycle = subagent_sub.add_parser(command, help=f"{command.title()} session sub-agents")
        lifecycle.add_argument("thread_id")
        if command not in {"list", "interrupt", "pause", "resume"}:
            lifecycle.add_argument("--type", choices=("consider", "execute"), required=True)
            lifecycle.add_argument("--name", required=True)
        if command in {"create", "close"}:
            lifecycle.add_argument("--model", required=True)
            lifecycle.add_argument(
                "--reasoning-level",
                choices=("off", "light", "medium", "Medium", "high", "xhigh", "max", "xh"),
                required=True,
            )
        if command == "message":
            lifecycle.add_argument("prompt")
        lifecycle.add_argument("--raw", action="store_true")
        _add_live_connection_arguments(lifecycle)
        lifecycle.set_defaults(func=cmd_subagent_lifecycle)
    sa_guide = subagent_sub.add_parser("guide", help="Show or edit the sub-agent delegation guide")
    sa_guide_sub = sa_guide.add_subparsers(dest="subagent_guide_command", required=True)
    sa_guide_show = sa_guide_sub.add_parser("show", help="Print the effective sub-agent guide")
    sa_guide_show.add_argument("--work-root", default="", help="Project work root")
    sa_guide_show.add_argument("--scope", choices=("project", "global"), default="", help="Show only a specific scope")
    sa_guide_show.set_defaults(func=cmd_subagent_guide_show)
    sa_guide_set = sa_guide_sub.add_parser("set", help="Write the guide from a UTF-8 file or stdin")
    sa_guide_set.add_argument("source_file", help="Path to a markdown file, or '-' for stdin")
    sa_guide_set.add_argument("--scope", choices=("project", "global"), default="global", help="Write scope")
    sa_guide_set.add_argument("--work-root", default="", help="Project work root (required for --scope project)")
    sa_guide_set.set_defaults(func=cmd_subagent_guide_set)
    sa_guide_edit = sa_guide_sub.add_parser("edit", help="Open the guide in $EDITOR")
    sa_guide_edit.add_argument("--scope", choices=("project", "global"), default="global", help="Edit scope")
    sa_guide_edit.add_argument("--work-root", default="", help="Project work root (required for --scope project)")
    sa_guide_edit.set_defaults(func=cmd_subagent_guide_edit)
    sa_roles = subagent_sub.add_parser("roles", help="Manage sub-agent role assignments")
    sa_roles_sub = sa_roles.add_subparsers(dest="subagent_roles_command", required=True)
    sa_roles_show = sa_roles_sub.add_parser("show", help="Show role assignments")
    sa_roles_show.add_argument(
        "--scope",
        choices=("global", "project", "effective"),
        default="effective",
    )
    sa_roles_show.add_argument("--work-root", default="", help="Project work root")
    sa_roles_show.set_defaults(func=cmd_subagent_roles_show)
    sa_roles_set = sa_roles_sub.add_parser("set", help="Add or replace one role assignment")
    sa_roles_set.add_argument("task_type", help="Task type matched case-insensitively")
    sa_roles_set.add_argument("--type", choices=("consider", "execute"), required=True)
    sa_roles_set.add_argument("--model", required=True, help="Exact configured model_id")
    sa_roles_set.add_argument(
        "--reasoning-min",
        choices=("off", "light", "medium", "high", "xhigh", "max", "xh"),
        required=True,
    )
    sa_roles_set.add_argument(
        "--reasoning-max",
        choices=("off", "light", "medium", "high", "xhigh", "max", "xh"),
        required=True,
    )
    sa_roles_set.add_argument("--scope", choices=("global", "project"), default="global")
    sa_roles_set.add_argument("--work-root", default="", help="Project work root")
    sa_roles_set.set_defaults(func=cmd_subagent_roles_set)
    sa_roles_delete = sa_roles_sub.add_parser("delete", help="Delete one local role assignment")
    sa_roles_delete.add_argument("task_type", help="Task type matched case-insensitively")
    sa_roles_delete.add_argument("--scope", choices=("global", "project"), default="global")
    sa_roles_delete.add_argument("--work-root", default="", help="Project work root")
    sa_roles_delete.set_defaults(func=cmd_subagent_roles_delete)
    sa_strategy = subagent_sub.add_parser("strategy", help="Manage the sub-agent delegation strategy")
    sa_strategy_sub = sa_strategy.add_subparsers(dest="subagent_strategy_command", required=True)
    sa_strategy_show = sa_strategy_sub.add_parser("show", help="Show the delegation strategy")
    sa_strategy_show.add_argument(
        "--scope",
        choices=("global", "project", "effective"),
        default="effective",
    )
    sa_strategy_show.add_argument("--work-root", default="", help="Project work root")
    sa_strategy_show.set_defaults(func=cmd_subagent_strategy_show)
    sa_strategy_set = sa_strategy_sub.add_parser("set", help="Set a local delegation strategy")
    sa_strategy_set.add_argument(
        "strategy", choices=("forbidden", "low", "medium", "high")
    )
    sa_strategy_set.add_argument("--scope", choices=("global", "project"), default="global")
    sa_strategy_set.add_argument("--work-root", default="", help="Project work root")
    sa_strategy_set.set_defaults(func=cmd_subagent_strategy_set)
    sa_strategy_unset = sa_strategy_sub.add_parser("unset", help="Remove a local strategy and inherit")
    sa_strategy_unset.add_argument("--scope", choices=("global", "project"), default="project")
    sa_strategy_unset.add_argument("--work-root", default="", help="Project work root")
    sa_strategy_unset.set_defaults(func=cmd_subagent_strategy_unset)
