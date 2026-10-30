"""user:“继续，把 2 阶段都做完”+(普通问答独立于审批，缺少回答者不能编造答案，撤回后不接受迟到回复)。"""
import asyncio

import pytest

from lamtools_core.plugin_system import PluginContext


def pair(tmp_path):
    base = PluginContext(tmp_path)
    caller, provider = base.for_work_root(tmp_path), base.for_work_root(tmp_path)
    caller._begin_registration_scope("caller", 1)
    provider._begin_registration_scope("provider", 1)
    return caller, provider


QUESTIONS = [{"id": "color", "question": "Choose a color", "options": ["red", "blue"]}]


@pytest.mark.asyncio
async def test_question_answer_is_validated_and_detached_from_provider_objects(tmp_path):
    caller, provider = pair(tmp_path)
    seen = []
    answer = [{"id": "color", "selected": ["red"], "custom": "green"}]
    def reply(request):
        seen.append(request)
        return answer
    provider.questions.answer(reply)
    provider._registration_scope.publish(set())
    try:
        result = await caller.questions.ask(QUESTIONS, timeout=1)
        assert result.answers[0].selected == ()  # single custom overrides selection
        assert result.answers[0].custom == "green"
        assert seen[0].questions[0].options == ("red", "blue")
        answer[0]["custom"] = "mutated"
        assert result.answers[0].custom == "green"
        assert not hasattr(result, "allowed")
    finally:
        await caller._registration_scope.dispose()
        await provider._registration_scope.dispose()


@pytest.mark.asyncio
async def test_missing_and_unpublished_answerer_are_explicit_errors(tmp_path):
    from lamtools_core.plugin_system.question_access import QuestionAccessError
    caller, provider = pair(tmp_path)
    provider.questions.answer(lambda request: [])
    try:
        with pytest.raises(QuestionAccessError) as error:
            await caller.questions.ask(QUESTIONS, timeout=1)
        assert error.value.code == "question/unavailable"
    finally:
        await caller._registration_scope.dispose()
        await provider._registration_scope.dispose()


@pytest.mark.asyncio
async def test_invalid_reply_is_rejected_and_multiple_selection_custom_can_combine(tmp_path):
    from lamtools_core.plugin_system.question_access import QuestionAccessError
    caller, provider = pair(tmp_path)
    reply = [{"id": "color", "selected": ["unknown"]}]
    provider.questions.answer(lambda request: reply)
    provider._registration_scope.publish(set())
    try:
        with pytest.raises(QuestionAccessError) as error:
            await caller.questions.ask(QUESTIONS, timeout=1)
        assert error.value.code == "question/invalid-answer"
        reply[:] = [{"id": "color", "selected": ["red", "blue"], "custom": "green"}]
        result = await caller.questions.ask([{**QUESTIONS[0], "multiple": True}], timeout=1)
        assert result.answers[0].selected == ("red", "blue")
        assert result.answers[0].custom == "green"
    finally:
        await caller._registration_scope.dispose()
        await provider._registration_scope.dispose()


@pytest.mark.asyncio
async def test_timeout_discards_late_reply_and_joins_answerer_cleanup(tmp_path):
    from lamtools_core.plugin_system.question_access import QuestionAccessError
    caller, provider = pair(tmp_path)
    cleaned = asyncio.Event()
    async def reply(request):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return [{"id": "color", "selected": ["red"]}]
        finally:
            cleaned.set()
    provider.questions.answer(reply)
    provider._registration_scope.publish(set())
    try:
        with pytest.raises(QuestionAccessError) as error:
            await caller.questions.ask(QUESTIONS, timeout=0.01)
        assert error.value.code == "question/timed-out"
        assert cleaned.is_set()
    finally:
        await caller._registration_scope.dispose()
        await provider._registration_scope.dispose()


@pytest.mark.asyncio
async def test_provider_withdrawal_cancels_pending_question_and_releases_both_scopes(tmp_path):
    from lamtools_core.plugin_system.question_access import QuestionAccessError
    caller, provider = pair(tmp_path)
    entered, cleaned = asyncio.Event(), asyncio.Event()
    async def reply(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()
    remove = provider.questions.answer(reply)
    provider._registration_scope.publish(set())
    task = asyncio.create_task(caller.questions.ask(QUESTIONS, timeout=3))
    await asyncio.wait_for(entered.wait(), 1)
    remove()
    try:
        with pytest.raises(QuestionAccessError) as error:
            await asyncio.wait_for(task, 1)
        assert error.value.code == "question/revoked"
        assert cleaned.is_set()
        assert not caller._registration_scope._calls and not provider._registration_scope._calls
    finally:
        await caller._registration_scope.dispose()
        await provider._registration_scope.dispose()


@pytest.mark.asyncio
async def test_caller_cancellation_is_not_converted_to_answer_or_timeout(tmp_path):
    caller, provider = pair(tmp_path)
    entered, cleaned = asyncio.Event(), asyncio.Event()
    async def reply(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()
    provider.questions.answer(reply)
    provider._registration_scope.publish(set())
    task = asyncio.create_task(caller.questions.ask(QUESTIONS, timeout=3))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()
        assert not caller._registration_scope._calls and not provider._registration_scope._calls
    finally:
        await caller._registration_scope.dispose()
        await provider._registration_scope.dispose()
