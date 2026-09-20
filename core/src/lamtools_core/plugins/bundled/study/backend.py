from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from pathlib import Path

from lamtools_core.app.operation_catalog import OperationResult
from lamtools_core.session import build_session_record
from lamtools_core.tool import ToolResult
from .exams import exam
from .marks import answer, mark_operation
from .store import LOCAL_COMPATIBILITY_SCOPE, StudyNoteError, StudyScope, StudyStore, identifier

TOOL_OPERATIONS = {
    'get_knowledge_net': 'study.get',
    'build_knowledge_net': 'study.build',
    'exam': 'study.exam',
    'sign': 'study.sign',
    'notes': 'study.notes',
}
STUDY_NODE_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')


def _load_study_system_prompt() -> str:
    """Load the Study prompt from source or the frozen plugin resource tree."""
    source_path = Path(__file__).resolve().parent / 'prompts' / 'study-system.md'
    if source_path.is_file():
        return source_path.read_text(encoding='utf-8').strip()

    # PyInstaller keeps the importable backend in its module archive while
    # plugin-owned prompts live under resources/plugins/bundled.  Resolving
    # through the registry preserves the same plugin root contract used by
    # discovery instead of assuming that data files sit beside the .pyc.
    from lamtools_core.plugins.registry import bundled_plugins_dir

    packaged_path = bundled_plugins_dir() / 'study' / 'prompts' / 'study-system.md'
    return packaged_path.read_text(encoding='utf-8').strip()


STUDY_SYSTEM_PROMPT = _load_study_system_prompt()


def study_node_session_id(node_id: str) -> str:
    """Keep readable legacy ids where safe and hash every other valid graph id."""
    if STUDY_NODE_ID.fullmatch(node_id):
        return f'study:node:{node_id}'
    digest = hashlib.sha256(node_id.encode('utf-8')).hexdigest()[:32]
    return f'study:node:{digest}'


def _scope_values(metadata: dict | None) -> tuple[str, str, str] | None:
    """Extract a complete Study scope from host metadata only.

    Operation payloads are deliberately not accepted here.  The operation
    catalog carries request metadata separately from the JSON payload, and a
    host context may also provide a process-owned metadata snapshot.  A
    partial scope is represented by a tuple containing empty values so the
    caller can reject it instead of silently falling back to the local scope.
    """
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get('study_scope')
    if not isinstance(raw, dict):
        raw = metadata.get('trusted_study_scope')
    if not isinstance(raw, dict):
        # Context metadata is host-owned, but do not treat arbitrary request
        # metadata keys as identity.  Only the explicit scope fields below
        # are meaningful.
        raw = metadata
    values = (
        str(raw.get('authenticated_user_id') or raw.get('user_id') or '').strip(),
        str(raw.get('environment_id') or raw.get('env_id') or '').strip(),
        str(raw.get('library_id') or '').strip(),
    )
    return values if any(values) else None


def resolve_study_scope(request_metadata: dict | None, context) -> StudyScope:
    """Resolve identity from trusted metadata; payload fields are ignored.

    If both the host context and operation request carry a scope they must
    agree.  This prevents a request-level value from silently overriding a
    process-owned context identity while retaining the operation-catalog
    metadata path used by authenticated hosts.
    """
    context_values = _scope_values(getattr(context, 'metadata', {}) or {})
    request_values = _scope_values(request_metadata)
    if context_values and request_values and context_values != request_values:
        raise ValueError('Trusted Study scope conflict')
    values = request_values or context_values
    if not values:
        return LOCAL_COMPATIBILITY_SCOPE
    user, environment, library = values
    present = [bool(user), bool(environment), bool(library)]
    if not all(present):
        raise ValueError('Trusted Study scope is incomplete')
    if any(len(value) > 200 or any(ord(ch) < 32 for ch in value) for value in values):
        raise ValueError('Trusted Study scope is invalid')
    return StudyScope(user, environment, library, False)


def scoped_session_id(scope: StudyScope, base: str) -> str:
    if scope.compatibility_fallback:
        return base
    digest = hashlib.sha256(scope.key.encode('utf-8')).hexdigest()[:16]
    return f'{base}:{digest}'


class StudyRuntime:
    def __init__(self, context):
        self.context = context
        self.store = StudyStore(Path(context.app_data_dir or context.data_dir or Path.home() / '.lam/core/data') / 'study.db')
        self.locks: dict[str, asyncio.Lock] = {}
        self.session_lock = asyncio.Lock()

    @property
    def tool_handlers(self):
        async def handle(call):
            arguments = dict(call.arguments or {})
            metadata = dict(call.metadata or {})
            if call.name == 'notes':
                # Object identity is process-owned authority and cannot be
                # reconstructed by a JSON RPC payload or metadata field.
                metadata['_study_notes_writer_runtime'] = self
            result = await self.context.operation_executor()(TOOL_OPERATIONS[call.name], arguments, metadata)
            return ToolResult(call_id=call.id, name=call.name,
                              status='ok' if result.status == 'ok' else 'failed',
                              content=json.dumps(result.payload, ensure_ascii=False),
                              error=str(result.payload.get('error', '')))
        return {name: handle for name in TOOL_OPERATIONS}


def create_plugin(context):
    return StudyRuntime(context)


async def manifest_tool(call):
    return ToolResult(call_id=call.id, name=call.name, status='failed', error='Study runtime is unavailable')


async def maybe(value):
    return await value if inspect.isawaitable(value) else value


def study_session_spec(store, payload):
    scope = str(payload.get('scope') or 'builder').strip().lower()
    if scope in ('builder', 'main', 'map'):
        return scoped_session_id(store.scope, 'study:main'), '知识图谱', {
            'owner_plugin': 'study', 'resource_type': 'study_session',
            'resource_id': 'map', 'study_scope': 'map',
            'resource_work_root': '', 'project_independent': True,
        }
    if scope == 'notes':
        return scoped_session_id(store.scope, 'study:notes'), '学习笔记', {
            'owner_plugin': 'study', 'resource_type': 'study_session',
            'resource_id': 'notes', 'study_scope': 'notes',
            'resource_work_root': '', 'project_independent': True,
        }
    if scope != 'node':
        raise ValueError('Study session scope must be map, notes or node')
    node_id = str(payload.get('node_id') or '').strip()
    if not node_id or len(node_id) > 512 or any(ord(char) < 32 for char in node_id):
        raise ValueError('Invalid Study node id')
    node = store.read({'node_id': node_id})['node']
    if not node.get('learnable', True):
        raise ValueError('GROUP_HAS_NO_SESSION')
    return scoped_session_id(store.scope, study_node_session_id(node_id)), f"学习 · {node['name']}", {
        'owner_plugin': 'study', 'resource_type': 'study_session',
        'resource_id': node_id, 'study_scope': 'node', 'study_node_id': node_id,
        'study_node_name': node['name'], 'resource_work_root': '',
        'project_independent': True,
    }


async def ensure_study_session(sessions, store, payload):
    sid, title, metadata = study_session_spec(store, payload)
    if not store.scope.compatibility_fallback:
        # SessionStore is shared with Core, so keep the Study scope explicit
        # on non-legacy records.  The legacy compatibility path intentionally
        # preserves its historical metadata shape.
        metadata = {**metadata, 'study_scope_key': store.scope.key}
    kind = metadata['study_scope']
    existing_binding = store.primary_binding(kind, metadata.get('study_node_id'))
    if existing_binding and not payload.get('replace_primary'):
        sid = existing_binding['session_id']
    elif payload.get('replace_primary'):
        sid = scoped_session_id(store.scope, f"study:{kind}:{identifier()}")
    existing = await maybe(sessions.get(sid))
    if existing is None:
        record = build_session_record(
            session_id=sid, member_id='core', title=title, metadata=metadata,
        )
        await maybe(sessions.create(record))
        store.ensure_binding(kind, record.id, node_id=metadata.get('study_node_id'), replace_primary=bool(payload.get('replace_primary')))
        return record, True
    owner = str(existing.metadata.get('owner_plugin') or '').strip()
    if owner and owner != 'study':
        raise ValueError(f"Session '{sid}' is owned by another plugin")
    existing_scope = str(existing.metadata.get('study_scope') or '').strip()
    existing_node = str(existing.metadata.get('study_node_id') or '').strip()
    if existing_scope and existing_scope != metadata['study_scope']:
        raise ValueError(f"Session '{sid}' has incompatible Study metadata")
    if existing_node and existing_node != metadata.get('study_node_id', ''):
        raise ValueError(f"Session '{sid}' belongs to another Study node")
    merged = {**existing.metadata, **metadata}
    merged.pop('project_id', None)
    merged.pop('work_root', None)
    previous_node_name = str(existing.metadata.get('study_node_name') or '').strip()
    previous_auto_title = f'学习 · {previous_node_name}' if previous_node_name else ''
    auto_titles = (sid, 'New Session', previous_auto_title)
    if metadata['study_scope'] == 'map':
        auto_titles = (*auto_titles, '学习')
    title_update = title if existing.title in auto_titles and existing.title != title else None
    patch = getattr(sessions, 'patch', None)
    if callable(patch) and (merged != existing.metadata or title_update is not None):
        updated = await maybe(patch(sid, title=title_update, metadata=merged))
        if updated is not None:
            existing = updated
    elif merged != existing.metadata or title_update is not None:
        existing.metadata = merged
        if title_update is not None:
            existing.title = title_update
        update = getattr(sessions, 'update', None)
        if callable(update):
            existing = await maybe(update(existing))
    store.ensure_binding(kind, existing.id, node_id=metadata.get('study_node_id'), replace_primary=bool(payload.get('replace_primary')))
    return existing, False


def _study_session_in_scope(record, store: StudyStore) -> bool:
    metadata = getattr(record, 'metadata', None)
    if not isinstance(metadata, dict) or metadata.get('owner_plugin') != 'study':
        return False
    recorded_scope = str(metadata.get('study_scope_key') or '').strip()
    if recorded_scope:
        return recorded_scope == store.scope.key
    if store.scope.compatibility_fallback:
        return True
    digest = hashlib.sha256(store.scope.key.encode('utf-8')).hexdigest()[:16]
    return str(getattr(record, 'id', '')).endswith(':' + digest)


async def _study_session_targets(context, store: StudyStore) -> dict[str, dict[str, object]]:
    sessions = context.service('session_store') if context else None
    if sessions is None:
        return {}
    listing = getattr(sessions, 'list', None)
    if not callable(listing):
        return {}
    records = await maybe(listing())
    targets: dict[str, dict[str, object]] = {}
    for record in records or []:
        if not _study_session_in_scope(record, store):
            continue
        session_id = str(getattr(record, 'id', '') or '').strip()
        if session_id:
            targets[session_id] = {
                'id': session_id,
                'title': str(getattr(record, 'title', '') or session_id),
            }
    return targets


async def study_search(context, store: StudyStore, payload: dict) -> dict:
    query = str(payload.get('query') or '').strip()
    if not query:
        return store.search({'query': '', 'limit': payload.get('limit', 20)})
    limit = min(50, max(1, int(payload.get('limit', 20))))
    # Fetch the operation cap before merging Core-owned sessions, otherwise a
    # large node result set could starve a matching Study session.
    result = store.search({**payload, 'limit': 50})
    results = list(result.get('results') or [])
    session_targets = await _study_session_targets(context, store)
    sessions = context.service('session_store') if context else None
    list_messages = getattr(sessions, 'list_messages', None) if sessions is not None else None
    folded = query.casefold()
    if sessions is not None:
        listing = getattr(sessions, 'list', None)
        records = await maybe(listing()) if callable(listing) else []
        for record in records or []:
            if not _study_session_in_scope(record, store):
                continue
            session_id = str(getattr(record, 'id', '') or '').strip()
            title = str(getattr(record, 'title', '') or session_id)
            metadata = getattr(record, 'metadata', None)
            metadata = metadata if isinstance(metadata, dict) else {}
            node_name = str(metadata.get('study_node_name') or '')
            message_id = ''
            snippet_source = ''
            if folded in ' '.join((title, node_name)).casefold():
                snippet_source = ' '.join(value for value in (title, node_name) if value)
            if callable(list_messages):
                messages = await maybe(list_messages(session_id))
                for message in messages or []:
                    content = str(getattr(message, 'content', '') or '').strip()
                    if folded in content.casefold():
                        snippet_source = content
                        message_id = str(getattr(message, 'id', '') or '')
                        break
            if not snippet_source:
                continue
            result_item = {
                'entity_type': 'session', 'kind': 'session',
                'entity_id': session_id, 'session_id': session_id,
                'title': title,
                'snippet': StudyStore._search_snippet(snippet_source, query),
                'target': {'kind': 'session', 'id': session_id, **({'message_id': message_id} if message_id else {})},
            }
            if message_id:
                result_item['message_id'] = message_id
            results.append(result_item)

    results.sort(key=lambda item: (str(item.get('entity_type') or ''), str(item.get('entity_id') or '')))
    return {
        **result,
        'results': results[:limit],
        'total': len(results),
        'has_more': len(results) > limit,
        'scope': store.scope.public(),
    }


async def study_pins(context, store: StudyStore, payload: dict) -> dict:
    targets = await _study_session_targets(context, store)
    return store.pins(payload, session_targets=targets)


async def study_context(context, store, payload):
    """Return the static Study identity and a compact request-local context."""
    session_id = str(payload.get('session_id') or payload.get('thread_id') or 'study:main').strip()
    metadata = {}
    sessions = context.service('session_store') if context else None
    if sessions is not None and session_id:
        record = await maybe(sessions.get(session_id))
        if record is not None and isinstance(getattr(record, 'metadata', None), dict):
            metadata = dict(record.metadata)
    latest: dict[str, object] = {}
    language = str(metadata.get('preferred_language') or metadata.get('language') or '').strip()
    if language:
        latest['preferred_language'] = language
    study_scope = str(metadata.get('study_scope') or payload.get('study_scope') or '').strip().lower()
    explicit_node_id = str(metadata.get('study_node_id') or payload.get('node_id') or '').strip()
    node_id = explicit_node_id
    current = store.state('current')
    # Notes management sessions are intentionally detached from the mutable
    # graph selection.  Otherwise opening the notes chat silently inherits the
    # last node and leaks unrelated teaching context into curation.
    if not node_id and study_scope != 'notes' and isinstance(current, dict):
        node_id = str(current.get('id') or '').strip()
    node = None
    if node_id:
        try:
            node = store.read({'node_id': node_id})['node']
        except (KeyError, ValueError):
            node = None
        latest['selected_node_id'] = node_id
    course_id = str(metadata.get('study_course_id') or payload.get('course_id') or '').strip()
    if not course_id and isinstance(node, dict) and node.get('course_ids'):
        course_id = str(node['course_ids'][0])
    if course_id:
        try:
            course = store.read({'course_id': course_id, 'limit': 1})['course']
            latest['current_course'] = {'id': course_id, 'name': course.get('name', '')}
        except (KeyError, ValueError):
            latest['current_course'] = {'id': course_id}
    position = metadata.get('study_teaching_position') or metadata.get('teaching_position')
    if position not in (None, '', [], {}):
        latest['teaching_position'] = position
    relevant = []
    if study_scope != 'notes' or explicit_node_id:
        with store.db(write=False) as db:
            for item in reversed(store.rows(db, 'exam')):
                if item.get('status') not in ('open', 'in_progress', 'submitted'):
                    continue
                if node_id and node_id not in item.get('node_ids', []):
                    continue
                relevant.append({'id': item['id'], 'status': item['status']})
                if len(relevant) >= 8:
                    break
    if relevant:
        latest['exams'] = relevant
    store.state('latest_context:' + session_id, latest, write=True)
    late = '[Study latest context]\n' + json.dumps(latest, ensure_ascii=False, separators=(',', ':'))
    return {
        'instructions': STUDY_SYSTEM_PROMPT,
        'latest_context': latest,
        'request_local_late_context': late,
    }


async def capture_note_raw(context, store: StudyStore, payload: dict) -> dict:
    """Resolve a Raw snapshot from host-owned data; caller text is ignored."""
    kind = str(payload.get('kind') or '').strip()
    origin_id = str(payload.get('origin_id') or '').strip()
    if kind == 'session_message':
        session_id = str(payload.get('session_id') or '').strip()
        sessions = context.service('session_store') if context else None
        listing = getattr(sessions, 'list_messages', None) if sessions is not None else None
        if not session_id or not origin_id or not callable(listing):
            raise ValueError('Unknown raw source')
        messages = await maybe(listing(session_id))
        message = next((item for item in (messages or []) if str(getattr(item, 'id', '')) == origin_id), None)
        if message is None:
            raise ValueError('Unknown raw source')
        content = str(getattr(message, 'content', '') or '')
        metadata = {'session_id': session_id, 'role': str(getattr(message, 'role', '') or '')}
    elif kind in ('mark', 'exam', 'node'):
        with store.db(write=False) as db:
            row = db.execute(
                'SELECT data FROM study_records WHERE scope_key=? AND kind=? AND id=?',
                (store.scope.key, kind, origin_id),
            ).fetchone()
        if not row:
            raise ValueError('Unknown raw source')
        content = row['data']
        metadata = {'record_kind': kind}
    else:
        raise ValueError('Raw kind must be session_message, mark, exam or node')
    return store.notes({
        'action': 'raw_capture', 'raw_id': payload.get('raw_id'), 'kind': kind,
        'origin_id': origin_id, 'content': content, 'metadata': metadata,
        '_trusted_capture': store,
    }, writer='user')


async def sync_note_raw_sources(context, store: StudyStore) -> int:
    """Idempotently snapshot host-owned Study records and Study messages."""
    candidates: list[dict] = []
    with store.db(write=False) as db:
        for kind in ('mark', 'exam', 'node'):
            for row in db.execute(
                'SELECT id,data FROM study_records WHERE scope_key=? AND kind=? ORDER BY id',
                (store.scope.key, kind),
            ):
                digest = hashlib.sha256(str(row['data']).encode('utf-8')).hexdigest()[:16]
                candidates.append({'raw_id': f'{kind}-{row["id"]}-{digest}', 'kind': kind,
                                   'origin_id': str(row['id']), 'content': str(row['data']),
                                   'metadata': {'record_kind': kind}})
    sessions = context.service('session_store') if context else None
    list_messages = getattr(sessions, 'list_messages', None) if sessions is not None else None
    if callable(list_messages):
        for session_id in (await _study_session_targets(context, store)):
            for message in (await maybe(list_messages(session_id))) or []:
                message_id = str(getattr(message, 'id', '') or '').strip()
                if not message_id:
                    continue
                content = str(getattr(message, 'content', '') or '')
                digest = hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]
                candidates.append({'raw_id': f'message-{message_id}-{digest}', 'kind': 'session_message',
                                   'origin_id': message_id, 'content': content,
                                   'metadata': {'session_id': session_id, 'role': str(getattr(message, 'role', '') or '')}})
    created = 0
    for candidate in candidates:
        try:
            store.notes({'action': 'raw_capture', **candidate, '_trusted_capture': store}, writer='user')
            created += 1
        except StudyNoteError as exc:
            if exc.payload.get('error') != 'RAW_EXISTS':
                raise
    return created


async def operation(request, *, context=None, **_):
    try:
        runtime = context.service('study') if context else None
        if runtime is None:
            raise ValueError('Study is unavailable')
        trusted_scope = resolve_study_scope(request.metadata, context)
        store, p = runtime.store.scoped(trusted_scope), request.payload
        name = request.name
        notes_synced = 0
        if name == 'study.session':
            async with runtime.session_lock:
                sessions = context.service('session_store')
                if sessions is None:
                    raise ValueError('Session service is unavailable')
                record, created = await ensure_study_session(sessions, store, p)
            payload = {
                'session_id': record.id,
                'scope': record.metadata.get('study_scope', 'map'),
                'node_id': record.metadata.get('study_node_id'),
                'study_scope': trusted_scope.public(),
            }
            if created and record.metadata.get('study_scope') == 'node':
                payload['draft_prefill'] = f"我想学 {record.metadata.get('study_node_name', '')}，给我讲一下"
                payload['draft_prefill_only_if_empty'] = True
        elif name == 'study.context':
            payload = await study_context(context, store, p)
        elif name == 'study.search':
            payload = await study_search(context, store, p)
        elif name == 'study.pin':
            payload = await study_pins(context, store, p)
        elif name == 'study.get':
            payload = store.read(p)
        elif name == 'study.build':
            payload = store.build(p)
        elif name == 'study.sign':
            payload = store.sign(p)
        elif name == 'study.exam':
            payload = exam(store, p)
        elif name == 'study.layout':
            key = 'layout:' + str(p.get('scope', 'overview'))[:200]
            value = p.get('value')
            if value is not None and len(json.dumps(value)) > 100000:
                raise ValueError('Layout is too large')
            payload = {'value': store.state(key, value, write=value is not None)}
        elif name == 'study.notes':
            writer = 'agent' if request.metadata.get('_study_notes_writer_runtime') is runtime else 'user'
            if p.get('action') == 'raw_capture':
                if writer == 'agent':
                    raise StudyNoteError('RAW_CAPTURE_FORBIDDEN', 'Agents cannot submit Raw content')
                payload = await capture_note_raw(context, store, p)
            else:
                if p.get('action') == 'raw_list':
                    notes_synced = await sync_note_raw_sources(context, store)
                payload = store.notes(p, writer=writer)
        elif name == 'study.outbox':
            payload = store.outbox(mark_delivered=p.get('mark_delivered'), limit=int(p.get('limit', 50)))
        elif name == 'study.current':
            nid = p.get('node_id')
            value = store.read({'node_id': nid})['node'] if nid else None
            current = store.state('current', value, write=bool(nid))
            if nid:
                # Keep the single Study session's mutable teaching position in
                # session metadata, not in mastery evidence.  The UI establishes
                # the selected node here; later hosts may pass a more specific
                # bounded position without changing the RPC/tool architecture.
                sessions = context.service('session_store') if context else None
                primary = store.primary_binding('map')
                map_session_id = primary['session_id'] if primary else scoped_session_id(trusted_scope, 'study:main')
                record = await maybe(sessions.get(map_session_id)) if sessions is not None else None
                if record is not None:
                    metadata = dict(getattr(record, 'metadata', {}) or {})
                    position = p.get('teaching_position')
                    if position in (None, '', [], {}):
                        position = {'node_id': str(nid)}
                    metadata.update(
                        study_node_id=str(nid),
                        study_node_name=str(value.get('name') or ''),
                        study_teaching_position=position,
                    )
                    patch = getattr(sessions, 'patch', None)
                    if callable(patch):
                        await maybe(patch(map_session_id, metadata=metadata))
                    else:
                        record.metadata = metadata
                        update = getattr(sessions, 'update', None)
                        if callable(update):
                            await maybe(update(record))
            payload = {'current': current}
        elif name == 'study.marks':
            payload = mark_operation(store, p)
        elif name == 'study.text':
            payload = await answer(context, store, p)
        else:
            raise ValueError('Unknown study operation')
        if name in ('study.build', 'study.sign', 'study.exam', 'study.marks', 'study.text', 'study.notes'):
            broadcast = getattr(getattr(context, 'event_bus', None), 'broadcast', None)
            read_only = (
                name in ('study.exam', 'study.marks') and p.get('action') in ('get', 'list', 'reference')
            ) or (
                name == 'study.notes' and p.get('action', 'list') in (
                    'raw_list', 'raw_get', 'resource_list', 'resource_get',
                    'list', 'tree', 'get', 'graph', 'backlinks', 'task_get',
                )
            )
            if name == 'study.notes' and p.get('action') == 'raw_list' and notes_synced:
                read_only = False
            if callable(broadcast) and not read_only:
                await maybe(broadcast({'method': 'study/changed', 'thread_id': '', 'payload': {'operation': name}}))
        return OperationResult(name=name, payload=payload)
    except StudyNoteError as exc:
        return OperationResult(name=request.name, status='error', payload=exc.payload)
    except (ValueError, KeyError, TypeError, RuntimeError, TimeoutError) as exc:
        return OperationResult(name=request.name, status='error', payload={'error': str(exc) or type(exc).__name__})


async def cli(args):
    from lamtools_core.app.live_client import CoreAppServerClient
    import os
    client = CoreAppServerClient(args.base_url or os.environ.get('LAMTOOLS_CORE_API_URL', 'http://127.0.0.1:5172'),
                                 path=args.ws_path or '/api/core/app-server', token=args.token or os.environ.get('LAMTOOLS_CORE_TOKEN', ''))
    try:
        await client.connect()
        payload = json.loads(Path(args.from_file).read_text(encoding='utf-8')) if args.from_file else json.loads(args.params)
        result = await client.request('study.' + args.operation, payload)
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result.get('error') else 0
    finally:
        await client.close()
