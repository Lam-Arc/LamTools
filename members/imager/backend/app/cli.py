from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
from pathlib import Path
import uuid
from contextlib import ExitStack, nullcontext
from typing import Any
from unittest.mock import patch

import aiohttp
from sqlalchemy import select

from app.database import async_session, engine, init_db
from app.core.artist.contact_sheet import build_review_contact_sheets
from app.core.artist.runtime import ARTIST_RUNTIME_SYSTEM, ArtistRuntime, ArtistRuntimeDeps
from app.models.api_provider import ApiProvider, ProviderType
from app.models.message import Message
from app.models.session import Session
from app.schemas.session import GenerateRequest, SessionCreate
from app.services import generate_service
from app.services.generate_service import handle_artist_generate
from app.services.task_manager import task_manager as global_task_manager
from app.services.api_manager import resolve_provider_vendor
from app.services.session_manager import add_system_message, create_session, get_session_detail, list_sessions
from app.utils.llm_client import LLMClient
from app.utils.llm_client import close_shared_session

_MOCK_BLACK_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAIklEQVR4nO3BAQ0AAADCoPdPbQ8HFAAAAAAAAAAAAAAA8G4wQAABiwCo9wAAAABJRU5ErkJggg=="
)


def _select_mock_image_fixture_label(prompt: str) -> str:
    text = (prompt or "").lower()
    is_refine = any(key in text for key in ("改", "修改", "调整", "更", "减少", "增加", "加一点", "修一版"))
    if any(key in text for key in ("灰径", "huijing")):
        return "huijing_anchor"
    if any(key in text for key in ("猫", "cat", "kitten")):
        return "cat"
    if any(key in text for key in ("冷白", "灯箱")) and any(key in text for key in ("门店招牌", "招牌", "sign")):
        return "sign_lightbox"
    if is_refine and any(key in text for key in ("极简", "简化", "更简单", "减少")) and any(key in text for key in ("杯身", "杯", "cup")):
        return "cup_refined"
    if is_refine and any(key in text for key in ("统一", "修一版", "不统一")):
        return "sign_fix"
    if any(key in text for key in ("主视觉海报", "海报", "poster")):
        return "poster"
    if any(key in text for key in ("杯身", "杯", "cup")):
        return "cup"
    if any(key in text for key in ("外卖袋", "袋", "bag")):
        return "bag"
    if any(key in text for key in ("社媒", "方图", "social")):
        return "social"
    if any(key in text for key in ("门店招牌", "招牌", "sign")):
        return "sign"
    if any(key in text for key in ("设计稿", "设定图", "视觉基准", "锚点", "anchor")):
        return "anchor"
    return "anchor"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="artist",
        description="Run Artist turns and manage sessions from the command line.",
    )
    parser.add_argument(
        "--session-id",
        default="",
        help="Reuse an existing session id. If omitted, a new session is created.",
    )
    parser.add_argument(
        "--title",
        default="Artist CLI",
        help="Title for a newly created session.",
    )
    parser.add_argument(
        "--image-count",
        type=int,
        default=1,
        help="Requested image count.",
    )
    parser.add_argument(
        "--image-size",
        default="1024x1024",
        help="Requested image size.",
    )
    parser.add_argument(
        "--negative-prompt",
        default="",
        help="Negative prompt.",
    )
    parser.add_argument(
        "--refine-mode",
        action="store_true",
        help="Force refine mode.",
    )
    parser.add_argument(
        "--selected-image-url",
        default="",
        help="Selected image URL for refine mode.",
    )
    parser.add_argument(
        "--reference-image",
        action="append",
        default=[],
        dest="reference_images",
        help="Explicit reference image URL. Repeatable.",
    )
    parser.add_argument(
        "--image-provider-id",
        default="",
        help="Override the image generation provider id for `artist image`.",
    )
    parser.add_argument(
        "--llm-provider-id",
        default="",
        help="Override the LLM provider id for `artist ct`.",
    )
    parser.add_argument(
        "--vlm-provider-id",
        default="",
        help="Override the VLM provider id for Artist decisions.",
    )
    parser.add_argument(
        "--vlm-base-url",
        default="",
        help="Temporary VLM base URL; can also use LAMIMAGER_CT_VLM_BASE_URL.",
    )
    parser.add_argument(
        "--vlm-model-id",
        default="",
        help="Temporary VLM model id; can also use LAMIMAGER_CT_VLM_MODEL_ID.",
    )
    parser.add_argument(
        "--vlm-api-key",
        default="",
        help="Temporary VLM API key; can also use LAMIMAGER_CT_VLM_API_KEY.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=6,
        help="Maximum loop steps for `artist ct`.",
    )
    parser.add_argument(
        "--one-loop",
        action="store_true",
        help="For `artist session <uuid> prompt`, run only one Artist loop and stop for manual confirmation.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Hide development details and print only progress plus the final summary.",
    )
    parser.add_argument(
        "--mock",
        nargs="?",
        const="image",
        choices=["image", "all"],
        default="",
        help="Mock image generation only, or mock both LLM and image generation with 'all'.",
    )
    parser.add_argument(
        "args",
        nargs="*",
        help="Prompt words, `ct <goal>`, `image <prompt>`, `copy <uuid>`, `rename <uuid> <title>`, or `session ls`, `session new`, `session <uuid>`.",
    )
    return parser


def _join_prompt(parts: list[str]) -> str:
    return " ".join(parts).strip()


def _flatten_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(p for p in parts if p).strip()
    if content is None:
        return ""
    return str(content)


def _extract_last_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        text = _flatten_message_content(msg.get("content"))
        if _looks_like_runtime_payload(text):
            continue
        return text
    return ""


def _looks_like_runtime_payload(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped.startswith("{"):
        return False
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return any(key in data for key in ("runtime_state", "runtime_note"))


def _mock_messages_have_visible_output(messages: list[dict[str, Any]]) -> bool:
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        text = _flatten_message_content(msg.get("content"))
        if not _looks_like_runtime_payload(text):
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        runtime_state = data.get("runtime_state")
        if isinstance(runtime_state, dict) and runtime_state.get("visible_artifacts"):
            return True
    return False


def _mock_messages_are_artist_runtime(messages: list[dict[str, Any]]) -> bool:
    for msg in messages:
        text = _flatten_message_content(msg.get("content"))
        if "ArtistRuntime" in text or _looks_like_runtime_payload(text):
            return True
    return False


def _copy_session_metadata(metadata: dict[str, Any] | None, new_session_id: str) -> dict[str, Any]:
    copied = json.loads(json.dumps(metadata or {}, ensure_ascii=False))
    workspace = copied.get("visual_workspace")
    if isinstance(workspace, dict):
        workspace["session_id"] = new_session_id
    return copied


def _mock_image_context_response(prompt_text: str) -> dict[str, Any]:
    if any(key in prompt_text for key in ("改", "修改", "替换", "换成", "调整", "精修")):
        mode = "edit_target"
        refs = ["图0"] if "图0" in prompt_text or "图1" in prompt_text else []
    elif any(key in prompt_text for key in ("统一", "套图", "系列", "同一", "沿用", "参考")):
        mode = "style_reference"
        refs = ["图0"] if "图0" in prompt_text or "图1" in prompt_text else []
    else:
        mode = "new_generation"
        refs = []

    content = json.dumps(
        {
            "is_new_independent": mode == "new_generation",
            "generation_mode": mode,
            "reference_images": refs,
            "needs_clarification": False,
            "clarification_message": "",
            "reason": "mock all",
        },
        ensure_ascii=False,
    )
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _mock_artist_turn_text(prompt_text: str, *, has_visible_output: bool = False) -> str:
    if has_visible_output:
        return json.dumps(
            {
                "message": "（mock）已看到输出图，画面与当前任务匹配。",
                "observations": [
                    {
                        "index": 0,
                        "summary": "可见输出图已生成。",
                        "output_role": "交付图",
                        "primary_deliverable": "当前用户要求的图片",
                        "secondary_elements": [],
                        "actual": "mock 环境中的可见输出图。",
                        "goal_match": True,
                        "task_match": True,
                        "deliverable_match": True,
                        "mismatch_reason": "",
                        "failure_type": "none",
                        "usable_as_anchor": True,
                        "identity": {},
                        "visual_language": {},
                        "inheritance_facts": [],
                        "allowed_changes": [],
                        "strengths": ["已生成可验收输出"],
                        "issues": [],
                    }
                ],
                "batch_review": {
                    "summary": "mock 输出通过验收。",
                    "all_outputs_match_targets": True,
                    "has_batch_issue": False,
                    "issues": [],
                    "failed_indices": [],
                    "suggested_next": "finish",
                },
                "tool_calls": [],
                "is_complete": True,
                "needs_user_input": False,
                "next_phase": "done",
            },
            ensure_ascii=False,
        )

    if any(key in prompt_text for key in ("查一下", "搜索", "检索", "调研", "找一下", "常见", "趋势", "参考")):
        return json.dumps(
            {
                "message": "（mock）当前不执行外部检索，先基于已有知识回答。",
                "observations": [],
                "tool_calls": [],
                "is_complete": True,
                "needs_user_input": False,
                "next_phase": "idle",
            },
            ensure_ascii=False,
        )

    if any(key in prompt_text for key in ("改", "修改", "替换", "换成", "调整", "继续")):
        tool_call = {
            "name": "generate_image",
            "arguments": {
                "task": prompt_text,
                "reference": [{"label": "图0", "artifact_index": 0}],
                "image_count": 1,
            },
        }
        phase = "refining"
        message = "（mock）收到，按参考图继续改。"
    elif any(key in prompt_text for key in ("套图", "系列", "一套", "每个", "多张", "组合")):
        tool_call = {
            "name": "generate_image",
            "arguments": {
                "items": [
                    {"name": "主视觉海报", "task": f"{prompt_text}：主视觉海报"},
                    {"name": "杯身", "task": f"{prompt_text}：杯身"},
                    {"name": "外卖袋", "task": f"{prompt_text}：外卖袋"},
                    {"name": "社媒方图", "task": f"{prompt_text}：社媒方图"},
                ]
            },
        }
        phase = "pack_ready"
        message = "（mock）先按套图走。"
    else:
        tool_call = {
            "name": "generate_image",
            "arguments": {
                "task": prompt_text,
                "image_count": 1,
            },
        }
        phase = "anchor_pending"
        message = "（mock）先出一个方向。"

    return json.dumps(
        {
            "message": message,
            "observations": [],
            "tool_calls": [tool_call],
            "is_complete": False,
            "needs_user_input": False,
            "next_phase": phase,
        },
        ensure_ascii=False,
    )


async def _mock_chat(self, messages, **kwargs):  # noqa: ANN001
    prompt_text = _extract_last_user_text(messages or [])
    if _mock_messages_are_artist_runtime(messages or []):
        content = _mock_artist_turn_text(prompt_text, has_visible_output=_mock_messages_have_visible_output(messages or []))
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
    return _mock_image_context_response(prompt_text)


async def _mock_chat_stream(self, messages, **kwargs):  # noqa: ANN001
    prompt_text = _extract_last_user_text(messages or [])
    content = _mock_artist_turn_text(prompt_text, has_visible_output=_mock_messages_have_visible_output(messages or []))
    yield content, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


async def _mock_chat_stream_with_tools(self, messages, tools, **kwargs):  # noqa: ANN001
    prompt_text = _extract_last_user_text(messages or [])
    content = _mock_artist_turn_text(prompt_text, has_visible_output=_mock_messages_have_visible_output(messages or []))
    yield {"type": "token", "content": content}
    yield {"type": "usage", "tokens_in": 0, "tokens_out": 0}


def _mock_generate_images_core_factory():
    root = Path(__file__).resolve().parents[2]
    for candidate in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (candidate / "tmp_real_artist_full_parallel").exists():
            root = candidate
            break
    fixtures = {
        "huijing_anchor": root / "tmp_real_artist_full_parallel" / "huijing_anchor.png",
        "anchor": root / "tmp_real_artist_full_parallel" / "anchor.png",
        "cat": root / "tmp_real_artist_full_parallel" / "cat.jpg",
        "poster": root / "tmp_real_artist_full_parallel" / "poster.png",
        "cup": root / "tmp_real_artist_full_parallel" / "cup.png",
        "bag": root / "tmp_real_artist_full_parallel" / "bag.png",
        "social": root / "tmp_real_artist_full_parallel" / "social.png",
        "sign": root / "tmp_real_artist_full_parallel" / "sign.png",
        "cup_refined": root / "tmp_real_artist_full_parallel" / "cup_refined.png",
        "sign_lightbox": root / "tmp_real_artist_t4_t7" / "t5_sign_cold_lightbox.png",
        "sign_fix": root / "tmp_real_artist_t4_t7" / "t6_unified_sign_fix.png",
    }
    fallback_paths = [
        path for path in fixtures.values()
        if path.exists()
    ]

    def _ensure_huijing_fixture(path: Path) -> None:
        try:
            from PIL import Image, ImageDraw, ImageFont
        except Exception:
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (1280, 1280), "#111111")
        draw = ImageDraw.Draw(image)
        font_cn = "C:/Windows/Fonts/msyh.ttc"
        font_en = "C:/Windows/Fonts/arial.ttf"
        title = ImageFont.truetype(font_cn, 92)
        subtitle = ImageFont.truetype(font_en, 42)
        label = ImageFont.truetype(font_cn, 30)
        small = ImageFont.truetype(font_en, 24)

        draw.rectangle((0, 0, 1280, 1280), fill="#111111")
        for y in range(96, 1180, 52):
            draw.line((70, y, 1210, y), fill="#222426", width=1)
        for x in range(90, 1200, 76):
            draw.line((x, 70, x, 1210), fill="#1A1D1F", width=1)
        draw.rectangle((44, 44, 1236, 1236), outline="#D9D9D6", width=3)
        draw.rectangle((70, 70, 1210, 560), fill="#090909", outline="#B9BEC2", width=2)
        draw.text((110, 120), "灰径咖啡", fill="#F4F4F2", font=title)
        draw.text((114, 116), "灰径咖啡", fill="#1EB7C6", font=title)
        draw.text((106, 124), "灰径咖啡", fill="#D64242", font=title)
        draw.text((116, 230), "HUIJING COFFEE", fill="#F4F4F2", font=subtitle)
        draw.line((116, 310, 520, 310), fill="#1EB7C6", width=4)
        draw.line((116, 326, 420, 326), fill="#D64242", width=4)
        draw.text((116, 350), "black / white / gray with blue, cyan and red accents", fill="#C6CDD2", font=small)
        draw.text((116, 402), "quiet urban specialty coffee identity", fill="#C6CDD2", font=small)
        for x, y, w, color in [
            (120, 462, 210, "#1EB7C6"),
            (156, 492, 320, "#2E5CFF"),
            (106, 518, 250, "#D64242"),
            (420, 454, 150, "#F4F4F2"),
            (460, 506, 90, "#D64242"),
        ]:
            draw.rectangle((x, y, x + w, y + 8), fill=color)

        draw.ellipse((760, 125, 1030, 395), outline="#F4F4F2", width=6)
        draw.arc((725, 95, 1065, 430), 210, 330, fill="#1EB7C6", width=5)
        draw.arc((725, 95, 1065, 430), 30, 150, fill="#D64242", width=5)
        draw.arc((700, 70, 1090, 455), 250, 300, fill="#2E5CFF", width=5)
        draw.line((895, 110, 895, 420), fill="#777777", width=2)
        draw.line((740, 260, 1050, 260), fill="#777777", width=2)
        draw.rectangle((815, 210, 972, 235), fill="#111111")
        draw.rectangle((842, 300, 1055, 318), fill="#111111")

        palette = [("#101010", "BLACK"), ("#F7F7F5", "WHITE"), ("#B9BEC2", "GRAY"), ("#2E5CFF", "BLUE"), ("#1EB7C6", "CYAN"), ("#D64242", "RED")]
        x = 110
        for color, name in palette:
            draw.rectangle((x, 625, x + 115, 740), fill=color, outline="#F4F4F2")
            draw.text((x, 760), name, fill="#F4F4F2", font=small)
            x += 150

        panels = [
            (110, 860, 350, 1090, "POSTER"),
            (405, 860, 645, 1090, "CUP"),
            (700, 860, 940, 1090, "BAG"),
            (995, 860, 1195, 1090, "SIGN"),
        ]
        for left, top, right, bottom, name in panels:
            draw.rectangle((left, top, right, bottom), fill="#1B1B1B", outline="#D9D9D6", width=2)
            draw.rectangle((left + 28, top + 26, right - 28, bottom - 62), fill="#090909", outline="#4B4F52")
            draw.text((left + 48, top + 52), "灰径", fill="#F4F4F2", font=label)
            draw.line((left + 48, top + 105, right - 50, top + 105), fill="#1EB7C6", width=3)
            draw.line((left + 48, top + 116, right - 90, top + 116), fill="#D64242", width=3)
            draw.line((left + 48, top + 128, right - 120, top + 128), fill="#2E5CFF", width=3)
            draw.text((left + 42, bottom - 48), name, fill="#F4F4F2", font=small)

        image.save(path)

    def _fixture_for_prompt(prompt: str) -> Path | None:
        label = _select_mock_image_fixture_label(prompt)
        path = fixtures.get(label)
        if label == "huijing_anchor" and path:
            _ensure_huijing_fixture(path)
        if path and path.exists():
            return path
        return fallback_paths[0] if fallback_paths else None

    def _persist_fixture(path: Path | None) -> str:
        from app.config import settings as _settings

        suffix = ".png"
        if path and path.exists() and path.suffix:
            suffix = path.suffix.lower()
        filename = f"mock_{uuid.uuid4().hex[:12]}{suffix}"
        output_path = _settings.UPLOAD_DIR / filename
        if path and path.exists():
            output_path.write_bytes(path.read_bytes())
        else:
            payload = _MOCK_BLACK_PNG_DATA_URL.split(",", 1)[1]
            output_path.write_bytes(base64.b64decode(payload))
        return f"http://127.0.0.1:{_settings.SERVER_PORT}/generated/{filename}"

    async def _mock_generate_images_core(**kwargs):  # noqa: ANN001
        image_count = int(kwargs.get("image_count") or kwargs.get("n") or 1)
        prompt = str(kwargs.get("prompt") or "")
        fixture = _fixture_for_prompt(prompt)
        urls = [_persist_fixture(fixture) for _ in range(image_count)]
        return urls, 0, 0

    return _mock_generate_images_core


def _mock_context(mock_mode: str):
    if not mock_mode:
        return nullcontext()

    stack = ExitStack()
    if mock_mode in ("image", "all"):
        stack.enter_context(
            patch("app.services.generate_service.generate_images_core", new=_mock_generate_images_core_factory())
        )
    if mock_mode == "all":
        stack.enter_context(patch("app.utils.llm_client.LLMClient.chat", new=_mock_chat))
        stack.enter_context(patch("app.utils.llm_client.LLMClient.chat_stream", new=_mock_chat_stream))
        stack.enter_context(patch("app.utils.llm_client.LLMClient.chat_stream_with_tools", new=_mock_chat_stream_with_tools))
    return stack


async def _ensure_session(db, session_id: str, title: str) -> str:
    if session_id:
        detail = await get_session_detail(db, session_id)
        if not detail:
            raise SystemExit(f"Session not found: {session_id}")
        return session_id

    session = await create_session(db, SessionCreate(title=title))
    return session.id


async def _create_new_session(db, title: str) -> str:
    session = await create_session(db, SessionCreate(title=title))
    return session.id


async def _copy_session(db, source_session_id: str, title: str = "") -> dict[str, Any]:
    source = await db.get(Session, source_session_id)
    if not source:
        raise SystemExit(f"Session not found: {source_session_id}")

    result = await db.execute(
        select(Message)
        .where(Message.session_id == source_session_id)
        .order_by(Message.created_at.asc())
    )
    source_messages = list(result.scalars().all())

    new_session = Session(
        title=title or f"{source.title} copy",
        status="idle",
    )
    db.add(new_session)
    await db.flush()
    new_session.metadata_ = _copy_session_metadata(source.metadata_, new_session.id)

    for message in source_messages:
        copied = Message(
            session_id=new_session.id,
            role=message.role,
            content=message.content,
            message_type=message.message_type,
            metadata_=json.loads(json.dumps(message.metadata_ or {}, ensure_ascii=False)),
            created_at=message.created_at,
        )
        db.add(copied)

    await db.commit()
    await db.refresh(new_session)
    return {
        "source_session_id": source_session_id,
        "session_id": new_session.id,
        "title": new_session.title,
        "messages": len(source_messages),
    }


async def _rename_session(db, session_id: str, title: str) -> dict[str, Any]:
    session = await db.get(Session, session_id)
    if not session:
        raise SystemExit(f"Session not found: {session_id}")
    cleaned_title = str(title or "").strip()
    if not cleaned_title:
        raise SystemExit("usage: artist session rename <uuid> <title>")
    old_title = session.title
    session.title = cleaned_title
    await db.commit()
    await db.refresh(session)
    return {
        "session_id": session.id,
        "old_title": old_title,
        "title": session.title,
    }


async def _list_session_rows(db) -> list[dict[str, Any]]:
    sessions = await list_sessions(db)
    return sessions


async def _load_ct_session_messages(db, session_id: str, limit: int = 10) -> list[dict[str, str]]:
    if not session_id:
        return []
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .where(Message.role.in_(["user", "assistant"]))
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    rows = list(reversed(result.scalars().all()))
    messages: list[dict[str, str]] = []
    for row in rows:
        content = (row.content or "").strip()
        if not content:
            continue
        role = "assistant" if row.role == "assistant" else "user"
        messages.append({"role": role, "content": content})
    return messages


def _ct_artifact_to_metadata(artifact) -> dict[str, Any]:
    data = artifact.model_dump() if hasattr(artifact, "model_dump") else dict(artifact)
    metadata = dict(data.get("metadata") or {})
    if data.get("parent_url") and not metadata.get("parent_url"):
        metadata["parent_url"] = data["parent_url"]
    if data.get("root_url") and not metadata.get("root_url"):
        metadata["root_url"] = data["root_url"]
    return {
        **data,
        "type": "image",
        "metadata": metadata,
    }


async def _persist_ct_result(db, session_id: str, result) -> None:
    if isinstance(result, dict):
        artifacts_source = result.get("artifacts") or []
        message = str(result.get("message") or "")
        goal = str(result.get("goal") or message)
        status = str(result.get("phase") or "completed")
        tokens_in = int(result.get("tokens_in") or 0)
        tokens_out = int(result.get("tokens_out") or 0)
        cost = float(result.get("cost") or 0.0)
        runtime_meta = dict(result.get("artist_runtime") or {})
        visual_memory = runtime_meta.get("visual_memory", {})
        lineage = runtime_meta.get("lineage", {})
        steps = runtime_meta.get("steps", [])
    else:
        artifacts_source = result.artifacts
        message = result.message
        goal = result.goal
        status = result.status
        tokens_in = result.tokens_in
        tokens_out = result.tokens_out
        cost = result.cost
        visual_memory = result.visual_memory
        lineage = result.lineage
        steps = [step.model_dump() for step in result.steps]

    if not session_id or not artifacts_source:
        return

    artifacts = [_ct_artifact_to_metadata(artifact) for artifact in artifacts_source]
    generated_urls = [
        artifact["url"]
        for artifact in artifacts
        if artifact.get("url") and not (artifact.get("metadata") or {}).get("initial_reference")
    ]
    all_urls = [artifact["url"] for artifact in artifacts if artifact.get("url")]
    parent_urls = []
    for artifact in artifacts:
        parent_url = artifact.get("parent_url") or (artifact.get("metadata") or {}).get("parent_url", "")
        if parent_url and parent_url.startswith("http") and parent_url not in parent_urls:
            parent_urls.append(parent_url)

    await add_system_message(
        db,
        session_id,
        message or goal,
        message_type="artist",
        metadata={
            "message": message or goal,
            "images": generated_urls,
            "final_images": generated_urls,
            "artifacts": artifacts,
            "blocks": [message] if message else [],
            "persona": "artist",
            "phase": "idle" if status == "completed" else status,
            "artist_turn_id": "artist-runtime",
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost": cost,
            "source_image_urls": parent_urls,
            "generation_mode": "artist_runtime",
            "artist_runtime": {
                "goal": goal,
                "status": status,
                "visual_memory": visual_memory,
                "lineage": lineage,
                "steps": steps,
            },
        },
    )

    head_url = generated_urls[-1] if generated_urls else (all_urls[-1] if all_urls else "")
    if not head_url:
        return
    session_result = await db.execute(select(Session).where(Session.id == session_id))
    session = session_result.scalar_one_or_none()
    if session:
        meta = dict(session.metadata_ or {})
        meta["lineage_head_url"] = head_url
        session.metadata_ = meta
        await db.commit()


def _print_json_block(title: str, value: Any) -> None:
    print(f"\n[debug:{title}]")
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _print_result(session_id: str, result: dict[str, Any], created: bool, compact: bool = False) -> None:
    if created:
        print(f"[summary] session_id: {session_id}")
    else:
        print(f"[summary] session_id: {session_id} (reused)")

    message = result.get("message", "")
    phase = result.get("phase", "")
    artifacts = result.get("artifacts", []) or []

    if result.get("error"):
        print(f"[error] {result.get('error')}")
    if result.get("traceback") and not compact:
        print("\n[debug:traceback]")
        print(result.get("traceback"))

    print(f"[summary] phase: {phase}")
    if message:
        print(f"[summary] message: {message}")
    print(f"[summary] artifacts: {len(artifacts)}")
    for idx, art in enumerate(artifacts, start=1):
        url = art.get("url", "")
        prompt = art.get("prompt", "")
        if prompt:
            print(f"[artifact:{idx}] url: {url} | prompt: {prompt}")
        else:
            print(f"[artifact:{idx}] url: {url}")
        if not compact:
            metadata = art.get("metadata") if isinstance(art.get("metadata"), dict) else {}
            if metadata:
                print(f"[artifact:{idx}:meta] artifact_id: {metadata.get('artifact_id', '')}")
                print(f"[artifact:{idx}:meta] parent: {metadata.get('parent_artifact_id', '')} {metadata.get('parent_url', '')}")
                print(f"[artifact:{idx}:meta] root: {metadata.get('root_artifact_id', '')} {metadata.get('root_url', '')}")
                print(f"[artifact:{idx}:meta] source_image_urls: {json.dumps(metadata.get('source_image_urls', []), ensure_ascii=False)}")

    if compact:
        return

    print(f"[usage] tokens_in: {result.get('tokens_in', 0)}")
    print(f"[usage] tokens_out: {result.get('tokens_out', 0)}")
    print(f"[usage] cost: {result.get('cost', 0.0)}")
    _print_json_block("tool_calls", result.get("tool_calls", []))
    _print_json_block("tool_results", result.get("tool_results", []))
    print("\n[debug:system_prompt]")
    print(ARTIST_RUNTIME_SYSTEM)
    runtime = result.get("artist_runtime")
    if isinstance(runtime, dict):
        _print_json_block("llm_input_messages", runtime.get("messages", []))
        _print_json_block("visual_memory", runtime.get("visual_memory", {}))
        _print_json_block("loop_steps", runtime.get("steps", []))
        _print_json_block("runtime_full", runtime)
    else:
        _print_json_block("artist_runtime", runtime)


def _parse_sse_payload(sse_line: str) -> dict[str, Any] | None:
    for line in sse_line.splitlines():
        if not line.startswith("data:"):
            continue
        raw = line.split(":", 1)[1].strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        payload = data.get("payload")
        return payload if isinstance(payload, dict) else None
    return None


def _print_cli_event(payload: dict[str, Any], state: dict[str, Any], compact: bool = False) -> None:
    event_type = str(payload.get("type") or "")
    if not compact:
        label = event_type or "unknown"
        print(f"\n[event:{label}]")
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str), flush=True)
    if event_type == "debug":
        if compact:
            return
        kind = str(payload.get("kind") or "event")
        body = {key: value for key, value in payload.items() if key not in {"type", "session_id", "kind"}}
        print(f"\n[debug:{kind}]")
        print(json.dumps(body, ensure_ascii=False, indent=2, default=str), flush=True)
        return
    if event_type == "task_started":
        print("[progress] started", flush=True)
        return
    if event_type == "task_progress":
        message = str(payload.get("message") or "")
        status = str(payload.get("status") or "").replace("TaskStatus.", "").lower()
        if status == "idle":
            return
        if message:
            print(f"[progress] {message}", flush=True)
        elif status:
            print(f"[progress] {status}", flush=True)
        return
    if event_type == "artist_turn_started":
        print(f"[runtime] turn {payload.get('artist_turn_id', '')} started", flush=True)
        return
    if event_type == "artist_reply_delta":
        if not state.get("reply_open"):
            print("[reply] ", end="", flush=True)
            state["reply_open"] = True
        print(str(payload.get("content") or ""), end="", flush=True)
        return
    if event_type == "artist_image_ready":
        if state.get("reply_open"):
            print(flush=True)
            state["reply_open"] = False
        artifact = payload.get("artifact") if isinstance(payload.get("artifact"), dict) else {}
        url = artifact.get("url", "")
        prompt = artifact.get("prompt", "")
        if prompt:
            print(f"[image_ready] {url} | {prompt}", flush=True)
        else:
            print(f"[image_ready] {url}", flush=True)
        return
    if event_type == "artist_turn_done":
        if state.get("reply_open"):
            print(flush=True)
            state["reply_open"] = False
        phase = str(payload.get("phase") or "")
        print(f"[runtime] done phase={phase}", flush=True)
        return
    if event_type == "agent_done":
        print(f"[progress] completed images={payload.get('image_count', 0)}", flush=True)
        return
    if event_type == "agent_error":
        print(f"[error] {payload.get('error', '')}", flush=True)


async def _stream_cli_events(session_id: str, stop_event: asyncio.Event, compact: bool = False) -> None:
    queue_id, queue = await global_task_manager.subscribe(session_id=session_id, last_event_id="cli-live")
    state: dict[str, Any] = {"reply_open": False}
    started = asyncio.get_running_loop().time()
    try:
        while not stop_event.is_set():
            try:
                sse_line = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                elapsed = int(asyncio.get_running_loop().time() - started)
                if state.get("reply_open"):
                    print(flush=True)
                    state["reply_open"] = False
                print(f"[progress] still running ({elapsed}s)", flush=True)
                continue
            payload = _parse_sse_payload(str(sse_line))
            if payload:
                key = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
                if key == state.get("last_payload_key"):
                    continue
                state["last_payload_key"] = key
                _print_cli_event(payload, state, compact=compact)
    finally:
        if state.get("reply_open"):
            print(flush=True)
        global_task_manager.unsubscribe(queue_id)


def _print_session_list(sessions: list[dict[str, Any]]) -> None:
    if not sessions:
        print("[session_list] no sessions")
        return
    for item in sessions:
        title = item.get("title", "")
        sid = item.get("id", "")
        print(f"[session_list] {title}\t{sid}")


async def _resolve_image_provider_id(db, explicit_provider_id: str = "") -> str:
    if explicit_provider_id:
        result = await db.execute(select(ApiProvider).where(ApiProvider.id == explicit_provider_id))
        provider = result.scalar_one_or_none()
        if not provider:
            raise SystemExit(f"Image provider not found: {explicit_provider_id}")
        return explicit_provider_id

    provider_id = await generate_service._get_default_provider(db, "default_image_provider_id")
    if provider_id:
        return provider_id

    result = await db.execute(
        select(ApiProvider).where(
            ApiProvider.provider_type == ProviderType.image_gen,
            ApiProvider.is_active == True,
        )
    )
    provider = result.scalars().first()
    if not provider:
        raise SystemExit("No image provider configured")
    return provider.id


async def _resolve_llm_provider_id(db, explicit_provider_id: str = "") -> str:
    if explicit_provider_id:
        result = await db.execute(select(ApiProvider).where(ApiProvider.id == explicit_provider_id))
        provider = result.scalar_one_or_none()
        if not provider:
            raise SystemExit(f"LLM provider not found: {explicit_provider_id}")
        return explicit_provider_id

    provider_id = await generate_service._get_artist_runtime_provider(db)
    if provider_id:
        return provider_id

    result = await db.execute(
        select(ApiProvider).where(
            ApiProvider.provider_type == ProviderType.llm,
            ApiProvider.is_active == True,
        )
    )
    provider = result.scalars().first()
    if not provider:
        raise SystemExit("No LLM provider configured")
    return provider.id


async def _build_vlm_call(db, args):
    base_url = args.vlm_base_url or os.environ.get("LAMIMAGER_CT_VLM_BASE_URL", "")
    model_id = args.vlm_model_id or os.environ.get("LAMIMAGER_CT_VLM_MODEL_ID", "")
    api_key = args.vlm_api_key or os.environ.get("LAMIMAGER_CT_VLM_API_KEY", "")

    if args.vlm_provider_id:
        result = await db.execute(select(ApiProvider).where(ApiProvider.id == args.vlm_provider_id))
        provider = result.scalar_one_or_none()
        if not provider:
            raise SystemExit(f"VLM provider not found: {args.vlm_provider_id}")
        base_url, api_key = await resolve_provider_vendor(db, provider)
        model_id = provider.model_id

    if not (base_url and model_id and api_key):
        return None

    def _prepare_messages_for_remote_vlm(messages):
        from io import BytesIO
        from urllib.parse import urlparse
        from app.config import settings as _settings

        def _local_image_path(url: str) -> Path | None:
            parsed = urlparse(url)
            if parsed.hostname not in {"127.0.0.1", "localhost"} or not parsed.path.startswith("/generated/"):
                return None
            filename = parsed.path.rsplit("/", 1)[-1]
            path = (_settings.UPLOAD_DIR / filename).resolve()
            upload_dir = _settings.UPLOAD_DIR.resolve()
            if upload_dir not in path.parents or not path.exists():
                return None
            return path

        def _open_image_from_url(url: str):
            from PIL import Image

            if url.startswith("data:image"):
                payload = url.split(",", 1)[1]
                return Image.open(BytesIO(base64.b64decode(payload)))
            path = _local_image_path(url)
            if path is None:
                return None
            return Image.open(path)

        def _compact_local_image_url(url: str) -> str:
            path = _local_image_path(url)
            if path is None:
                return url
            try:
                from PIL import Image

                with Image.open(path) as image:
                    image = image.convert("RGB")
                    image.thumbnail((320, 320))
                    buffer = BytesIO()
                    image.save(buffer, format="JPEG", quality=60, optimize=True)
                payload = base64.b64encode(buffer.getvalue()).decode("ascii")
                return f"data:image/jpeg;base64,{payload}"
            except Exception:
                payload = base64.b64encode(path.read_bytes()).decode("ascii")
                return f"data:image/png;base64,{payload}"

        def _contact_sheet_urls(urls: list[str]) -> list[str]:
            try:
                items = []
                for idx, url in enumerate(urls):
                    data_url = _compact_local_image_url(url)
                    if not isinstance(data_url, str) or not data_url.startswith("data:image"):
                        continue
                    items.append({
                        "index": idx,
                        "label": f"图{idx}",
                        "image_data_url": data_url,
                    })
                sheets = build_review_contact_sheets(items, max_items_per_sheet=4)
                return [sheet.data_url for sheet in sheets]
            except Exception:
                return []

        prepared = []
        for message in messages or []:
            if not isinstance(message, dict):
                prepared.append(message)
                continue
            copied = dict(message)
            content = copied.get("content")
            if isinstance(content, list):
                image_urls = [
                    part.get("image_url", {}).get("url")
                    for part in content
                    if isinstance(part, dict)
                    and isinstance(part.get("image_url"), dict)
                    and isinstance(part.get("image_url", {}).get("url"), str)
                ]
                text_parts = [
                    str(part.get("text") or "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                already_contact_sheets = any("验收拼图" in text or "contact_sheets" in text for text in text_parts)
                sheet_urls = _contact_sheet_urls(image_urls) if len(image_urls) > 1 and not already_contact_sheets else []
                new_content = []
                for part in content:
                    if not isinstance(part, dict):
                        new_content.append(part)
                        continue
                    if sheet_urls and part.get("type") == "image_url":
                        continue
                    new_part = dict(part)
                    image_url = new_part.get("image_url")
                    if isinstance(image_url, dict) and isinstance(image_url.get("url"), str):
                        new_image_url = dict(image_url)
                        new_image_url["url"] = _compact_local_image_url(new_image_url["url"])
                        new_part["image_url"] = new_image_url
                    new_content.append(new_part)
                if sheet_urls:
                    new_content.append({
                        "type": "text",
                        "text": "上面候选图已合并成标号预览拼图；选择 reference_images 时仍使用文字中的 artifact_id 或图号。",
                    })
                    for sheet_url in sheet_urls:
                        new_content.append({
                            "type": "image_url",
                            "image_url": {"url": sheet_url, "detail": "low"},
                        })
                copied["content"] = new_content
            prepared.append(copied)
        system_parts = [
            str(message.get("content") or "")
            for message in prepared
            if isinstance(message, dict) and message.get("role") == "system"
        ]
        if len(system_parts) <= 1:
            return prepared
        collapsed = [{"role": "system", "content": "\n\n".join(system_parts)}]
        collapsed.extend(
            message
            for message in prepared
            if not (isinstance(message, dict) and message.get("role") == "system")
        )
        return collapsed

    if base_url.rstrip("/").endswith("/v2"):
        endpoint = f"{base_url.rstrip('/')}/chat/completions"

        async def vlm_call(messages, kwargs):
            prepared_messages = _prepare_messages_for_remote_vlm(messages)
            has_image = any(
                isinstance(message, dict)
                and isinstance(message.get("content"), list)
                and any(isinstance(part, dict) and part.get("type") == "image_url" for part in message.get("content", []))
                for message in prepared_messages
            )
            payload = {
                "model": model_id,
                "messages": prepared_messages,
                "temperature": kwargs.get("temperature", 0.4),
                "max_tokens": kwargs.get("max_tokens", 1200),
            }
            if kwargs.get("response_format") and not has_image:
                payload["response_format"] = kwargs["response_format"]
            if os.environ.get("LAMIMAGER_DEBUG_VLM"):
                image_count = sum(
                    1
                    for message in prepared_messages
                    if isinstance(message, dict) and isinstance(message.get("content"), list)
                    for part in message.get("content", [])
                    if isinstance(part, dict) and part.get("type") == "image_url"
                )
                print(
                    f"[debug:vlm] messages={len(prepared_messages)} images={image_count} "
                    f"bytes={len(json.dumps(payload, ensure_ascii=False))} "
                    f"response_format={'response_format' in payload}",
                )
                for idx, message in enumerate(prepared_messages):
                    if not isinstance(message, dict):
                        print(f"[debug:vlm_message] {idx}: non-dict")
                        continue
                    content = message.get("content")
                    if isinstance(content, list):
                        kinds = [part.get("type") if isinstance(part, dict) else type(part).__name__ for part in content]
                        preview = f"list:{kinds}"
                    else:
                        preview = str(content or "").replace("\n", " ")[:160]
                    print(f"[debug:vlm_message] {idx}: role={message.get('role')} content={preview}")
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(endpoint, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=600)) as resp:
                    text = await resp.text()
                    if resp.status != 200:
                        raise RuntimeError(f"VLM API error {resp.status}: {text[:500]}")
                    data = json.loads(text)
            return LLMClient.extract_content(data), data.get("usage", {})

        return vlm_call

    client = LLMClient(base_url=base_url, api_key=api_key, model_id=model_id)

    async def vlm_call(messages, kwargs):
        response = await client.chat(messages=_prepare_messages_for_remote_vlm(messages), **kwargs)
        return LLMClient.extract_content(response), response.get("usage", {})

    return vlm_call


def _print_image_result(prompt: str, urls: list[str], tokens_in: int, tokens_out: int) -> None:
    print(f"[image_command] prompt: {prompt}")
    print(f"[image_command] images: {len(urls)}")
    for idx, url in enumerate(urls, start=1):
        print(f"[image_command:{idx}] url: {url}")
    if tokens_in or tokens_out:
        print(f"[usage] tokens_in: {tokens_in}")
        print(f"[usage] tokens_out: {tokens_out}")


async def _run_image_command(db, args) -> int:
    prompt = _join_prompt(list(args.args or [])[1:])
    if not prompt:
        raise SystemExit('usage: artist image "prompt"')

    provider_id = await _resolve_image_provider_id(db, args.image_provider_id)
    with _mock_context(args.mock):
        urls, tokens_in, tokens_out = await generate_service.generate_images_core(
            db=db,
            provider_id=provider_id,
            prompt=prompt,
            image_count=args.image_count,
            image_size=args.image_size,
            negative_prompt=args.negative_prompt,
            reference_images=args.reference_images or None,
            session_id=args.session_id or None,
        )

    _print_image_result(prompt, urls, tokens_in, tokens_out)
    return 0


async def _run_ct_command(db, args) -> int:
    goal = _join_prompt(list(args.args or [])[1:])
    if not goal:
        raise SystemExit('usage: artist ct "complex task"')

    image_provider_id = await _resolve_image_provider_id(db, args.image_provider_id)
    model_call = await _build_vlm_call(db, args)
    if model_call is None:
        llm_provider_id = await _resolve_llm_provider_id(db, args.llm_provider_id)
        provider_result = await db.execute(select(ApiProvider).where(ApiProvider.id == llm_provider_id))
        provider = provider_result.scalar_one_or_none()
        if not provider:
            raise SystemExit(f"LLM provider not found: {llm_provider_id}")
        base_url, api_key = await resolve_provider_vendor(db, provider)
        client = LLMClient(base_url=base_url, api_key=api_key, model_id=provider.model_id)

        async def model_call(messages, kwargs):
            response = await client.chat(messages=messages, **kwargs)
            return LLMClient.extract_content(response), response.get("usage", {})

    async def image_generate(**kwargs):
        return await generate_service.generate_images_core(
            db=db,
            provider_id=image_provider_id,
            session_id=args.session_id or None,
            **kwargs,
        )

    runtime = ArtistRuntime(
        deps=ArtistRuntimeDeps(
            llm_call=model_call,
            image_generate=image_generate,
            delegate_agent=None,
        ),
        max_steps=max(1, args.max_steps),
        image_size=args.image_size,
        negative_prompt=args.negative_prompt,
    )

    initial_messages = await _load_ct_session_messages(db, args.session_id)
    with _mock_context(args.mock):
        from app.core.artist.core_kernel_adapter import run_core_kernel, kernel_result_to_service_dict
        kernel_result = await run_core_kernel(
            runtime,
            goal,
            session_id=args.session_id or f"artist-cli-{uuid.uuid4().hex}",
            max_steps=max(1, args.max_steps),
        )
        result = kernel_result_to_service_dict(kernel_result, artist_turn_id=f"artist-cli-{uuid.uuid4().hex}")
    await _persist_ct_result(db, args.session_id, result)

    print(f"[ct] goal: {goal}")
    print(f"[ct] status: {result.get('phase', 'completed')}")
    if result.get("message"):
        print(f"[ct] message: {result['message']}")
    runtime_meta = result.get("artist_runtime") or {}
    visual_memory = runtime_meta.get("visual_memory") or {}
    if visual_memory:
        print(f"[ct:visual_memory] {json.dumps(visual_memory, ensure_ascii=False)}")
    steps = runtime_meta.get("steps") or []
    print(f"[ct] steps: {len(steps)}")
    for step in steps:
        if not isinstance(step, dict):
            continue
        index = step.get("index", "")
        print(f"[ct:step:{index}] decision: {step.get('decision', '')}")
        if step.get("phase"):
            print(f"[ct:step:{index}] phase: {step['phase']}")
        if step.get("error"):
            print(f"[ct:step:{index}:error] {step['error']}")
    artifacts = result.get("artifacts") or []
    print(f"[ct] artifacts: {len(artifacts)}")
    for idx, artifact in enumerate(artifacts):
        art_url = artifact.get("url", "") if isinstance(artifact, dict) else getattr(artifact, "url", "")
        art_prompt = (artifact.get("metadata") or {}).get("prompt", "") if isinstance(artifact, dict) else getattr(artifact, "prompt", "")
        print(f"[ct:artifact:{idx}] {art_url} | {art_prompt}")
    return 0


async def _run_turn(
    db,
    *,
    session_id: str,
    prompt: str,
    args,
    created: bool,
) -> dict[str, Any]:
    request = GenerateRequest(
        session_id=session_id,
        prompt=prompt,
        image_count=args.image_count,
        image_size=args.image_size,
        negative_prompt=args.negative_prompt,
        refine_mode=args.refine_mode,
        selected_image_url=args.selected_image_url,
        reference_images=args.reference_images,
        max_loop_steps=1 if args.one_loop else None,
    )

    with ExitStack() as stack:
        stack.enter_context(_mock_context(args.mock))
        model_call = await _build_vlm_call(db, args)
        if model_call is not None:
            async def _vlm_chat_stream(self, messages, **kwargs):  # noqa: ANN001
                content, usage = await model_call(messages, kwargs)
                yield content, usage

            async def _vlm_chat(self, messages, **kwargs):  # noqa: ANN001
                content, usage = await model_call(messages, kwargs)
                return {
                    "choices": [{"message": {"content": content}}],
                    "usage": usage or {},
                }

            stack.enter_context(patch("app.utils.llm_client.LLMClient.chat_stream", new=_vlm_chat_stream))
            stack.enter_context(patch("app.utils.llm_client.LLMClient.chat", new=_vlm_chat))
        stop_event = asyncio.Event()
        stream_task = asyncio.create_task(_stream_cli_events(session_id, stop_event, compact=bool(args.compact)))
        try:
            await asyncio.sleep(0)
            result = await handle_artist_generate(db, request)
        finally:
            stop_event.set()
            await asyncio.sleep(0)
            stream_task.cancel()
            try:
                await stream_task
            except asyncio.CancelledError:
                pass

    _print_result(session_id, result, created=created, compact=bool(args.compact))
    return result


async def _interactive_session(db, *, session_id: str, args) -> None:
    print(f"[interactive] session_id: {session_id}")
    print("[interactive] enter prompts, type /exit to quit")
    while True:
        try:
            prompt = input("artist> ").strip()
        except EOFError:
            print("[interactive] eof")
            break
        if not prompt:
            continue
        if prompt in {"/exit", "/quit", "exit", "quit"}:
            break
        await _run_turn(db, session_id=session_id, prompt=prompt, args=args, created=False)


async def _run_session_command(db, args) -> int:
    tokens = list(args.args or [])
    if len(tokens) < 2:
        raise SystemExit("usage: artist session ls | artist session new | artist session copy <uuid> | artist session rename <uuid> <title> | artist session <uuid> [prompt...]")

    action = tokens[1]
    if action == "ls":
        rows = await _list_session_rows(db)
        _print_session_list(rows)
        return 0

    if action == "new":
        session_id = await _create_new_session(db, args.title)
        print(f"[session_new] session_id: {session_id}")
        print(f"[session_new] title: {args.title}")
        return 0

    if action == "copy":
        if len(tokens) < 3:
            raise SystemExit("usage: artist session copy <uuid>")
        copied = await _copy_session(db, tokens[2], args.title if args.title != "Artist CLI" else "")
        print(f"[session_copy] source_session_id: {copied['source_session_id']}")
        print(f"[session_copy] session_id: {copied['session_id']}")
        print(f"[session_copy] title: {copied['title']}")
        print(f"[session_copy] messages: {copied['messages']}")
        return 0

    if action == "rename":
        if len(tokens) < 4:
            raise SystemExit("usage: artist session rename <uuid> <title>")
        renamed = await _rename_session(db, tokens[2], _join_prompt(tokens[3:]))
        print(f"[session_rename] session_id: {renamed['session_id']}")
        print(f"[session_rename] old_title: {renamed['old_title']}")
        print(f"[session_rename] title: {renamed['title']}")
        return 0

    session_id = action
    prompt = _join_prompt(tokens[2:])
    session_id = await _ensure_session(db, session_id, args.title)
    if prompt:
        await _run_turn(db, session_id=session_id, prompt=prompt, args=args, created=False)
        return 0

    await _interactive_session(db, session_id=session_id, args=args)
    return 0


async def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        async with async_session() as db:
            await init_db()
            if args.args and args.args[0] == "ct":
                return await _run_ct_command(db, args)
            if args.args and args.args[0] == "image":
                return await _run_image_command(db, args)
            if args.args and args.args[0] == "copy":
                if len(args.args) < 2:
                    raise SystemExit("usage: artist copy <uuid>")
                copied = await _copy_session(db, args.args[1], args.title if args.title != "Artist CLI" else "")
                print(f"[session_copy] source_session_id: {copied['source_session_id']}")
                print(f"[session_copy] session_id: {copied['session_id']}")
                print(f"[session_copy] title: {copied['title']}")
                print(f"[session_copy] messages: {copied['messages']}")
                return 0
            if args.args and args.args[0] == "rename":
                if len(args.args) < 3:
                    raise SystemExit("usage: artist rename <uuid> <title>")
                renamed = await _rename_session(db, args.args[1], _join_prompt(args.args[2:]))
                print(f"[session_rename] session_id: {renamed['session_id']}")
                print(f"[session_rename] old_title: {renamed['old_title']}")
                print(f"[session_rename] title: {renamed['title']}")
                return 0
            if args.args and args.args[0] == "session":
                return await _run_session_command(db, args)

            prompt = _join_prompt(args.args or [])
            if not prompt:
                parser.error("prompt is required")

            session_id = await _ensure_session(db, args.session_id, args.title)
            await _run_turn(db, session_id=session_id, prompt=prompt, args=args, created=not bool(args.session_id))
        return 0
    finally:
        await close_shared_session()


def main(argv: list[str] | None = None) -> int:
    engine.echo = False
    logging.getLogger().setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.ERROR)
    logging.getLogger("app.services.task_manager").setLevel(logging.ERROR)
    return asyncio.run(run(argv))


if __name__ == "__main__":
    raise SystemExit(main())
