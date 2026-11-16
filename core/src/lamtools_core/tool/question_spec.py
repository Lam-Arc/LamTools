"""user:“Question 是纯提问工具，只负责向用户提出问题，不负责等待、收集或返回答案”
+(提问的数据模型在这里一次定清：题目身份、类型、必答性、选项与输入提示都在进入
界面之前规范化；非法载荷直接拒绝，而不是让界面去猜。)

The question tool used to accept a flat ``question``/``options``/``multiSelect``
payload and leave every semantic decision to the renderer. This module owns the
one normal form:

    {id, title, description, type, required, options, placeholder}

``type`` is ``single`` / ``multiple`` / ``text``. A question that declares no
options degrades to ``text`` — the interface must never show a selection control
that cannot select anything. ``required`` defaults to true because asking used
to mean waiting; a model that only wants optional background information has to
say ``required: false`` explicitly.
"""
from __future__ import annotations

from typing import Any

QUESTION_TYPES = ("single", "multiple", "text")
MAX_QUESTIONS = 10
MAX_TITLE = 4000
MAX_DESCRIPTION = 2000
MAX_LABEL = 256
MAX_PLACEHOLDER = 256
MAX_ID = 128


def _text(
    value: Any,
    *,
    field: str,
    maximum: int,
    required: bool,
) -> str:
    if value is None:
        if required:
            raise ValueError(f"{field} is required")
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = value.strip()
    if required and not text:
        raise ValueError(f"{field} must not be blank")
    if len(text) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    return text


def _options(value: Any, *, field: str) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if isinstance(item, str):
            label = _text(item, field=f"{field}[{index}].label", maximum=MAX_LABEL, required=True)
            description = ""
        elif isinstance(item, dict):
            label = _text(
                item.get("label"),
                field=f"{field}[{index}].label",
                maximum=MAX_LABEL,
                required=True,
            )
            description = _text(
                item.get("description"),
                field=f"{field}[{index}].description",
                maximum=MAX_DESCRIPTION,
                required=False,
            )
        else:
            raise ValueError(f"{field}[{index}] must be a label or an object with a label")
        if label in seen:
            raise ValueError(f"duplicate option label: {label}")
        seen.add(label)
        result.append({"label": label, "description": description})
    return result


def _question(raw: dict[str, Any], index: int) -> dict[str, Any]:
    identifier = _text(
        raw.get("id"),
        field=f"questions[{index}].id",
        maximum=MAX_ID,
        required=False,
    ) or f"q{index + 1}"
    title = raw.get("title")
    if title is None:
        # 旧字段映射：question 就是题目正文。
        title = raw.get("question")
    resolved_title = _text(
        title,
        field=f"questions[{index}].title",
        maximum=MAX_TITLE,
        required=True,
    )
    description = _text(
        raw.get("description"),
        field=f"questions[{index}].description",
        maximum=MAX_DESCRIPTION,
        required=False,
    )
    if not description:
        # 旧字段映射：header 原本是短标题，作为补充说明保留下来。
        description = _text(
            raw.get("header"),
            field=f"questions[{index}].header",
            maximum=MAX_DESCRIPTION,
            required=False,
        )
    placeholder = _text(
        raw.get("placeholder"),
        field=f"questions[{index}].placeholder",
        maximum=MAX_PLACEHOLDER,
        required=False,
    )
    options = _options(raw.get("options"), field=f"questions[{index}].options")
    raw_type = raw.get("type")
    if raw_type is None:
        raw_type = (
            "multiple" if raw.get("multiSelect") is True else "single"
        ) if options else "text"
    if raw_type not in QUESTION_TYPES:
        raise ValueError(
            f"questions[{index}].type must be one of {', '.join(QUESTION_TYPES)}"
        )
    if raw_type == "text":
        options = []
    elif not options:
        # user:“选项不存在时自动退化为纯文本交互”+(没有可选项就不能展示选择控件。)
        raw_type = "text"
    required = raw.get("required", True)
    if not isinstance(required, bool):
        raise ValueError(f"questions[{index}].required must be a boolean")
    return {
        "id": identifier,
        "title": resolved_title,
        "description": description,
        "type": raw_type,
        "required": required,
        "options": options,
        "placeholder": placeholder,
    }


def normalize_questions(args: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the canonical question list for one ``question`` tool call."""
    if not isinstance(args, dict):
        raise ValueError("question arguments must be an object")
    raw = args.get("questions")
    if raw is not None:
        if not isinstance(raw, list) or not raw:
            raise ValueError("questions must be a non-empty list")
        items: list[Any] = list(raw)
    else:
        if args.get("question") is None:
            raise ValueError("question or questions is required")
        items = [args]
    if len(items) > MAX_QUESTIONS:
        raise ValueError(f"at most {MAX_QUESTIONS} questions are allowed")
    questions = [
        _question(item if isinstance(item, dict) else {}, index)
        for index, item in enumerate(items)
    ]
    seen: set[str] = set()
    for item in questions:
        if item["id"] in seen:
            raise ValueError(f"duplicate question id: {item['id']}")
        seen.add(item["id"])
    return questions


def has_required(questions: list[dict[str, Any]]) -> bool:
    """Whether this group must pause the turn (a required question exists)."""
    return any(bool(item.get("required")) for item in questions)


def question_input_schema() -> dict[str, Any]:
    """The JSON schema advertised to the model."""
    option = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "description": "Short option label."},
            "description": {"type": "string", "description": "Optional detail."},
        },
        "required": ["label"],
    }
    question = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Stable id within this call."},
            "title": {"type": "string", "description": "The question itself."},
            "description": {"type": "string", "description": "Optional detail."},
            "type": {
                "type": "string",
                "enum": list(QUESTION_TYPES),
                "description": "single / multiple / text. Omit to derive it from options.",
            },
            "required": {
                "type": "boolean",
                "description": (
                    "True pauses the session until answered. Defaults to true; "
                    "use false for optional background information."
                ),
            },
            "options": {"type": "array", "items": option},
            "placeholder": {"type": "string", "description": "Hint for free text."},
        },
        "required": ["title"],
    }
    return {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "description": "Several questions, presented as one group.",
                "items": question,
            },
            "question": {
                "type": "string",
                "description": "Shorthand for a single question (legacy form).",
            },
            "options": {"type": "array", "items": option},
            "multiSelect": {"type": "boolean"},
            "context": {"type": "string", "description": "Optional background."},
        },
        "anyOf": [{"required": ["question"]}, {"required": ["questions"]}],
    }


__all__ = [
    "MAX_QUESTIONS",
    "QUESTION_TYPES",
    "has_required",
    "normalize_questions",
    "question_input_schema",
]
