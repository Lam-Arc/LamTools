"""Durable plan packages (方案) — the document a phone authors and a desktop executes.

A plan package is not the session checklist: `runtime/plan.py` owns the live
`task_plan` a turn mutates, while this module owns the durable document that
survives sessions — requirement and its non-goals, the chosen approach and what
was rejected, the documents to write, the step list to install on execution, the
goal, the risks and the open questions.

One shape is shared with the mobile host. `core/protocol/plan-package-v1-fixtures.json`
is the contract of record: both hosts run the same cases through their own
implementation, so a field, a default or a refusal wording cannot drift.

Semantics kept identical on both hosts:

* **save is a patch.** A field the payload does not mention keeps its stored
  value; on a plan that does not exist yet the missing fields take their
  defaults. Validation runs on the merged result.
* **`expected_revision` is an optimistic-concurrency token.** Given, it must
  match the stored revision. Absent, the write is not checked (the panels always
  send it; a model tool does not have to).
* **History only grows.** Every accepted save records a snapshot, and
  `revert` writes the old content as a *new* revision instead of rewriting
  history.
* **Deletion is soft.** A deleted plan leaves the lists but keeps its record and
  its history, and `restore` brings it back.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, runtime_checkable

PlanStatus = Literal["draft", "ready", "executing", "done", "archived"]
StepStatus = Literal["pending", "in_progress", "completed", "blocked", "skipped", "replaced"]
QuestionStatus = Literal["open", "answered"]
RiskSeverity = Literal["low", "medium", "high"]
DocKind = Literal["research", "spec", "design", "plan", "tasks", "notes"]

PLAN_STATUSES: tuple[PlanStatus, ...] = ("draft", "ready", "executing", "done", "archived")
STEP_STATUSES: tuple[StepStatus, ...] = (
    "pending",
    "in_progress",
    "completed",
    "blocked",
    "skipped",
    "replaced",
)
QUESTION_STATUSES: tuple[QuestionStatus, ...] = ("open", "answered")
RISK_SEVERITIES: tuple[RiskSeverity, ...] = ("low", "medium", "high")
DOC_KINDS: tuple[DocKind, ...] = ("research", "spec", "design", "plan", "tasks", "notes")

# draft -> ready is the 定稿 gate; executing is entered by the host when the plan
# starts running, and archived is reachable from anywhere except itself.
_ALLOWED_PLAN_TRANSITIONS: dict[PlanStatus, frozenset[PlanStatus]] = {
    "draft": frozenset({"ready", "archived"}),
    "ready": frozenset({"draft", "executing", "archived"}),
    "executing": frozenset({"done", "archived"}),
    "done": frozenset({"archived"}),
    "archived": frozenset(),
}

PLAN_ID_PREFIX = "plan_"
_DRIVE_LETTER = re.compile(r"^[A-Za-z]:")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _text_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(clean for item in value if (clean := _text(item)))


@dataclass(frozen=True)
class PlanStep:
    id: str
    description: str
    deliverables: tuple[str, ...] = ()
    status: StepStatus = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "deliverables": list(self.deliverables),
            "status": self.status,
        }


@dataclass(frozen=True)
class PlanQuestion:
    id: str
    question: str
    status: QuestionStatus = "open"
    answer: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "status": self.status,
            "answer": self.answer,
        }


@dataclass(frozen=True)
class RejectedApproach:
    option: str
    why: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"option": self.option, "why": self.why}


@dataclass(frozen=True)
class PlanRequirement:
    restatement: str
    success_looks_like: str = ""
    non_goals: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "restatement": self.restatement,
            "success_looks_like": self.success_looks_like,
            "non_goals": list(self.non_goals),
            "assumptions": list(self.assumptions),
        }


@dataclass(frozen=True)
class PlanApproach:
    chosen: str
    why: str = ""
    rejected: tuple[RejectedApproach, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "chosen": self.chosen,
            "why": self.why,
            "rejected": [item.to_dict() for item in self.rejected],
        }


@dataclass(frozen=True)
class PlanChecklist:
    design_summary: str = ""
    steps: tuple[PlanStep, ...] = ()
    files: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "design_summary": self.design_summary,
            "steps": [step.to_dict() for step in self.steps],
            "files": list(self.files),
        }


@dataclass(frozen=True)
class PlanGoal:
    objective: str = ""
    completion_criteria: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "completion_criteria": list(self.completion_criteria),
        }


@dataclass(frozen=True)
class PlanRisk:
    risk: str
    severity: RiskSeverity = "medium"
    mitigation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"risk": self.risk, "severity": self.severity, "mitigation": self.mitigation}


@dataclass(frozen=True)
class PlanDoc:
    path: str
    kind: DocKind = "notes"
    title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "kind": self.kind, "title": self.title}


@dataclass(frozen=True)
class PlanExecution:
    thread_id: str
    revision: int = 0
    started_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "revision": self.revision,
            "started_at": self.started_at,
        }


@dataclass(frozen=True)
class PlanPackage:
    id: str
    project_id: str
    title: str
    summary: str = ""
    status: PlanStatus = "draft"
    requirement: PlanRequirement = field(default_factory=lambda: PlanRequirement(restatement=""))
    open_questions: tuple[PlanQuestion, ...] = ()
    approach: PlanApproach = field(default_factory=lambda: PlanApproach(chosen=""))
    checklist: PlanChecklist = field(default_factory=PlanChecklist)
    goal: PlanGoal = field(default_factory=PlanGoal)
    risks: tuple[PlanRisk, ...] = ()
    docs: tuple[PlanDoc, ...] = ()
    source: str = ""
    revision: int = 1
    execution: PlanExecution | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    deleted_at: datetime | None = None

    def body(self) -> dict[str, Any]:
        """The part both hosts must agree on byte for byte.

        `revision`, `source`, `project_id` and the timestamps are host-local
        bookkeeping: they travel with an exported package but are not compared
        by the shared fixtures.
        """

        return {
            "schema_version": 1,
            "plan_id": self.id,
            "title": self.title,
            "status": self.status,
            "summary": self.summary,
            "requirement": self.requirement.to_dict(),
            "open_questions": [item.to_dict() for item in self.open_questions],
            "approach": self.approach.to_dict(),
            "checklist": self.checklist.to_dict(),
            "goal": self.goal.to_dict(),
            "risks": [item.to_dict() for item in self.risks],
            "docs": [item.to_dict() for item in self.docs],
            "execution": self.execution.to_dict() if self.execution else None,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.body()
        payload.update(
            {
                "project_id": self.project_id,
                "source": self.source,
                "revision": self.revision,
                "created_at": self.created_at.isoformat(),
                "updated_at": self.updated_at.isoformat(),
                "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            }
        )
        return payload


@runtime_checkable
class PlanStore(Protocol):
    async def insert(self, plan: PlanPackage) -> PlanPackage: ...
    async def replace(self, plan: PlanPackage, *, expected_revision: int) -> PlanPackage: ...
    async def get(self, plan_id: str) -> PlanPackage | None: ...
    async def list(
        self,
        *,
        project_id: str | None = None,
        status: PlanStatus | None = None,
        include_deleted: bool = False,
    ) -> list[PlanPackage]: ...
    async def set_deleted(self, plan_id: str, *, deleted: bool) -> PlanPackage: ...
    async def record_revision(self, plan: PlanPackage) -> None: ...
    async def revisions(self, plan_id: str) -> list[PlanPackage]: ...


class InMemoryPlanStore:
    """The adapter the tests and embedded hosts use."""

    def __init__(self) -> None:
        self._plans: dict[str, PlanPackage] = {}
        self._revisions: dict[str, dict[int, PlanPackage]] = {}

    async def insert(self, plan: PlanPackage) -> PlanPackage:
        if plan.id in self._plans:
            raise ValueError(f"Plan already exists: {plan.id}")
        self._plans[plan.id] = deepcopy(plan)
        return deepcopy(plan)

    async def replace(self, plan: PlanPackage, *, expected_revision: int) -> PlanPackage:
        current = self._plans.get(plan.id)
        if current is None:
            raise LookupError(f"Plan not found: {plan.id}")
        if current.revision != expected_revision:
            raise RuntimeError(f"plan revision conflict: {plan.id}")
        self._plans[plan.id] = deepcopy(plan)
        return deepcopy(plan)

    async def get(self, plan_id: str) -> PlanPackage | None:
        plan = self._plans.get(_text(plan_id))
        return deepcopy(plan) if plan is not None else None

    async def list(
        self,
        *,
        project_id: str | None = None,
        status: PlanStatus | None = None,
        include_deleted: bool = False,
    ) -> list[PlanPackage]:
        plans = [
            deepcopy(plan)
            for plan in self._plans.values()
            if (project_id is None or plan.project_id == project_id)
            and (status is None or plan.status == status)
            and (include_deleted or plan.deleted_at is None)
        ]
        plans.sort(key=lambda plan: (plan.created_at, plan.id), reverse=True)
        return plans

    async def set_deleted(self, plan_id: str, *, deleted: bool) -> PlanPackage:
        current = self._plans.get(_text(plan_id))
        if current is None:
            raise LookupError(f"Plan not found: {_text(plan_id)}")
        updated = replace(current, deleted_at=_utcnow() if deleted else None)
        self._plans[current.id] = updated
        return deepcopy(updated)

    async def record_revision(self, plan: PlanPackage) -> None:
        self._revisions.setdefault(plan.id, {})[plan.revision] = deepcopy(plan)

    async def revisions(self, plan_id: str) -> list[PlanPackage]:
        history = self._revisions.get(_text(plan_id), {})
        return [deepcopy(history[number]) for number in sorted(history)]


def _clean_error_list(value: Any) -> list[Any]:
    """Drop blank entries before validating: a stray empty row is not an error."""
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if item]


def _merge_object(existing: dict[str, Any], incoming: Any) -> dict[str, Any]:
    """Patch one nested object: keys the payload omits keep the stored value."""
    if not isinstance(incoming, dict):
        return existing
    merged = dict(existing)
    merged.update(incoming)
    return merged


def _plan_step(raw: Any, index: int) -> PlanStep:
    source = raw if isinstance(raw, dict) else {}
    step_id = _text(source.get("id")) or f"s{index + 1}"
    description = _text(source.get("description"))
    if not description:
        raise ValueError(f"plan step description is required: {step_id}")
    status = _text(source.get("status")) or "pending"
    if status not in STEP_STATUSES:
        raise ValueError(f"invalid plan step status: {status}")
    return PlanStep(
        id=step_id,
        description=description,
        deliverables=_text_list(source.get("deliverables")),
        status=status,  # type: ignore[arg-type]
    )


def _plan_question(raw: Any, index: int) -> PlanQuestion | None:
    source = raw if isinstance(raw, dict) else {}
    question = _text(source.get("question"))
    question_id = _text(source.get("id")) or f"q{index + 1}"
    if not question:
        # A question with no text carries nothing; the panel's empty row is
        # dropped rather than refused.
        return None
    status = _text(source.get("status")) or "open"
    if status not in QUESTION_STATUSES:
        raise ValueError(f"invalid plan question status: {status}")
    return PlanQuestion(
        id=question_id,
        question=question,
        status=status,  # type: ignore[arg-type]
        answer=_text(source.get("answer")),
    )


def _plan_risk(raw: Any) -> PlanRisk | None:
    source = raw if isinstance(raw, dict) else {}
    risk = _text(source.get("risk"))
    if not risk:
        return None
    severity = _text(source.get("severity")) or "medium"
    if severity not in RISK_SEVERITIES:
        raise ValueError(f"invalid plan risk severity: {severity}")
    return PlanRisk(
        risk=risk,
        severity=severity,  # type: ignore[arg-type]
        mitigation=_text(source.get("mitigation")),
    )


def _plan_doc(raw: Any) -> PlanDoc | None:
    source = raw if isinstance(raw, dict) else {}
    raw_path = _text(source.get("path"))
    if not raw_path:
        return None
    path = raw_path.replace("\\", "/")
    segments = [segment for segment in path.split("/") if segment not in ("", ".")]
    if (
        path.startswith("/")
        or _DRIVE_LETTER.match(path)
        or ".." in segments
        or not segments
    ):
        raise ValueError(f"plan doc path must be relative: {raw_path}")
    kind = _text(source.get("kind")) or "notes"
    if kind not in DOC_KINDS:
        raise ValueError(f"unknown plan doc kind: {kind}")
    return PlanDoc(path=path, kind=kind, title=_text(source.get("title")))  # type: ignore[arg-type]


def _plan_execution(raw: Any) -> PlanExecution | None:
    if raw is None:
        return None
    source = raw if isinstance(raw, dict) else {}
    thread_id = _text(source.get("thread_id") or source.get("threadId"))
    if not thread_id:
        raise ValueError("plan execution thread is required")
    revision = source.get("revision")
    try:
        revision_number = int(revision) if revision not in (None, "") else 0
    except (TypeError, ValueError) as exc:
        raise ValueError("plan execution revision must be a number") from exc
    return PlanExecution(
        thread_id=thread_id,
        revision=max(revision_number, 0),
        started_at=_text(source.get("started_at") or source.get("startedAt")),
    )


def normalize_plan(
    payload: dict[str, Any],
    *,
    existing: PlanPackage | None,
    source: str,
) -> PlanPackage:
    """Merge a save payload onto the stored plan and validate the result."""

    base = existing.body() if existing is not None else {}
    if existing is not None:
        # `body()` is the portable half; a patch still has to keep the
        # host-local project when it does not name one.
        base["project_id"] = existing.project_id
    requirement = _merge_object(
        base.get("requirement") or {"restatement": "", "success_looks_like": "", "non_goals": [], "assumptions": []},
        payload.get("requirement"),
    )
    approach = _merge_object(base.get("approach") or {"chosen": "", "why": "", "rejected": []}, payload.get("approach"))
    checklist = _merge_object(
        base.get("checklist") or {"design_summary": "", "steps": [], "files": []},
        payload.get("checklist"),
    )
    goal = _merge_object(base.get("goal") or {"objective": "", "completion_criteria": []}, payload.get("goal"))

    def pick(name: str) -> Any:
        if name in payload:
            return payload[name]
        return base.get(name)

    project_id = _text(pick("project_id"))
    if not project_id:
        raise ValueError("plan project is required")
    title = _text(pick("title"))
    if not title:
        raise ValueError("plan title is required")

    restatement = _text(requirement.get("restatement"))
    if not restatement:
        raise ValueError("plan requirement is required")
    chosen = _text(approach.get("chosen"))
    if not chosen:
        raise ValueError("plan approach is required")

    plan_requirement = PlanRequirement(
        restatement=restatement,
        success_looks_like=_text(requirement.get("success_looks_like")),
        non_goals=_text_list(requirement.get("non_goals")),
        assumptions=_text_list(requirement.get("assumptions")),
    )
    plan_approach = PlanApproach(
        chosen=chosen,
        why=_text(approach.get("why")),
        rejected=tuple(
            RejectedApproach(option=_text(item.get("option")), why=_text(item.get("why")))
            for item in _clean_error_list(approach.get("rejected"))
            if isinstance(item, dict) and _text(item.get("option"))
        ),
    )

    steps: list[PlanStep] = []
    seen_steps: set[str] = set()
    raw_steps = checklist.get("steps")
    for index, raw_step in enumerate(raw_steps if isinstance(raw_steps, (list, tuple)) else []):
        step = _plan_step(raw_step, index)
        if step.id in seen_steps:
            raise ValueError(f"duplicate plan step id: {step.id}")
        seen_steps.add(step.id)
        steps.append(step)
    plan_checklist = PlanChecklist(
        design_summary=_text(checklist.get("design_summary")),
        steps=tuple(steps),
        files=_text_list(checklist.get("files")),
    )

    questions: list[PlanQuestion] = []
    raw_questions = pick("open_questions")
    for index, raw_question in enumerate(raw_questions if isinstance(raw_questions, (list, tuple)) else []):
        question = _plan_question(raw_question, index)
        if question is not None:
            questions.append(question)

    risks: list[PlanRisk] = []
    raw_risks = pick("risks")
    for raw_risk in raw_risks if isinstance(raw_risks, (list, tuple)) else []:
        risk = _plan_risk(raw_risk)
        if risk is not None:
            risks.append(risk)

    docs: list[PlanDoc] = []
    raw_docs = pick("docs")
    for raw_doc in raw_docs if isinstance(raw_docs, (list, tuple)) else []:
        doc = _plan_doc(raw_doc)
        if doc is not None:
            docs.append(doc)

    goal_objective = _text(goal.get("objective"))
    goal_criteria = _text_list(goal.get("completion_criteria"))
    if not goal_objective and goal_criteria:
        raise ValueError("plan goal objective is required")

    status = _text(pick("status")) or "draft"
    if status not in PLAN_STATUSES:
        raise ValueError(f"invalid plan status: {status}")

    execution = _plan_execution(pick("execution"))

    now = _utcnow()
    if existing is not None:
        return replace(
            existing,
            project_id=project_id,
            title=title,
            summary=_text(pick("summary")),
            status=status,  # type: ignore[arg-type]
            requirement=plan_requirement,
            open_questions=tuple(questions),
            approach=plan_approach,
            checklist=plan_checklist,
            goal=PlanGoal(objective=goal_objective, completion_criteria=goal_criteria),
            risks=tuple(risks),
            docs=tuple(docs),
            source=source,
            revision=existing.revision + 1,
            execution=execution,
            updated_at=now,
            deleted_at=existing.deleted_at,
        )
    return PlanPackage(
        id=_text(payload.get("plan_id") or payload.get("planId") or payload.get("id")) or f"{PLAN_ID_PREFIX}{uuid.uuid4().hex}",
        project_id=project_id,
        title=title,
        summary=_text(pick("summary")),
        status=status,  # type: ignore[arg-type]
        requirement=plan_requirement,
        open_questions=tuple(questions),
        approach=plan_approach,
        checklist=plan_checklist,
        goal=PlanGoal(objective=goal_objective, completion_criteria=goal_criteria),
        risks=tuple(risks),
        docs=tuple(docs),
        source=source,
        revision=1,
        execution=execution,
        created_at=now,
        updated_at=now,
    )


def assert_status_transition(current: PlanStatus, target: PlanStatus) -> None:
    if target == current:
        return
    if target not in _ALLOWED_PLAN_TRANSITIONS[current]:
        raise ValueError(f"invalid plan status transition: {current} -> {target}")


class PlanManager:
    """The lifecycle both hosts expose: save, read, revise, revert, delete."""

    def __init__(self, store: PlanStore) -> None:
        self.store = store

    async def save(
        self,
        payload: dict[str, Any],
        *,
        source: str,
        expected_revision: int | None = None,
    ) -> PlanPackage:
        plan_id = _text(payload.get("plan_id") or payload.get("planId") or payload.get("id"))
        stored = await self.store.get(plan_id) if plan_id else None
        if expected_revision is not None and stored is None:
            raise LookupError(f"Plan not found: {plan_id}")
        if stored is None:
            plan = normalize_plan(payload, existing=None, source=source)
            if plan.id and await self.store.get(plan.id) is not None:
                raise ValueError(f"Plan already exists: {plan.id}")
            assert_status_transition("draft", plan.status)
            if plan.status == "ready" and not plan.checklist.steps:
                raise ValueError("plan needs at least one step before it is ready")
            created = await self.store.insert(plan)
            await self.store.record_revision(created)
            return created
        if expected_revision is not None and stored.revision != expected_revision:
            raise RuntimeError(f"plan revision conflict: {stored.id}")
        updated = normalize_plan(payload, existing=stored, source=source)
        assert_status_transition(stored.status, updated.status)
        if updated.status == "ready" and not updated.checklist.steps:
            raise ValueError("plan needs at least one step before it is ready")
        replaced = await self.store.replace(updated, expected_revision=stored.revision)
        await self.store.record_revision(replaced)
        return replaced

    async def get(self, plan_id: str) -> PlanPackage | None:
        return await self.store.get(_text(plan_id))

    async def require(self, plan_id: str) -> PlanPackage:
        plan = await self.store.get(_text(plan_id))
        if plan is None:
            raise LookupError(f"Plan not found: {_text(plan_id)}")
        return plan

    async def list(
        self,
        *,
        project_id: str | None = None,
        status: PlanStatus | None = None,
        include_deleted: bool = False,
    ) -> list[PlanPackage]:
        return await self.store.list(
            project_id=_text(project_id) or None,
            status=status,
            include_deleted=include_deleted,
        )

    async def revisions(self, plan_id: str) -> list[PlanPackage]:
        await self.require(plan_id)
        return await self.store.revisions(_text(plan_id))

    async def revert(self, plan_id: str, revision: int, *, source: str = "") -> PlanPackage:
        current = await self.require(plan_id)
        history = await self.store.revisions(_text(plan_id))
        target = next((item for item in history if item.revision == revision), None)
        if target is None:
            raise LookupError(f"plan revision not found: {current.id}@{revision}")
        # A revert restores content verbatim, so the status machine is not
        # re-applied — only the id, the revision number and the host-local
        # execution record come from the present.
        restored = replace(
            target,
            id=current.id,
            revision=current.revision + 1,
            source=_text(source) or current.source,
            project_id=current.project_id,
            execution=current.execution,
            created_at=current.created_at,
            updated_at=_utcnow(),
            deleted_at=current.deleted_at,
        )
        replaced = await self.store.replace(restored, expected_revision=current.revision)
        await self.store.record_revision(replaced)
        return replaced

    async def delete(self, plan_id: str) -> PlanPackage:
        await self.require(plan_id)
        return await self.store.set_deleted(_text(plan_id), deleted=True)

    async def restore(self, plan_id: str) -> PlanPackage:
        await self.require(plan_id)
        return await self.store.set_deleted(_text(plan_id), deleted=False)

    async def record_execution(self, plan_id: str, execution: PlanExecution) -> PlanPackage:
        """Attach a started turn to the plan without touching its content.

        Execution is host-local bookkeeping, so it deliberately does not spend a
        revision: the phone's revision still matches after an import.
        """

        current = await self.require(plan_id)
        updated = replace(current, execution=execution, updated_at=_utcnow())
        replaced = await self.store.replace(updated, expected_revision=current.revision)
        await self.store.record_revision(replaced)
        return replaced


def _entries(raw: Any) -> list[Any]:
    return list(raw) if isinstance(raw, (list, tuple)) else []


def _stored_time(value: Any, *, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = _text(value)
    if not text:
        return fallback
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return fallback
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def plan_from_dict(payload: dict[str, Any]) -> PlanPackage:
    """Rebuild a package that was stored or imported.

    A stored record is data, not a payload: every field is expected to be there
    and a broken one raises, so a corrupted row or a hand-edited import file is
    loud instead of silently normalised into something else.
    """

    if not isinstance(payload, dict):
        raise ValueError("plan payload must be an object")
    raw_requirement = payload.get("requirement") or {}
    raw_approach = payload.get("approach") or {}
    raw_checklist = payload.get("checklist") or {}
    raw_goal = payload.get("goal") or {}
    now = _utcnow()

    requirement = PlanRequirement(
        restatement=_text(raw_requirement.get("restatement")),
        success_looks_like=_text(raw_requirement.get("success_looks_like")),
        non_goals=_text_list(raw_requirement.get("non_goals")),
        assumptions=_text_list(raw_requirement.get("assumptions")),
    )
    if not requirement.restatement:
        raise ValueError("plan requirement is required")
    approach = PlanApproach(
        chosen=_text(raw_approach.get("chosen")),
        why=_text(raw_approach.get("why")),
        rejected=tuple(
            RejectedApproach(option=_text(item.get("option")), why=_text(item.get("why")))
            for item in _entries(raw_approach.get("rejected"))
            if isinstance(item, dict) and _text(item.get("option"))
        ),
    )
    if not approach.chosen:
        raise ValueError("plan approach is required")
    status = _text(payload.get("status")) or "draft"
    if status not in PLAN_STATUSES:
        raise ValueError(f"invalid plan status: {status}")
    return PlanPackage(
        id=_text(payload.get("plan_id") or payload.get("id")),
        project_id=_text(payload.get("project_id")),
        title=_text(payload.get("title")),
        summary=_text(payload.get("summary")),
        status=status,  # type: ignore[arg-type]
        requirement=requirement,
        open_questions=tuple(
            question
            for index, raw in enumerate(_entries(payload.get("open_questions")))
            if (question := _plan_question(raw, index)) is not None
        ),
        approach=approach,
        checklist=PlanChecklist(
            design_summary=_text(raw_checklist.get("design_summary")),
            steps=tuple(_plan_step(raw, index) for index, raw in enumerate(_entries(raw_checklist.get("steps")))),
            files=_text_list(raw_checklist.get("files")),
        ),
        goal=PlanGoal(
            objective=_text(raw_goal.get("objective")),
            completion_criteria=_text_list(raw_goal.get("completion_criteria")),
        ),
        risks=tuple(
            risk for raw in _entries(payload.get("risks")) if (risk := _plan_risk(raw)) is not None
        ),
        docs=tuple(
            doc for raw in _entries(payload.get("docs")) if (doc := _plan_doc(raw)) is not None
        ),
        source=_text(payload.get("source")),
        revision=int(payload.get("revision") or 1),
        execution=_plan_execution(payload.get("execution")),
        created_at=_stored_time(payload.get("created_at"), fallback=now),
        updated_at=_stored_time(payload.get("updated_at"), fallback=now),
        deleted_at=(
            _stored_time(payload.get("deleted_at"), fallback=now)
            if payload.get("deleted_at")
            else None
        ),
    )


def revision_summaries(history: Sequence[PlanPackage]) -> list[dict[str, Any]]:
    return [
        {
            "revision": item.revision,
            "title": item.title,
            "status": item.status,
            "source": item.source,
            "created_at": item.updated_at.isoformat(),
        }
        for item in history
    ]


__all__ = [
    "DOC_KINDS",
    "PLAN_STATUSES",
    "QUESTION_STATUSES",
    "RISK_SEVERITIES",
    "STEP_STATUSES",
    "InMemoryPlanStore",
    "PlanApproach",
    "PlanChecklist",
    "PlanDoc",
    "PlanExecution",
    "PlanGoal",
    "PlanManager",
    "PlanPackage",
    "PlanQuestion",
    "PlanRequirement",
    "PlanRisk",
    "PlanStatus",
    "PlanStep",
    "PlanStore",
    "RejectedApproach",
    "assert_status_transition",
    "normalize_plan",
    "plan_from_dict",
    "revision_summaries",
]
