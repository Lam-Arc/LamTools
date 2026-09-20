"""Durable Study exam boundary with public/private separation and versioned grading."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math

from .store import identifier


def _private_id(exam_id: str) -> str:
    return f"exam-private:{exam_id}"


def _public_question(raw: dict, question_id: str) -> dict:
    """Project a question onto fields that are safe for the learner.

    Author/model output is untrusted.  A deny-list (for example, removing only
    ``answer`` and ``rubric``) would allow fields such as ``solution`` or
    ``standard_answer`` to leak through a public exam response.
    """
    raw_node_ids = raw.get('node_ids', [])
    if not isinstance(raw_node_ids, list):
        raw_node_ids = []
    question = {
        'type': str(raw.get('type') or ''),
        'prompt': str(raw.get('prompt') or '').strip(),
        'node_ids': [str(value).strip() for value in raw_node_ids],
        'id': str(question_id),
        'max_score': raw.get('max_score', 1),
    }
    if question['type'] == 'choice':
        question['options'] = [str(value) for value in raw.get('options', [])]
    return question


def _public_reason(value: str, private: dict, state: str) -> str:
    # Feedback is authored by the active Agent after submission and may quote
    # the reference answer when that helps the learner.  Ordinary exam reads
    # still omit the stored reference/rubric themselves.
    return str(value or '').strip()[:2000]


def _score_value(value, *, field: str, positive: bool = False, maximum: float = 1000) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{field} must be a number')
    result = float(value)
    if not math.isfinite(result) or result < 0 or result > maximum or (positive and result <= 0):
        raise ValueError(f'{field} is outside its allowed range')
    return int(result) if result.is_integer() else result


def _normalize_step_scores(value, *, question_max: int | float) -> list[dict]:
    if value in (None, []):
        return []
    if not isinstance(value, list) or len(value) > 50:
        raise ValueError('step_scores must be an array with at most 50 items')
    normalized = []
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError('Each step score must be an object')
        label = str(raw.get('step') or raw.get('criterion') or raw.get('name') or raw.get('reason') or '').strip()
        if not label or len(label) > 1000:
            raise ValueError('Each step score requires a bounded step description')
        score = _score_value(raw.get('score'), field='step score', maximum=float(question_max))
        step_max_raw = raw.get('max_score')
        step_max = (
            _score_value(step_max_raw, field='step max_score', positive=True, maximum=float(question_max))
            if step_max_raw is not None else None
        )
        if step_max is not None and float(score) > float(step_max):
            raise ValueError('A step score cannot exceed its max_score')
        entry = {'step': label, 'score': score}
        if step_max is not None:
            entry['max_score'] = step_max
        detail = str(raw.get('detail') or raw.get('feedback') or '').strip()
        if detail:
            entry['detail'] = detail[:2000]
        normalized.append(entry)
    return normalized


def _payload_hash(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _normalize_suggestions(raw_suggestions, *, questions: dict, results: list[dict], version: int) -> list[dict] | None:
    if raw_suggestions is None:
        return None
    if not isinstance(raw_suggestions, list):
        raise ValueError('suggestions must be an array')
    result_by_question = {result['question_id']: result for result in results}
    known_nodes = {node_id for question in questions.values() for node_id in question.get('node_ids', [])}
    normalized, seen = [], set()
    for raw in raw_suggestions:
        if not isinstance(raw, dict):
            raise ValueError('Each suggestion must be an object')
        node_id = str(raw.get('node_id') or '').strip()
        if not node_id or node_id not in known_nodes or node_id in seen:
            raise ValueError('Each suggestion must identify one unique assessed node')
        question_ids = raw.get('question_ids')
        if (
            not isinstance(question_ids, list) or not question_ids
            or any(str(question_id) not in result_by_question for question_id in question_ids)
        ):
            raise ValueError('Suggestion question_ids must reference graded questions')
        question_ids = list(dict.fromkeys(str(question_id) for question_id in question_ids))
        if any(
            node_id not in result_by_question[question_id].get('assessed_node_ids', [])
            or result_by_question[question_id].get('helped')
            or result_by_question[question_id].get('state') == 'uncertain'
            for question_id in question_ids
        ):
            raise ValueError('Suggestions require independent assessed question evidence')
        passed = raw.get('passed')
        mastery = raw.get('mastery')
        reason = str(raw.get('reason') or '').strip()
        if type(passed) is not bool or mastery not in (None, 'low', 'medium', 'high') or not reason:
            raise ValueError('Each suggestion requires passed, mastery and reason')
        if (passed and mastery is None) or (not passed and mastery is not None):
            raise ValueError('Suggestion mastery must match its passed state')
        normalized.append({
            'node_id': node_id,
            'passed': passed,
            'mastery': mastery,
            'reason': reason[:2000],
            'question_ids': question_ids,
            'grading_version': version,
        })
        seen.add(node_id)
    return normalized


def exam(store, p: dict, *, trusted_results: bool | None = None) -> dict:
    """Apply one durable exam action without making a second model call.

    The active Study Agent authors questions and grading results.  This
    boundary checks only durable structure, score ranges, node ownership and
    version/idempotency invariants; it does not compare answer wording or try
    to re-grade the Agent's semantic judgment.

    ``trusted_results`` remains as a no-op compatibility keyword for older
    direct callers.  Public callers and the Agent use the same path now.
    """
    action = str(p.get('action') or '').strip()
    with store.db() as db:
        if action == 'create':
            raw_questions = p.get('questions', [])
            if not isinstance(raw_questions, list) or not 1 <= len(raw_questions) <= 30:
                raise ValueError('A complete small exam requires 1–30 questions')
            exam_id, public_questions, private_questions, all_ids = identifier(), [], {}, set()
            for index, raw in enumerate(raw_questions, 1):
                if not isinstance(raw, dict):
                    raise ValueError('Each question must be an object')
                q, qid = dict(raw), str(index)
                answer = str(q.pop('answer', '')).strip()
                rubric = str(q.pop('rubric', answer) or '').strip()
                grading_steps = q.pop('grading_steps', q.pop('step_scores', []))
                if grading_steps is None:
                    grading_steps = []
                if not isinstance(grading_steps, list) or len(grading_steps) > 50:
                    raise ValueError('Private grading_steps must be an array with at most 50 items')
                if len(json.dumps(grading_steps, ensure_ascii=False, default=str)) > 20000:
                    raise ValueError('Private grading_steps are too long')
                max_score = _score_value(q.get('max_score', 1), field='question max_score', positive=True)
                node_ids = q.get('node_ids')
                if (
                    q.get('type') not in ('choice', 'written')
                    or not str(q.get('prompt') or '').strip()
                    or not answer
                    or not isinstance(node_ids, list)
                    or not node_ids
                    or any(not str(nid).strip() for nid in node_ids)
                    or len({str(nid) for nid in node_ids}) != len(node_ids)
                ):
                    raise ValueError('Each question needs type, prompt, private answer/rubric and node_ids')
                if len(answer) > 4000 or len(rubric) > 4000:
                    raise ValueError('Private answer and rubric are too long')
                q['node_ids'] = [str(nid).strip() for nid in node_ids]
                q['max_score'] = max_score
                if q['type'] == 'choice' and (
                    not isinstance(q.get('options'), list)
                    or len(q.get('options', [])) < 2
                ):
                    raise ValueError('Choice questions need at least two options')
                for nid in q['node_ids']:
                    store.get(db, nid, 'node'); all_ids.add(nid)
                public_questions.append(_public_question(q, qid))
                private_questions[qid] = {
                    'answer': answer,
                    'rubric': rubric or answer,
                    'grading_steps': deepcopy(grading_steps),
                    'max_score': max_score,
                }
            item = {'id': exam_id, 'title': str(p.get('title') or '考试'), 'questions': public_questions,
                    'node_ids': sorted(all_ids), 'status': 'open', 'answers': {}, 'image_ids': [],
                    'uncertain': {}, 'help': {}, 'results': [], 'suggestions': [],
                    'grading_version': 0, 'grading_history': [],
                    'max_score': sum(float(question['max_score']) for question in public_questions)}
            store.put(db, 'exam_private', {'id': _private_id(exam_id), 'questions': private_questions})
        elif action == 'list':
            items = store.rows(db, 'exam'); offset = max(0, int(p.get('offset', 0))); limit = min(30, max(1, int(p.get('limit', 30))))
            return {'exams': [{k: e.get(k) for k in ('id', 'title', 'status', 'node_ids', 'grading_version')} for e in items[::-1][offset:offset + limit]], 'total': len(items), 'offset': offset, 'limit': limit}
        else:
            exam_id = str(p.get('exam_id') or '').strip()
            if not exam_id: raise ValueError('exam_id is required')
            item = store.get(db, exam_id, 'exam'); questions = {str(q['id']): q for q in item.get('questions', [])}
            if action == 'get':
                qid = str(p.get('question_id') or '').strip()
                private = store.get(db, _private_id(exam_id), 'exam_private')['questions']
                return {'exam': public_exam(item, help_question_id=qid or None, private_questions=private)}
            if action == 'reference':
                private = store.get(db, _private_id(exam_id), 'exam_private')['questions']
                reference_questions = []
                for question_id, question in questions.items():
                    grading = deepcopy(private.get(question_id, {}))
                    reference_questions.append({
                        **_public_question(question, question_id),
                        'answer': grading.get('answer', ''),
                        'rubric': grading.get('rubric', grading.get('answer', '')),
                        'grading_steps': grading.get('grading_steps', []),
                    })
                return {'reference': {
                    'exam_id': exam_id,
                    'title': item.get('title', '考试'),
                    'status': item.get('status'),
                    'grading_version': int(item.get('grading_version') or 0),
                    'questions': reference_questions,
                    'student_answers': deepcopy(item.get('answers', {})),
                    'image_ids': deepcopy(item.get('image_ids', [])),
                    'uncertain': deepcopy(item.get('uncertain', {})),
                    'help': deepcopy(item.get('help', {})),
                }}
            if action in ('save_answers', 'save'):
                if item['status'] not in ('open', 'in_progress'): raise ValueError('Answers can only be saved before submission')
                answers = p.get('answers')
                if not isinstance(answers, dict) or not answers: raise ValueError('answers must map question ids to draft answers')
                if set(map(str, answers)) - set(questions): raise ValueError('Answers reference unknown question ids')
                item['answers'].update({str(k): v for k, v in answers.items()})
                uncertain = p.get('uncertain', {})
                if uncertain:
                    if not isinstance(uncertain, dict) or not set(map(str, uncertain)) <= set(questions): raise ValueError('uncertain must reference exam question ids')
                    item['uncertain'].update({str(k): str(v)[:500] for k, v in uncertain.items()})
                _merge_images(item, p.get('image_ids', [])); item['status'] = 'in_progress'
            elif action == 'submit':
                if item['status'] not in ('open', 'in_progress'): raise ValueError('Only an open or in-progress exam can be submitted')
                raw_answers = p.get('answers')
                if isinstance(raw_answers, dict):
                    if not set(map(str, raw_answers)) <= set(questions): raise ValueError('Answers reference unknown question ids')
                    item['answers'].update({str(k): v for k, v in raw_answers.items()})
                elif isinstance(raw_answers, str) and raw_answers.strip(): item['answers']['_sheet'] = raw_answers.strip()
                _merge_images(item, p.get('image_ids', []))
                if not item.get('answers') and not item.get('image_ids'): raise ValueError('Submit the answer sheet after saving text or image answers')
                item['status'] = 'submitted'
            elif action == 'help':
                if item['status'] not in ('open', 'in_progress'): raise ValueError('Help is only available while answering')
                qid, level = str(p.get('question_id') or ''), str(p.get('level') or 'hint')
                disclosure = str(p.get('disclosure') or '').strip()
                if qid not in questions: raise ValueError('question_id must belong to this exam')
                if level not in ('hint', 'strategy', 'solution') or not disclosure:
                    raise ValueError('Help requires a valid level and disclosure')
                history = item.setdefault('help', {}).setdefault(qid, [])
                history.append({'id': identifier(), 'level': level, 'disclosure': disclosure[:2000]}); item['status'] = 'in_progress'
                store.put(db, 'exam', item); store.bump(db)
                return {'exam_id': exam_id, 'question_id': qid, 'help': deepcopy(history)}
            elif action in ('grade', 'review'):
                if action == 'grade' and item['status'] not in ('submitted', 'graded'): raise ValueError('Submit the entire exam before grading')
                if action == 'review' and item['status'] != 'graded': raise ValueError('Only a graded exam can be reviewed')
                results = p.get('results', [])
                if (
                    not isinstance(results, list)
                    or any(not isinstance(result, dict) for result in results)
                    or len(results) != len(questions)
                    or {str(result.get('question_id')) for result in results} != set(questions)
                ):
                    raise ValueError('Grade every question exactly once')
                grading_hash = _payload_hash({
                    'action': action,
                    'results': results,
                    'suggestions': p.get('suggestions'),
                })
                request_id = str(p.get('request_id') or '').strip()
                if request_id and (len(request_id) > 256 or any(ord(char) < 32 for char in request_id)):
                    raise ValueError('Invalid grading request_id')
                receipts = item.get('_grading_receipts', {})
                if request_id and request_id in receipts:
                    if receipts[request_id].get('payload_hash') != grading_hash:
                        raise ValueError('Conflicting retry for grading request_id')
                    return {'exam': public_exam(item)}
                if item.get('_last_grading_hash') == grading_hash and item.get('status') == 'graded':
                    return {'exam': public_exam(item)}
                current_version = int(item.get('grading_version') or 0)
                expected_version = p.get('expected_grading_version')
                if expected_version is not None and (
                    type(expected_version) is not int or expected_version != current_version
                ):
                    raise ValueError('Grading version conflict')
                if action == 'grade' and item['status'] != 'submitted': raise ValueError('Submit the entire exam before grading')
                private = store.get(db, _private_id(exam_id), 'exam_private')['questions']; evidence = {}; normalized = []
                for raw in results:
                    if not isinstance(raw, dict):
                        raise ValueError('Each result must be an object')
                    r = dict(raw); qid = str(r.get('question_id')); q = questions[qid]
                    question_max = _score_value(q.get('max_score', 1), field='question max_score', positive=True)
                    supplied_max = r.get('max_score')
                    if supplied_max is not None and float(_score_value(supplied_max, field='result max_score', positive=True)) != float(question_max):
                        raise ValueError(f'Result max_score does not match question {qid}')
                    state = str(r.get('state') or '').strip()
                    if state == 'uncertain':
                        score = None
                    else:
                        if r.get('score') is None:
                            if state == 'correct' or r.get('correct') is True:
                                score = question_max
                            elif state == 'incorrect' or r.get('correct') is False:
                                score = 0
                            else:
                                raise ValueError('Each certain result requires a score')
                        else:
                            score = _score_value(r.get('score'), field='result score', maximum=float(question_max))
                        if float(score) > float(question_max):
                            raise ValueError(f'Score exceeds max_score for question {qid}')
                        derived_state = (
                            'correct' if float(score) == float(question_max)
                            else 'incorrect' if float(score) == 0
                            else 'partial'
                        )
                        if state and state not in ('correct', 'partial', 'incorrect'):
                            raise ValueError('Each result state must be correct, partial, incorrect or uncertain')
                        # Scores are authoritative.  Normalize a stale/coarse state
                        # rather than rejecting a semantically valid model grade.
                        state = derived_state
                    reason = str(r.get('reason') or '').strip()
                    if not reason:
                        raise ValueError('Each result requires grading feedback')
                    step_scores = _normalize_step_scores(
                        r.get('step_scores', r.get('grading_steps', r.get('steps'))),
                        question_max=question_max,
                    )
                    raw_failed = r.get('incorrect_node_ids', [])
                    raw_assessed = r.get('assessed_node_ids', q['node_ids'])
                    if not isinstance(raw_failed, list) or not isinstance(raw_assessed, list):
                        raise ValueError('Assessed/incorrect node ids must be arrays')
                    failed = list(dict.fromkeys(str(nid).strip() for nid in raw_failed if str(nid).strip()))
                    assessed = list(dict.fromkeys(str(nid).strip() for nid in raw_assessed if str(nid).strip()))
                    if not set(failed) <= set(assessed) <= set(q['node_ids']):
                        raise ValueError('Assessed/incorrect nodes must belong to the question')
                    if state != 'uncertain' and not assessed:
                        raise ValueError('A certain result requires assessed node evidence')
                    if state == 'uncertain':
                        assessed, failed, step_scores = [], [], []
                    helped = qid in item.get('help', {})
                    if not helped and state != 'uncertain':
                        for nid in assessed:
                            node_score = (
                                float(score)
                                if not failed or nid in failed
                                else float(question_max)
                            )
                            evidence.setdefault(nid, []).append((node_score, float(question_max), qid))
                    normalized.append({
                        'question_id': qid,
                        'state': state,
                        'correct': None if state == 'uncertain' else state == 'correct',
                        'score': score,
                        'max_score': question_max,
                        'reason': _public_reason(reason, private[qid], state),
                        'step_scores': step_scores,
                        'node_ids': q['node_ids'],
                        'assessed_node_ids': assessed,
                        'incorrect_node_ids': failed,
                        'helped': helped,
                    })
                version = current_version + 1
                suggestions = _normalize_suggestions(
                    p.get('suggestions'), questions=questions, results=normalized, version=version,
                )
                if suggestions is None:
                    suggestions = []
                    for nid, marks in evidence.items():
                        earned = sum(mark[0] for mark in marks)
                        possible = sum(mark[1] for mark in marks)
                        ratio = earned / possible if possible else 0
                        passed = ratio >= .6
                        prior_success = any(
                            assessment.get('node_id') == nid
                            and assessment.get('exam_id') not in (None, exam_id)
                            and assessment.get('passed') is True
                            for assessment in store.rows(db, 'assessment')
                        )
                        mastery = (
                            'high' if ratio == 1 and len(marks) >= 2 and prior_success
                            else 'medium' if ratio >= .8 and len(marks) >= 2
                            else 'low'
                        )
                        suggestions.append({
                            'node_id': nid,
                            'passed': passed,
                            'mastery': mastery if passed else None,
                            'reason': f'独立评分证据 {earned:g}/{possible:g} 分',
                            'question_ids': list(dict.fromkeys(mark[2] for mark in marks)),
                            'grading_version': version,
                        })
                if item.get('grading_version'):
                    item.setdefault('grading_history', []).append({
                        'grading_version': item['grading_version'],
                        'results': item.get('results', []),
                        'suggestions': item.get('suggestions', []),
                        'score': item.get('score'),
                        'earned_score': item.get('earned_score'),
                        'max_score': item.get('max_score'),
                    })
                counted = [result for result in normalized if result['state'] != 'uncertain']
                earned_score = sum(float(result['score']) for result in counted)
                max_score = sum(float(result['max_score']) for result in counted)
                ratio = earned_score / max_score if max_score else None
                item.update(
                    status='graded', results=normalized, suggestions=suggestions,
                    grading_version=version, passed=ratio is not None and ratio >= .6,
                    score=ratio, earned_score=earned_score, max_score=max_score,
                    _last_grading_hash=grading_hash,
                )
                if request_id:
                    receipts = dict(receipts)
                    receipts[request_id] = {'payload_hash': grading_hash, 'grading_version': version}
                    item['_grading_receipts'] = receipts
            else: raise ValueError('Unknown exam action')
        private_for_public = None
        try:
            private_for_public = store.get(db, _private_id(item['id']), 'exam_private')['questions']
        except ValueError:
            # A legacy/incomplete record remains readable without inventing
            # private material; the public projection still allowlists fields.
            pass
        store.put(db, 'exam', item); store.bump(db)
        return {'exam': public_exam(item, private_questions=private_for_public)}


def _merge_images(item: dict, images) -> None:
    if images is None or images == []:
        return
    if (
        not isinstance(images, list)
        or len(images) > 20
        or any(
            not isinstance(image_id, str)
            or not image_id.strip()
            or len(image_id.strip()) > 256
            or any(ord(char) < 32 for char in image_id)
            or '/' in image_id
            or '\\' in image_id
            for image_id in images
        )
    ):
        raise ValueError('Invalid answer image references')
    item['image_ids'] = list(dict.fromkeys([*item.get('image_ids', []), *(i.strip() for i in images)]))


def public_exam(item: dict, *, help_question_id: str | None = None,
                private_questions: dict | None = None) -> dict:
    public = deepcopy(item)
    public.pop('_last_grading_hash', None)
    public.pop('_grading_receipts', None)
    public['questions'] = [
        _public_question(question, str(question.get('id') or index))
        for index, question in enumerate(public.get('questions', []), 1)
        if isinstance(question, dict)
    ]
    all_help = public.pop('help', {})
    if isinstance(private_questions, dict):
        for question_id, entries in list(all_help.items()):
            private = private_questions.get(str(question_id), {})
            if not isinstance(entries, list):
                all_help[question_id] = []
                continue
            all_help[question_id] = [
                {**entry, 'disclosure': str(entry.get('disclosure') or '')[:2000]}
                for entry in entries if isinstance(entry, dict)
            ]
        for result in public.get('results', []):
            if isinstance(result, dict):
                private = private_questions.get(str(result.get('question_id')), {})
                state = str(result.get('state') or 'uncertain')
                result['reason'] = _public_reason(result.get('reason', ''), private, state)
        for history in public.get('grading_history', []):
            if not isinstance(history, dict):
                continue
            for result in history.get('results', []):
                if isinstance(result, dict):
                    private = private_questions.get(str(result.get('question_id')), {})
                    state = str(result.get('state') or 'uncertain')
                    result['reason'] = _public_reason(result.get('reason', ''), private, state)
    if help_question_id:
        public['help'] = {help_question_id: all_help.get(help_question_id, [])}
    return public
