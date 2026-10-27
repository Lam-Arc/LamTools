"""Parse turns responsibilities."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
import os


def register_run(sub: argparse._SubParsersAction) -> None:
    from .connection import _add_live_connection_arguments, _positive_timeout_or_none
    from .task import cmd_run
    run = sub.add_parser("run", help="Start a Sunday task")
    run.add_argument("message", nargs="+")
    run.add_argument("--model-id", default="", help="Model record id, provider model id, or display name")
    run.add_argument("--thread-id", default="", help="Stable Core thread/session id")
    run.add_argument("--goal-id", default="", help="Durable Goal ID to verify on completion")
    run.add_argument("--work-root", "--project", dest="work_root", default="")
    run.add_argument("--thinking-budget", type=int, default=10000)
    run.add_argument("--no-thinking", action="store_true")
    run.add_argument("--reasoning-level", choices=("off", "light", "medium", "high", "xhigh", "max"), default=None)
    run.add_argument("--shallow-thinking", action="store_true", help="Require a prompt-based shallow thinking block")
    run.add_argument("--auto-approve", action="store_true", help="Run approval-gated Core tools without prompting")
    run.add_argument("--allow-outside-workdir", action="store_true", default=None, help="Allow file tools to access paths outside work_root")
    run.add_argument("--permission-preset", choices=("ask", "auto", "full_access"), default=None)
    run.add_argument("--max-tokens", type=int, default=None)
    run.add_argument("--compact-trigger-tokens", type=int, default=None, help="Session-only automatic compaction trigger")
    run.add_argument("--compact-limit-tokens", type=int, default=None, help="Session-only post-compaction upper limit")
    run.add_argument("--temperature", type=float, default=0.2)
    run.add_argument("--raw", action="store_true")
    run.add_argument("--verbose", action="store_true")
    _add_live_connection_arguments(run)
    run.add_argument("--heartbeat-interval", type=int, default=30)
    run.add_argument("--event-timeout", type=_positive_timeout_or_none, default=None)
    run.add_argument("--max-reconnects", type=int, default=3)
    run.add_argument("--interactive-decisions", action="store_true")
    run.add_argument("--approval-decision", choices=("approve_once", "deny", "other_guidance"))
    run.set_defaults(func=cmd_run)


def register_run_local(sub: argparse._SubParsersAction) -> None:
    from .config import _default_cli_plugin_state_path, _default_work_root
    from .task import cmd_run_local
    run_local = sub.add_parser("run-local", help="Run a Sunday task directly without a server")
    run_local.add_argument("message", nargs="+")
    run_local.add_argument("--profile", default="", help="Run under a declared run profile (plugin:profile or unique short name)")
    run_local.add_argument("--tools", default="", help="Comma-separated tool whitelist; defines the run surface without a declared profile")
    run_local.add_argument("--mode", dest="profile_mode", default="", help="Use an already-declared mode's tool group as the run surface")
    run_local.add_argument("--profile-approval", choices=("auto", "ask"), default=None, help="Unattended approval semantics under the profile (default auto)")
    run_local.add_argument("--profile-budget-calls", type=int, default=None, help="Max tool calls under the profile")
    run_local.add_argument("--profile-budget-tokens", type=int, default=None, help="Max tokens under the profile")

    profile_list = sub.add_parser("profile-list", help="List declared run profiles and their tool whitelists")
    profile_list.add_argument("--work-root", default="", help="Project root for plugin discovery")

    async def cmd_profile_list(args: argparse.Namespace) -> int:
        from lamtools_core.plugin_system import PluginHost, available_profiles
        from lamtools_core.plugin_system.paths import default_plugin_roots

        work_root = args.work_root or str(_default_work_root())
        host = PluginHost(
            roots=default_plugin_roots(work_root),
            state_path=_default_cli_plugin_state_path(),
        )
        specs = available_profiles(host.discover())
        if not specs:
            print("no run profiles declared")
            return 0
        for spec in sorted(specs, key=lambda item: item.full_name):
            print(f"{spec.full_name}  [{spec.approval}]  {spec.title}")
            for name in spec.tools:
                print(f"  - {name}")
        return 0

    profile_list.set_defaults(func=cmd_profile_list)
    run_local.add_argument("--model-id", default="", help="Model record id, provider model id, or display name")
    run_local.add_argument("--thread-id", default="", help="Stable Core thread/session id")
    run_local.add_argument("--work-root", "--project", dest="work_root", default="")
    run_local.add_argument("--run-dir", default="", help="Output directory for run artifacts (summary.json etc.)")
    run_local.add_argument("--core-db", default="", help="Path to Core agent database")
    run_local.add_argument("--thinking-budget", type=int, default=10000)
    run_local.add_argument("--no-thinking", action="store_true")
    run_local.add_argument("--reasoning-level", choices=("off", "light", "medium", "high", "xhigh", "max"), default=None)
    run_local.add_argument("--shallow-thinking", action="store_true", help="Require a prompt-based shallow thinking block")
    run_local.add_argument("--auto-approve", action="store_true", help="Run approval-gated tools without prompting")
    run_local.add_argument("--allow-outside-workdir", action="store_true", default=None, help="Allow file tools to access paths outside work_root")
    run_local.add_argument("--permission-preset", choices=("ask", "auto", "full_access"), default=None)
    run_local.add_argument("--max-tokens", type=int, default=None)
    run_local.add_argument("--compact-trigger-tokens", type=int, default=None, help="Session-only automatic compaction trigger")
    run_local.add_argument("--compact-limit-tokens", type=int, default=None, help="Session-only post-compaction upper limit")
    run_local.add_argument("--temperature", type=float, default=0.2)
    run_local.add_argument("--raw", action="store_true")
    run_local.add_argument("--verbose", action="store_true")
    run_local.set_defaults(func=cmd_run_local)


def register_watch(sub: argparse._SubParsersAction) -> None:
    from .connection import _positive_timeout_or_none
    from .task import cmd_watch
    watch = sub.add_parser("watch", help="Watch a Core app-server thread")
    watch.add_argument("thread_id")
    watch.add_argument("--base-url", default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"))
    watch.add_argument("--ws-path", default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"))
    watch.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))
    watch.add_argument("--raw", action="store_true")
    watch.add_argument("--verbose", action="store_true")
    watch.add_argument("--heartbeat-interval", type=int, default=30)
    watch.add_argument("--event-timeout", type=_positive_timeout_or_none, default=None)
    watch.add_argument("--max-reconnects", type=int, default=3)
    watch.add_argument("--interactive-decisions", action="store_true")
    watch.add_argument("--approval-decision", choices=("approve_once", "deny", "other_guidance"))
    watch.set_defaults(func=cmd_watch)


def register_start(sub: argparse._SubParsersAction) -> None:
    from .connection import _add_live_connection_arguments, _positive_timeout_or_none
    from .turns import cmd_start
    start = sub.add_parser("start", help="Start a live Sunday turn")
    start.add_argument("thread_id")
    start.add_argument("message", nargs="+")
    start.add_argument("--goal-id", default="", help="Durable Goal ID")
    _add_live_connection_arguments(start)
    start.add_argument("--work-root", "--project", dest="work_root", default="")
    start.add_argument("--model-id", default="")
    start.add_argument("--thinking", choices=("enabled", "disabled"), default="enabled")
    start.add_argument("--thinking-budget", type=int, default=10000)
    start.add_argument("--reasoning-level", choices=("off", "light", "medium", "high", "xhigh", "max"), default=None)
    start.add_argument("--shallow", action="store_true")
    start.add_argument("--auto-approve", action="store_true", help="Run approval-gated Core tools without prompting")
    start.add_argument("--approval-policy", choices=("require", "auto_approve"), default=None)
    start.add_argument("--allow-outside-workdir", action="store_true", default=None, help="Allow file tools to access paths outside work_root")
    start.add_argument("--permission-preset", choices=("ask", "auto", "full_access"), default=None)
    start.add_argument("--client-message-id", default="")
    start.add_argument("--watch", action="store_true")
    start.add_argument("--raw", action="store_true")
    start.add_argument("--verbose", action="store_true")
    start.add_argument("--heartbeat-interval", type=int, default=30)
    start.add_argument("--event-timeout", type=_positive_timeout_or_none, default=None)
    start.add_argument("--max-reconnects", type=int, default=3)
    start.add_argument("--interactive-decisions", action="store_true")
    start.add_argument("--approval-decision", choices=("approve_once", "deny", "other_guidance"))
    start.set_defaults(func=cmd_start)


def register_resume(sub: argparse._SubParsersAction) -> None:
    from .connection import _add_live_connection_arguments
    from .turns import cmd_resume_turn
    resume_turn = sub.add_parser("resume", help="Continue the latest paused turn without a new user message")
    resume_turn.add_argument("thread_id")
    resume_turn.add_argument("--turn-id", default="")
    _add_live_connection_arguments(resume_turn)
    resume_turn.add_argument("--raw", action="store_true")
    resume_turn.set_defaults(func=cmd_resume_turn)


def register_pause(sub: argparse._SubParsersAction) -> None:
    from .connection import _add_live_connection_arguments
    from .turns import cmd_pause_turn
    pause = sub.add_parser("pause", help="Pause a live Sunday turn (resumable)")
    pause.add_argument("thread_id")
    pause.add_argument("--turn-id", default="")
    _add_live_connection_arguments(pause)
    pause.add_argument("--raw", action="store_true")
    pause.set_defaults(func=cmd_pause_turn)


def register_terminate(sub: argparse._SubParsersAction) -> None:
    from .connection import _add_live_connection_arguments
    from .turns import cmd_terminate_turn
    terminate = sub.add_parser("terminate", help="Terminate a live Sunday turn for good")
    terminate.add_argument("thread_id")
    terminate.add_argument("--turn-id", default="")
    _add_live_connection_arguments(terminate)
    terminate.add_argument("--raw", action="store_true")
    terminate.set_defaults(func=cmd_terminate_turn)


def register_cancel(sub: argparse._SubParsersAction) -> None:
    from .connection import _add_live_connection_arguments
    from .turns import cmd_cancel
    cancel = sub.add_parser("cancel", help="Cancel a live Sunday turn")
    cancel.add_argument("thread_id")
    cancel.add_argument("--turn-id", default="")
    _add_live_connection_arguments(cancel)
    cancel.add_argument("--raw", action="store_true")
    cancel.set_defaults(func=cmd_cancel)


def register_steer(sub: argparse._SubParsersAction) -> None:
    from .connection import _add_live_connection_arguments
    from .turns import cmd_steer
    steer = sub.add_parser("steer", help="Steer a live Sunday turn")
    steer.add_argument("thread_id")
    steer.add_argument("turn_id")
    steer.add_argument("message", nargs="+")
    _add_live_connection_arguments(steer)
    steer.add_argument("--raw", action="store_true")
    steer.set_defaults(func=cmd_steer)


def register_queue(sub: argparse._SubParsersAction) -> None:
    from .connection import _add_live_connection_arguments
    from .turns import cmd_queue_create, cmd_queue_delete, cmd_queue_guide, cmd_queue_update
    queue = sub.add_parser("queue", help="Manage live Sunday queued input")
    queue_sub = queue.add_subparsers(dest="queue_command", required=True)
    queue_create = queue_sub.add_parser("create", help="Queue input for the next turn")
    queue_create.add_argument("thread_id")
    queue_create.add_argument("message", nargs="+")
    _add_live_connection_arguments(queue_create)
    queue_create.add_argument("--auto-approve", action="store_true", help="Run approval-gated tools without prompting")
    queue_create.add_argument("--approval-policy", choices=("require", "auto_approve"), default=None)
    queue_create.add_argument("--allow-outside-workdir", action="store_true", default=None, help="Allow file tools to access paths outside work_root")
    queue_create.add_argument("--permission-preset", choices=("ask", "auto", "full_access"), default=None)
    queue_create.add_argument("--raw", action="store_true")
    queue_create.set_defaults(func=cmd_queue_create)
    queue_update = queue_sub.add_parser("update", help="Update queued input")
    queue_update.add_argument("thread_id")
    queue_update.add_argument("queue_item_id")
    queue_update.add_argument("message", nargs="+")
    _add_live_connection_arguments(queue_update)
    queue_update.add_argument("--raw", action="store_true")
    queue_update.set_defaults(func=cmd_queue_update)
    queue_delete = queue_sub.add_parser("delete", help="Delete queued input")
    queue_delete.add_argument("thread_id")
    queue_delete.add_argument("queue_item_id")
    _add_live_connection_arguments(queue_delete)
    queue_delete.add_argument("--raw", action="store_true")
    queue_delete.set_defaults(func=cmd_queue_delete)
    queue_guide = queue_sub.add_parser("guide", help="Use queued input to steer the active turn")
    queue_guide.add_argument("thread_id")
    queue_guide.add_argument("turn_id")
    queue_guide.add_argument("queue_item_id")
    queue_guide.add_argument("message", nargs="*")
    _add_live_connection_arguments(queue_guide)
    queue_guide.add_argument("--raw", action="store_true")
    queue_guide.set_defaults(func=cmd_queue_guide)


def register_process(sub: argparse._SubParsersAction) -> None:
    from .connection import _add_live_connection_arguments
    from .turns import cmd_process_forget, cmd_process_kill, cmd_process_list, cmd_process_logs
    process = sub.add_parser("process", help="Manage long-lived background processes of a session")
    process_sub = process.add_subparsers(dest="process_command", required=True)
    process_list = process_sub.add_parser("list", help="List background processes registered for a session")
    process_list.add_argument("session_id")
    process_list.add_argument("--raw", action="store_true")
    _add_live_connection_arguments(process_list)
    process_list.set_defaults(func=cmd_process_list)
    process_kill = process_sub.add_parser("kill", help="Terminate a registered background process")
    process_kill.add_argument("session_id")
    process_kill.add_argument("--pid", type=int, required=True)
    process_kill.add_argument("--raw", action="store_true")
    _add_live_connection_arguments(process_kill)
    process_kill.set_defaults(func=cmd_process_kill)
    process_forget = process_sub.add_parser("forget", help="Remove a finished/lost process record")
    process_forget.add_argument("session_id")
    process_forget.add_argument("--pid", type=int, required=True)
    process_forget.add_argument("--raw", action="store_true")
    _add_live_connection_arguments(process_forget)
    process_forget.set_defaults(func=cmd_process_forget)
    process_logs = process_sub.add_parser("logs", help="Print recent output of a registered process")
    process_logs.add_argument("session_id")
    process_logs.add_argument("--pid", type=int, required=True)
    process_logs.add_argument("--stream", choices=("stdout", "stderr"), default="stdout")
    process_logs.add_argument("--max-bytes", type=int, default=8192)
    process_logs.add_argument("--raw", action="store_true")
    _add_live_connection_arguments(process_logs)
    process_logs.set_defaults(func=cmd_process_logs)


def register_approval(sub: argparse._SubParsersAction) -> None:
    from .connection import _add_live_connection_arguments
    from .turns import cmd_approval_respond
    approval = sub.add_parser("approval", help="Respond to a live Sunday approval")
    approval_sub = approval.add_subparsers(dest="approval_command", required=True)
    approval_respond = approval_sub.add_parser("respond", help="Respond to a pending Core approval")
    approval_respond.add_argument("thread_id")
    approval_respond.add_argument("action", choices=("approve", "deny", "guide"))
    approval_respond.add_argument("response", nargs="*")
    _add_live_connection_arguments(approval_respond)
    approval_respond.add_argument("--raw", action="store_true")
    approval_respond.set_defaults(func=cmd_approval_respond)
