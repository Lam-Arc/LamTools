"""Dreaming — asynchronous maintenance of the memory library and its L1 document.

PRD 5: while the user talks to Sunday, a background pass periodically reads the
*new* part of finished conversations, decides what is worth keeping, writes the
detail into ordinary memory files and rewrites ``memory.md`` (the core cognition
injected into every request).

Design rules this module implements:

* **Incremental.**  A per-session cursor (``.dreaming/state.json``) means only
  turns that were never digested are sent to the model.  Length is used only to
  pace the turn-end trigger — the periodic sweep digests short turns too, so a
  brief but important statement is never dropped.
* **Cheap.**  Short small talk still goes through the model only on the sweep's
  schedule, per-tier passes are throttled, one pass is one model call with
  bounded input and output.
* **Evolvable, not append-only.**  The pass rewrites ``memory.md`` as a whole so
  contradictions get resolved instead of piling up, with two guards: regions the
  user pinned between ``memory:keep`` markers are carried over verbatim, and every
  replaced version is kept on disk.  A failed pass writes nothing at all.
* **Honest.**  Inferences are labelled as such in the prompt; secrets are
  stripped before anything is stored; entries the user deleted stay on a
  "forgotten" list that the prompt forbids restoring.
* **Safe under concurrency.**  One pass per process and one per tier at a time;
  the core document is written only if it still matches the version sent to
  the model, preserving any concurrent user save.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lamtools_core.llm import ChatMessage, LLMRequest
from lamtools_core.llm.retry import complete_with_retry
from lamtools_core.mem import library as memory_library
from lamtools_core.mem import settings as memory_settings

# ---------------------------------------------------------------------------
# Budgets and thresholds (engineering defaults; the PRD leaves them open)
# ---------------------------------------------------------------------------

#: Only decides *when* the turn-end trigger fires — it never decides whether the
#: information is worth keeping. The periodic sweep ignores it, so a short but
#: important turn is digested a few minutes later instead of being dropped.
DREAM_MIN_NEW_CHARS = 240

#: Per-tier throttle between two passes.
DREAM_MIN_INTERVAL_SECONDS = 900.0

#: Per-session throttle, so a rapid multi-turn burst becomes one pass.
DREAM_SESSION_COOLDOWN_SECONDS = 300.0

#: Bounds on one pass.
DREAM_MAX_NEW_CHARS = 12_000
DREAM_MAX_TURNS = 40
DREAM_MAX_TURN_CHARS = 1_500
DREAM_MAX_INDEX_CHARS = 4_000
DREAM_MAX_MEMORY_CHARS = 20_000
DREAM_MAX_MEMORIES_PER_SCOPE = 8

#: Exception guard for a runaway model answer; size is otherwise controlled by
#: the prompt's ~3000-character target (distillation, not truncation).
DREAM_MAX_CORE_CHARS = memory_library.MAX_CORE_PROMPT_CHARS

DREAM_CALL_TIMEOUT_SECONDS = 180.0
DREAM_LOCK_STALE_SECONDS = 600.0
DREAM_SWEEP_SECONDS = 600.0

STATE_DIRNAME = ".dreaming"
STATE_FILENAME = "state.json"
LOCK_FILENAME = "lock"
PROMPT_VERSION = 1
MAX_FORGOTTEN_ENTRIES = 200

#: Model output paths that would corrupt the library are refused outright.
_RESERVED_DREAM_PATHS: frozenset[str] = frozenset(
    {memory_library.INDEX_FILENAME, memory_library.CORE_FILENAME}
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|password|passwd|secret|access[_-]?token|refresh[_-]?token|token"
        r"|密钥|密码|口令|令牌)\b\s*[:=]\s*\S{6,}"
    ),
)


# ---------------------------------------------------------------------------
# State (cursor, throttle, forgotten list)
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "prompt_version": PROMPT_VERSION,
        "sessions": {},
        "last_dream_at": "",
        "last_error": "",
        "forgotten": [],
    }


def _state_path(scope: str, work_root: str | Path | None) -> Path:
    return (
        memory_library.memory_root(scope, work_root) / STATE_DIRNAME / STATE_FILENAME
    )


def load_state(scope: str, work_root: str | Path | None) -> dict[str, Any]:
    """Read the tier's dream state, falling back to an empty one."""
    try:
        path = _state_path(scope, work_root)
    except memory_library.MemoryError:
        return _default_state()
    if not path.is_file():
        return _default_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _default_state()
    state = _default_state()
    if isinstance(data, dict):
        sessions = data.get("sessions")
        if isinstance(sessions, dict):
            state["sessions"] = {
                str(key): value
                for key, value in sessions.items()
                if isinstance(value, dict)
            }
        forgotten = data.get("forgotten")
        if isinstance(forgotten, list):
            state["forgotten"] = [item for item in forgotten if isinstance(item, dict)]
        state["last_dream_at"] = str(data.get("last_dream_at") or "")
        state["last_error"] = str(data.get("last_error") or "")
    return state


def save_state(scope: str, work_root: str | Path | None, state: dict[str, Any]) -> None:
    memory_library._atomic_write(
        _state_path(scope, work_root), json.dumps(state, ensure_ascii=False, indent=2)
    )


def record_forgotten(
    scope: str, work_root: str | Path | None, path: str, title: str = ""
) -> None:
    """Remember that the user deleted *path*, so no pass restores it (PRD 6)."""
    entry = {
        "path": str(path or "").strip(),
        "title": str(title or "").strip()[:200],
        "at": _now_iso(),
    }
    if not entry["path"]:
        return
    try:
        state = load_state(scope, work_root)
        forgotten = [
            item for item in state.get("forgotten", []) if item.get("path") != entry["path"]
        ]
        forgotten.append(entry)
        state["forgotten"] = forgotten[-MAX_FORGOTTEN_ENTRIES:]
        save_state(scope, work_root, state)
    except (OSError, memory_library.MemoryError):
        # Losing a tombstone must never fail the delete the user asked for.
        return


def dream_status(scope: str, work_root: str | Path | None) -> dict[str, Any]:
    """Everything the UI needs about the last pass of one tier."""
    state = load_state(scope, work_root)
    return {
        "enabled": dreaming_enabled(),
        "last_dream_at": state.get("last_dream_at", ""),
        "last_error": state.get("last_error", ""),
        "sessions": len(state.get("sessions", {})),
        "forgotten": len(state.get("forgotten", [])),
    }


def dreaming_enabled() -> bool:
    return memory_settings.memory_enabled()


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------


def acquire_dream_lock(scope: str, work_root: str | Path | None) -> Path | None:
    """Take the tier lock, or return None when another pass holds it."""
    try:
        root = memory_library.memory_root(scope, work_root)
    except memory_library.MemoryError:
        return None
    lock = root / STATE_DIRNAME / LOCK_FILENAME
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    def _create() -> int:
        return os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)

    try:
        handle = _create()
    except FileExistsError:
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            return None
        if age <= DREAM_LOCK_STALE_SECONDS:
            return None
        # A pass that died without releasing the lock must not stop every later
        # pass: the lock is a mutual-exclusion hint, not a permanent token.
        try:
            lock.unlink(missing_ok=True)
            handle = _create()
        except OSError:
            return None
    except OSError:
        return None
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(f"{os.getpid()} {time.time()}")
    return lock


def release_dream_lock(lock: Path | None) -> None:
    if lock is None:
        return
    try:
        lock.unlink(missing_ok=True)
    except OSError:  # pragma: no cover - defensive
        return


# ---------------------------------------------------------------------------
# Turn selection
# ---------------------------------------------------------------------------


def select_undreamt_turns(
    items: list[dict[str, Any]] | None, last_seq: int = 0
) -> tuple[list[dict[str, Any]], int]:
    """Return the turns after the cursor, plus the (never decreasing) cursor."""
    cursor = int(last_seq or 0)
    turns: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        try:
            seq = int(item.get("seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        if seq <= int(last_seq or 0):
            cursor = max(cursor, seq)
            continue
        prompt = str(item.get("prompt") or "").strip()
        response = str(
            item.get("response_excerpt") or item.get("response") or ""
        ).strip()
        if not prompt and not response:
            cursor = max(cursor, seq)
            continue
        turns.append(
            {
                "seq": seq,
                "prompt": prompt[:DREAM_MAX_TURN_CHARS],
                "response": response[:DREAM_MAX_TURN_CHARS],
            }
        )
        cursor = max(cursor, seq)
    return turns, cursor


def truncate_turns(
    turns: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Bound one pass; the cursor only advances past turns actually included."""
    kept: list[dict[str, Any]] = []
    used = 0
    cursor = 0
    for turn in turns:
        size = len(str(turn.get("prompt") or "")) + len(str(turn.get("response") or ""))
        if kept and (used + size > DREAM_MAX_NEW_CHARS or len(kept) >= DREAM_MAX_TURNS):
            break
        kept.append(turn)
        used += size
        cursor = max(cursor, int(turn.get("seq") or 0))
    return kept, cursor


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

DREAM_SYSTEM_PROMPT = """You are Sunday's memory distillation pass ("Dreaming").
You read a slice of a finished conversation and keep the assistant's long-term
knowledge about the user, their projects and their decisions accurate.

What to keep (only durable value):
- facts the user stated about themselves, their setup, their preferences;
- decisions the user confirmed, with the reason and the date when it matters;
- hard constraints and design principles that will still matter next week;
- lessons from failures and conclusions that were actually reached;
- ongoing work and its latest agreed state.

What not to keep:
- small talk, one-off requests, transient states;
- anything you merely guessed: label an inference as 推断 explicitly;
- credentials, API keys, tokens, passwords, private keys — never;
- anything listed below as forgotten/deleted by the user.

How to write:
- `core` is the whole memory.md: the cognition the assistant carries into every
  request. Rewrite the document as a whole, not as an append-only log — merge
  duplicates and replace conclusions that were superseded, so the document never
  contains two answers to the same question.
- Text between `<!-- memory:keep:start -->` and `<!-- memory:keep:end -->` is
  pinned by the user. Keep those regions verbatim.
- Keep the document around 3000 characters. When it grows, move the detail into
  `memories` and leave one line here: compress by organising, never by dropping
  facts that still matter.
- Do NOT repeat the whole conversation; this is cognition, not a transcript.
- `memories` are detailed files. One topic per file. The first line is the
  trigger: "when X, read this" (the condition under which the file is useful),
  never just a topic label. 3-10 lines per file. Reuse an existing path (see the
  index) instead of creating a near-duplicate; use mode "append" to add to it.
- Global scope = the user across projects. Project scope = this workspace only.
  Never put project-specific facts into the global scope.

Output STRICT JSON, no prose, no code fence:
{"global": {"core": "", "memories": [{"path": "", "mode": "append|write", "content": ""}]},
 "project": {"core": "", "memories": []},
 "notes": ""}
Leave a section empty when nothing durable belongs there."""


def scrub_secrets(text: str) -> tuple[str, int]:
    """Drop lines that look like credentials; return the text and drop count."""
    dropped = 0
    kept: list[str] = []
    for line in str(text or "").splitlines():
        if any(pattern.search(line) for pattern in _SECRET_PATTERNS):
            dropped += 1
            continue
        kept.append(line)
    return "\n".join(kept), dropped


def _bound_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    newline = cut.rfind("\n")
    if newline > limit // 2:
        cut = cut[:newline]
    return cut.rstrip() + "\n（已按预算截断）"


def _cut_at_paragraph(text: str, limit: int) -> str:
    cut = text[:limit]
    boundary = cut.rfind("\n\n")
    if boundary > limit // 2:
        cut = cut[:boundary]
    return cut.rstrip()


def _read_core_documents(work_root: str | Path | None) -> dict[str, str]:
    documents = {
        memory_library.SCOPE_GLOBAL: memory_library.read_core_document(memory_library.SCOPE_GLOBAL, None)
    }
    if work_root:
        documents[memory_library.SCOPE_PROJECT] = memory_library.read_core_document(
            memory_library.SCOPE_PROJECT, work_root
        )
    return documents


def build_dream_messages(
    *,
    work_root: str | Path | None,
    session_id: str,
    turns: list[dict[str, Any]],
    scope: str | None = None,
    core_before: dict[str, str] | None = None,
) -> list[ChatMessage]:
    """Assemble the single prompt of one pass."""
    tier = (
        memory_library.SCOPE_PROJECT
        if (work_root and scope != memory_library.SCOPE_GLOBAL)
        else memory_library.SCOPE_GLOBAL
    )
    state = load_state(tier, work_root if tier == memory_library.SCOPE_PROJECT else None)

    if core_before is None:
        core_before = _read_core_documents(work_root if tier == memory_library.SCOPE_PROJECT else None)
    project_core = core_before.get(memory_library.SCOPE_PROJECT, "")
    index = (
        memory_library.render_index(memory_library.SCOPE_PROJECT, work_root)
        if tier == memory_library.SCOPE_PROJECT
        else ""
    )
    global_core = core_before[memory_library.SCOPE_GLOBAL]

    forgotten = state.get("forgotten") or []
    forgotten_lines = (
        "\n".join(
            f"- {item.get('path') or ''}"
            + (f" — {item.get('title')}" if item.get("title") else "")
            for item in forgotten
            if item.get("path")
        )
        or "(none)"
    )

    transcript: list[str] = []
    for turn in turns:
        transcript.append(f"[turn seq {turn.get('seq')}]")
        if turn.get("prompt"):
            transcript.append(f"User: {turn['prompt']}")
        if turn.get("response"):
            transcript.append(f"Assistant: {turn['response']}")
    transcript_text = "\n".join(transcript)

    sections = [
        "## Scope",
        f"session: {session_id}",
        f"project root: {work_root}"
        if tier == memory_library.SCOPE_PROJECT
        else "project root: (none — global scope only)",
        "",
        "## Existing project core cognition (memory.md)",
        _bound_text(project_core.strip(), 4_000) if project_core.strip() else "(empty)",
        "",
        "## Project memory index (file titles only)",
        _bound_text(index.strip(), DREAM_MAX_INDEX_CHARS) if index.strip() else "(empty)",
        "",
        "## Existing global cognition (memory.md)",
        _bound_text(global_core.strip(), 2_000) if global_core.strip() else "(empty)",
        "",
        "## 已被用户删除或要求忘记（不要恢复 / forgotten — never restore）",
        forgotten_lines,
        "",
        "## New conversation turns to digest",
        transcript_text or "(empty)",
        "",
        "Return the JSON object only.",
    ]
    return [
        ChatMessage(role="system", content=DREAM_SYSTEM_PROMPT),
        ChatMessage(role="user", content="\n".join(sections)),
    ]


def parse_dream_output(text: str) -> dict[str, Any]:
    """Parse the model's strict-JSON answer (tolerating a code fence)."""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty dream response")
    if raw.startswith("```"):
        raw = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("dream response is not a JSON object")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("dream response must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Applying one parsed pass
# ---------------------------------------------------------------------------


def _apply_core_document(
    scope: str, work_root: str | Path | None, core_text: str, *, expected: str
) -> bool:
    text, _ = scrub_secrets(str(core_text or ""))
    text = text.strip()
    if not text:
        return False
    if len(text) > DREAM_MAX_CORE_CHARS:
        # Size is supposed to be controlled by distillation; this branch only
        # stops a runaway answer from turning the document into a dump.
        text = _cut_at_paragraph(text, DREAM_MAX_CORE_CHARS)
        text += "\n\n（整理结果超出体积上限，末尾已截断；更细的内容应放进独立记忆文件）"
    # user:“全修，但是不要过度工程化”+(以送给模型的原文校验；整理期间手动保存或清空后，丢弃这次旧稿)。
    merged = memory_library.merge_core_document(expected, text)
    if merged == expected:
        return False
    try:
        memory_library.write_core_document(scope, work_root, merged, expected=expected)
    except memory_library.MemoryConflictError:
        return False
    return True


def _apply_memories(
    scope: str, work_root: str | Path | None, items: Any
) -> list[dict[str, str]]:
    written: list[dict[str, str]] = []
    if not isinstance(items, list):
        return written
    root = memory_library.memory_root(scope, work_root).resolve()
    # user:“全修，但是不要过度工程化”+(在写入前用最新的删除记录挡住已删除路径)。
    forgotten = {
        Path(entry["path"])
        for entry in load_state(scope, work_root).get("forgotten", [])
        if isinstance(entry.get("path"), str)
    }
    for item in items[:DREAM_MAX_MEMORIES_PER_SCOPE]:
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path") or "").strip()
        if not raw_path:
            continue
        try:
            memory_library.resolve_memory_path(scope, work_root, raw_path)
        except memory_library.MemoryError:
            # Escaping paths and generated files are refused silently: the pass
            # must never be able to rewrite INDEX.md or memory.md.
            continue
        cleaned = str(raw_path).replace("\\", "/").strip("/")
        if cleaned.split("/")[-1] in _RESERVED_DREAM_PATHS:
            continue
        if not cleaned.lower().endswith(".md"):
            continue
        content, _ = scrub_secrets(str(item.get("content") or ""))
        content = content.strip()
        if not content:
            continue
        content = content[:DREAM_MAX_MEMORY_CHARS]
        try:
            relative = (
                memory_library.resolve_memory_path(scope, work_root, cleaned)
                .relative_to(root)
                .as_posix()
            )
        except (ValueError, memory_library.MemoryError):
            continue
        path = Path(relative)
        if path in forgotten or not forgotten.isdisjoint(path.parents):
            continue
        mode = str(item.get("mode") or "write").strip().lower()
        try:
            if mode == "append":
                memory_library.append_memory(scope, work_root, relative, content + "\n")
            else:
                memory_library.write_memory(scope, work_root, relative, content + "\n")
        except memory_library.MemoryError:
            continue
        written.append({"scope": scope, "path": relative})
    return written


def apply_dream_output(
    *,
    work_root: str | Path | None,
    output: dict[str, Any],
    core_before: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Write one validated pass.  Called only after the JSON parsed."""
    if core_before is None:
        core_before = _read_core_documents(work_root)
    written: list[dict[str, str]] = []
    global_section = output.get("global") if isinstance(output.get("global"), dict) else {}
    project_section = output.get("project") if isinstance(output.get("project"), dict) else {}

    global_core = global_section.get("core") or global_section.get("core_auto") or ""
    if _apply_core_document(
        memory_library.SCOPE_GLOBAL, None, global_core, expected=core_before[memory_library.SCOPE_GLOBAL]
    ):
        written.append({"scope": memory_library.SCOPE_GLOBAL, "path": memory_library.CORE_FILENAME})
    written.extend(
        _apply_memories(memory_library.SCOPE_GLOBAL, None, global_section.get("memories"))
    )

    if work_root:
        project_core = project_section.get("core") or project_section.get("core_auto") or ""
        if _apply_core_document(
            memory_library.SCOPE_PROJECT, work_root, project_core,
            expected=core_before[memory_library.SCOPE_PROJECT],
        ):
            written.append(
                {"scope": memory_library.SCOPE_PROJECT, "path": memory_library.CORE_FILENAME}
            )
        written.extend(
            _apply_memories(
                memory_library.SCOPE_PROJECT, work_root, project_section.get("memories")
            )
        )
    return written


# ---------------------------------------------------------------------------
# One pass
# ---------------------------------------------------------------------------

#: One pass at a time inside the process. The per-tier file lock only guards
#: same-tier passes across processes; two sessions in two different projects can
#: still write the *global* tier at once, so the process also serializes them.
#: A plain flag (not an asyncio.Lock) keeps this loop-agnostic for tests and for
#: hosts that run more than one event loop.
_PASS_ACTIVE = False


async def dream_session(
    *,
    llm_client: Any,
    model_id: str,
    work_root: str | Path | None,
    session_id: str,
    turns: list[dict[str, Any]],
    scope: str | None = None,
    force: bool = False,
    now: float | None = None,
) -> dict[str, Any]:
    """Digest *turns* for one session.

    Returns ``{"status": applied|skipped|failed, "reason": str, "written": [...]}``.
    """
    # user:“关闭后…取消尚未完成的自动整理任务，避免关闭后继续写入”+(开关在任何写入前再确认一次)。
    if not dreaming_enabled():
        return {"status": "skipped", "reason": "disabled", "written": []}

    tier = (
        memory_library.SCOPE_PROJECT
        if (work_root and scope != memory_library.SCOPE_GLOBAL)
        else memory_library.SCOPE_GLOBAL
    )
    root = work_root if tier == memory_library.SCOPE_PROJECT else None

    kept, cursor = truncate_turns(turns)
    if not kept:
        return {"status": "skipped", "reason": "no_new_turns", "written": []}

    state = load_state(tier, root)
    current = float(now if now is not None else time.time())
    if not force:
        last = _parse_iso(state.get("last_dream_at"))
        if last and current - last < DREAM_MIN_INTERVAL_SECONDS:
            return {"status": "skipped", "reason": "cooldown", "written": []}

    global _PASS_ACTIVE
    if _PASS_ACTIVE:
        return {"status": "skipped", "reason": "busy", "written": []}
    # No await between the check and the claim: on one event loop this is atomic.
    _PASS_ACTIVE = True
    try:
        return await _run_pass(
            llm_client=llm_client,
            model_id=model_id,
            tier=tier,
            root=root,
            session_id=session_id,
            kept=kept,
            cursor=cursor,
        )
    finally:
        _PASS_ACTIVE = False


async def _run_pass(
    *,
    llm_client: Any,
    model_id: str,
    tier: str,
    root: str | Path | None,
    session_id: str,
    kept: list[dict[str, Any]],
    cursor: int,
) -> dict[str, Any]:
    """The part of a pass that talks to the model and writes state."""
    lock = acquire_dream_lock(tier, root)
    if lock is None:
        return {"status": "skipped", "reason": "busy", "written": []}
    try:
        core_before = _read_core_documents(root)
        messages = build_dream_messages(
            work_root=root,
            session_id=session_id,
            turns=kept,
            scope=tier,
            core_before=core_before,
        )
        request = LLMRequest(
            messages=messages,
            model=str(model_id or ""),
            temperature=0,
            metadata={
                "thinking_enabled": False,
                "reasoning_level": "off",
                "_runtime_session_id": session_id,
                "_memory_dream": PROMPT_VERSION,
            },
        )
        response = await complete_with_retry(
            llm_client,
            request,
            max_attempts=1,
            timeout_seconds=DREAM_CALL_TIMEOUT_SECONDS,
        )
        if not dreaming_enabled():
            return {"status": "skipped", "reason": "disabled", "written": []}
        output = parse_dream_output(getattr(response, "content", "") or "")
        written = apply_dream_output(work_root=root, output=output, core_before=core_before)

        # Re-read before writing the cursor: a delete may have added a tombstone
        # while the model was running, and that must not be clobbered.
        latest = load_state(tier, root)
        sessions = dict(latest.get("sessions") or {})
        sessions[session_id] = {"last_seq": cursor, "dreamt_at": _now_iso()}
        latest["sessions"] = sessions
        latest["last_dream_at"] = _now_iso()
        latest["last_error"] = ""
        latest["prompt_version"] = PROMPT_VERSION
        save_state(tier, root, latest)
        return {"status": "applied", "reason": "", "written": written, "turns": len(kept)}
    except Exception as exc:  # noqa: BLE001 - a failed pass must never break the app
        try:
            failed = load_state(tier, root)
            failed["last_error"] = f"{type(exc).__name__}: {exc}"[:500]
            save_state(tier, root, failed)
        except (OSError, memory_library.MemoryError):
            pass
        return {"status": "failed", "reason": str(exc), "written": []}
    finally:
        release_dream_lock(lock)


# ---------------------------------------------------------------------------
# Triggers (turn end, periodic sweep, manual request)
# ---------------------------------------------------------------------------

_LAST_ATTEMPT: dict[str, float] = {}
_SUPERVISOR: "DreamSupervisor | None" = None


async def _load_outline_snapshot(context: Any, thread_id: str) -> dict[str, Any]:
    async with context.session_factory() as db:
        loader = getattr(context.persistence, "load_items_by_kind", None)
        if callable(loader):
            return await loader(db, thread_id, text_marker="agentMessage")
        return await context.persistence.load(db, thread_id)


async def _session_work_root(context: Any, thread_id: str) -> str:
    store = getattr(getattr(context, "host", None), "session_store", None)
    if store is None:
        return ""
    try:
        session = await store.get(thread_id)
    except Exception:  # noqa: BLE001 - a missing session simply has no project
        return ""
    metadata = getattr(session, "metadata", None)
    return str((metadata or {}).get("work_root") or "") if isinstance(metadata, dict) else ""


def _background_model_id() -> str:
    from lamtools_core.config.model_selection import (
        SCENE_BACKGROUND,
        ModelResolutionError,
        record_model_notice,
        resolve_scene_model,
    )

    try:
        return resolve_scene_model(SCENE_BACKGROUND).model_id
    except ModelResolutionError:
        record_model_notice(
            "后台任务没有可用模型，已跳过记忆整理；请先添加供应商/模型"
        )
        return ""


async def maybe_dream_after_turn(
    *,
    context: Any,
    thread_id: str,
    work_root: str = "",
    force: bool = False,
    ignore_size_gate: bool = False,
) -> dict[str, Any]:
    """Best-effort pass after a turn: cheap checks first, model only if worth it.

    ``force`` skips throttling (manual request); ``ignore_size_gate`` lets the
    periodic sweep digest a short turn that the immediate trigger deferred.
    """
    if not dreaming_enabled():
        return {"status": "skipped", "reason": "disabled", "written": []}
    llm_client = getattr(getattr(context, "host", None), "llm_client", None)
    if llm_client is None:
        return {"status": "skipped", "reason": "no_model", "written": []}

    root = str(work_root or "").strip() or await _session_work_root(context, thread_id)
    tier = memory_library.SCOPE_PROJECT if root else memory_library.SCOPE_GLOBAL
    state = load_state(tier, root or None)
    now = time.time()
    if not force:
        last = _parse_iso(state.get("last_dream_at"))
        if last and now - last < DREAM_MIN_INTERVAL_SECONDS:
            return {"status": "skipped", "reason": "cooldown", "written": []}
        if now - _LAST_ATTEMPT.get(thread_id, 0.0) < DREAM_SESSION_COOLDOWN_SECONDS:
            return {"status": "skipped", "reason": "session_cooldown", "written": []}

    from lamtools_core.app.thread_outline import build_thread_outline

    try:
        snapshot = await _load_outline_snapshot(context, thread_id)
    except Exception as exc:  # noqa: BLE001 - never break the turn
        return {"status": "failed", "reason": f"outline unavailable: {exc}", "written": []}
    outline = build_thread_outline(snapshot, thread_id=thread_id, char_limit=DREAM_MAX_TURN_CHARS)
    last_seq = int((state.get("sessions") or {}).get(thread_id, {}).get("last_seq") or 0)
    turns, _ = select_undreamt_turns(outline.get("items") or [], last_seq)
    if not turns:
        return {"status": "skipped", "reason": "no_new_turns", "written": []}
    if not (force or ignore_size_gate):
        new_chars = sum(
            len(turn.get("prompt") or "") + len(turn.get("response") or "")
            for turn in turns
        )
        if new_chars < DREAM_MIN_NEW_CHARS:
            # Not dropped: the cursor stays put and the sweep picks it up.
            return {"status": "skipped", "reason": "waiting_for_more", "written": []}

    model_id = _background_model_id()
    if not model_id:
        return {"status": "skipped", "reason": "no_model", "written": []}
    # Only a pass that really runs counts against the session cooldown; a
    # deferred short turn must stay reachable by the next sweep.
    _LAST_ATTEMPT[thread_id] = now
    return await dream_session(
        llm_client=llm_client,
        model_id=model_id,
        work_root=root or None,
        session_id=thread_id,
        turns=turns,
        force=force,
        now=now,
    )


class DreamSupervisor:
    """Periodic safety net for sessions whose turn-end pass never ran.

    A turn-end pass is the normal path; this loop exists so a crash, a restart
    or a host without the live turn tail still catches up (PRD 5.2: "不应长期积压
    导致记忆明显落后于实际情况").
    """

    def __init__(self, *, context: Any, poll_seconds: float = DREAM_SWEEP_SECONDS) -> None:
        self._context = context
        self._poll_seconds = max(60.0, float(poll_seconds))
        self._task: Any = None
        self._wake: Any = None
        self._stopping = False
        self._manual_root = ""

    async def start(self) -> None:
        global _SUPERVISOR
        if self._task is not None:
            return
        import asyncio

        self._wake = asyncio.Event()
        self._stopping = False
        _SUPERVISOR = self
        self._task = asyncio.create_task(self._run(), name="memory-dream-supervisor")

    async def stop(self) -> None:
        global _SUPERVISOR
        self._stopping = True
        if self._wake is not None:
            self._wake.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except BaseException:  # noqa: BLE001 - shutdown must not raise
                pass
            self._task = None
        if _SUPERVISOR is self:
            _SUPERVISOR = None

    def kick(self, work_root: str = "") -> None:
        """Ask for a pass soon (manual "整理记忆" request)."""
        self._manual_root = str(work_root or "")
        if self._wake is not None:
            self._wake.set()

    async def _run(self) -> None:
        import asyncio

        while not self._stopping:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll_seconds)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                raise
            self._wake.clear()
            try:
                await self._sweep(force=bool(self._manual_root))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop must survive its own bugs
                continue
            self._manual_root = ""

    async def _sweep(self, *, force: bool = False) -> None:
        if not dreaming_enabled():
            return
        store = getattr(getattr(self._context, "host", None), "session_store", None)
        if store is None:
            return
        try:
            sessions = await store.list()
        except Exception:  # noqa: BLE001
            return
        sessions = sorted(
            sessions,
            # ISO/UTC strings sort chronologically; never mix datetime and int.
            key=lambda item: str(getattr(item, "updated_at", "") or ""),
            reverse=True,
        )
        wanted = self._manual_root
        for session in sessions[:10]:
            thread_id = str(getattr(session, "id", "") or "")
            if not thread_id:
                continue
            metadata = getattr(session, "metadata", None)
            root = str((metadata or {}).get("work_root") or "") if isinstance(metadata, dict) else ""
            if wanted and root != wanted:
                continue
            try:
                result = await maybe_dream_after_turn(
                    context=self._context,
                    thread_id=thread_id,
                    work_root=root,
                    force=force,
                    # A short but important turn must not be lost: the sweep
                    # digests it even though the immediate trigger deferred it.
                    ignore_size_gate=True,
                )
            except Exception:  # noqa: BLE001
                continue
            if result.get("status") == "applied":
                # One applied pass per sweep keeps background cost predictable.
                break


async def start_memory_dream_supervisor(*, context: Any) -> "DreamSupervisor | None":
    """Start the periodic loop against the live context (best effort)."""
    global _SUPERVISOR
    if _SUPERVISOR is not None:
        return _SUPERVISOR
    try:
        supervisor = DreamSupervisor(context=context)
        await supervisor.start()
        _SUPERVISOR = supervisor
        return supervisor
    except Exception:  # noqa: BLE001 - memory maintenance must not block boot
        return None


async def stop_memory_dream_supervisor() -> None:
    global _SUPERVISOR
    supervisor, _SUPERVISOR = _SUPERVISOR, None
    if supervisor is None:
        return
    try:
        await supervisor.stop()
    except Exception:  # noqa: BLE001 - shutdown must not raise
        return


def request_dream(work_root: str = "") -> bool:
    """Manual trigger used by the RPC layer; False when no supervisor runs."""
    supervisor = _SUPERVISOR
    if supervisor is None:
        return False
    supervisor.kick(work_root)
    return True


__all__ = [
    "DREAM_MAX_CORE_CHARS",
    "DREAM_MAX_MEMORY_CHARS",
    "DREAM_MAX_NEW_CHARS",
    "DREAM_MAX_TURNS",
    "DREAM_MIN_INTERVAL_SECONDS",
    "DREAM_MIN_NEW_CHARS",
    "DREAM_SESSION_COOLDOWN_SECONDS",
    "DreamSupervisor",
    "PROMPT_VERSION",
    "acquire_dream_lock",
    "apply_dream_output",
    "build_dream_messages",
    "dream_session",
    "dream_status",
    "dreaming_enabled",
    "load_state",
    "maybe_dream_after_turn",
    "parse_dream_output",
    "record_forgotten",
    "release_dream_lock",
    "request_dream",
    "save_state",
    "scrub_secrets",
    "select_undreamt_turns",
    "start_memory_dream_supervisor",
    "stop_memory_dream_supervisor",
    "truncate_turns",
]
