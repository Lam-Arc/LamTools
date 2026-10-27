"""Parse preferences responsibilities."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse


def register_command_shell(sub: argparse._SubParsersAction) -> None:
    from .preferences import cmd_command_shell_get, cmd_command_shell_set
    command_shell = sub.add_parser("command-shell", help="Show or select the shell used for command execution")
    command_shell_sub = command_shell.add_subparsers(dest="command_shell_command", required=True)
    command_shell_get = command_shell_sub.add_parser("get", help="Show the saved preference and effective shell")
    command_shell_get.set_defaults(func=cmd_command_shell_get)
    command_shell_set = command_shell_sub.add_parser("set", help="Save the command shell preference")
    command_shell_set.add_argument("preference", choices=("auto", "wsl", "git-bash", "powershell"))
    command_shell_set.set_defaults(func=cmd_command_shell_set)


def register_network(sub: argparse._SubParsersAction) -> None:
    from .preferences import cmd_network_get, cmd_network_set
    network = sub.add_parser("network", help="Show or set outbound routing (proxy / bypass list / CA bundle)")
    network_sub = network.add_subparsers(dest="network_command", required=True)
    network_get = network_sub.add_parser("get", help="Print the saved routing settings")
    network_get.set_defaults(func=cmd_network_get)
    network_set = network_sub.add_parser("set", help="Update routing settings (only the flags you pass change)")
    network_set.add_argument("--proxy", default=None, help="Proxy URL (http://127.0.0.1:7890); empty string means direct")
    network_set.add_argument("--no-proxy", dest="no_proxy", default=None, help="Comma-separated hosts that bypass the proxy")
    network_set.add_argument("--ca-cert", dest="ca_cert", default=None, help="PEM bundle path; empty string clears it")
    network_set.set_defaults(func=cmd_network_set)


def register_language(sub: argparse._SubParsersAction) -> None:
    from .preferences import cmd_language_get, cmd_language_set
    language = sub.add_parser("language", help="Show or set the interface language")
    language_sub = language.add_subparsers(dest="language_command", required=True)
    language_get = language_sub.add_parser("get", help="Print the interface language")
    language_get.set_defaults(func=cmd_language_get)
    language_set = language_sub.add_parser("set", help="Save the interface language")
    language_set.add_argument("locale", choices=("zh-CN", "zh-TW", "ja", "en"))
    language_set.set_defaults(func=cmd_language_set)


def register_keep_awake(sub: argparse._SubParsersAction) -> None:
    from .preferences import cmd_keep_awake_get, cmd_keep_awake_set
    keep_awake = sub.add_parser("keep-awake", help="Show or set whether the app keeps the machine awake")
    keep_awake_sub = keep_awake.add_subparsers(dest="keep_awake_command", required=True)
    keep_awake_get = keep_awake_sub.add_parser("get", help="Print the stored preference and whether it is active")
    keep_awake_get.set_defaults(func=cmd_keep_awake_get)
    keep_awake_set = keep_awake_sub.add_parser("set", help="Save the preference and apply it now")
    keep_awake_set.add_argument("state", choices=("on", "off"))
    keep_awake_set.set_defaults(func=cmd_keep_awake_set)


def register_ask_auto_continue(sub: argparse._SubParsersAction) -> None:
    from .preferences import cmd_ask_auto_continue_get, cmd_ask_auto_continue_set
    ask_auto_continue = sub.add_parser(
        "ask-auto-continue", help="Show or set unattended question auto-continue (approvals are never auto-answered)"
    )
    ask_auto_continue_sub = ask_auto_continue.add_subparsers(dest="ask_auto_continue_command", required=True)
    ask_auto_continue_get = ask_auto_continue_sub.add_parser(
        "get", help="Print the stored preference and the wait window"
    )
    ask_auto_continue_get.set_defaults(func=cmd_ask_auto_continue_get)
    ask_auto_continue_set = ask_auto_continue_sub.add_parser("set", help="Save the preference")
    ask_auto_continue_set.add_argument("state", choices=("on", "off"))
    ask_auto_continue_set.set_defaults(func=cmd_ask_auto_continue_set)


def register_memory_resume(sub: argparse._SubParsersAction) -> None:
    from .preferences import cmd_memory_resume_get, cmd_memory_resume_set
    memory_resume = sub.add_parser(
        "memory-resume",
        help="Show or set whether a turn interrupted by low memory continues by itself once memory recovers",
    )
    memory_resume_sub = memory_resume.add_subparsers(dest="memory_resume_command", required=True)
    memory_resume_get = memory_resume_sub.add_parser(
        "get", help="Print the stored preference, the threshold and the current reading"
    )
    memory_resume_get.set_defaults(func=cmd_memory_resume_get)
    memory_resume_set = memory_resume_sub.add_parser("set", help="Save the preference and threshold")
    memory_resume_set.add_argument("state", choices=("on", "off"), nargs="?")
    memory_resume_set.add_argument(
        "--threshold-gb", type=float, default=None,
        help="Continue once available memory (physical + page file) exceeds this many GB",
    )
    memory_resume_set.set_defaults(func=cmd_memory_resume_set)


def register_memory(sub: argparse._SubParsersAction) -> None:
    from .resources import cmd_memory
    memory = sub.add_parser(
        "memory",
        help="浏览 / 编辑两档记忆库（project：<工作区>/.lam/memory/；global：配置目录 memory/）",
    )
    memory_sub = memory.add_subparsers(dest="memory_command", required=True)

    def _memory_scope_args(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--global", dest="memory_global", action="store_true", help="作用于全局档（默认项目档）")
        parser.add_argument("--work-root", default="", help="项目档的工作区根（默认当前目录）")

    memory_tree = memory_sub.add_parser("tree", help="列出某档记忆库的目录树")
    memory_tree.add_argument("--path", default="", help="相对记忆库根的路径（默认根目录）")
    memory_tree.add_argument("--max-depth", default=0, type=int, help="最大深度，0 表示不限")
    memory_tree.add_argument("--flat", action="store_true", help="只列当前层，不递归")
    _memory_scope_args(memory_tree)
    memory_tree.set_defaults(func=cmd_memory)

    memory_read = memory_sub.add_parser("read", help="读取一个记忆文件")
    memory_read.add_argument("path", help="相对记忆库根的路径")
    _memory_scope_args(memory_read)
    memory_read.set_defaults(func=cmd_memory)

    memory_write = memory_sub.add_parser("write", help="写入（覆盖）一个记忆文件")
    memory_write.add_argument("path", help="相对记忆库根的路径")
    memory_write.add_argument("--content", default="", help="要写入的内容（与 --from-file 二选一；都省略则读 stdin）")
    memory_write.add_argument("--from-file", default="", help="从该 UTF-8 文件读取内容，'-' 表示 stdin")
    _memory_scope_args(memory_write)
    memory_write.set_defaults(func=cmd_memory)

    memory_append = memory_sub.add_parser("append", help="在记忆文件末尾追加内容")
    memory_append.add_argument("path", help="相对记忆库根的路径")
    memory_append.add_argument("--content", default="", help="要追加的内容（与 --from-file 二选一；都省略则读 stdin）")
    memory_append.add_argument("--from-file", default="", help="从该 UTF-8 文件读取内容，'-' 表示 stdin")
    _memory_scope_args(memory_append)
    memory_append.set_defaults(func=cmd_memory)

    memory_edit = memory_sub.add_parser("edit", help="局部替换记忆文件中的文本")
    memory_edit.add_argument("path", help="相对记忆库根的路径")
    memory_edit.add_argument("--old", required=True, help="要替换的原文")
    memory_edit.add_argument("--new", required=True, help="替换后的文本")
    memory_edit.add_argument("--occurrence", default=0, type=int, help="原文出现多次时替换第几次（1 起；0 表示未指定，此时多处匹配会报错）")
    _memory_scope_args(memory_edit)
    memory_edit.set_defaults(func=cmd_memory)

    memory_delete = memory_sub.add_parser("delete", help="删除一个记忆文件或目录")
    memory_delete.add_argument("path", help="相对记忆库根的路径")
    _memory_scope_args(memory_delete)
    memory_delete.set_defaults(func=cmd_memory)

    memory_rename = memory_sub.add_parser("rename", help="重命名 / 移动记忆条目")
    memory_rename.add_argument("path", help="源路径")
    memory_rename.add_argument("new_path", help="目标路径")
    _memory_scope_args(memory_rename)
    memory_rename.set_defaults(func=cmd_memory)

    memory_mkdir = memory_sub.add_parser("mkdir", help="在记忆库中新建目录")
    memory_mkdir.add_argument("path", help="相对记忆库根的路径")
    _memory_scope_args(memory_mkdir)
    memory_mkdir.set_defaults(func=cmd_memory)

    memory_reveal = memory_sub.add_parser("reveal", help="在系统文件资源管理器中打开某档记忆文件夹")
    _memory_scope_args(memory_reveal)
    memory_reveal.set_defaults(func=cmd_memory)

    memory_projects = memory_sub.add_parser(
        "projects",
        help="在候选项目工作区中列出真正存有记忆的（纯探测：不创建目录、不生成索引）",
    )
    memory_projects.add_argument("roots", nargs="+", help="候选项目的工作区根目录")
    memory_projects.set_defaults(func=cmd_memory)


def register_onboarding(sub: argparse._SubParsersAction) -> None:
    from .preferences import cmd_onboarding_complete, cmd_onboarding_reset, cmd_onboarding_show
    onboarding = sub.add_parser("onboarding", help="首次启动引导（Onboarding）状态：显示 / 标记完成 / 重置")
    onboarding_sub = onboarding.add_subparsers(dest="onboarding_command", required=True)
    onboarding_show = onboarding_sub.add_parser("show", help="显示当前首次引导状态（是否已完成、是否已配置供应商）")
    onboarding_show.set_defaults(func=cmd_onboarding_show)
    onboarding_complete = onboarding_sub.add_parser("complete", help="标记首次引导已完成（此后启动不再弹出向导）")
    onboarding_complete.set_defaults(func=cmd_onboarding_complete)
    onboarding_reset = onboarding_sub.add_parser("reset", help="清除完成标记，下次启动重新弹出引导向导")
    onboarding_reset.set_defaults(func=cmd_onboarding_reset)


def register_load_context(sub: argparse._SubParsersAction) -> None:
    from .preferences import cmd_load_context_get, cmd_load_context_set
    load_context = sub.add_parser("load-context", help="Read or write the global load_context.jsonc (unified config dir)")
    load_context_sub = load_context.add_subparsers(dest="load_context_command", required=True)
    load_context_get = load_context_sub.add_parser("get", help="Print the parsed global load_context (addition/except)")
    load_context_get.set_defaults(func=cmd_load_context_get)
    load_context_set = load_context_sub.add_parser("set", help="Write global load_context from a JSON file or stdin")
    load_context_set.add_argument("source_file", help="Path to a JSON file, or '-' for stdin")
    load_context_set.set_defaults(func=cmd_load_context_set)
