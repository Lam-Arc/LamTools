"""Artist-to-CoreKernel adapter.

Implements the ``lamtools_core.kernel.RuntimeKit`` protocol by delegating to
existing ``ArtistRuntime`` business helpers.

Scope (stage-10 slice):
- Text-only LLM rounds **and simple VLM rounds** with uploaded/visible images
- Five tools: ``generate_image``, ``finish``, ``ask_user``, ``inspect_lineage``, ``set_lineage_head``
- Visual context: a small generic ``VisualContextItem`` list carried in
  ``RuntimeState.metadata`` — no cloning of legacy visual workspace / lineage
- **VLM visual verification** after ``generate_image``: the Kit's ``verify``
  sends artifact images to VLM for acceptance check; on failure it produces a
  ``repair_prompt`` that the Kernel injects into the next iteration
- **Lightweight lineage**: ``inspect_lineage`` returns head/branch/items from
  visual context + ``state.metadata['lineage_items']``; ``set_lineage_head``
  switches HEAD by index or URL; ``generate_image`` appends new artifacts to
  ``lineage_items`` — no DAG system, just metadata
- No ``delegate_agent``, no streaming, no contact sheets
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable
from uuid import uuid4

from lamtools_core.event import CoreEvent, EventSink
from lamtools_core.kernel.kit import RuntimeKit
from lamtools_core.kernel.loop import CoreLoopKernel
from lamtools_core.kernel.policy import LoopPolicy
from lamtools_core.kernel.state import (
    KernelResult,
    KernelStep,
    KernelTurn,
    LoopDecision,
    VerificationResult,
)
from lamtools_core.llm import (
    ChatMessage,
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMUsage,
)
from lamtools_core.prompt import PromptContext
from lamtools_core.runtime import RuntimeState, RuntimeStateStore, RuntimeTurnInput
from lamtools_core.tool import ToolArtifact, ToolCall, ToolResult

from app.core.artist.runtime import (
    ARTIST_RUNTIME_SYSTEM,
    ArtistRuntime,
)


# ---------------------------------------------------------------------------
# VLM verification prompt
# ---------------------------------------------------------------------------


_VERIFICATION_SYSTEM_PROMPT = """\
你是一个视觉验收助手。你会看到一张或多张生成的图片以及原始生图目标。
请判断图片是否符合目标要求。

输出 JSON，不要 markdown：
{
  "passed": true/false,
  "summary": "一句话描述验收结论",
  "repair_prompt": "如果 passed=false，给出具体的修复指令；passed=true 时留空"
}

判断标准：
- 图片主体与目标一致 → passed=true
- 图片明显偏离目标（如要求猫却生成了 logo、文字、空白或完全无关内容）→ passed=false
- 质量一般但主体正确 → passed=true（非阻塞问题不在验收范围）
"""

@dataclass
class _ReferenceResolution:
    """Result of resolving reference images with lineage context.

    Attributes
    ----------
    urls:
        Ordered list of reference image URLs (possibly empty).
    context_map:
        Mapping from URL → lineage metadata dict (artifact_id,
        root_artifact_id, etc.) from visual context items.
    """

    urls: list[str] = field(default_factory=list)
    context_map: dict[str, dict[str, str]] = field(default_factory=dict)


_MAX_GENERATE_IMAGE_COUNT = 16


def _build_verification_user_message(
    goal: str,
    artifact_urls: list[str],
) -> list[dict[str, Any]]:
    """Build multimodal content blocks for VLM verification."""
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": f"生图目标：{goal}"},
        {"type": "text", "text": "请验收以下生成的图片："},
    ]
    for idx, url in enumerate(artifact_urls):
        blocks.append({"type": "text", "text": f"[生成图{idx}]"})
        blocks.append({
            "type": "image_url",
            "image_url": {"url": url, "detail": "low"},
        })
    return blocks


def _parse_verification_response(text: str) -> dict[str, Any]:
    """Parse VLM verification JSON response.

    Returns a dict with keys: passed, summary, repair_prompt, parse_ok.
    """
    try:
        data = json.loads(text)
        return {
            "passed": bool(data.get("passed", True)),
            "summary": str(data.get("summary", "")),
            "repair_prompt": str(data.get("repair_prompt", "")),
            "parse_ok": True,
        }
    except (json.JSONDecodeError, ValueError):
        return {
            "passed": True,
            "summary": "VLM 响应解析失败，未计为视觉验收通过",
            "repair_prompt": "",
            "parse_ok": False,
        }


__all__ = [
    "ArtistRuntimeKit",
    "ArtistLLMClientAdapter",
    "ArtistVLMClientAdapter",
    "VisualContextItem",
    "InMemoryRuntimeStateStore",
    "InMemoryEventSink",
    "run_core_kernel",
    "kernel_result_to_service_dict",
    "visual_context_from_image_map",
]


# ---------------------------------------------------------------------------
# Visual context model
# ---------------------------------------------------------------------------


@dataclass
class VisualContextItem:
    """A single visible image reference for the core kernel path.

    This is a minimal, generic representation — *not* a clone of the legacy
    ``visual_workspace`` or ``lineage`` models.  It carries just enough for a
    simple VLM-style "user uploaded one image and asks what it is" flow.
    """

    url: str
    label: str = ""
    role: str = "evidence"  # evidence | target | output
    detail: str = "low"  # OpenAI image_url detail hint
    metadata: dict[str, Any] = field(default_factory=dict)


def _visual_context_from_initial_items(
    items: list[dict[str, Any]],
) -> list[VisualContextItem]:
    """Convert legacy ``_initial_items_from_turn_inputs`` dicts to ``VisualContextItem``.

    Only items with a valid ``url`` are included.
    """
    result: list[VisualContextItem] = []
    for item in items:
        url = str(item.get("url") or "")
        if not url:
            continue
        context_role = str(item.get("context_role") or "evidence")
        label = str(item.get("label") or "")
        result.append(VisualContextItem(
            url=url,
            label=label,
            role=context_role,
            metadata={
                k: v
                for k, v in item.items()
                if k not in ("url", "label", "context_role")
            },
        ))
    return result


# ---------------------------------------------------------------------------
# In-memory infrastructure
# ---------------------------------------------------------------------------


class InMemoryRuntimeStateStore:
    """Simple in-memory implementation of ``RuntimeStateStore``."""

    def __init__(self) -> None:
        self._store: dict[str, RuntimeState] = {}

    async def get(self, session_id: str) -> RuntimeState | None:
        return self._store.get(session_id)

    async def save(self, state: RuntimeState) -> None:
        self._store[state.session_id] = state


class InMemoryEventSink:
    """Simple in-memory ``EventSink`` that collects events in a list."""

    def __init__(self) -> None:
        self._events: list[CoreEvent] = []

    async def emit(self, event: CoreEvent) -> None:
        self._events.append(event)

    @property
    def events(self) -> list[CoreEvent]:
        return list(self._events)


# ---------------------------------------------------------------------------
# LLM client adapter
# ---------------------------------------------------------------------------


class ArtistLLMClientAdapter:
    """Wrap the Artist's ``llm_call`` callable into the Core ``LLMClient`` protocol.

    The Artist ``llm_call`` signature is::

        async def llm_call(
            messages: list[dict[str, Any]],
            kwargs: dict[str, Any],
        ) -> tuple[str, dict | None]

    where the returned tuple is ``(response_text, usage_dict)`` and
    ``usage_dict`` may contain ``prompt_tokens`` / ``completion_tokens`` /
    ``total_tokens`` keys.
    """

    def __init__(self, llm_call: Callable[..., Any]) -> None:
        self._llm_call = llm_call

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Convert Core ``LLMRequest`` → dicts → artist ``llm_call`` → ``LLMResponse``."""
        messages_dicts: list[dict[str, Any]] = []
        for msg in request.messages:
            content = msg.content
            # Multimodal content blocks pass through as-is (list of dicts)
            entry: dict[str, Any] = {"role": msg.role, "content": content}
            if msg.name:
                entry["name"] = msg.name
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            messages_dicts.append(entry)

        kwargs: dict[str, Any] = {}
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        if request.response_format is not None:
            kwargs["response_format"] = request.response_format

        try:
            text, usage_dict = await self._llm_call(messages_dicts, kwargs)
        except TypeError:
            # Some llm_call implementations unpack kwargs
            text, usage_dict = await self._llm_call(messages_dicts, **kwargs)

        usage: LLMUsage | None = None
        if isinstance(usage_dict, dict):
            usage = LLMUsage(
                prompt_tokens=usage_dict.get("prompt_tokens", 0),
                completion_tokens=usage_dict.get("completion_tokens", 0),
                total_tokens=usage_dict.get("total_tokens", 0),
            )

        return LLMResponse(
            content=text or "",
            usage=usage,
            finish_reason="stop",
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        raise NotImplementedError("Streaming not supported in Artist CoreKernel adapter")


class ArtistVLMClientAdapter:
    """Wrap the Artist's ``vlm_call`` callable into the Core ``LLMClient`` protocol.

    Falls back to ``llm_call`` (text-only) when the request contains no
    multimodal content blocks.  This mirrors ``ArtistLLMClientAdapter`` but
    routes vision-capable requests through ``vlm_call``.
    """

    def __init__(
        self,
        vlm_call: Callable[..., Any],
        llm_call: Callable[..., Any] | None = None,
    ) -> None:
        self._vlm_call = vlm_call
        self._llm_call = llm_call

    def _has_multimodal_content(self, request: LLMRequest) -> bool:
        """Check if any message in the request has list-type content blocks."""
        for msg in request.messages:
            if isinstance(msg.content, list):
                return True
        return False

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Route to ``vlm_call`` for multimodal, ``llm_call`` for text-only."""
        use_vlm = self._has_multimodal_content(request)
        call_fn = self._vlm_call if use_vlm else self._llm_call
        if call_fn is None:
            call_fn = self._vlm_call

        messages_dicts: list[dict[str, Any]] = []
        for msg in request.messages:
            content = msg.content
            entry: dict[str, Any] = {"role": msg.role, "content": content}
            if msg.name:
                entry["name"] = msg.name
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            messages_dicts.append(entry)

        kwargs: dict[str, Any] = {}
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        if request.response_format is not None:
            kwargs["response_format"] = request.response_format

        try:
            text, usage_dict = await call_fn(messages_dicts, kwargs)
        except TypeError:
            text, usage_dict = await call_fn(messages_dicts, **kwargs)

        usage: LLMUsage | None = None
        if isinstance(usage_dict, dict):
            usage = LLMUsage(
                prompt_tokens=usage_dict.get("prompt_tokens", 0),
                completion_tokens=usage_dict.get("completion_tokens", 0),
                total_tokens=usage_dict.get("total_tokens", 0),
            )

        return LLMResponse(
            content=text or "",
            usage=usage,
            finish_reason="stop",
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        raise NotImplementedError("Streaming not supported in Artist CoreKernel VLM adapter")


# ---------------------------------------------------------------------------
# RuntimeKit implementation
# ---------------------------------------------------------------------------


class ArtistRuntimeKit:
    """Experimental ``RuntimeKit`` implementation delegating to ``ArtistRuntime``.

    Each method maps Core abstractions to the Artist's internal helpers.
    Stage-10 scope:

    * Text-only LLM rounds **and** simple VLM rounds with visible images
    * Five tools: ``generate_image``, ``finish``, ``ask_user``,
      ``inspect_lineage``, ``set_lineage_head``
    * Visual context via ``VisualContextItem`` list in ``state.metadata``
    * **VLM visual verification** after ``generate_image``: calls VLM with
      artifact images to check if output matches goal; on failure produces
      ``repair_prompt`` for Kernel to inject into next iteration
    * **Lightweight lineage**: ``inspect_lineage`` reads head/branch/items
      from visual context + ``state.metadata['lineage_items']``;
      ``set_lineage_head`` switches HEAD by artifact_index or URL;
      ``generate_image`` appends new artifacts to ``lineage_items``
    """

    name: str = "artist"

    def __init__(
        self,
        runtime: ArtistRuntime,
        session_id: str = "",
        artist_turn_id: str = "",
        visual_context: list[VisualContextItem] | None = None,
        vlm_call: Callable[..., Any] | None = None,
    ) -> None:
        self._runtime = runtime
        self._session_id = session_id
        self._artist_turn_id = artist_turn_id
        self._visual_context: list[VisualContextItem] = visual_context or []
        self._vlm_call = vlm_call

    @property
    def has_visual_context(self) -> bool:
        """Whether this kit has image context requiring VLM."""
        return bool(self._visual_context)

    # -- Lifecycle ---------------------------------------------------------

    async def on_run_start(
        self,
        state: RuntimeState,
        turn_input: RuntimeTurnInput,
    ) -> None:
        """Store the user goal and visual context in state metadata."""
        state.metadata["artist_goal"] = turn_input.user_message
        if self._visual_context:
            state.metadata["visual_context"] = [
                {"url": item.url, "label": item.label, "role": item.role, "detail": item.detail, "metadata": item.metadata}
                for item in self._visual_context
            ]

    async def build_context(
        self,
        state: RuntimeState,
        turn_input: RuntimeTurnInput,
        history: list[ChatMessage],
        step_index: int,
    ) -> PromptContext:
        """Assemble a ``PromptContext`` for the current loop iteration."""
        return PromptContext(
            session_id=state.session_id,
            user_message=turn_input.user_message,
            history=list(history),
            state=state,
            metadata={
                "step_index": step_index,
                "artist_session_id": self._session_id,
                "has_visual_context": bool(self._visual_context),
            },
        )

    async def build_model_request(
        self,
        state: RuntimeState,
        context: PromptContext,
    ) -> LLMRequest:
        """Construct an ``LLMRequest`` mirroring ``ArtistRuntime._call_model``.

        When visual context is present, the user message is built as a
        multimodal ``ChatMessage`` with ``content`` as a list of content blocks
        (text + image_url), matching the OpenAI chat completions format.
        """
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=ARTIST_RUNTIME_SYSTEM),
        ]

        hook_context = state.metadata.get("hook_context")
        if hook_context and isinstance(hook_context, dict):
            context_parts = [f"{k}: {v}" for k, v in hook_context.items() if v]
            if context_parts:
                messages.append(ChatMessage(
                    role="system",
                    content="[Hook Context] " + "; ".join(context_parts),
                ))

        messages.extend(context.history)

        # If we have visual context, append a multimodal user message with images
        if self._visual_context:
            content_blocks: list[dict[str, Any]] = [
                {
                    "type": "text",
                    "text": (
                        "当前可见图片如下。请先观察这些图片，再根据用户目标决定本轮操作。"
                    ),
                },
            ]
            for item in self._visual_context:
                label_text = item.label or "参考图"
                content_blocks.append({
                    "type": "text",
                    "text": f"[{label_text}]",
                })
                content_blocks.append({
                    "type": "image_url",
                    "image_url": {"url": item.url, "detail": item.detail},
                })
            messages.append(ChatMessage(role="user", content=content_blocks))

        return LLMRequest(
            messages=messages,
            temperature=0.4,
            max_tokens=1800,
            response_format={"type": "json_object"},
            metadata={"session_id": state.session_id, "has_visual_context": bool(self._visual_context)},
        )

    async def parse_model_output(
        self,
        state: RuntimeState,
        response: LLMResponse,
    ) -> KernelTurn:
        """Parse LLM JSON output via ``ArtistRuntime._parse_loop_turn`` and map to ``KernelTurn``."""
        turn = self._runtime._parse_loop_turn(response.content)

        tool_calls: list[ToolCall] = []
        for tc in turn.tool_calls:
            tool_calls.append(
                ToolCall(
                    id=uuid4().hex[:12],
                    name=tc.name,
                    arguments=tc.arguments or {},
                )
            )

        decision_hint: LoopDecision
        if turn.is_complete:
            decision_hint = "done"
        elif turn.needs_user_input:
            decision_hint = "wait"
        else:
            decision_hint = "continue"

        return KernelTurn(
            reply=turn.message or turn.reply,
            tool_calls=tool_calls,
            decision_hint=decision_hint,
            wait_reason=turn.message if turn.needs_user_input else "",
            metadata={
                "usage": response.usage.to_dict() if response.usage else {},
                "artist_turn_raw": {
                    "is_complete": turn.is_complete,
                    "needs_user_input": turn.needs_user_input,
                    "next_phase": turn.next_phase,
                    "reply_lines": turn.reply_lines,
                    "task_card": turn.task_card,
                },
            },
        )

    async def execute_tool(
        self,
        state: RuntimeState,
        call: ToolCall,
    ) -> ToolResult:
        """Execute a single tool call (narrow scope).

        Supported tools: ``generate_image``, ``finish``, ``ask_user``,
        ``inspect_lineage``, ``set_lineage_head``.
        """
        name = call.name
        args = call.arguments or {}

        if name == "generate_image":
            # Store the task prompt in state metadata for verify() to use
            task_prompt = str(args.get("task") or args.get("prompt") or "")
            if task_prompt:
                state.metadata["artist_goal"] = task_prompt
            # Reset pending artifacts for this generation. Keep the verification
            # attempt counter for the current user task so repair loops can hit
            # their ceiling.
            state.metadata.pop("_pending_verify_artifacts", None)
            result = await self._execute_generate_image(call, args)
            if result.status == "ok":
                self._append_generated_lineage_items(result, state)
            return result

        if name == "finish":
            return ToolResult(
                call_id=call.id,
                name="finish",
                status="ok",
                content=args.get("reason", "completed"),
            )

        if name == "ask_user":
            return ToolResult(
                call_id=call.id,
                name="ask_user",
                status="ok",
                content=args.get("question", ""),
            )

        if name == "inspect_lineage":
            return self._execute_inspect_lineage(call, state)

        if name == "set_lineage_head":
            return self._execute_set_lineage_head(call, args, state)

        return ToolResult(
            call_id=call.id,
            name=name,
            status="failed",
            error=f"Unsupported tool: {name}",
        )

    # -- Lineage tools -----------------------------------------------------

    def _execute_inspect_lineage(
        self,
        call: ToolCall,
        state: RuntimeState,
    ) -> ToolResult:
        """Return lightweight lineage info from visual context + state metadata.

        Returns a JSON-serializable dict with:
        - ``head``: current HEAD artifact_id (from ``state.metadata['lineage_head']``)
        - ``current_head_url``: URL of the HEAD item (from ``state.metadata['lineage_head_url']``)
        - ``active_branch``: current branch name (from ``state.metadata['active_branch']``)
        - ``items``: list of lineage items, each with index, label, url,
          artifact_id, parent_artifact_id, root_artifact_id, branch_name, role

        Items are built from two sources:
        1. ``self._visual_context`` — the kit's initial visual context items
        2. ``state.metadata['lineage_items']`` — artifacts appended by
           ``generate_image`` during this run
        """
        head_artifact_id = state.metadata.get("lineage_head", "")
        head_url = state.metadata.get("lineage_head_url", "")
        active_branch = state.metadata.get("active_branch", "main")

        items: list[dict[str, Any]] = []

        # Source 1: visual context items
        for idx, vc_item in enumerate(self._visual_context):
            meta = vc_item.metadata or {}
            items.append({
                "index": idx,
                "label": vc_item.label or f"图{idx}",
                "url": vc_item.url,
                "artifact_id": str(meta.get("artifact_id", "")),
                "parent_artifact_id": str(meta.get("parent_artifact_id", "")),
                "root_artifact_id": str(meta.get("root_artifact_id", "")),
                "branch_name": str(meta.get("branch_name", active_branch)),
                "role": vc_item.role,
            })

        # Source 2: lineage_items from state metadata (appended by generate_image)
        lineage_items = state.metadata.get("lineage_items", [])
        if isinstance(lineage_items, list):
            base_index = len(items)
            for idx, li in enumerate(lineage_items):
                if not isinstance(li, dict):
                    continue
                items.append({
                    "index": base_index + idx,
                    "label": str(li.get("label", f"图{base_index + idx}")),
                    "url": str(li.get("url", "")),
                    "artifact_id": str(li.get("artifact_id", "")),
                    "parent_artifact_id": str(li.get("parent_artifact_id", "")),
                    "root_artifact_id": str(li.get("root_artifact_id", "")),
                    "branch_name": str(li.get("branch_name", active_branch)),
                    "role": str(li.get("role", "output")),
                })

        result_data = {
            "head": head_artifact_id or (items[-1].get("artifact_id", "") if items else ""),
            "current_head_url": head_url or (items[-1].get("url", "") if items else ""),
            "active_branch": active_branch,
            "items": items,
        }

        return ToolResult(
            call_id=call.id,
            name="inspect_lineage",
            status="ok",
            content=json.dumps(result_data, ensure_ascii=False),
            metadata=result_data,
        )

    def _execute_set_lineage_head(
        self,
        call: ToolCall,
        args: dict[str, Any],
        state: RuntimeState,
    ) -> ToolResult:
        """Switch the lineage HEAD by ``artifact_index`` or ``url``.

        When a match is found in visual context or ``state.metadata['lineage_items']``,
        updates ``state.metadata['lineage_head']``, ``lineage_head_url``,
        and ``active_branch``.  Returns ``ok`` on success, ``failed`` on miss
        (never raises).
        """
        # Build the combined items list (visual context + lineage_items)
        all_items: list[dict[str, Any]] = []
        for vc_item in self._visual_context:
            meta = vc_item.metadata or {}
            all_items.append({
                "url": vc_item.url,
                "artifact_id": str(meta.get("artifact_id", "")),
                "branch_name": str(meta.get("branch_name", "")),
            })
        lineage_items = state.metadata.get("lineage_items", [])
        if isinstance(lineage_items, list):
            for li in lineage_items:
                if isinstance(li, dict):
                    all_items.append({
                        "url": str(li.get("url", "")),
                        "artifact_id": str(li.get("artifact_id", "")),
                        "branch_name": str(li.get("branch_name", "")),
                    })

        # Try by artifact_index first
        raw_idx = args.get("artifact_index")
        if isinstance(raw_idx, int) and 0 <= raw_idx < len(all_items):
            matched = all_items[raw_idx]
            state.metadata["lineage_head"] = matched.get("artifact_id", "")
            state.metadata["lineage_head_url"] = matched.get("url", "")
            if matched.get("branch_name"):
                state.metadata["active_branch"] = matched["branch_name"]
            return ToolResult(
                call_id=call.id,
                name="set_lineage_head",
                status="ok",
                content=f"HEAD set to index {raw_idx}",
                metadata={
                    "head": state.metadata.get("lineage_head", ""),
                    "current_head_url": state.metadata.get("lineage_head_url", ""),
                    "active_branch": state.metadata.get("active_branch", ""),
                },
            )

        # Try by url
        raw_url = str(args.get("url") or "").strip()
        if raw_url:
            for item in all_items:
                if item.get("url") == raw_url:
                    state.metadata["lineage_head"] = item.get("artifact_id", "")
                    state.metadata["lineage_head_url"] = raw_url
                    if item.get("branch_name"):
                        state.metadata["active_branch"] = item["branch_name"]
                    return ToolResult(
                        call_id=call.id,
                        name="set_lineage_head",
                        status="ok",
                        content=f"HEAD set to url {raw_url}",
                        metadata={
                            "head": state.metadata.get("lineage_head", ""),
                            "current_head_url": state.metadata.get("lineage_head_url", ""),
                            "active_branch": state.metadata.get("active_branch", ""),
                        },
                    )

        # No match found
        return ToolResult(
            call_id=call.id,
            name="set_lineage_head",
            status="failed",
            error="No matching artifact found for the given index or url",
        )

    def _append_generated_lineage_items(self, result: ToolResult, state: RuntimeState) -> None:
        lineage_items = state.metadata.setdefault("lineage_items", [])
        if not isinstance(lineage_items, list):
            lineage_items = []
            state.metadata["lineage_items"] = lineage_items
        for artifact in result.artifacts:
            meta = artifact.metadata or {}
            references = meta.get("references")
            first_reference = references[0] if isinstance(references, list) and references and isinstance(references[0], dict) else {}
            lineage_items.append({
                "label": f"生成图{len(lineage_items)}",
                "url": artifact.uri,
                "artifact_id": str(meta.get("artifact_id", "")),
                "parent_artifact_id": str(first_reference.get("artifact_id", "")),
                "root_artifact_id": str(first_reference.get("root_artifact_id") or first_reference.get("artifact_id") or ""),
                "branch_name": str(first_reference.get("branch_name") or state.metadata.get("active_branch") or ""),
                "role": "output",
            })

    # -- Reference image resolution ----------------------------------------

    @staticmethod
    def _resolve_reference_images_from_args(args: dict[str, Any]) -> list[str]:
        """Extract reference image URLs from generate_image tool arguments.

        Supports the following argument keys (mirroring the legacy
        ``ArtistRuntime._raw_reference_items`` convention):

        - ``reference`` / ``references`` / ``reference_images``: a URL string
          or list of URL strings / dicts with ``url`` key
        - ``url``: a single reference URL
        Invalid entries (empty strings, non-string scalars, dicts without
        ``url``) are silently skipped.
        """
        urls: list[str] = []

        # 1. Explicit reference / references / reference_images
        raw_refs = (
            args.get("reference")
            or args.get("references")
            or args.get("reference_images")
        )
        if raw_refs is not None:
            if isinstance(raw_refs, str):
                raw_refs = [raw_refs]
            if isinstance(raw_refs, list):
                for ref in raw_refs:
                    if isinstance(ref, str) and ref.strip():
                        urls.append(ref.strip())
                    elif isinstance(ref, dict):
                        url = str(ref.get("url") or "").strip()
                        if url:
                            urls.append(url)
                        # artifact_index dicts are handled below

        # 2. Single url parameter
        raw_url = str(args.get("url") or "").strip()
        if raw_url and raw_url not in urls:
            urls.append(raw_url)

        return urls

    def _resolve_reference_images_from_visual_context(
        self,
        *,
        include_roles: set[str] | None = None,
    ) -> list[str]:
        """Extract reference image URLs from the kit's visual context.

        By default includes items with ``role=target``, ``role=evidence``, or
        ``role=output``.  The ``output`` role is included because in the Core
        Kernel path, ``image_map``-derived items carry ``context_role="output"``
        and should serve as reference images for the generate call.
        """
        roles = include_roles or {"target", "evidence", "output"}
        urls: list[str] = []
        for item in self._visual_context:
            if item.role in roles and item.url.strip():
                urls.append(item.url.strip())
        return urls

    def _resolve_artifact_index_references(
        self,
        args: dict[str, Any],
    ) -> list[str]:
        """Resolve ``artifact_index`` / ``reference_artifact_indices`` from
        tool arguments into URLs from the visual context list.

        Indices are 0-based into ``self._visual_context``.
        Out-of-range indices are silently skipped.
        """
        urls: list[str] = []
        indices: list[int] = []

        # Single artifact_index
        raw_idx = args.get("artifact_index")
        if isinstance(raw_idx, int):
            indices.append(raw_idx)

        # Multiple reference_artifact_indices
        raw_indices = args.get("reference_artifact_indices")
        if isinstance(raw_indices, list):
            for idx in raw_indices:
                if isinstance(idx, int):
                    indices.append(idx)

        for idx in indices:
            if 0 <= idx < len(self._visual_context):
                url = self._visual_context[idx].url.strip()
                if url:
                    urls.append(url)

        return urls

    def _build_reference_images(
        self,
        args: dict[str, Any],
    ) -> list[str] | None:
        """Build the final ``reference_images`` list for ``image_generate``.

        Priority / merge logic:
        1. Explicit reference URLs from tool arguments (``reference``,
           ``references``, ``reference_images``, ``url``).
        2. ``artifact_index`` / ``reference_artifact_indices`` resolved to
           visual context URLs.
        3. Visual context items as fallback (only when no explicit references
           were provided).  ``role=output`` is included because image_map
           entries currently arrive with that legacy context role.

        Returns ``None`` when no reference images are available (preserving
        the existing ``image_generate`` call signature).
        """
        result = self._build_reference_images_with_context(args)
        return result.urls if result.urls else None

    def _build_reference_images_with_context(
        self,
        args: dict[str, Any],
    ) -> _ReferenceResolution:
        """Build the final ``reference_images`` list AND collect lineage context.

        Returns a ``_ReferenceResolution`` containing:
        - ``urls``: the merged reference image URL list (same as
          ``_build_reference_images``)
        - ``context_map``: a dict mapping each reference URL to its lineage
          metadata (artifact_id, root_artifact_id, parent_artifact_id,
          root_url, branch_name, label) from ``VisualContextItem.metadata``.

        Explicit URLs that don't match any visual context item are recorded
        with ``parent_url`` only (no lineage IDs).
        """
        # Step 1: explicit URLs from args
        explicit_urls = self._resolve_reference_images_from_args(args)

        # Step 2: artifact index resolution
        index_urls = self._resolve_artifact_index_references(args)

        # Merge explicit + index, deduplicate while preserving order
        seen: set[str] = set()
        merged: list[str] = []
        for url in explicit_urls + index_urls:
            if url not in seen:
                seen.add(url)
                merged.append(url)

        # Step 3: if no explicit references, fall back to visual context
        if not merged:
            vc_urls = self._resolve_reference_images_from_visual_context()
            for url in vc_urls:
                if url not in seen:
                    seen.add(url)
                    merged.append(url)

        # Build lineage context map from visual context items
        context_map: dict[str, dict[str, str]] = {}
        for item in self._visual_context:
            url = item.url.strip()
            if url and url in seen:
                meta = item.metadata or {}
                lineage_keys = (
                    "artifact_id",
                    "root_artifact_id",
                    "parent_artifact_id",
                    "root_url",
                    "branch_name",
                    "label",
                )
                context: dict[str, str] = {}
                for key in lineage_keys:
                    value = meta.get(key)
                    if value:
                        context[key] = str(value)
                if context:
                    context_map[url] = context

        return _ReferenceResolution(urls=merged, context_map=context_map)

    @staticmethod
    def _reference_metadata(resolution: _ReferenceResolution) -> dict[str, Any]:
        if not resolution.urls:
            return {}
        references: list[dict[str, Any]] = []
        for url in resolution.urls:
            context = dict(resolution.context_map.get(url) or {})
            references.append({"url": url, "parent_url": url, **context})
        return {
            "source_image_urls": list(resolution.urls),
            "references": references,
        }

    async def _execute_generate_image(
        self,
        call: ToolCall,
        args: dict[str, Any],
    ) -> ToolResult:
        """Execute ``generate_image`` by calling the Artist's image generation dep.

        Also stores the task prompt in state metadata so ``verify()`` can
        check whether the output matches the goal.

        Supports ``items`` array for batch generation. Each item is executed
        independently with its own prompt/image_count/reference_images.
        Artifacts include ``item_index`` and ``item_name`` in metadata.
        """
        if not self._runtime.deps.image_generate:
            return ToolResult(
                call_id=call.id,
                name="generate_image",
                status="failed",
                error="image_generate is not configured",
            )

        # Check for items array (batch mode)
        raw_items = args.get("items")
        if isinstance(raw_items, list) and raw_items:
            return await self._execute_generate_image_items(call, args, raw_items)

        # Single-item mode (existing behavior)
        return await self._execute_generate_image_single(call, args)

    async def _execute_generate_image_single(
        self,
        call: ToolCall,
        args: dict[str, Any],
        item_index: int = 0,
        item_name: str = "",
    ) -> ToolResult:
        """Execute a single generate_image call (non-items mode or one item from items)."""
        prompt = str(args.get("task") or args.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(
                call_id=call.id,
                name="generate_image",
                status="failed",
                error="generate_image requires a non-empty task or prompt",
            )
        try:
            image_count = int(args.get("image_count") or 1)
        except (TypeError, ValueError):
            return ToolResult(
                call_id=call.id,
                name="generate_image",
                status="failed",
                error="image_count must be an integer",
            )
        if image_count < 1 or image_count > _MAX_GENERATE_IMAGE_COUNT:
            return ToolResult(
                call_id=call.id,
                name="generate_image",
                status="failed",
                error=f"image_count must be between 1 and {_MAX_GENERATE_IMAGE_COUNT}",
            )

        # Resolve reference images from args + visual context
        reference_resolution = self._build_reference_images_with_context(args)
        reference_images = reference_resolution.urls if reference_resolution.urls else None

        try:
            urls, tokens_in, tokens_out = await self._runtime.deps.image_generate(
                prompt=prompt,
                image_count=image_count,
                image_size=self._runtime.image_size,
                negative_prompt=self._runtime.negative_prompt,
                image_quality=self._runtime.image_quality,
                reference_images=reference_images,
            )
        except Exception as exc:
            return ToolResult(
                call_id=call.id,
                name="generate_image",
                status="failed",
                error=f"Image generation failed: {exc}",
            )

        if not urls:
            return ToolResult(
                call_id=call.id,
                name="generate_image",
                status="failed",
                error="Image generation returned no URLs",
            )

        # Build artifact metadata with item_index/item_name for batch mode
        artifact_metadata_base: dict[str, Any] = self._reference_metadata(reference_resolution)
        if item_index > 0 or item_name:
            artifact_metadata_base["item_index"] = item_index
            if item_name:
                artifact_metadata_base["item_name"] = item_name

        return ToolResult(
            call_id=call.id,
            name="generate_image",
            status="ok",
            content=f"Generated {len(urls)} image(s)",
            artifacts=[
                ToolArtifact(
                    kind="image",
                    uri=url,
                    metadata={**artifact_metadata_base, "index": idx},
                )
                for idx, url in enumerate(urls)
            ],
            usage=LLMUsage(
                prompt_tokens=tokens_in,
                completion_tokens=tokens_out,
                total_tokens=tokens_in + tokens_out,
            ),
        )

    async def _execute_generate_image_items(
        self,
        call: ToolCall,
        args: dict[str, Any],
        raw_items: list[Any],
    ) -> ToolResult:
        """Execute generate_image with items array (batch mode).

        Each item is validated and executed independently. Invalid items
        return a failed result immediately without calling subsequent items.
        """
        all_artifacts: list[ToolArtifact] = []
        total_tokens_in = 0
        total_tokens_out = 0
        total_generated = 0
        for item_index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, dict):
                return ToolResult(
                    call_id=call.id,
                    name="generate_image",
                    status="failed",
                    error=f"Item {item_index}: items entries must be objects",
                )

            # Merge base args with item-specific args
            item_args = dict(args)
            item_args.pop("items", None)  # Remove items array
            item_args.update(raw_item)  # Item fields override base

            item_name = str(raw_item.get("name") or "")

            # Validate item before calling image_generate
            prompt = str(item_args.get("task") or item_args.get("prompt") or "").strip()
            if not prompt:
                return ToolResult(
                    call_id=call.id,
                    name="generate_image",
                    status="failed",
                    error=f"Item {item_index} ({item_name or 'unnamed'}): generate_image requires a non-empty task or prompt",
                )
            try:
                image_count = int(item_args.get("image_count") or 1)
            except (TypeError, ValueError):
                return ToolResult(
                    call_id=call.id,
                    name="generate_image",
                    status="failed",
                    error=f"Item {item_index} ({item_name or 'unnamed'}): image_count must be an integer",
                )
            if image_count < 1 or image_count > _MAX_GENERATE_IMAGE_COUNT:
                return ToolResult(
                    call_id=call.id,
                    name="generate_image",
                    status="failed",
                    error=f"Item {item_index} ({item_name or 'unnamed'}): image_count must be between 1 and {_MAX_GENERATE_IMAGE_COUNT}",
                )

            # Resolve reference images for this item (item-specific)
            reference_resolution = self._build_reference_images_with_context(item_args)
            reference_images = reference_resolution.urls if reference_resolution.urls else None

            try:
                urls, tokens_in, tokens_out = await self._runtime.deps.image_generate(
                    prompt=prompt,
                    image_count=image_count,
                    image_size=self._runtime.image_size,
                    negative_prompt=self._runtime.negative_prompt,
                    image_quality=self._runtime.image_quality,
                    reference_images=reference_images,
                )
            except Exception as exc:
                return ToolResult(
                    call_id=call.id,
                    name="generate_image",
                    status="failed",
                    error=f"Item {item_index} ({item_name or 'unnamed'}): Image generation failed: {exc}",
                )

            if not urls:
                return ToolResult(
                    call_id=call.id,
                    name="generate_image",
                    status="failed",
                    error=f"Item {item_index} ({item_name or 'unnamed'}): Image generation returned no URLs",
                )

            total_tokens_in += tokens_in
            total_tokens_out += tokens_out
            total_generated += len(urls)

            # Build artifacts with item metadata
            for idx, url in enumerate(urls):
                artifact_metadata: dict[str, Any] = {
                    **self._reference_metadata(reference_resolution),
                    "item_index": item_index,
                    "index": idx,
                }
                if item_name:
                    artifact_metadata["item_name"] = item_name
                all_artifacts.append(ToolArtifact(kind="image", uri=url, metadata=artifact_metadata))

        return ToolResult(
            call_id=call.id,
            name="generate_image",
            status="ok",
            content=f"Generated {total_generated} image(s) from {len(raw_items)} item(s)",
            artifacts=all_artifacts,
            usage=LLMUsage(
                prompt_tokens=total_tokens_in,
                completion_tokens=total_tokens_out,
                total_tokens=total_tokens_in + total_tokens_out,
            ),
        )

    async def format_tool_result_for_model(
        self,
        state: RuntimeState,
        call: ToolCall,
        result: ToolResult,
    ) -> ChatMessage:
        """Return a tool-result ``ChatMessage`` with business-relevant content only.

        For ``generate_image`` with artifacts, include the image URLs so the
        model can "see" the generated images in the next iteration for verification.
        """
        content = result.content or result.error or ""

        # For generate_image with image artifacts, append URLs for VLM visibility
        if call.name == "generate_image" and result.artifacts:
            urls = [a.uri for a in result.artifacts if a.uri]
            if urls:
                url_list = ", ".join(urls)
                content = f"{content}\nGenerated image URLs: {url_list}" if content else f"Generated image URLs: {url_list}"
                # Store artifact URLs in state metadata for verify() to use
                stored = state.metadata.get("_pending_verify_artifacts", [])
                stored.extend(urls)
                state.metadata["_pending_verify_artifacts"] = stored

        return ChatMessage(
            role="tool",
            content=content,
            tool_call_id=call.id,
        )

    async def verify(
        self,
        state: RuntimeState,
        turn: KernelTurn,
        tool_results: list[ToolResult],
    ) -> VerificationResult:
        """VLM visual verification after ``generate_image``.

        When ``generate_image`` produced image artifacts, call VLM with those
        images and the original goal to check if the output matches.  On
        failure, produce a ``repair_prompt`` that the Kernel injects into the
        next iteration.

        If no image artifacts were produced (text-only turn, finish, ask_user),
        verification is a no-op (passed=True, required=False).
        """
        # Collect artifact URLs from tool results
        artifact_urls: list[str] = []
        for tr in tool_results:
            if tr.name == "generate_image" and tr.status == "ok":
                for art in tr.artifacts:
                    if art.uri:
                        artifact_urls.append(art.uri)
        if artifact_urls:
            state.metadata.pop("_pending_verify_artifacts", None)

        # Also check state metadata (set by format_tool_result_for_model)
        if not artifact_urls:
            artifact_urls = state.metadata.pop("_pending_verify_artifacts", [])

        # No image artifacts → no-op verification
        if not artifact_urls:
            return VerificationResult(passed=True, required=False)

        # No VLM available means there was no visual acceptance. Preserve the
        # legacy follow-up loop instead of treating the image as verified.
        vlm_call = self._vlm_call if self._vlm_call is not None else self._runtime.deps.vlm_call
        if vlm_call is None:
            return VerificationResult(
                passed=True,
                required=False,
                summary="VLM 不可用，跳过视觉验收",
            )

        # Build VLM verification request
        goal = state.metadata.get("artist_goal", "")
        content_blocks = _build_verification_user_message(goal, artifact_urls)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _VERIFICATION_SYSTEM_PROMPT},
            {"role": "user", "content": content_blocks},
        ]

        try:
            text, usage_dict = await vlm_call(messages, {"temperature": 0.2, "max_tokens": 300})
        except Exception as exc:
            # VLM call failed. Do not block, but also do not count it as
            # visual acceptance.
            return VerificationResult(
                passed=True,
                required=False,
                summary=f"VLM 验收调用失败: {exc}",
            )

        parsed = _parse_verification_response(text or "")
        if not parsed["parse_ok"]:
            return VerificationResult(
                passed=True,
                required=False,
                summary=parsed["summary"],
            )
        passed = parsed["passed"]
        summary = parsed["summary"]
        repair_prompt = parsed["repair_prompt"]

        # Track verification attempt count in state metadata
        verify_count = state.metadata.get("_verify_attempt", 0) + 1
        state.metadata["_verify_attempt"] = verify_count

        return VerificationResult(
            passed=passed,
            required=True,
            summary=summary,
            repair_prompt=repair_prompt if not passed else "",
            attempt=verify_count,
            max_attempts=3,
        )

    async def decide_next(
        self,
        state: RuntimeState,
        turn: KernelTurn,
        verification: VerificationResult,
        step: KernelStep,
    ) -> LoopDecision:
        """Decide next action based on turn hints, tool results, and verification.

        Priority:
        1. Turn-level hints (done / wait) take priority
        2. Tool failures → failed
        3. Verification failed → continue (Kernel will inject repair_prompt)
        4. Verification passed after generate_image → done (goal met)
        5. Text-only reply with no tool calls → done
        6. Default → continue
        """
        # Turn-level hints take priority
        if turn.decision_hint == "done":
            return "done"
        if turn.decision_hint == "wait":
            return "wait"

        # Check for tool failures
        for result in step.tool_steps:
            tr = result.result
            if tr is not None and tr.status == "failed" and tr.name == "generate_image":
                return "failed"

        # If verification was required and failed, continue for repair
        if verification.required and not verification.passed:
            if verification.attempt >= verification.max_attempts:
                return "failed"
            return "continue"

        # If verification passed after generate_image, the goal is met → done
        if verification.required and verification.passed:
            has_gen_image = any(
                ts.result is not None and ts.result.name == "generate_image" and ts.result.status == "ok"
                for ts in step.tool_steps
            )
            if has_gen_image:
                return "done"

        # If we just generated images but verification was not required,
        # continue to observe them (legacy behavior)
        for result in step.tool_steps:
            tr = result.result
            if tr is not None and tr.name == "generate_image" and tr.status == "ok":
                return "continue"

        # Text-only reply with no tool calls → done
        if not turn.tool_calls and turn.reply:
            return "done"

        # Default: continue
        return "continue"

    async def writeback(
        self,
        state: RuntimeState,
        turn: KernelTurn,
        tool_results: list[ToolResult],
        verification: VerificationResult,
        decision: LoopDecision,
    ) -> None:
        """No-op writeback.  Store last decision for debugging."""
        state.metadata["artist_last_decision"] = decision

    async def on_run_end(
        self,
        state: RuntimeState,
        result: KernelResult,
    ) -> None:
        """No-op end hook."""


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------


async def run_core_kernel(
    runtime: ArtistRuntime,
    goal: str,
    *,
    session_id: str = "",
    llm_client: LLMClient | None = None,
    max_steps: int = 6,
    visual_context: list[VisualContextItem] | None = None,
) -> KernelResult:
    """Construct and run the CoreLoopKernel path.

    Parameters
    ----------
    runtime:
        An existing ``ArtistRuntime`` instance with configured deps.
    goal:
        The user message / goal to process.
    session_id:
        Optional session identifier for state persistence.
    llm_client:
        Optional Core ``LLMClient``.  If ``None``, an adapter is chosen
        automatically: ``ArtistVLMClientAdapter`` when ``visual_context``
        is present and ``runtime.deps.vlm_call`` is available, otherwise
        ``ArtistLLMClientAdapter`` wrapping ``runtime.deps.llm_call``.
    max_steps:
        Maximum loop iterations (default 6).
    visual_context:
        Optional list of visible image references.  When present, the kit
        builds multimodal ``ChatMessage`` content blocks and the VLM adapter
        is preferred for model calls.

    Returns
    -------
    KernelResult
        The outcome of the kernel run.
    """
    vc = visual_context or []
    kit = ArtistRuntimeKit(runtime, session_id=session_id, visual_context=vc, vlm_call=runtime.deps.vlm_call)
    state_store = InMemoryRuntimeStateStore()
    event_sink = InMemoryEventSink()

    policy = LoopPolicy(
        max_steps=max_steps,
        model_timeout_seconds=runtime.model_call_timeout_seconds,
        fail_on_max_steps=False,  # let the kit decide, don't auto-fail
    )

    if llm_client is None:
        # Auto-select VLM adapter when visual context is present
        if vc and runtime.deps.vlm_call:
            llm_client = ArtistVLMClientAdapter(runtime.deps.vlm_call, runtime.deps.llm_call)
        else:
            llm_client = ArtistLLMClientAdapter(runtime.deps.llm_call)

    from lamtools_core.kernel.hook_dispatcher import HookDispatcher
    from app.core.artist.hook_set import ArtistHookSet

    hook_dispatcher = HookDispatcher()
    hook_dispatcher.register(ArtistHookSet())

    kernel = CoreLoopKernel(
        kit=kit,
        llm_client=llm_client,
        state_store=state_store,
        event_sink=event_sink,
        policy=policy,
        hook_dispatcher=hook_dispatcher,
    )

    turn_input = RuntimeTurnInput(
        user_message=goal,
        metadata={
            "session_id": session_id,
            "has_visual_context": bool(vc),
        },
    )

    result = await kernel.run(turn_input)

    # Inject core events and summary metadata into KernelResult.metadata
    # This allows callers to access core events without global variables
    core_events = event_sink.events
    result.metadata["core_events"] = [e.to_dict() for e in core_events]
    result.metadata["decision"] = result.decision
    result.metadata["error"] = result.error or ""
    result.metadata["steps_count"] = len(result.steps)
    result.metadata["verification_summaries"] = [
        {
            "step_index": step.index,
            "passed": step.verification.passed if step.verification else None,
            "required": step.verification.required if step.verification else None,
            "summary": step.verification.summary if step.verification else "",
            "attempt": step.verification.attempt if step.verification else 0,
        }
        for step in result.steps
    ]
    result.metadata["tool_results_summary"] = [
        {
            "step_index": step.index,
            "tool_name": ts.result.name if ts.result else None,
            "status": ts.result.status if ts.result else None,
            "artifact_count": len(ts.result.artifacts) if ts.result else 0,
            "error": ts.result.error if ts.result else "",
        }
        for step in result.steps
        for ts in step.tool_steps
    ]

    return result
