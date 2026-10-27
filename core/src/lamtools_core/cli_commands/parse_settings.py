"""Parse settings responsibilities."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
from lamtools_core.context_compaction_budget import DEFAULT_RETAINED_STEPS, MAX_RETAINED_STEPS


def register_imagegen(sub: argparse._SubParsersAction) -> None:
    from .settings import cmd_imagegen_config, cmd_imagegen_show
    imagegen = sub.add_parser("imagegen", help="Manage the generate_image tool configuration (设置 → 生图)")
    imagegen_sub = imagegen.add_subparsers(dest="imagegen_command", required=True)
    imagegen_show = imagegen_sub.add_parser("show", help="Show the current image generation configuration")
    imagegen_show.set_defaults(func=cmd_imagegen_show)
    imagegen_config = imagegen_sub.add_parser("config", help="Update the image generation configuration")
    imagegen_config.add_argument(
        "--enabled", choices=["true", "false"], default=None,
        help="Enable or disable the generate_image tool (disabled tools are hidden from the model)",
    )
    imagegen_config.add_argument("--api-url", default=None, help="Image generation API base URL")
    imagegen_config.add_argument("--api-key", default=None, help="API key (stored in plaintext in imagegen.jsonc)")
    imagegen_config.add_argument("--model", default=None, help="Image model id")
    imagegen_config.set_defaults(func=cmd_imagegen_config)


def register_models(sub: argparse._SubParsersAction) -> None:
    from .settings import cmd_model_group_members_set, cmd_model_groups_create, cmd_model_groups_delete, cmd_model_groups_list, cmd_model_groups_rename, cmd_model_groups_reorder, cmd_models_create, cmd_models_default, cmd_models_list, cmd_models_set, cmd_models_show
    models = sub.add_parser("models", help="Manage model definitions (jsonc-backed)")
    models_sub = models.add_subparsers(dest="models_command", required=True)
    models_list = models_sub.add_parser("list", help="List configured models")
    models_list.add_argument("--work-root", default="")
    models_list.set_defaults(func=cmd_models_list)
    models_show = models_sub.add_parser("show", help="Show a model definition")
    models_show.add_argument("model_id")
    models_show.add_argument("--work-root", default="")
    models_show.set_defaults(func=cmd_models_show)
    models_create = models_sub.add_parser("create", help="Create a model and visible provider, optionally in a group")
    models_create.add_argument("--group", required=True, dest="group_id")
    models_create.add_argument("--model-id", required=True)
    models_create.add_argument("--display-name", default="")
    models_create.add_argument("--base-url", required=True, help="API base URL (not /chat/completions)")
    models_create.add_argument("--provider-id", default="")
    models_create.add_argument("--provider-name", default="")
    models_create.add_argument("--api-type", default="openai")
    models_create.add_argument("--api-key", default="", help="Prefer LAMTOOLS_LLM_API_KEY to avoid shell history")
    models_create.add_argument("--adapter-profile-id", default="")
    models_create.add_argument("--context-window", type=int, default=0)
    models_create.add_argument("--max-output-tokens", type=int, default=4096)
    models_create.add_argument("--temperature", type=float, default=0.2)
    models_create.add_argument("--thinking-supported", action="store_true")
    models_create.add_argument("--thinking-budget", type=int, default=10000)
    models_create.set_defaults(func=cmd_models_create)
    models_set = models_sub.add_parser("set", help="Update a model field (e.g. capability)")
    models_set.add_argument("model_id")
    models_set.add_argument("--field", required=True, help="Field to set: capability|is_default|adapter_profile_id|context_window|max_output_tokens|temperature")
    models_set.add_argument("--value", required=True)
    models_set.add_argument("--scope", choices=("project", "global"), default="global")
    models_set.add_argument("--work-root", default="")
    models_set.set_defaults(func=cmd_models_set)
    models_default = models_sub.add_parser("default", help="Set the default model")
    models_default.add_argument("model_id")
    models_default.add_argument("--scope", choices=("project", "global"), default="global")
    models_default.add_argument("--work-root", default="")
    models_default.set_defaults(func=cmd_models_default)
    model_groups = models_sub.add_parser("groups", help="Manage user-defined model groups")
    model_groups_sub = model_groups.add_subparsers(dest="model_groups_command", required=True)
    groups_list = model_groups_sub.add_parser("list")
    groups_list.set_defaults(func=cmd_model_groups_list)
    groups_create = model_groups_sub.add_parser("create")
    groups_create.add_argument("name")
    groups_create.add_argument("--model", action="append", default=[])
    groups_create.set_defaults(func=cmd_model_groups_create)
    groups_rename = model_groups_sub.add_parser("rename")
    groups_rename.add_argument("group_id")
    groups_rename.add_argument("name")
    groups_rename.set_defaults(func=cmd_model_groups_rename)
    groups_delete = model_groups_sub.add_parser("delete")
    groups_delete.add_argument("group_id")
    groups_delete.set_defaults(func=cmd_model_groups_delete)
    groups_reorder = model_groups_sub.add_parser("reorder")
    groups_reorder.add_argument("group_ids", nargs="+")
    groups_reorder.set_defaults(func=cmd_model_groups_reorder)
    groups_members = model_groups_sub.add_parser("members")
    groups_members_sub = groups_members.add_subparsers(dest="model_group_members_command", required=True)
    groups_members_set = groups_members_sub.add_parser("set")
    groups_members_set.add_argument("group_id")
    groups_members_set.add_argument("model_ids", nargs="*")
    groups_members_set.set_defaults(func=cmd_model_group_members_set)


def register_permissions(sub: argparse._SubParsersAction) -> None:
    from .settings import cmd_permissions_config, cmd_permissions_show
    permissions = sub.add_parser("permissions", help="Manage Core permission defaults (设置 → 权限)")
    permissions_sub = permissions.add_subparsers(dest="permissions_command", required=True)
    permissions_show = permissions_sub.add_parser("show", help="Show the global permission defaults")
    permissions_show.set_defaults(func=cmd_permissions_show)
    permissions_config = permissions_sub.add_parser("config", help="Update global permission defaults")
    permissions_config.add_argument(
        "--mode",
        choices=("read_only", "limited_edit", "full_edit"),
        help="Default capability range for new sessions",
    )
    permissions_config.add_argument(
        "--approval",
        choices=("ask", "auto", "full_access"),
        help="Default approval behavior for new sessions",
    )
    permissions_config.add_argument(
        "--allow-outside-workdir",
        choices=("true", "false"),
        help="Whether new sessions may access paths outside the work directory",
    )
    permissions_config.set_defaults(func=cmd_permissions_config)
    from .trust import cmd_trust_list, cmd_trust_revoke
    trust = permissions_sub.add_parser("trust", help="Inspect and revoke persistent exact-operation trust")
    trust_sub = trust.add_subparsers(dest="trust_command", required=True)
    trust_sub.add_parser("list").set_defaults(func=cmd_trust_list)
    revoke = trust_sub.add_parser("revoke")
    revoke.add_argument("key", help="Exact key returned by permissions trust list")
    revoke.set_defaults(func=cmd_trust_revoke)



def register_context_compaction(sub: argparse._SubParsersAction) -> None:
    from .settings import cmd_context_compaction_config, cmd_context_compaction_show
    context_compaction = sub.add_parser(
        "context-compaction",
        help="Show or configure structural context-compaction retention",
    )
    context_compaction_sub = context_compaction.add_subparsers(
        dest="context_compaction_command", required=True
    )
    context_compaction_show = context_compaction_sub.add_parser(
        "show", help="Show effective context-compaction retention"
    )
    context_compaction_show.set_defaults(func=cmd_context_compaction_show)
    context_compaction_config = context_compaction_sub.add_parser(
        "config", help="Update structural context-compaction retention"
    )
    context_compaction_config.add_argument(
        "--retained-steps",
        type=int,
        default=None,
        help=f"Initial model Steps to retain (0-{MAX_RETAINED_STEPS}; default {DEFAULT_RETAINED_STEPS})",
    )
    context_compaction_config.set_defaults(func=cmd_context_compaction_config)


def register_loadtools(sub: argparse._SubParsersAction) -> None:
    from .resources import cmd_loadtools_delete_mode, cmd_loadtools_edit_mode, cmd_loadtools_show
    loadtools = sub.add_parser("loadtools", help="Manage mode tool-set configuration (loadtools.jsonc)")
    loadtools_sub = loadtools.add_subparsers(dest="loadtools_command", required=True)
    loadtools_show = loadtools_sub.add_parser("show", help="Print the effective mode tool-sets")
    loadtools_show.set_defaults(func=cmd_loadtools_show)
    loadtools_edit = loadtools_sub.add_parser("edit-mode", help="Create or update a mode's tool whitelist")
    loadtools_edit.add_argument("--mode", required=True, help="Mode name (e.g. consider)")
    loadtools_edit.add_argument("--description", default="", help="Mode description shown in the system prompt")
    loadtools_edit.add_argument("--tools", default="", help="Comma-separated tool names; empty means all tools allowed")
    loadtools_edit.add_argument("--no-limit", action="store_true", help="Full access: empty tools list (all tools allowed)")
    loadtools_edit.set_defaults(func=cmd_loadtools_edit_mode)
    loadtools_delete = loadtools_sub.add_parser("delete-mode", help="Remove a mode from the configuration")
    loadtools_delete.add_argument("--mode", required=True)
    loadtools_delete.set_defaults(func=cmd_loadtools_delete_mode)
