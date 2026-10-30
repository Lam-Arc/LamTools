"""user:“继续，把 2 阶段都做完”+(程序化普通问答有独立词汇和受管回答者，不能把用户答案当工具授权)。"""
from __future__ import annotations

import asyncio
import inspect
import math
import uuid
from dataclasses import dataclass

from .durable_access import _json
from .services import ServiceError, ServiceKey, ServiceRef


QUESTION_ANSWERER = ServiceKey("plugin.questions.answerer")


class QuestionAccessError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class UserQuestion:
    id: str
    question: str
    options: tuple[str, ...]
    multiple: bool


@dataclass(frozen=True)
class QuestionRequest:
    id: str
    plugin: str
    questions: tuple[UserQuestion, ...]


@dataclass(frozen=True)
class UserAnswer:
    id: str
    selected: tuple[str, ...]
    custom: str | None


@dataclass(frozen=True)
class QuestionResult:
    id: str
    answers: tuple[UserAnswer, ...]


def _text(value, maximum):
    return type(value) is str and bool(value.strip()) and len(value) <= maximum and "\x00" not in value


def _questions(values):
    try:
        values = _json(values, maximum=65536)
        if type(values) is not list or not 1 <= len(values) <= 10:
            raise ValueError
        result, ids = [], set()
        for value in values:
            if type(value) is not dict or set(value) - {"id", "question", "options", "multiple"}:
                raise ValueError
            identifier, question = value.get("id"), value.get("question")
            options, multiple = value.get("options", []), value.get("multiple", False)
            if not _text(identifier, 128) or identifier in ids or not _text(question, 4000) or type(multiple) is not bool:
                raise ValueError
            if (type(options) is not list or len(options) > 10 or any(not _text(option, 256) for option in options)
                    or len(set(options)) != len(options)):
                raise ValueError
            ids.add(identifier)
            result.append(UserQuestion(identifier, question, tuple(options), multiple))
        return tuple(result)
    except Exception:
        raise QuestionAccessError("question/invalid-request", "Use 1–10 unique questions, bounded text and at most10 distinct option labels; no presentation/approval intent") from None


def _answers(request, values):
    try:
        values = _json(values, maximum=65536)
        if type(values) is not list or len(values) != len(request.questions):
            raise ValueError
        result, seen = {}, set()
        questions = {q.id: q for q in request.questions}
        for value in values:
            if type(value) is not dict or set(value) - {"id", "selected", "custom"}:
                raise ValueError
            identifier, selected, custom = value.get("id"), value.get("selected", []), value.get("custom")
            if type(identifier) is not str or identifier not in questions or identifier in seen:
                raise ValueError
            question = questions[identifier]
            if (type(selected) is not list or any(type(item) is not str or item not in question.options for item in selected)
                    or len(selected) != len(set(selected)) or not question.multiple and len(selected) > 1):
                raise ValueError
            if custom is not None and (type(custom) is not str or len(custom) > 16000 or "\x00" in custom):
                raise ValueError
            custom = custom if custom and custom.strip() else None
            if custom and not question.multiple:
                selected = []
            seen.add(identifier)
            result[identifier] = UserAnswer(identifier, tuple(selected), custom)
        return QuestionResult(request.id, tuple(result[q.id] for q in request.questions))
    except Exception:
        raise QuestionAccessError("question/invalid-answer", "Answer every question exactly once with declared options, optional custom text or an explicit empty selection to skip") from None


class _Answerer:
    def __init__(self, callback):
        self.callback = callback

    async def reply(self, request):
        value = self.callback(request)
        return await value if inspect.isawaitable(value) else value


class PluginQuestionAPI:
    def __init__(self, context, scope):
        self._scope, self._registry, self._pending = scope, context._service_registry, 0

    def answer(self, callback):
        self._scope.check_open()
        if not callable(callback):
            raise QuestionAccessError("question/invalid-answerer", "Answerer must be callable")
        return self._scope.register(QUESTION_ANSWERER, _Answerer(callback))

    async def ask(self, questions, *, timeout):
        self._scope.acquire()
        task = None
        admitted = False
        try:
            values = _questions(questions)
            if type(timeout) not in {int,float} or not math.isfinite(timeout) or not 0 < timeout <= 300:
                raise QuestionAccessError("question/invalid-timeout", "Explicit timeout must be within (0,300] seconds")
            if self._pending >= 8:
                raise QuestionAccessError("question/busy", "At most8 pending question batches per view")
            self._pending += 1
            admitted = True
            def resolve():
                record = self._registry.record(QUESTION_ANSWERER.name)
                if record is None or not record.live or not record.scope.accepting or not isinstance(record.value, _Answerer):
                    raise ServiceError("service/unavailable", QUESTION_ANSWERER.name, "No live question answerer")
                return record.value, record
            try:
                reference = ServiceRef(QUESTION_ANSWERER, resolve, self._scope)
            except ServiceError:
                raise QuestionAccessError("question/unavailable", "No published question answerer") from None
            request = QuestionRequest("question_" + uuid.uuid4().hex, self._scope.owner, values)
            task = asyncio.create_task(reference.call("reply", request), name="plugin-question-answer")
            try:
                async with asyncio.timeout(timeout):
                    while not task.done():
                        reference.get()  # Revoke a pending request promptly when either epoch stops.
                        await asyncio.wait({task}, timeout=0.05)
                    reference.get()
                    return _answers(request, task.result())
            except TimeoutError:
                raise QuestionAccessError("question/timed-out", "Question deadline expired without a usable answer") from None
            except ServiceError:
                raise QuestionAccessError("question/revoked", "Question requester or answerer was withdrawn") from None
            except QuestionAccessError:
                raise
            except Exception:
                raise QuestionAccessError("question/answerer-failed", "Question answerer failed") from None
        finally:
            if task is not None:
                if not task.done():
                    task.cancel()
                cancelled = False
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        # Distinguish caller cancellation from the cancelled answerer task.
                        if asyncio.current_task().cancelling():
                            cancelled = True
                    except Exception:
                        break
                if not task.cancelled():
                    task.exception()
            else:
                cancelled = False
            if admitted:
                self._pending -= 1
            self._scope.release()
            if cancelled:
                raise asyncio.CancelledError
