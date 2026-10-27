"""Parse server responsibilities."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse


def register_serve(sub: argparse._SubParsersAction) -> None:
    from .server import cmd_serve
    serve = sub.add_parser("serve", help="Run the Sunday HTTP app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--allow-lan", action="store_true", default=None, help="Enable authenticated direct network access; requires LAMTOOLS_CORE_API_TOKEN")
    serve.add_argument("--ssl-certfile", default="", help="TLS certificate for direct HTTPS/WSS access")
    serve.add_argument("--ssl-keyfile", default="", help="TLS private key for direct HTTPS/WSS access")
    serve.add_argument("--port", type=int, default=5172)
    serve.add_argument("--model-id", default="")
    serve.add_argument("--core-db", default="")
    serve.add_argument("--data-dir", default="")
    serve.add_argument("--work-root", "--project", dest="work_root", default="")
    serve.add_argument("--frontend-dir", default="", help="Path to built frontend SPA directory (desktop/packaged mode)")
    serve.add_argument("--thinking", choices=("enabled", "disabled"), default="enabled")
    serve.add_argument("--reasoning-level", choices=("off", "light", "medium", "high", "xhigh", "max"), default="")
    serve.add_argument("--thinking-budget", type=int, default=10000)
    serve.add_argument("--max-tokens", type=int, default=None)
    serve.add_argument("--temperature", type=float, default=0.2)
    serve.add_argument("--raw", action="store_true")
    serve.add_argument("--reload", action="store_true", help="Enable auto-reload on code changes")
    serve.set_defaults(func=cmd_serve)


def register_setup(sub: argparse._SubParsersAction) -> None:
    from .server import cmd_setup
    setup = sub.add_parser("setup", help="Initialize the lam_projects directory for default project workspaces")
    setup.set_defaults(func=cmd_setup)


def register_migrate_projects(sub: argparse._SubParsersAction) -> None:
    from .server import cmd_migrate_projects
    migrate = sub.add_parser(
        "migrate-projects",
        help="Migrate existing project workspaces into lam_projects/",
    )
    migrate.add_argument("--core-db", default="", help="Core-owned SQLite runtime database")
    migrate.add_argument("--apply", action="store_true", help="Apply the migration (default is a dry-run preview)")
    migrate.set_defaults(func=cmd_migrate_projects)


def register_maintenance(sub: argparse._SubParsersAction) -> None:
    from .server import cmd_maintenance_checkpoint_baseline, cmd_maintenance_dialogue_records, cmd_maintenance_prune_checkpoints, cmd_maintenance_strip_snapshot_images
    maintenance = sub.add_parser(
        "maintenance",
        help="Run one-shot data maintenance on the local development database",
    )
    maintenance_sub = maintenance.add_subparsers(dest="maintenance_command", required=True)
    strip_images = maintenance_sub.add_parser(
        "strip-snapshot-images",
        help=(
            "Drop legacy inline image copies no reader observes (snapshot registry, "
            "item/event/sync payload metadata) from the local dev database only"
        ),
    )
    strip_images.add_argument(
        "--core-db",
        default="",
        help="Core-owned SQLite runtime database (defaults to the local development database)",
    )
    strip_images.add_argument(
        "--apply",
        action="store_true",
        help="Back up, migrate and verify (default is a dry-run preview)",
    )
    strip_images.set_defaults(func=cmd_maintenance_strip_snapshot_images)

    checkpoint_baseline = maintenance_sub.add_parser(
        "checkpoint-baseline",
        help=(
            "Capture (or compare) the shape and size baseline of every checkpoint; "
            "read-only, local development database only"
        ),
    )
    checkpoint_baseline.add_argument("--core-db", default="")
    checkpoint_baseline.add_argument(
        "--out", default="", help="Write the baseline JSON document to this path"
    )
    checkpoint_baseline.add_argument(
        "--compare", default="", help="Compare the current database against a baseline JSON file"
    )
    checkpoint_baseline.set_defaults(func=cmd_maintenance_checkpoint_baseline)

    prune_checkpoints = maintenance_sub.add_parser(
        "prune-checkpoints",
        help=(
            "Delete superseded checkpoints, keeping the newest per session "
            "(default is a dry-run preview; local development database only)"
        ),
    )
    prune_checkpoints.add_argument("--core-db", default="")
    prune_checkpoints.add_argument(
        "--apply", action="store_true", help="Back up, delete and verify (default is a preview)"
    )
    prune_checkpoints.add_argument(
        "--keep-recent",
        type=int,
        default=1,
        help="How many newest checkpoints to keep per session (default 1)",
    )
    prune_checkpoints.set_defaults(func=cmd_maintenance_prune_checkpoints)

    dialogue_records = maintenance_sub.add_parser(
        "dialogue-records",
        help="Verify the append-only compaction/rollback control records; read-only",
    )
    dialogue_records.add_argument("--core-db", default="")
    dialogue_records.add_argument("--thread-id", default="", help="Limit to one thread")
    dialogue_records.set_defaults(func=cmd_maintenance_dialogue_records)


def register_update(sub: argparse._SubParsersAction) -> None:
    from .server import cmd_update_check
    update = sub.add_parser("update", help="Check for a newer Sunday release (设置 → 关于与更新)")
    update_sub = update.add_subparsers(dest="update_command", required=True)
    update_check = update_sub.add_parser("check", help="Check the official site (then GitHub) for a newer version")
    update_check.add_argument("--json", action="store_true", help="Print the raw check result as JSON")
    update_check.set_defaults(func=cmd_update_check)


def register_mobile(sub: argparse._SubParsersAction) -> None:
    from .server import cmd_mobile_control
    mobile = sub.add_parser("mobile", help="Manage desktop mobile control")
    mobile_sub = mobile.add_subparsers(dest="mobile_command", required=True)
    for action in ("start", "stop", "status"):
        command = mobile_sub.add_parser(action, help=f"{action.title()} the desktop mobile-control gateway")
        command.set_defaults(func=cmd_mobile_control, mobile_action=action)
    pairing = mobile_sub.add_parser("pairing", help="Create a one-time pairing QR payload")
    pairing.set_defaults(func=cmd_mobile_control, mobile_action="pairing")
    devices = mobile_sub.add_parser("devices", help="List trusted mobile devices")
    devices.set_defaults(func=cmd_mobile_control, mobile_action="devices")
    revoke = mobile_sub.add_parser("revoke", help="Revoke a trusted mobile device")
    revoke.add_argument("device_id")
    revoke.set_defaults(func=cmd_mobile_control, mobile_action="revoke")
    account = mobile_sub.add_parser("account", help="Bind Sunday desktop to a Relay account")
    account.add_argument("--mode", choices=("login", "register"), default="login")
    account.add_argument("--base-url", required=True, help="Relay server base URL")
    account.add_argument("--username", required=True)
    account.add_argument("--password", required=True)
    account.set_defaults(func=cmd_mobile_control, mobile_action="account")
