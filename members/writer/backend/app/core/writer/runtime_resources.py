from __future__ import annotations

import asyncio
import datetime
import logging
import platform as _platform_mod
from pathlib import Path
from typing import Any

import httpx

from lamtools_core.llm import ChatMessage
from lamtools_core.prompt import PromptPart, prompt_parts_to_messages

from app.core.persona import get_writer_system_prompt
from app.core.prompt_assembler import get_writer_execution_discipline
from app.core.prompt_files import load_writer_prompt
from app.core.writer.skills import WriterSkillRegistry

logger = logging.getLogger(__name__)

_STREAM_HTTP_CLIENT: httpx.AsyncClient | None = None
_STREAM_HTTP_CLIENT_LOCK: asyncio.Lock | None = None
_MCP_REGISTRY_CACHE: dict[str, Any] = {}
_MCP_REGISTRY_LOCKS: dict[str, asyncio.Lock] = {}
_STATIC_PROMPT_CACHE: dict[str, tuple[tuple[Any, ...], list[ChatMessage]]] = {}
_STATIC_PROMPT_LOCKS: dict[str, asyncio.Lock] = {}


def _work_root_cache_key(work_root: str | Path | None) -> str:
    if not work_root:
        return ""
    try:
        return str(Path(work_root).resolve())
    except OSError:
        return str(work_root)


async def stream_http_client() -> httpx.AsyncClient:
    global _STREAM_HTTP_CLIENT, _STREAM_HTTP_CLIENT_LOCK
    client_type = httpx.AsyncClient
    cached_client_matches = (
        _STREAM_HTTP_CLIENT is not None
        and (not isinstance(client_type, type) or isinstance(_STREAM_HTTP_CLIENT, client_type))
    )
    if cached_client_matches and not bool(getattr(_STREAM_HTTP_CLIENT, "is_closed", False)):
        return _STREAM_HTTP_CLIENT
    if _STREAM_HTTP_CLIENT_LOCK is None:
        _STREAM_HTTP_CLIENT_LOCK = asyncio.Lock()
    async with _STREAM_HTTP_CLIENT_LOCK:
        cached_client_matches = (
            _STREAM_HTTP_CLIENT is not None
            and (not isinstance(client_type, type) or isinstance(_STREAM_HTTP_CLIENT, client_type))
        )
        if not cached_client_matches or bool(getattr(_STREAM_HTTP_CLIENT, "is_closed", False)):
            _STREAM_HTTP_CLIENT = httpx.AsyncClient(
                timeout=httpx.Timeout(300.0, connect=15.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                trust_env=False,
            )
        return _STREAM_HTTP_CLIENT


def _platform_prompt() -> str:
    platform_notes = ""
    if _platform_mod.system() == "Windows":
        platform_notes = load_writer_prompt("platform_windows")
    return load_writer_prompt(
        "platform",
        {
            "os_name": _platform_mod.system(),
            "platform": _platform_mod.platform(),
            "platform_notes": platform_notes,
        },
    )


def runtime_now_prompt() -> str:
    return "now: " + datetime.datetime.now().astimezone().strftime("%Y-%m-%d")


def _skill_signature(work_root: str) -> tuple[Any, ...]:
    return ("skills", WriterSkillRegistry().signature(work_root))


def _static_prompt_signature(work_root: str) -> tuple[Any, ...]:
    return (
        get_writer_system_prompt(),
        get_writer_execution_discipline(),
        _platform_prompt(),
        _skill_signature(work_root),
    )


def _static_prompt_parts(work_root: str) -> list[PromptPart]:
    parts: list[PromptPart] = [
        PromptPart(
            key="persona",
            kind="system",
            content=get_writer_system_prompt(),
            priority=10,
            metadata={"kind": "identity"},
        ),
        PromptPart(
            key="execution_discipline",
            kind="constraint",
            content=get_writer_execution_discipline(),
            priority=20,
        ),
        PromptPart(
            key="platform",
            kind="constraint",
            content=_platform_prompt(),
            priority=30,
        ),
    ]
    skill_index = WriterSkillRegistry().prompt_index(work_root)
    if skill_index:
        parts.append(PromptPart(
            key="skill_index",
            kind="system",
            content=skill_index,
            priority=50,
            metadata={"kind": "context"},
        ))
    return parts


def _build_static_prompt_messages(work_root: str) -> list[ChatMessage]:
    return prompt_parts_to_messages(_static_prompt_parts(work_root))


async def static_prompt_messages(work_root: str | Path | None) -> list[ChatMessage]:
    key = _work_root_cache_key(work_root)
    signature = _static_prompt_signature(key)
    cached = _STATIC_PROMPT_CACHE.get(key)
    if cached and cached[0] == signature:
        return list(cached[1])
    lock = _STATIC_PROMPT_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        cached = _STATIC_PROMPT_CACHE.get(key)
        if cached and cached[0] == signature:
            return list(cached[1])
        messages = _build_static_prompt_messages(key)
        _STATIC_PROMPT_CACHE[key] = (signature, messages)
        return list(messages)


async def cached_mcp_registry(work_root: str | Path | None) -> Any:
    key = _work_root_cache_key(work_root)
    cached = _MCP_REGISTRY_CACHE.get(key)
    if cached is not None:
        return cached
    lock = _MCP_REGISTRY_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        cached = _MCP_REGISTRY_CACHE.get(key)
        if cached is not None:
            return cached
        from app.core.mcp.registry import MCPToolRegistry
        registry = MCPToolRegistry(key)
        await registry.load()
        _MCP_REGISTRY_CACHE[key] = registry
        if registry.tools:
            logger.info(
                "MCP loaded: %d tools from %d servers",
                len(registry.tools),
                len(set(t.server for t in registry.tools)),
            )
        return registry


async def prewarm_writer_startup(work_root: str | Path | None) -> None:
    await asyncio.gather(
        static_prompt_messages(work_root),
        cached_mcp_registry(work_root),
    )


def schedule_writer_startup_prewarm(work_root: str | Path | None) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(prewarm_writer_startup(work_root))
    task.add_done_callback(_log_prewarm_failure)


def _log_prewarm_failure(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.debug("Writer startup prewarm failed", exc_info=True)


async def close_writer_runtime_resources() -> None:
    global _STREAM_HTTP_CLIENT
    if _STREAM_HTTP_CLIENT is not None and not bool(getattr(_STREAM_HTTP_CLIENT, "is_closed", False)):
        close_client = getattr(_STREAM_HTTP_CLIENT, "aclose", None)
        if close_client is not None:
            await close_client()
    _STREAM_HTTP_CLIENT = None
    registries = list(_MCP_REGISTRY_CACHE.values())
    _MCP_REGISTRY_CACHE.clear()
    _MCP_REGISTRY_LOCKS.clear()
    _STATIC_PROMPT_CACHE.clear()
    _STATIC_PROMPT_LOCKS.clear()
    for registry in registries:
        close = getattr(registry, "close", None)
        if close is None:
            continue
        try:
            await close()
        except Exception:
            logger.debug("MCP registry close failed", exc_info=True)
