"""Approval and question channels bridged to QQ buttons / text.

LamTools emits both kinds through the same ``pending_approval`` record:
``request_kind`` is ``"permission"`` for a tool approval and ``"question"``
for the built-in ``question`` tool.  The two channels below share the button
encoding (top-level ``t`` discriminator) so one interaction dispatcher can
route a click without guessing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from .protocol import InboundMessage, ReplyTarget


# ── Button helpers ─────────────────────────────────────────────────────────

BUTTON_LABEL_MAX = 10
BUTTONS_PER_ROW = 2


def button_label(text: str | None) -> str:
    value = str(text or "").strip()
    return value[: BUTTON_LABEL_MAX - 1] + "…" if len(value) > BUTTON_LABEL_MAX else value


def encode_button_data(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def decode_button_data(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    if isinstance(parsed, dict) and parsed.get("t") in {"question", "approval"}:
        return parsed
    return None


def build_approval_keyboard() -> dict[str, Any]:
    def button(button_id: str, label: str, visited: str, style: int, decision: str) -> dict[str, Any]:
        return {
            "id": button_id,
            "render_data": {"label": label, "visited_label": visited, "style": style},
            "action": {
                "type": 1,
                "permission": {"type": 2},
                "click_limit": 1,
                "data": encode_button_data({"t": "approval", "d": decision}),
            },
            "group_id": "approval",
        }

    return {
        "content": {
            "rows": [
                {
                    "buttons": [
                        button("approval-allow", "✅ 允许一次", "✓ 已允许", 1, "allow"),
                        button("approval-deny", "❌ 拒绝", "✓ 已拒绝", 0, "deny"),
                    ]
                }
            ]
        }
    }


def build_question_keyboard(question: dict[str, Any]) -> dict[str, Any] | None:
    options = question.get("options") or []
    if not options or question.get("multiSelect"):
        return None
    question_id = str(question.get("id") or "")
    rows: list[dict[str, Any]] = []
    for index in range(0, len(options), BUTTONS_PER_ROW):
        buttons = []
        for offset, option in enumerate(options[index : index + BUTTONS_PER_ROW]):
            option_index = index + offset
            buttons.append(
                {
                    "id": f"q-{question_id}-opt-{option_index}",
                    "render_data": {
                        "label": button_label(option.get("label")),
                        "visited_label": "✓ 已选",
                        "style": 1,
                    },
                    "action": {
                        "type": 1,
                        "permission": {"type": 2},
                        "click_limit": 1,
                        "data": encode_button_data(
                            {"t": "question", "q": question_id, "i": option_index}
                        ),
                    },
                    "group_id": f"q-{question_id}",
                }
            )
        rows.append({"buttons": buttons})
    return {"content": {"rows": rows}}


def format_question(
    question: dict[str, Any],
    *,
    require_mention_hint: bool,
    with_buttons: bool,
    index: int = 0,
    total: int = 0,
) -> str:
    lines: list[str] = []
    if total > 1:
        lines.append(f"**问题 {index + 1}/{total}**")
    header = str(question.get("header") or "").strip()
    if header:
        lines.append(f"**{header}**")
    text = str(question.get("question") or question.get("message") or "请选择")
    multi = bool(question.get("multiSelect"))
    lines.append(f"{text}（可多选）" if multi else text)
    options = question.get("options") or []
    for option_index, option in enumerate(options):
        description = str(option.get("description") or "").strip()
        suffix = f" · {description}" if description else ""
        lines.append(f"{option_index + 1}. {option.get('label')}{suffix}")
    if options:
        lines.append("")
        mention = "（需 @机器人）" if require_mention_hint else ""
        if with_buttons:
            lines.append(f"> 👇 点击下方按钮选择，或回复编号{mention}")
        elif multi:
            lines.append(f"> 💡 回复多个编号即可多选（如 1,3）{mention}，或直接输入你的想法")
        else:
            lines.append(f"> 💡 回复编号选择{mention}，或直接输入你的想法")
    return "\n".join(lines)


def parse_answer(question: dict[str, Any], text: str) -> dict[str, Any]:
    options = question.get("options") or []
    text = str(text or "").strip()
    if options:
        if text and all(char in "0123456789 \t,，、;；./" for char in text):
            numbers = []
            for token in text.replace("，", ",").replace("、", ",").replace("；", ",").replace(";", ",").split(","):
                token = token.strip()
                if token.isdigit():
                    numbers.append(int(token))
            numbers = [number for number in numbers if 1 <= number <= len(options)]
            if numbers:
                picked = numbers if question.get("multiSelect") else numbers[:1]
                labels = []
                for number in dict.fromkeys(picked):
                    label = options[number - 1].get("label")
                    if isinstance(label, str):
                        labels.append(label)
                return {"id": str(question.get("id") or ""), "selected": labels}
        for option in options:
            if str(option.get("label") or "").lower() == text.lower():
                return {"id": str(question.get("id") or ""), "selected": [option.get("label")]}
    return {"id": str(question.get("id") or ""), "selected": [], "custom": text}


# ── Channels ───────────────────────────────────────────────────────────────

@dataclass
class _Pending:
    key: str
    future: asyncio.Future
    question: dict[str, Any] = field(default_factory=dict)
    timer: asyncio.TimerHandle | None = None


class ApprovalChannel:
    def __init__(self, *, logger: logging.Logger) -> None:
        self.logger = logger
        self.pending: dict[str, _Pending] = {}

    async def ask(self, session: Any, pending_approval: dict[str, Any], *, timeout_ms: int) -> str:
        key = session.key
        tool_call = pending_approval.get("tool_call") or {}
        request_payload = pending_approval.get("request_payload") or {}
        tool_name = str(tool_call.get("name") or request_payload.get("tool_name") or "tool")
        arguments = tool_call.get("arguments") or request_payload.get("arguments") or {}
        command = ""
        if isinstance(arguments, dict):
            raw_command = arguments.get("command")
            if isinstance(raw_command, str):
                command = raw_command[:500]
        reason = str(pending_approval.get("reason") or request_payload.get("message") or "").strip()

        text = self._build_text(tool_name, command, reason)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        entry = _Pending(key=key, future=future)
        self.pending[key] = entry
        try:
            await session.send_markdown(text, keyboard=build_approval_keyboard())
        except Exception as exc:
            self.pending.pop(key, None)
            self.logger.error("approval send failed key=%s: %s", key, exc)
            return "unavailable"

        try:
            return await asyncio.wait_for(future, timeout=max(1, timeout_ms) / 1000.0)
        except asyncio.TimeoutError:
            self.pending.pop(key, None)
            try:
                await session.send_markdown("⚠️ 审批等待超时，本轮按拒绝处理。")
            except Exception:
                pass
            return "timeout"
        finally:
            self.pending.pop(key, None)

    @staticmethod
    def _build_text(tool_name: str, command: str, reason: str) -> str:
        lines = ["🔐 **执行审批**", "", f"🔧 工具: {tool_name}"]
        if command:
            lines.extend(["", "```", command, "```"])
        if reason:
            lines.extend(["", f"📝 {reason}"])
        lines.extend(["", "> 👇 点击下方按钮确认是否允许执行"])
        return "\n".join(lines)

    def handle_interaction(self, event: dict[str, Any], manager: Any) -> bool:
        scope, peer_id = interaction_scope_peer(event)
        session = manager.get(scope, peer_id) if manager is not None else None
        if session is None:
            return False
        entry = self.pending.get(session.key)
        if entry is None:
            return False
        raw = ((event.get("data") or {}).get("resolved") or {}).get("button_data")
        button = decode_button_data(raw)
        if not button or button.get("t") != "approval":
            return False
        if not entry.future.done():
            entry.future.set_result("allow" if button.get("d") == "allow" else "deny")
        return True

    def handle_text(self, scope: str, peer_id: str, text: str, manager: Any) -> bool:
        session = manager.get(scope, peer_id) if manager is not None else None
        if session is None:
            return False
        entry = self.pending.get(session.key)
        if entry is None or entry.future.done():
            return False
        lowered = str(text or "").strip().lower()
        allow = {"允许", "同意", "批准", "可以", "yes", "y", "allow", "ok"}
        deny = {"拒绝", "不允许", "不行", "no", "n", "deny", "cancel", "取消"}
        if lowered in allow:
            entry.future.set_result("allow")
            return True
        if lowered in deny:
            entry.future.set_result("deny")
            return True
        return False

    def cancel_pending(self, key: str) -> None:
        entry = self.pending.pop(key, None)
        if entry is not None and not entry.future.done():
            entry.future.set_result("cancelled")

    def cancel_all(self) -> None:
        for key in list(self.pending):
            self.cancel_pending(key)


class QuestionChannel:
    def __init__(self, *, logger: logging.Logger) -> None:
        self.logger = logger
        self.pending: dict[str, _Pending] = {}

    async def ask(self, session: Any, pending_approval: dict[str, Any], *, timeout_ms: int, require_mention: bool) -> dict[str, Any] | list[dict[str, Any]] | None:
        key = session.key
        questions = self._questions_from_pending(pending_approval, key)
        if not questions:
            return None
        multiple = len(questions) > 1
        answers: list[dict[str, Any]] = []
        for index, question in enumerate(questions):
            future: asyncio.Future = asyncio.get_running_loop().create_future()
            entry = _Pending(key=key, future=future, question=question)
            self.pending[key] = entry
            try:
                await self._send_question(session, question, index, len(questions), require_mention)
            except Exception as exc:
                self.pending.pop(key, None)
                self.logger.error("question send failed key=%s: %s", key, exc)
                return None
            try:
                answer = await asyncio.wait_for(future, timeout=max(1, timeout_ms) / 1000.0)
            except asyncio.TimeoutError:
                self.pending.pop(key, None)
                try:
                    await session.send_markdown("⚠️ 提问已超时，未收到回答。")
                except Exception:
                    pass
                return None
            finally:
                self.pending.pop(key, None)
            if answer is None:
                return None
            answers.append(answer)
        return answers if multiple else answers[0]

    @staticmethod
    def _normalize_options(options: Any) -> list[dict[str, str]]:
        return [
            {
                "label": str(option.get("label") or f"选项 {index + 1}"),
                "description": str(option.get("description") or ""),
                "response": str(option.get("response") or option.get("label") or ""),
            }
            for index, option in enumerate(options or [])
            if isinstance(option, dict)
        ]

    def _questions_from_pending(self, pending_approval: dict[str, Any], key: str) -> list[dict[str, Any]]:
        request_payload = pending_approval.get("request_payload") or {}
        tool_call = pending_approval.get("tool_call") or {}
        arguments = tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else {}
        raw = arguments.get("questions") or request_payload.get("questions") or []
        base_id = str(request_payload.get("request_id") or pending_approval.get("request_id") or key)
        questions: list[dict[str, Any]] = []
        if isinstance(raw, list) and raw:
            for index, item in enumerate(raw):
                if not isinstance(item, dict):
                    continue
                questions.append(
                    {
                        "id": str(item.get("id") or f"{base_id}:{index}"),
                        "header": str(item.get("header") or ""),
                        "question": str(item.get("question") or item.get("message") or f"问题 {index + 1}"),
                        "options": self._normalize_options(item.get("options")),
                        "multiSelect": bool(item.get("multiSelect")),
                    }
                )
        if questions:
            return questions
        message = str(
            request_payload.get("message")
            or pending_approval.get("message")
            or "请选择"
        )
        return [
            {
                "id": base_id,
                "question": message,
                "options": self._normalize_options(
                    request_payload.get("options") or pending_approval.get("options")
                ),
                "multiSelect": False,
            }
        ]

    async def _send_question(
        self,
        session: Any,
        question: dict[str, Any],
        index: int,
        total: int,
        require_mention: bool,
    ) -> None:
        keyboard = build_question_keyboard(question)
        if keyboard is not None:
            try:
                await session.send_markdown(
                    format_question(
                        question,
                        require_mention_hint=require_mention,
                        with_buttons=True,
                        index=index,
                        total=total,
                    ),
                    keyboard=keyboard,
                )
                return
            except Exception as exc:
                self.logger.warning("question keyboard send failed, fallback to text: %s", exc)
        await session.send_markdown(
            format_question(
                question,
                require_mention_hint=require_mention,
                with_buttons=False,
                index=index,
                total=total,
            )
        )

    def handle_interaction(self, event: dict[str, Any], manager: Any) -> bool:
        scope, peer_id = interaction_scope_peer(event)
        session = manager.get(scope, peer_id) if manager is not None else None
        if session is None:
            return False
        entry = self.pending.get(session.key)
        if entry is None or entry.future.done():
            return False
        raw = ((event.get("data") or {}).get("resolved") or {}).get("button_data")
        button = decode_button_data(raw)
        if not button or button.get("t") != "question":
            return False
        question = entry.question
        if str(button.get("q")) != str(question.get("id")):
            return False
        index = button.get("i")
        options = question.get("options") or []
        if not isinstance(index, int) or index < 0 or index >= len(options):
            return False
        entry.future.set_result(
            {"id": question.get("id"), "selected": [options[index].get("label")], "custom": ""}
        )
        return True

    def handle_text(self, scope: str, peer_id: str, text: str, manager: Any) -> bool:
        session = manager.get(scope, peer_id) if manager is not None else None
        if session is None:
            return False
        entry = self.pending.get(session.key)
        if entry is None or entry.future.done():
            return False
        if not str(text or "").strip():
            return False
        entry.future.set_result(parse_answer(entry.question, text))
        return True

    def cancel_pending(self, key: str) -> None:
        entry = self.pending.pop(key, None)
        if entry is not None and not entry.future.done():
            entry.future.set_result(None)

    def cancel_all(self) -> None:
        for key in list(self.pending):
            self.cancel_pending(key)


def interaction_scope_peer(event: dict[str, Any]) -> tuple[str, str]:
    group_openid = str(event.get("group_openid") or "")
    user_openid = str(event.get("user_openid") or "")
    if group_openid:
        return "group", group_openid
    return "c2c", user_openid


def answer_text(answer: dict[str, Any] | list[dict[str, Any]] | None) -> str:
    """Convert one or more structured answers into the text handed to the model."""
    if isinstance(answer, list):
        if not answer:
            return "（用户没有回答这些问题。）"
        if len(answer) == 1:
            return answer_text(answer[0])
        return "\n".join(
            f"问题 {index + 1}: {answer_text(item)}"
            for index, item in enumerate(answer)
        )
    if not answer:
        return "（用户没有回答这个问题。）"
    selected = [str(item) for item in (answer.get("selected") or []) if str(item)]
    custom = str(answer.get("custom") or "").strip()
    if selected:
        return "、".join(selected)
    if custom:
        return custom
    return "（用户没有回答这个问题。）"


class InteractionRouter:
    def __init__(self, *, approvals: ApprovalChannel, questions: QuestionChannel, manager: Any) -> None:
        self.approvals = approvals
        self.questions = questions
        self.manager = manager

    def handle(self, event: dict[str, Any]) -> bool:
        raw = ((event.get("data") or {}).get("resolved") or {}).get("button_data")
        button = decode_button_data(raw)
        if not button:
            return False
        if button.get("t") == "question":
            return self.questions.handle_interaction(event, self.manager)
        if button.get("t") == "approval":
            return self.approvals.handle_interaction(event, self.manager)
        return False


__all__ = [
    "BUTTON_LABEL_MAX",
    "BUTTONS_PER_ROW",
    "button_label",
    "encode_button_data",
    "decode_button_data",
    "build_approval_keyboard",
    "build_question_keyboard",
    "format_question",
    "parse_answer",
    "ApprovalChannel",
    "QuestionChannel",
    "InteractionRouter",
    "interaction_scope_peer",
    "answer_text",
]
