"""Dreaming: distil a session's worth of conversation into long-term memory.

Dreaming is LamTools' analogue of Claude's "dreaming" step. After a session
(or a run within one), the kernel or a ``/dream`` command calls
:func:`dream_session` to:

1. **Extract** candidates — facts, preferences, decisions, lessons — that are
   worth keeping across sessions, using an LLM call over the session history
   (and any existing compaction summary).
2. **De-duplicate** against the short-term :class:`MemoryStore` so the same
   fact isn't recorded twice; repeated observations boost confidence.
3. **Settle** the high-confidence survivors into ``MEMORY.md``, which the
   next session picks up automatically via ``ProjectContextLoader``.

The function is pure-ish: it takes explicit dependencies (history, store,
llm_client) and returns a :class:`DreamResult`. It performs no I/O beyond the
memory store and the MEMORY.md file, matching the style of
``context_compaction.compact_context``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

from lamtools_core.llm import ChatMessage, LLMClient, LLMRequest
from lamtools_core.llm.retry import complete_with_retry
from lamtools_core.mem import MemoryEntry, MemoryQuery, MemoryScope, MemoryStoreProtocol
from lamtools_core.mem.memory_file import merge_into_memory_md, parse_memory_md
from lamtools_core.runtime import RuntimeState

try:
    from lamtools_core.kernel.policy import LoopPolicy
except ImportError:  # pragma: no cover - policy is optional at import time
    LoopPolicy = None  # type: ignore[assignment, misc]

__all__ = [
    "DreamResult",
    "DreamCandidate",
    "DreamingCheckpoint",
    "dream_session",
    "DREAM_PROMPT",
]


# ── prompt ───────────────────────────────────────────────────────

DREAM_PROMPT = """\
You organize long-term memory. Extract only information from this agent conversation that is worth retaining across sessions.

Include only these kinds of information, and only when they will be useful in a future session:
- preference (user preferences or working habits), for example: "The user prefers UTF-8 when handling Chinese text in PowerShell."
- fact (project facts or architecture), for example: "The project database is at data/core.db and has 14 tables."
- decision (confirmed technical or design decisions), for example: "context_compaction does not overwrite raw history; it only sets a read boundary."
- lesson (pitfalls or rejected approaches), for example: "SQLite writes must use write_coordinator, or they conflict with concurrent live writes."
- todo (explicit follow-up tasks), for example: "Add FTS5 to memory.search."

Do not extract one-off task details (such as a recent line edit), temporary debugging steps, or context relevant only to this session.

Output a strict JSON array with each element in this shape:
{"kind": "preference|fact|decision|lesson|todo", "content": "One concise sentence in Chinese", "confidence": 0.0~1.0}

- confidence measures certainty and future value. Give confirmed facts and explicit preferences 0.8 or higher; give speculative items 0.5 to 0.7.
- Output nothing outside the JSON array: no markdown fences or explanation.
- If there is nothing worth retaining across sessions, output the empty array `[]`.
"""


# ── data classes ─────────────────────────────────────────────────


@dataclass
class DreamCandidate:
    """A single candidate extracted by the LLM, before de-duplication."""

    kind: str
    content: str
    confidence: float = 0.5
    source: str = ""
    origin: str = "inferred"
    source_metadata: dict[str, Any] = field(default_factory=dict)
    source_refs: list[dict[str, Any]] = field(default_factory=list)

    def to_entry(
        self,
        *,
        session_id: str,
        work_root: str,
        scope: MemoryScope | None = None,
        status: str = "active",
    ) -> MemoryEntry:
        canonical_scope = scope or MemoryScope.local_legacy(work_root)
        metadata = {
            "session_id": session_id,
            "thread_id": session_id,
            "work_root": work_root,
        }
        if self.source_refs:
            metadata["source_refs"] = [dict(item) for item in self.source_refs]
        return MemoryEntry(
            id="",
            kind=self.kind,
            content=self.content,
            domain="",
            source=self.source or f"session#{session_id}",
            layer="hot",
            confidence=self.confidence,
            metadata=metadata,
            scope=canonical_scope,
            status=status,  # type: ignore[arg-type]
            origin=self.origin if self.origin in {"explicit", "observed", "inferred", "legacy", "teaching_hint"} else "inferred",  # type: ignore[arg-type]
            source_metadata=dict(self.source_metadata),
            source_refs=[dict(item) for item in self.source_refs],
        )


@dataclass
class DreamResult:
    """Outcome of a single dreaming pass."""

    status: str = "skipped"  # "dreamed" | "skipped" | "no_llm" | "failed"
    extracted: int = 0
    added: int = 0
    updated: int = 0
    memory_md_updated: bool = False
    summary: str = ""
    candidates: list[DreamCandidate] = field(default_factory=list)
    error: str = ""


@dataclass
class DreamingCheckpoint:
    """Serializable progress marker for a durable Dreaming/Arrange run."""

    job_id: str = ""
    batch_index: int = 0
    extracted: int = 0
    settled: int = 0
    status: str = "pending"
    fencing_token: int = 0
    last_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "batch_index": self.batch_index,
            "extracted": self.extracted,
            "settled": self.settled,
            "status": self.status,
            "fencing_token": self.fencing_token,
            "last_source": self.last_source,
        }


# ── main entry ───────────────────────────────────────────────────

DreamEventSink = Callable[[dict[str, Any]], Awaitable[None] | None]


async def dream_session(
    *,
    session_id: str,
    work_root: Path | str,
    history: list[ChatMessage],
    compaction_summary: str | None = None,
    memory_store: MemoryStoreProtocol,
    llm_client: LLMClient | None = None,
    model: str = "",
    on_event: DreamEventSink | None = None,
    policy: Any | None = None,
    min_confidence: float = 0.5,
    scope: MemoryScope | None = None,
    memory_service: Any | None = None,
    checkpoint: DreamingCheckpoint | None = None,
    checkpoint_callback: Callable[[DreamingCheckpoint], Awaitable[None] | None] | None = None,
    cancel_event: asyncio.Event | None = None,
    lease_guard: Callable[[], bool | Awaitable[bool]] | None = None,
) -> DreamResult:
    """Distil a session into short-term store + MEMORY.md.

    Parameters mirror what the two call sites provide:
    - Stop hook (``loop.py``): passes ``history`` reloaded from the store,
      ``compaction_summary`` from ``state.metadata``, ``self.llm_client``.
    - ``/dream`` command (``command_execution.py``): same, via the command
      handler.

    The function never raises on LLM failures — it returns a
    ``DreamResult(status="failed", error=...)`` so callers (especially the
    Stop hook, which must not kill the run) can simply log it.
    """
    work_root_str = str(work_root) if work_root else ""
    # Existing project callers get an explicit compatibility scope.  Study
    # must pass a library scope (project_id is None), which also prevents the
    # compatibility MEMORY.md export below.
    effective_scope = scope or MemoryScope.local_legacy(work_root_str)
    if checkpoint is None:
        checkpoint = DreamingCheckpoint(status="running")
    else:
        checkpoint.status = "running"

    async def checkpoint_now(*, status: str | None = None, last_source: str = "") -> None:
        checkpoint.batch_index = max(0, checkpoint.batch_index)
        checkpoint.last_source = last_source or checkpoint.last_source
        if status:
            checkpoint.status = status
        if checkpoint_callback is not None:
            result = checkpoint_callback(checkpoint)
            if hasattr(result, "__await__"):
                await result

    async def cancelled() -> bool:
        if cancel_event is not None and cancel_event.is_set():
            return True
        if lease_guard is not None:
            result = lease_guard()
            if hasattr(result, "__await__"):
                result = await result
            if not result:
                return True
        return False

    if await cancelled():
        await checkpoint_now(status="cancelled")
        return DreamResult(status="cancelled", summary="Dreaming was cancelled before extraction.")

    if not history and not compaction_summary:
        return DreamResult(status="skipped", summary="No session content to dream.")

    await _emit(on_event, {"status": "running", "phase": "extract", "label": "正在提取记忆候选"})

    # ── 1. extract candidates via LLM ──
    candidates: list[DreamCandidate] = []
    if llm_client is None:
        # Without an LLM we can still settle any existing compaction summary
        # as a single fact. Seeded at the MEMORY.md threshold (0.6) so it
        # actually lands in the long-term file — the previous 0.4 was below
        # both the candidate filter and the settle gate, a dead path
        # (audit 11).
        if compaction_summary:
            candidates.append(
                DreamCandidate(kind="fact", content=compaction_summary[:500], confidence=0.6)
            )
    else:
        try:
            candidates = await _extract_candidates(
                history=history,
                compaction_summary=compaction_summary,
                llm_client=llm_client,
                model=model,
                policy=policy,
            )
        except Exception as exc:  # noqa: BLE001 - dreaming must not kill the run
            return DreamResult(
                status="failed",
                error=str(exc),
                summary=f"Dreaming extraction failed: {exc}",
            )

    # Filter by confidence.
    # Model output is untrusted.  Discard ability/grade/mastery labels rather
    # than allowing one mark or one mistake to become durable identity.  A
    # knowledge teaching hint is retained as a separate kind/origin and is
    # never returned by personal-memory queries by default.
    candidates = [c for c in candidates if _safe_candidate(c) and c.confidence >= min_confidence]
    if not candidates:
        await _emit(on_event, {"status": "done", "phase": "done", "label": "无可沉淀记忆"})
        no_llm = llm_client is None
        return DreamResult(
            status="no_llm" if no_llm else "dreamed",
            extracted=0,
            summary="No candidates above threshold.",
        )

    await _emit(
        on_event,
        {"status": "running", "phase": "dedupe", "label": f"去重归并 · {len(candidates)} 条候选"},
    )

    # ── 2. de-duplicate against the short-term store ──
    added = 0
    updated = 0
    settled: list[MemoryEntry] = []
    for index, candidate in enumerate(candidates):
        if await cancelled():
            await checkpoint_now(status="cancelled")
            return DreamResult(
                status="cancelled",
                extracted=len(candidates),
                added=added,
                updated=updated,
                summary="Dreaming was cancelled before the next memory write.",
                candidates=candidates,
            )
        entry = candidate.to_entry(
            session_id=session_id,
            work_root=work_root_str,
            scope=effective_scope,
        )
        if await _source_is_suppressed(memory_store, effective_scope, entry.source):
            checkpoint.batch_index = index + 1
            await checkpoint_now(last_source=entry.source)
            continue
        # Search for an existing entry with overlapping content.
        existing = await memory_store.search(
            MemoryQuery(
                query=candidate.content,
                kinds=[candidate.kind],
                limit=3,
                scope=effective_scope,
                work_root=work_root_str or None,
                statuses=["active"],
                include_teaching_hints=True,
            )
        )
        if existing.hits:
            # Merge: bump confidence, refresh content if the new one is richer.
            hit = existing.hits[0]
            hit.entry.confidence = min(1.0, hit.entry.confidence + 0.1)
            if len(candidate.content) > len(hit.entry.content):
                hit.entry.content = candidate.content
            hit.entry.accessed_at = datetime.now()
            # De-duplicate the session trace and cap it so a high-frequency
            # memory's metadata cannot grow without bound (audit 11).
            sessions = hit.entry.metadata.setdefault("sessions", [])
            if session_id not in sessions:
                sessions.append(session_id)
            del sessions[:-20]
            await memory_store.add(hit.entry)
            updated += 1
            settled.append(hit.entry)
        else:
            await memory_store.add(entry)
            added += 1
            settled.append(entry)
        checkpoint.batch_index = index + 1
        checkpoint.extracted = len(candidates)
        checkpoint.settled = len(settled)
        await checkpoint_now(last_source=entry.source)

    await _emit(
        on_event,
        {"status": "running", "phase": "settle", "label": "沉淀到 MEMORY.md"},
    )

    # ── 3. settle high-confidence entries into MEMORY.md ──
    memory_md_updated = False
    merge_report = {"added": 0, "updated": 0, "total": 0}
    # ``MEMORY.md`` is only a project compatibility export.  A projectless
    # Study scope remains authoritative in the shared store and never creates
    # or reads a project file.
    allow_memory_file = bool(
        work_root_str
        and (effective_scope.compatibility_fallback or effective_scope.project_id)
        and not effective_scope.library_id
    )
    if allow_memory_file:
        memory_md_path = Path(work_root_str) / "MEMORY.md"
        # Only settle entries that are confident enough for the long-term file.
        to_settle = [e for e in settled if e.confidence >= 0.6]
        if to_settle:
            try:
                merge_report = merge_into_memory_md(memory_md_path, to_settle)
                memory_md_updated = merge_report["added"] > 0 or merge_report["updated"] > 0
            except Exception as exc:  # noqa: BLE001
                return DreamResult(
                    status="failed",
                    error=str(exc),
                    extracted=len(candidates),
                    added=added,
                    updated=updated,
                    summary=f"Dreaming MEMORY.md write failed: {exc}",
                    candidates=candidates,
                )

    summary = (
        f"提取 {len(candidates)} 条候选，新增 {added}，更新 {updated}，"
        f"MEMORY.md {'已更新' if memory_md_updated else '无变化'}。"
    )
    await _emit(on_event, {"status": "done", "phase": "done", "label": summary})

    await checkpoint_now(status="completed")
    return DreamResult(
        status="dreamed",
        extracted=len(candidates),
        added=added,
        updated=updated,
        memory_md_updated=memory_md_updated,
        summary=summary,
        candidates=candidates,
    )


# ── LLM extraction ───────────────────────────────────────────────


async def _extract_candidates(
    *,
    history: list[ChatMessage],
    compaction_summary: str | None,
    llm_client: LLMClient,
    model: str,
    policy: Any | None,
) -> list[DreamCandidate]:
    """Ask the LLM to extract memory candidates from the session transcript."""
    transcript = _format_history_for_dream(history, compaction_summary=compaction_summary)
    if not transcript.strip():
        return []

    request = LLMRequest(
        messages=[
            ChatMessage(role="system", content=DREAM_PROMPT),
            ChatMessage(role="user", content=transcript),
        ],
        model=model,
        temperature=0,
        max_tokens=2048,
    )

    max_attempts = int(getattr(policy, "model_retries", 3)) or 3
    timeout = getattr(policy, "model_timeout_seconds", None)
    response = await complete_with_retry(
        llm_client,
        request,
        max_attempts=max_attempts,
        timeout_seconds=timeout,
    )
    return _parse_candidates(response.content)


def _format_history_for_dream(
    history: list[ChatMessage],
    *,
    compaction_summary: str | None = None,
    max_chars: int = 12000,
) -> str:
    """Render the session as a compact transcript for the dreaming LLM.

    Tool results are truncated heavily — dreaming cares about *outcomes* and
    *facts*, not the full tool output. The compaction summary (if present) is
    prepended as it already distils earlier context.
    """
    parts: list[str] = []
    if compaction_summary:
        parts.append(f"[Prior session summary]\n{compaction_summary}\n")
        parts.append("[Current session]")

    total = 0
    for msg in history:
        role = msg.role
        content = msg.content
        if isinstance(content, list):
            # Multimodal: join text blocks, skip images.
            content = " ".join(
                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
            )
        content = str(content).strip()
        if not content:
            # Keep tool call traces but without args detail.
            if msg.tool_calls:
                names = ", ".join(tc.name for tc in msg.tool_calls)
                content = f"(Called tools: {names})"
            else:
                continue

        # Truncate long tool results aggressively.
        if role == "tool":
            if len(content) > 300:
                content = content[:300] + "…"
        elif len(content) > 1000:
            content = content[:1000] + "…"

        line = f"[{role}] {content}"
        if total + len(line) > max_chars:
            parts.append(line[: max_chars - total] + "…")
            break
        parts.append(line)
        total += len(line) + 1

    return "\n".join(parts)


def _parse_candidates(raw: str) -> list[DreamCandidate]:
    """Parse the LLM's JSON array output into candidates.

    Tolerates surrounding whitespace, stray markdown fences, and a single
    object (wrapped into a one-element list).
    """
    text = (raw or "").strip()
    if not text:
        return []
    # Strip markdown code fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to locate the first JSON array in the text.
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return []
        else:
            return []

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []

    candidates: list[DreamCandidate] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        raw_kind = str(item.get("kind", "fact")).strip().lower()
        # Keep the public vocabulary small.  The model may call a knowledge
        # hint by either spelling, but ability/grade labels are never valid
        # durable personal-memory kinds.
        if raw_kind in {"knowledge.teaching_hint", "knowledge_teaching_hint", "teaching-hint"}:
            kind = "teaching_hint"
            origin = "teaching_hint"
        elif raw_kind in {
            "ability",
            "global_ability",
            "mastery",
            "score",
            "grade",
            "exam_result",
            "exam-score",
        }:
            continue
        else:
            kind = raw_kind or "fact"
            origin = "inferred"
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        raw_refs = item.get("source_refs") or item.get("sources") or []
        refs = [dict(ref) for ref in raw_refs if isinstance(ref, dict)] if isinstance(raw_refs, list) else []
        candidates.append(DreamCandidate(
            kind=kind,
            content=content,
            confidence=max(0.0, min(1.0, confidence)),
            origin=origin,
            source_metadata={"model_origin": "dreaming"},
            source_refs=refs,
        ))
    return candidates


# ── helpers ──────────────────────────────────────────────────────


async def _emit(sink: DreamEventSink | None, payload: dict[str, Any]) -> None:
    if sink is None:
        return
    result = sink(payload)
    if hasattr(result, "__await__"):
        await result


def _safe_candidate(candidate: DreamCandidate) -> bool:
    """Return whether a model candidate is eligible for consolidation."""

    kind = str(candidate.kind or "").strip().lower()
    if kind in {
        "ability",
        "global_ability",
        "mastery",
        "score",
        "grade",
        "exam_result",
        "exam-score",
    }:
        return False
    # A model cannot promote an inferred row to an explicit user claim.
    if candidate.origin == "explicit":
        candidate.origin = "inferred"
    return bool(candidate.content.strip())


async def _source_is_suppressed(
    memory_store: MemoryStoreProtocol,
    scope: MemoryScope,
    source: str,
) -> bool:
    source = str(source or "").strip()
    if not source:
        return False
    checker = getattr(memory_store, "is_source_suppressed", None)
    if callable(checker):
        return bool(await checker(scope, source))
    return False


def should_dream(
    state: RuntimeState,
    *,
    policy: Any | None = None,
    had_compaction: bool = False,
    had_tool_use: bool = False,
) -> bool:
    """Decide whether dreaming should fire this turn (Stop-hook throttling).

    Conditions (all must hold):
    - ``dreaming_enabled`` on policy (default True)
    - enough turns since the last dream (``dream_min_turns``)
    - the turn produced something worth dreaming: a compaction summary or
      tool use (pure chit-chat with no tools is unlikely to yield facts)
    """
    if policy is not None and not getattr(policy, "dreaming_enabled", True):
        return False
    min_turns = int(getattr(policy, "dream_min_turns", 3) or 3)
    last_dream = 0
    metadata = state.metadata if isinstance(state.metadata, dict) else {}
    raw_last = metadata.get("last_dream_turn")
    if isinstance(raw_last, (int, float)):
        last_dream = int(raw_last)
    turns_since = state.turn_count - last_dream
    if turns_since < min_turns:
        return False
    if not had_compaction and not had_tool_use:
        return False
    return True


def record_dream_turn(state: RuntimeState) -> None:
    """Stamp the current turn as the last dreamed turn."""
    if not isinstance(state.metadata, dict):
        state.metadata = {}
    state.metadata["last_dream_turn"] = state.turn_count
