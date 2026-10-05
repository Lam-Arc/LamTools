"""Run a bounded real-API context-compaction experiment.

The runner is intentionally independent from ``data/core.db``.  It seeds a
copy of the de-identified fixture into a temporary experiment database, then
executes the production ``CoreLoopKernel`` with an OpenAI-compatible HTTP
client that records redacted request/response evidence.

The API key is read only from ``LAMTOOLS_CONTEXT_EXP_API_KEY`` and is never
written to the evidence files.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.context_compaction import COMPACTION_PROMPT
from lamtools_core.event import CollectingEventSink
from lamtools_core.kernel import CoreLoopKernel, KernelTurn, LoopPolicy, VerificationResult
from lamtools_core.kernel.errors import LLMProviderError, RateLimitError
from lamtools_core.kernel.loop import _chat_message_from_dict
from lamtools_core.llm import (
    ChatMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMToolCall,
    LLMUsage,
)
from lamtools_core.llm.helpers import normalize_usage
from lamtools_core.llm.profiles import (
    build_profiled_openai_request,
    normalize_response_with_profile,
    normalize_stream_chunk_with_profile,
)
from lamtools_core.llm.policy import RetryPolicy
from lamtools_core.prompt import PromptContext
from lamtools_core.runtime import RuntimeState, RuntimeTurnInput
from lamtools_core.tool import ToolCall, ToolResult
from lamtools_core.tokens import estimate_message_tokens


MODEL = "gpt-5.6-terra"
BASE_URL = "https://api.codex666ai.com"
API_BASE_URL = f"{BASE_URL}/v1"
WINDOW = 236_000
TRIGGER = 188_800
LIMIT = 141_600
FIXTURE_NAME = "real_near_threshold_01.json"
_SECRET_RE = re.compile(r"(?i)(?:bearer\s+|sk-)[^\s\"']+")
STREAM_DISABLED = os.environ.get("LAMTOOLS_CONTEXT_EXP_DISABLE_STREAM", "") == "1"


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return _SECRET_RE.sub("[REDACTED]", value)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(_redact(value), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _selected_headers(headers: httpx.Headers) -> dict[str, str]:
    selected: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if (
            lowered == "retry-after"
            or lowered.startswith("x-ratelimit-")
            or lowered in {"cf-ray", "server", "content-type"}
        ):
            selected[lowered] = value
    return selected


def _error_code(body: str) -> str:
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return ""
    error = payload.get("error") if isinstance(payload, dict) else None
    return str(error.get("code") or "") if isinstance(error, dict) else ""


def _message_from_fixture(value: dict[str, Any]) -> ChatMessage | None:
    return _chat_message_from_dict(value)


class ObservedOpenAIChatClient:
    """Small instrumented client using the same profile path as Core CLI."""

    context_window = WINDOW

    def __init__(self, *, api_key: str, output_dir: Path) -> None:
        self.api_key = api_key
        self.output_dir = output_dir
        self.records: list[dict[str, Any]] = []
        self.profile = {"id": "openai-chat"}

    def _url(self, endpoint: str) -> str:
        # ``build_profiled_openai_request`` returns protocol-relative paths
        # (for example ``/chat/completions``), while this gateway exposes the
        # OpenAI-compatible API under ``/v1``.  The endpoint probes below use
        # the public URL explicitly; keep the two forms aligned here too.
        if endpoint.startswith("/v1/"):
            return f"{BASE_URL}{endpoint}"
        return f"{API_BASE_URL}{endpoint}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _record_base(self, request: LLMRequest, assembled: dict[str, Any], *, stream: bool) -> dict[str, Any]:
        messages = list(request.messages)
        is_compaction = bool(
            messages
            and messages[-1].role == "user"
            and messages[-1].metadata.get("key") == "context_compaction_instruction"
            and COMPACTION_PROMPT in str(messages[-1].content)
        )
        return {
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "endpoint": assembled["endpoint"],
            "url": self._url(assembled["endpoint"]),
            "stream": stream,
            "phase": "compaction" if is_compaction else "model",
            "request": _redact(assembled["payload"]),
            "request_message_count": len(messages),
            "request_exact_tokens": estimate_message_tokens(
                [message.to_dict() for message in messages], fast=False
            ),
            "request_fast_tokens": estimate_message_tokens(
                [message.to_dict() for message in messages], fast=True
            ),
        }

    def _flush(self) -> None:
        _write_json(self.output_dir / "http_attempts.json", self.records)

    @staticmethod
    def _provider_error(status_code: int, body: str, headers: httpx.Headers) -> Exception:
        message = f"LLM API error {status_code}: {body[:300]}"
        if status_code == 429:
            raw_retry_after = headers.get("retry-after")
            retry_after: float | None = None
            try:
                retry_after = float(raw_retry_after) if raw_retry_after else None
            except (TypeError, ValueError):
                retry_after = None
            return RateLimitError(message, retry_after=retry_after)
        return LLMProviderError(message, status_code=status_code)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        assembled = build_profiled_openai_request(
            request,
            self.profile,
            thinking_enabled=False,
            capability="",
        )
        record = self._record_base(request, assembled, stream=False)
        self.records.append(record)
        self._flush()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=30.0)) as client:
                response = await client.post(
                    self._url(assembled["endpoint"]),
                    json=assembled["payload"],
                    headers=self._headers(),
                )
            body = response.text
            record["status_code"] = response.status_code
            record["response_headers"] = _selected_headers(response.headers)
            record["response_content_type"] = response.headers.get("content-type", "")
            record["response_content_length"] = response.headers.get("content-length", "")
            record["response_body"] = _redact(body[:20_000])
            record["error_code"] = _error_code(body)
            if response.status_code >= 400:
                error = self._provider_error(response.status_code, body, response.headers)
                record["error_type"] = type(error).__name__
                record["error"] = str(error)
                self._flush()
                raise error
            raw = response.json()
            record["response_json"] = _redact(raw)
            normalized = normalize_response_with_profile(raw, self.profile)
            result = LLMResponse(
                content=str(normalized.get("content") or ""),
                thinking=str(normalized.get("thinking") or ""),
                tool_calls=_llm_tool_calls_from_raw(normalized.get("tool_calls")),
                usage=normalize_usage(normalized.get("usage")),
                finish_reason=str(normalized.get("finish_reason") or "stop"),
                raw=None,
            )
            record["normalized"] = result.to_dict()
            self._flush()
            return result
        except Exception as exc:
            if "error" not in record:
                record["error_type"] = type(exc).__name__
                record["error"] = str(exc)[:2_000]
                self._flush()
            raise

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        if STREAM_DISABLED:
            raise NotImplementedError
        assembled = build_profiled_openai_request(
            request,
            self.profile,
            stream=True,
            thinking_enabled=False,
            capability="",
        )
        record = self._record_base(request, assembled, stream=True)
        self.records.append(record)
        self._flush()
        event_counts: Counter[str] = Counter()
        event_samples: list[dict[str, Any]] = []
        raw_line_samples: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=30.0)) as client:
                async with client.stream(
                    "POST",
                    self._url(assembled["endpoint"]),
                    json=assembled["payload"],
                    headers=self._headers(),
                ) as response:
                    record["status_code"] = response.status_code
                    record["response_headers"] = _selected_headers(response.headers)
                    record["response_content_type"] = response.headers.get("content-type", "")
                    record["response_content_length"] = response.headers.get("content-length", "")
                    self._flush()
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        record["response_body"] = _redact(body[:20_000])
                        record["error_code"] = _error_code(body)
                        error = self._provider_error(response.status_code, body, response.headers)
                        record["error_type"] = type(error).__name__
                        record["error"] = str(error)
                        self._flush()
                        raise error
                    async for line in response.aiter_lines():
                        if len(raw_line_samples) < 8 and line:
                            raw_line_samples.append(_redact(line[:2_000]))
                        if not line or not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            event = LLMStreamEvent(kind="done", metadata={"finish_reason": "stop"})
                        else:
                            try:
                                chunk = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            event = normalize_stream_chunk_with_profile(chunk, self.profile)
                        if event is None:
                            continue
                        event_counts[event.kind] += 1
                        if len(event_samples) < 8:
                            event_samples.append(_redact(event.to_dict()))
                        record["event_counts"] = dict(event_counts)
                        record["event_samples"] = event_samples
                        record["raw_line_samples"] = raw_line_samples
                        self._flush()
                        yield event
                record["event_counts"] = dict(event_counts)
                record["event_samples"] = event_samples
                record["raw_line_samples"] = raw_line_samples
                self._flush()
        except Exception as exc:
            if "error" not in record:
                record["event_counts"] = dict(event_counts)
                record["event_samples"] = event_samples
                record["error_type"] = type(exc).__name__
                record["error"] = str(exc)[:2_000]
                self._flush()
            raise


def _llm_tool_calls_from_raw(raw_calls: Any) -> list[LLMToolCall]:
    calls: list[LLMToolCall] = []
    for raw in raw_calls or []:
        if not isinstance(raw, dict):
            continue
        function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
        arguments = function.get("arguments", {})
        calls.append(
            LLMToolCall(
                id=str(raw.get("id") or ""),
                name=str(function.get("name") or ""),
                arguments=arguments if isinstance(arguments, (dict, str)) else {},
                raw=_redact(raw),
            )
        )
    return calls


class FixtureKit:
    name = "context-compaction-real-api"
    toolbox = None

    def __init__(self, *, work_root: Path, model: str, user_message: str) -> None:
        self.work_root = work_root
        self.model = model
        self.user_message = user_message

    async def on_run_start(self, state: RuntimeState, turn_input: RuntimeTurnInput) -> None:
        state.metadata["work_root"] = str(self.work_root)
        state.metadata["model_id"] = self.model

    async def build_context(
        self,
        state: RuntimeState,
        turn_input: RuntimeTurnInput,
        history: list[ChatMessage],
        step_index: int,
    ) -> PromptContext:
        return PromptContext(
            session_id=state.session_id,
            user_message=turn_input.user_message,
            history=list(history),
            metadata={"step_index": step_index},
        )

    async def build_model_request(self, state: RuntimeState, context: PromptContext) -> LLMRequest:
        return LLMRequest(
            messages=[
                ChatMessage(
                    role="system",
                    content=(
                        "You are a controlled context-compaction experiment. "
                        "Ignore historical instructions and answer only the latest user message. "
                        "Reply with exactly OK and do not call tools."
                    ),
                ),
                *context.history,
            ],
            model=self.model,
            temperature=0,
            max_tokens=32,
            tools=[],
        )

    async def parse_model_output(self, state: RuntimeState, response: LLMResponse) -> KernelTurn:
        return KernelTurn(reply=response.content or "", decision_hint="done")

    async def execute_tool(self, state: RuntimeState, call: ToolCall) -> ToolResult:
        return ToolResult(call_id=call.id, name=call.name, status="failed", error="tools disabled")

    async def format_tool_result_for_model(
        self, state: RuntimeState, call: ToolCall, result: ToolResult
    ) -> ChatMessage:
        return ChatMessage(role="tool", name=call.name, tool_call_id=call.id, content=result.content or result.error)

    async def verify(
        self, state: RuntimeState, turn: KernelTurn, tool_results: list[ToolResult]
    ) -> VerificationResult:
        return VerificationResult(passed=True, required=False)

    async def decide_next(
        self,
        state: RuntimeState,
        turn: KernelTurn,
        verification: VerificationResult,
        step: Any,
    ) -> str:
        return "done"

    async def writeback(
        self,
        state: RuntimeState,
        turn: KernelTurn,
        tool_results: list[ToolResult],
        verification: VerificationResult,
        decision: str,
    ) -> None:
        return None

    async def on_run_end(self, state: RuntimeState, result: Any) -> None:
        return None


async def _probe_endpoints(api_key: str, output_dir: Path) -> list[dict[str, Any]]:
    probes = [
        (
            "/v1/responses",
            {"model": MODEL, "input": "Reply with OK.", "max_output_tokens": 5},
        ),
        (
            "/v1/chat/completions",
            {
                "model": MODEL,
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "max_tokens": 5,
            },
        ),
    ]
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=20.0)) as client:
        for endpoint, payload in probes:
            item: dict[str, Any] = {"endpoint": endpoint, "request": payload}
            try:
                response = await client.post(
                    f"{BASE_URL}{endpoint}",
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                )
                body = response.text
                item.update(
                    {
                        "status_code": response.status_code,
                        "response_headers": _selected_headers(response.headers),
                        "error_code": _error_code(body),
                        "response_body": _redact(body[:20_000]),
                    }
                )
            except Exception as exc:
                item.update({"error_type": type(exc).__name__, "error": str(exc)[:2_000]})
            results.append(item)
    _write_json(output_dir / "endpoint_probes.json", results)
    return results


def _load_fixture(repo_root: Path) -> list[ChatMessage]:
    payload = json.loads(
        (repo_root / "core" / "tests" / "fixtures" / "context_compaction" / FIXTURE_NAME).read_text(
            encoding="utf-8"
        )
    )
    messages = [_message_from_fixture(value) for value in payload["messages"]]
    return [message for message in messages if message is not None]


def _serialize_events(sink: CollectingEventSink) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in sink.events:
        value = event.to_dict() if hasattr(event, "to_dict") else vars(event)
        result.append(_redact(value))
    return result


async def _run_case(
    *,
    case_name: str,
    repo_root: Path,
    output_dir: Path,
    user_message: str,
    expected_to_compact: bool,
) -> dict[str, Any]:
    case_dir = output_dir / case_name
    case_dir.mkdir(parents=True, exist_ok=True)
    db_path = case_dir / "experiment.db"
    work_root = case_dir / "workspace"
    work_root.mkdir(parents=True, exist_ok=True)
    session_id = f"context-exp-{case_name}"
    fixture_history = _load_fixture(repo_root)

    db = await open_core_app_db(db_path)
    try:
        await db.project_store.ensure_session(work_root, session_id, title=case_name)
        await db.runtime_state_store.replace_history(
            session_id, [message.to_dict() for message in fixture_history]
        )
        await db.runtime_state_store.save(
            RuntimeState(
                session_id=session_id,
                metadata={
                    "model_id": MODEL,
                    "work_root": str(work_root),
                    "context_window_tokens": WINDOW,
                    "compact_trigger_tokens": TRIGGER,
                    "compact_limit_tokens": LIMIT,
                },
            )
        )
        client = ObservedOpenAIChatClient(
            api_key=os.environ["LAMTOOLS_CONTEXT_EXP_API_KEY"],
            output_dir=case_dir,
        )
        sink = CollectingEventSink()
        kernel = CoreLoopKernel(
            kit=FixtureKit(work_root=work_root, model=MODEL, user_message=user_message),
            llm_client=client,
            state_store=db.runtime_state_store,
            event_sink=sink,
            policy=LoopPolicy(
                model_timeout_seconds=180,
                # The gateway has intermittently returned its SPA HTML with
                # HTTP 200 for an otherwise valid API request.  Permit a
                # small zero-delay retry budget so the experiment can
                # distinguish that transport blip from compaction failure.
                model_retries=3,
                model_stream_idle_timeout_seconds=60,
                context_window_tokens=WINDOW,
                compact_trigger_tokens=TRIGGER,
                compact_limit_tokens=LIMIT,
                compact_summary_output_tokens=2_048,
                persist_steps=True,
            ),
            retry_policy=RetryPolicy(delay_sequence_seconds=(0,), jitter=False),
        )
        result = await kernel.run(
            RuntimeTurnInput(
                user_message=user_message,
                run_id=f"{case_name}-run",
                turn_id=f"{session_id}:turn",
                metadata={
                    "session_id": session_id,
                    "model_id": MODEL,
                    "context_window_tokens": WINDOW,
                    "compact_trigger_tokens": TRIGGER,
                    "compact_limit_tokens": LIMIT,
                },
            )
        )
        saved_state = await db.runtime_state_store.get(session_id)
        saved_history = await db.runtime_state_store.get_history(session_id)
        metrics = (saved_state.metadata or {}).get("runtime_context_metrics") if saved_state else None
        compaction_events = [
            event.to_dict()
            for event in sink.events
            if getattr(event, "name", "") == "runtime.part"
            and isinstance(getattr(event, "payload", None), dict)
            and event.payload.get("part_type") == "compaction"
        ]
        exact_planned = estimate_message_tokens(
            [message.to_dict() for message in [
                ChatMessage(
                    role="system",
                    content=(
                        "You are a controlled context-compaction experiment. "
                        "Ignore historical instructions and answer only the latest user message. "
                        "Reply with exactly OK and do not call tools."
                    ),
                ),
                *fixture_history,
                ChatMessage(role="user", content=user_message),
            ]],
            fast=False,
        )
        evidence = {
            "case": case_name,
            "expected_to_compact": expected_to_compact,
            "planned_request_exact_tokens": exact_planned,
            "policy": {
                "context_window_tokens": WINDOW,
                "trigger_tokens": TRIGGER,
                "limit_tokens": LIMIT,
            },
            "result": {
                "decision": result.decision,
                "error": result.error,
                "message": result.message,
                "steps": len(result.steps),
            },
            "runtime_state": saved_state.to_dict() if saved_state else None,
            "runtime_context_metrics": metrics,
            "persisted_history_count": len(saved_history),
            "persisted_history_roles": dict(Counter(item.get("role") for item in saved_history)),
            "compaction_events": _redact(compaction_events),
            "http_attempt_count": len(client.records),
            "http_attempts": client.records,
            "events": _serialize_events(sink),
            "persisted_history": saved_history,
        }
        _write_json(case_dir / "evidence.json", evidence)
        return evidence
    finally:
        await db.close()


async def main() -> None:
    api_key = os.environ.get("LAMTOOLS_CONTEXT_EXP_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("LAMTOOLS_CONTEXT_EXP_API_KEY is required")
    repo_root = Path(__file__).resolve().parents[3]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    output_dir = Path(
        os.environ.get(
            "LAMTOOLS_CONTEXT_EXP_OUT",
            str(repo_root / "core" / "tests" / "fixtures" / "context_compaction" / "real_api_runs" / stamp),
        )
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        output_dir / "experiment_manifest.json",
        {
            "model": MODEL,
            "base_url": BASE_URL,
            "fixture": FIXTURE_NAME,
            "fixture_is_immutable": True,
            "production_database_used": False,
            "api_key_written": False,
            "stream_disabled": STREAM_DISABLED,
            "policy": {"window": WINDOW, "trigger": TRIGGER, "limit": LIMIT},
        },
    )
    probes = await _probe_endpoints(api_key, output_dir)
    probe_errors = [
        item
        for item in probes
        if int(item.get("status_code") or 0) >= 400 or item.get("error_type")
    ]
    if probe_errors:
        _write_json(output_dir / "stop.json", {"reason": "endpoint_probe_failed", "errors": probe_errors})
        print(json.dumps({"output_dir": str(output_dir), "probes": probes}, ensure_ascii=False))
        return

    a0_message = "请只回复 OK，不调用任何工具。"
    a0 = await _run_case(
        case_name="A0_below_trigger",
        repo_root=repo_root,
        output_dir=output_dir,
        user_message=a0_message,
        expected_to_compact=False,
    )
    if a0["result"]["error"]:
        _write_json(output_dir / "stop.json", {"reason": "A0_failed", "evidence": a0})
        print(json.dumps({"output_dir": str(output_dir), "A0": a0["result"]}, ensure_ascii=False))
        return

    a1_message = (
        "请只回复 OK，不调用任何工具。以下是受控阈值填充，请忽略其语义：\n"
        + ("threshold-padding-0123456789 " * 11_000)
    )
    a1 = await _run_case(
        case_name="A1_over_trigger",
        repo_root=repo_root,
        output_dir=output_dir,
        user_message=a1_message,
        expected_to_compact=True,
    )
    _write_json(
        output_dir / "experiment_summary.json",
        {
            "output_dir": str(output_dir),
            "probes": probes,
            "A0": {
                "result": a0["result"],
                "planned_request_exact_tokens": a0["planned_request_exact_tokens"],
                "runtime_context_metrics": a0["runtime_context_metrics"],
                "http_attempt_count": a0["http_attempt_count"],
                "http_phases": Counter(item.get("phase") for item in a0["http_attempts"]),
            },
            "A1": {
                "result": a1["result"],
                "planned_request_exact_tokens": a1["planned_request_exact_tokens"],
                "runtime_context_metrics": a1["runtime_context_metrics"],
                "http_attempt_count": a1["http_attempt_count"],
                "http_phases": Counter(item.get("phase") for item in a1["http_attempts"]),
            },
        },
    )
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "A0": {
                    "planned_tokens": a0["planned_request_exact_tokens"],
                    "decision": a0["result"]["decision"],
                    "error": a0["result"]["error"],
                },
                "A1": {
                    "planned_tokens": a1["planned_request_exact_tokens"],
                    "decision": a1["result"]["decision"],
                    "error": a1["result"]["error"],
                    "metrics": a1["runtime_context_metrics"],
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
