"""Slash commands for the QQ bot.

Commands are intentionally split from the inbound pipeline: they must run
before the per-peer concurrency guard (a command answers immediately even when
an agent turn is running), and they never reach the model.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from . import __version__
from .agent_bridge import AgentBridge, PeerSession
from .protocol import InboundMessage
from .util import format_relative_time

PLUGIN_VERSION = __version__


@dataclass
class CommandResult:
    text: str = ""
    noop: bool = False


@dataclass
class Command:
    names: tuple[str, ...]
    description: str
    category: str
    handler: Callable[["CommandContext"], Awaitable[CommandResult] | CommandResult]
    hidden: bool = False

    @property
    def name(self) -> str:
        return self.names[0]


@dataclass
class CommandContext:
    session: PeerSession
    message: InboundMessage
    args: list[str]
    raw: str
    bridge: AgentBridge
    runtime: Any


def _command_text(result: Any) -> CommandResult:
    if isinstance(result, CommandResult):
        return result
    if result is None:
        return CommandResult(noop=True)
    if isinstance(result, str):
        return CommandResult(text=result)
    return CommandResult(text=str(result))


def _fmt_model(session: PeerSession, config: dict[str, Any]) -> str:
    if session.model:
        provider = f"{session.model_provider}/" if session.model_provider else ""
        return f"{provider}{session.model}"
    if config.get("model"):
        provider = f"{config.get('provider')}/" if config.get("provider") else ""
        return f"{provider}{config['model']}"
    return "宿主默认"


def build_commands(bridge: AgentBridge, runtime: Any, config: dict[str, Any]) -> list[Command]:
    async def new_session(ctx: CommandContext) -> CommandResult:
        bridge.new_session(ctx.session)
        return CommandResult("已开启新会话 ✓")

    async def compact(ctx: CommandContext) -> CommandResult:
        if not ctx.session.session_id:
            return CommandResult("当前无活跃会话")
        runner = ctx.bridge.runner
        # Prefer the preset-scoped compaction service (host contract); fall
        # back to the runner method for older hosts.
        service = None
        resolver = getattr(runner, "preset_service", None)
        if callable(resolver):
            try:
                service = resolver("compaction", ctx.session.preset)
            except Exception:
                service = None
        compact_fn = getattr(service, "compact_now", None)
        if not callable(compact_fn):
            compact_fn = getattr(runner, "compact", None)
        if not callable(compact_fn):
            return CommandResult("宿主未提供子会话压缩接口。")
        try:
            result = await compact_fn(ctx.session.session_id)
        except Exception as exc:
            return CommandResult(f"压缩失败: {exc}")
        status = str((result or {}).get("status") or "")
        if status == "compacted":
            return CommandResult(
                f"✅ 已压缩 {result.get('compacted_messages', 0)} 条历史"
                f"（约 {result.get('before_tokens', 0)} → {result.get('after_tokens', 0)} tokens）"
            )
        if status == "not_needed":
            return CommandResult("没有可压缩的历史")
        message = str((result or {}).get("summary") or (result or {}).get("message") or "")
        return CommandResult(message or "压缩完成")

    async def fork(ctx: CommandContext) -> CommandResult:
        try:
            result = await ctx.bridge.fork_session(ctx.session)
        except Exception as exc:
            return CommandResult(f"分支失败: {exc}")
        return CommandResult(
            "✅ 已从当前会话分叉\n"
            f"新会话: {str(result.get('session_id') or '')[:8]}\n"
            f"携带历史: {result.get('history_count', 0)} 条"
        )

    async def history(ctx: CommandContext) -> CommandResult:
        try:
            info = await ctx.bridge.session_info(ctx.session)
        except Exception as exc:
            return CommandResult(f"读取失败: {exc}")
        messages = info.get("messages") or []
        limit = 10
        if ctx.args:
            try:
                limit = max(1, min(30, int(ctx.args[0])))
            except ValueError:
                limit = 10
        lines = [
            "### 🧾 会话历史",
            f"状态: {info.get('status') or '—'} · 轮次: {info.get('turn_count', 0)} · 历史: {info.get('history_count', 0)} 条",
        ]
        if messages:
            lines.append("")
            for item in messages[-limit:]:
                role = "用户" if item.get("role") == "user" else "助手"
                text = str(item.get("text") or "").strip().replace("\n", " ")
                if len(text) > 120:
                    text = text[:117] + "…"
                lines.append(f"**{role}**：{text}")
        else:
            lines.append("（没有可显示的消息）")
        return CommandResult("\n".join(lines))

    async def model(ctx: CommandContext) -> CommandResult:
        if not ctx.raw.strip():
            models = bridge.list_models()
            current = _fmt_model(ctx.session, config)
            lines = ["### 🤖 模型配置", "", f"**当前模型:** {current}"]
            if models:
                lines.extend(["", "**可用模型（点击切换）:**"])
                for item in models:
                    model_path = f"{item['provider']}/{item['id']}" if item.get("provider") else item["id"]
                    display = item.get("name") or model_path
                    lines.append(f'<qqbot-cmd-input text="/model {model_path}" show="/model {display}"/>')
            lines.extend(["", "手动指定: `/model provider/model`"])
            return CommandResult("\n".join(lines))
        try:
            result = bridge.set_model(ctx.session, ctx.raw.strip())
        except Exception as exc:
            return CommandResult(f"切换失败: {exc}")
        provider = result.get("provider") or ""
        model_id = result.get("model") or ""
        shown = f"{provider}/{model_id}" if provider else model_id
        return CommandResult(f"✅ 模型已切换: {shown}\n立即生效，对话上下文保留。")

    async def preset(ctx: CommandContext) -> CommandResult:
        if not ctx.raw.strip():
            presets = bridge.list_presets()
            if not presets:
                return CommandResult("当前部署没有可用的 agent preset")
            current = ctx.session.preset or config.get("preset") or "默认"
            lines = ["### 🧩 Agent Preset", "", f"**当前:** {current}", "", "**可用 preset（点击切换）:**"]
            for item in presets:
                display = item.get("title") or item.get("id")
                if item.get("title") and item.get("title") != item.get("id"):
                    display = f"{item['title']} ({item['id']})"
                lines.append(f'<qqbot-cmd-input text="/preset {item["id"]}" show="/preset {display}"/>')
            lines.extend(["", "手动指定: `/preset <id>`，重置默认: `/preset reset`"])
            return CommandResult("\n".join(lines))
        value = ctx.raw.strip()
        if value in {"reset", "default"}:
            bridge.clear_preset(ctx.session)
            return CommandResult("✅ 已重置为默认 preset（新会话生效）")
        outcome = bridge.set_preset(ctx.session, value)
        if not outcome.get("ok"):
            return CommandResult(str(outcome.get("message") or f"切换失败: {value}"))
        return CommandResult(
            f"✅ preset 已切换: {value}\n新会话生效（当前会话保持原 preset，发送 /new 后生效）。"
        )

    async def stop(ctx: CommandContext) -> CommandResult:
        stopped = await bridge.cancel(ctx.session)
        return CommandResult("已中止 ⛔" if stopped else "当前没有进行中的生成")

    def ping(ctx: CommandContext) -> CommandResult:
        now = int(time.time() * 1000)
        event_time = ctx.message.timestamp_ms
        if not event_time:
            return CommandResult("✅ pong!")
        total = max(0, now - event_time)
        qq_to_plugin = max(0, int(ctx.message.timestamp_ms and (time.time() - event_time / 1000) * 1000) - total)
        del qq_to_plugin
        return CommandResult(f"✅ pong！\n⏱ 延迟: {total}ms")

    def version(ctx: CommandContext) -> CommandResult:
        return CommandResult(
            f"qq-bot v{PLUGIN_VERSION} (port of dsh-qqbot 0.5.3) | model: {_fmt_model(ctx.session, config)}"
        )

    def status(ctx: CommandContext) -> CommandResult:
        info = bridge.status(ctx.session)
        lines = [
            "📊 会话状态",
            f"会话: {(info.get('sessionId') or info.get('agent') or '—')[:8]}",
            f"模型: {_fmt_model(ctx.session, config)}",
            f"Preset: {info.get('preset') or '默认'}",
            f"消息数: {info.get('messageCount') or 0}",
            f"最后活动: {format_relative_time(info.get('lastActivity'))}",
            f"正在生成: {'是' if info.get('running') else '否'}",
        ]
        return CommandResult("\n".join(lines))

    def cost(ctx: CommandContext) -> CommandResult:
        usage = ctx.session.usage
        return CommandResult(
            "\n".join(
                [
                    "💰 Token 用量",
                    f"输入: {usage.get('input', 0)}",
                    f"输出: {usage.get('output', 0)}",
                    f"缓存读: {usage.get('cacheRead', 0)}",
                    f"缓存写: {usage.get('cacheWrite', 0)}",
                ]
            )
        )

    def export(ctx: CommandContext) -> CommandResult:
        markdown = bridge.export_markdown(ctx.session)
        return CommandResult(markdown or "当前会话还没有可导出的内容。")

    def help_command(ctx: CommandContext, commands: list[Command]) -> CommandResult:
        agent_cmds = [cmd for cmd in commands if cmd.category == "agent" and not cmd.hidden]
        bot_cmds = [cmd for cmd in commands if cmd.category == "qqbot" and not cmd.hidden]
        lines = ["### 🤖 QQ 机器人指令", ""]

        def render(items: list[Command]) -> list[str]:
            out = []
            for cmd in items:
                name = cmd.names[0]
                out.append(f'<qqbot-cmd-input text="/{name}" show="/{name}"/> {cmd.description}')
            return out

        if agent_cmds:
            lines.extend(["**通用能力**", "", *render(agent_cmds), ""])
        if bot_cmds:
            lines.extend(["**插件内置指令**", "", *render(bot_cmds), ""])
        lines.extend(["", f"> qq-bot v{PLUGIN_VERSION}"])
        return CommandResult("\n".join(lines))

    commands: list[Command] = [
        Command(("new", "reset", "clear"), "开始新会话（清空上下文）", "agent", new_session),
        Command(("compact",), "压缩会话历史（摘要替换旧记录）", "agent", compact),
        Command(("fork",), "从当前会话分叉出一个新分支并切换过去", "agent", fork),
        Command(("history",), "查看当前会话最近的历史（用法: /history [条数]）", "agent", history),
        Command(("model",), "查看或切换模型（用法: /model [provider/model]）", "agent", model),
        Command(("preset",), "查看或切换 agent preset（用法: /preset [id]）", "agent", preset),
        Command(("stop",), "中止当前生成", "agent", stop, hidden=True),
        Command(("bot-ping",), "测试当前 dsh 与 QQ 连接的网络延迟", "qqbot", ping),
        Command(("bot-version",), "查看版本信息", "qqbot", version),
        Command(("bot-status",), "查看当前会话状态", "qqbot", status),
        Command(("cost",), "查看本会话 token 用量", "qqbot", cost),
        Command(("export",), "导出当前会话为 Markdown", "qqbot", export),
    ]

    async def help_handler(ctx: CommandContext) -> CommandResult:
        return help_command(ctx, commands)

    commands.append(Command(("bot-help", "help"), "查看所有指令", "qqbot", help_handler))
    return commands


class CommandRegistry:
    def __init__(self, commands: list[Command]) -> None:
        self.commands = commands
        self._by_name: dict[str, Command] = {}
        for command in commands:
            for name in command.names:
                self._by_name[name.lower()] = command

    def find(self, name: str) -> Command | None:
        return self._by_name.get(str(name or "").lower())

    def parse(self, content: str, message: InboundMessage) -> tuple[Command, list[str], str] | None:
        text = str(content or "").strip()
        if not text:
            return None
        # Strip server-side mention markers before matching.
        import re

        cleaned = re.sub(r"<@!?[^>]+>\s*", "", text).strip()
        if message.kind == "group":
            mentioned = message.raw_event_type == "GROUP_AT_MESSAGE_CREATE" or any(
                bool(item.get("is_you")) for item in (message.mentions or []) if isinstance(item, dict)
            )
            if not mentioned:
                return None
        if not cleaned.startswith("/"):
            return None
        body = cleaned[1:]
        parts = body.split(None, 1)
        if not parts:
            return None
        command = self.find(parts[0])
        if command is None:
            return None
        raw = parts[1].strip() if len(parts) > 1 else ""
        return command, raw.split() if raw else [], raw


__all__ = [
    "Command",
    "CommandContext",
    "CommandRegistry",
    "CommandResult",
    "build_commands",
]
