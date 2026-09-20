"""Transactional, incremental study data. Presentation state is stored separately."""
from __future__ import annotations

import base64
import difflib
import hashlib
import hmac
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .note_vault import (
    content_hash as note_content_hash,
    normalize_relative_path,
    read_document,
    resolve_document_path,
    vault_root,
    write_document,
)


WIKILINK_RE = re.compile(r'\[\[([^\]\r\n]+)\]\]')


def identifier() -> str:
    return uuid.uuid4().hex


LEGACY_USER_ID = 'local-user'
LEGACY_ENVIRONMENT_ID = 'local-environment'
LEGACY_LIBRARY_ID = 'default'


@dataclass(frozen=True)
class StudyScope:
    """Authorization scope supplied by the host, never by a tool payload."""
    user_id: str
    environment_id: str
    library_id: str
    compatibility_fallback: bool = False

    @property
    def key(self) -> str:
        return '\x1f'.join((self.user_id, self.environment_id, self.library_id))

    def public(self) -> dict[str, Any]:
        return {
            'user_id': self.user_id, 'environment_id': self.environment_id,
            'library_id': self.library_id,
            'compatibility_fallback': self.compatibility_fallback,
        }


LOCAL_COMPATIBILITY_SCOPE = StudyScope(
    LEGACY_USER_ID, LEGACY_ENVIRONMENT_ID, LEGACY_LIBRARY_ID, True,
)


class StudyNoteError(ValueError):
    """A note failure whose structured details must cross the RPC boundary."""

    def __init__(self, error: str, reason: str | None = None, **details: Any):
        super().__init__(error)
        self.payload = {'error': error, **({'reason': reason} if reason else {}), **details}


class StudyStore:
    def __init__(self, path: Path, scope: StudyScope = LOCAL_COMPATIBILITY_SCOPE):
        self.path = path
        self.scope = scope
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS study_entities(id TEXT PRIMARY KEY, kind TEXT NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS study_kind ON study_entities(kind);
                CREATE TABLE IF NOT EXISTS study_meta(key TEXT PRIMARY KEY, data TEXT NOT NULL);
                INSERT OR IGNORE INTO study_meta VALUES('revision', '0');
                CREATE TABLE IF NOT EXISTS study_records(
                    scope_key TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(scope_key,id));
                CREATE INDEX IF NOT EXISTS study_records_kind ON study_records(scope_key,kind);
                CREATE TABLE IF NOT EXISTS study_scope_meta(
                    scope_key TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(scope_key,key));
                CREATE TABLE IF NOT EXISTS study_receipts(
                    scope_key TEXT NOT NULL, request_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(scope_key,request_id));
                CREATE TABLE IF NOT EXISTS study_sign_receipts(
                    scope_key TEXT NOT NULL, request_hash TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(scope_key,request_hash));
                CREATE TABLE IF NOT EXISTS study_outbox(
                    scope_key TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL,
                    delivered_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(scope_key,id));
                CREATE TABLE IF NOT EXISTS study_session_bindings(
                    scope_key TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL,
                    node_id TEXT NOT NULL DEFAULT '', session_id TEXT NOT NULL, is_primary INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, replaced_at TEXT,
                    PRIMARY KEY(scope_key,id), UNIQUE(scope_key,session_id));
                CREATE UNIQUE INDEX IF NOT EXISTS study_one_primary_binding
                    ON study_session_bindings(scope_key,kind,node_id) WHERE is_primary=1;
                CREATE TABLE IF NOT EXISTS study_notes(
                    scope_key TEXT NOT NULL, id TEXT NOT NULL, title TEXT NOT NULL, revision INTEGER NOT NULL,
                    source_json TEXT NOT NULL, deleted_at TEXT, PRIMARY KEY(scope_key,id));
                CREATE TABLE IF NOT EXISTS study_note_blocks(
                    scope_key TEXT NOT NULL, note_id TEXT NOT NULL, id TEXT NOT NULL, position INTEGER NOT NULL,
                    author TEXT NOT NULL, content TEXT NOT NULL, locked INTEGER NOT NULL, revision INTEGER NOT NULL,
                    source_json TEXT NOT NULL, PRIMARY KEY(scope_key,note_id,id),
                    FOREIGN KEY(scope_key,note_id) REFERENCES study_notes(scope_key,id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS study_note_resources(
                    scope_key TEXT NOT NULL, id TEXT NOT NULL, note_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL, content TEXT NOT NULL, raw_refs_json TEXT NOT NULL,
                    origin TEXT NOT NULL, revision INTEGER NOT NULL, deleted_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(scope_key,id));
                CREATE INDEX IF NOT EXISTS study_note_resources_note
                    ON study_note_resources(scope_key,note_id,created_at,id);
                CREATE TABLE IF NOT EXISTS study_note_resource_versions(
                    scope_key TEXT NOT NULL, resource_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    title TEXT NOT NULL, content TEXT NOT NULL, raw_refs_json TEXT NOT NULL,
                    origin TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(scope_key,resource_id,revision));
                CREATE TABLE IF NOT EXISTS study_note_raw_sources(
                    scope_key TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL,
                    origin_id TEXT NOT NULL, content TEXT NOT NULL, metadata_json TEXT NOT NULL,
                    captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(scope_key,id));
                CREATE INDEX IF NOT EXISTS study_note_raw_origin
                    ON study_note_raw_sources(scope_key,kind,origin_id,captured_at,id);
                CREATE TABLE IF NOT EXISTS study_note_locks(
                    scope_key TEXT NOT NULL, id TEXT NOT NULL, note_id TEXT NOT NULL,
                    start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL,
                    quote TEXT NOT NULL, prefix TEXT NOT NULL, suffix TEXT NOT NULL,
                    reason TEXT NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(scope_key,id),
                    FOREIGN KEY(scope_key,note_id) REFERENCES study_notes(scope_key,id) ON DELETE CASCADE);
                CREATE INDEX IF NOT EXISTS study_note_locks_note
                    ON study_note_locks(scope_key,note_id,start_offset,end_offset);
                CREATE TABLE IF NOT EXISTS study_curation_tasks(
                    scope_key TEXT NOT NULL, id TEXT NOT NULL, state TEXT NOT NULL, checkpoint_json TEXT NOT NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(scope_key,id));
                CREATE TABLE IF NOT EXISTS study_pins(
                    scope_key TEXT NOT NULL, kind TEXT NOT NULL, entity_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(scope_key,kind,entity_id));
                CREATE INDEX IF NOT EXISTS study_pins_scope_order
                    ON study_pins(scope_key,created_at,kind,entity_id);
                CREATE TABLE IF NOT EXISTS study_course_removals(
                    scope_key TEXT NOT NULL, id TEXT NOT NULL, course_id TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(scope_key,id));
                CREATE INDEX IF NOT EXISTS study_course_removals_lookup
                    ON study_course_removals(scope_key,course_id,created_at);
            ''')
            self._ensure_note_block_foreign_key(db)
            self._ensure_notes_v3_columns(db)
            self._migrate_legacy(db)

    def scoped(self, scope: StudyScope) -> 'StudyStore':
        scoped = object.__new__(StudyStore)
        scoped.path, scoped.scope = self.path, scope
        return scoped

    def _cursor_secret(self) -> bytes:
        """Return a deterministic, database-local cursor signing key.

        Cursors are an API guard against accidentally mixing scopes, queries,
        or structure revisions.  They are not an authentication mechanism;
        the operation still resolves the trusted Study scope before reading.
        Deriving the key from the database path and scope keeps tokens local to
        one store without adding another configuration secret.
        """
        identity = f'{self.path.resolve()}\x1f{self.scope.key}'
        return hashlib.sha256(identity.encode('utf-8')).digest()

    def _cursor_fingerprint(self, payload: dict) -> str:
        ignored = {
            'cursor', 'offset', 'expected_structure_revision', 'expected_revision',
            'legacy_offset', 'allow_legacy_offset', 'legacy', 'limit',
        }
        query = {key: value for key, value in payload.items() if key not in ignored}
        encoded = json.dumps(query, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(encoded.encode('utf-8')).hexdigest()

    def _encode_cursor(self, *, revision: int, offset: int, fingerprint: str) -> str:
        value = {
            'scope': self.scope.key,
            'revision': revision,
            'offset': offset,
            'fingerprint': fingerprint,
        }
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        signature = hmac.new(self._cursor_secret(), raw, hashlib.sha256).hexdigest().encode('ascii')
        return base64.urlsafe_b64encode(raw + b'.' + signature).decode('ascii')

    def _decode_cursor(self, value: str) -> dict[str, Any]:
        try:
            raw, signature = base64.b64decode(value.encode('ascii'), altchars=b'-_', validate=True).rsplit(b'.', 1)
            expected = hmac.new(self._cursor_secret(), raw, hashlib.sha256).hexdigest().encode('ascii')
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            decoded = json.loads(raw)
            if not isinstance(decoded, dict) or decoded.get('scope') != self.scope.key:
                raise ValueError
            if type(decoded.get('revision')) is not int or type(decoded.get('offset')) is not int:
                raise ValueError
            if decoded['offset'] < 0 or not isinstance(decoded.get('fingerprint'), str):
                raise ValueError
            return decoded
        except (ValueError, UnicodeError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError('INVALID_CURSOR') from exc

    def _migrate_legacy(self, db) -> None:
        """Idempotently copy the v1 JSON store into the explicit local scope."""
        key = LOCAL_COMPATIBILITY_SCOPE.key
        db.execute("INSERT OR IGNORE INTO study_scope_meta VALUES(?,?,?)", (key, 'structure_revision', '0'))
        db.execute("INSERT OR IGNORE INTO study_scope_meta VALUES(?,?,?)", (key, 'state_revision', '0'))
        migrated = db.execute(
            "SELECT 1 FROM study_scope_meta WHERE scope_key=? AND key='legacy_migrated'", (key,),
        ).fetchone()
        if migrated is None:
            db.execute(
                "INSERT OR IGNORE INTO study_records(scope_key,id,kind,data) SELECT ?,id,kind,data FROM study_entities",
                (key,),
            )
            for row in db.execute('SELECT key,data FROM study_meta'):
                mapped = 'structure_revision' if row['key'] == 'revision' else row['key']
                db.execute("INSERT OR REPLACE INTO study_scope_meta VALUES(?,?,?)", (key, mapped, row['data']))
            db.execute("INSERT INTO study_scope_meta VALUES(?,?,?)", (key, 'legacy_migrated', '1'))

    @staticmethod
    def _ensure_note_block_foreign_key(db) -> None:
        """Upgrade pre-v2 note blocks to the scoped composite foreign key."""
        foreign_keys = db.execute('PRAGMA foreign_key_list(study_note_blocks)').fetchall()
        if foreign_keys:
            return
        db.execute('ALTER TABLE study_note_blocks RENAME TO study_note_blocks_legacy')
        db.execute('''
            CREATE TABLE study_note_blocks(
                scope_key TEXT NOT NULL, note_id TEXT NOT NULL, id TEXT NOT NULL, position INTEGER NOT NULL,
                author TEXT NOT NULL, content TEXT NOT NULL, locked INTEGER NOT NULL, revision INTEGER NOT NULL,
                source_json TEXT NOT NULL, PRIMARY KEY(scope_key,note_id,id),
                FOREIGN KEY(scope_key,note_id) REFERENCES study_notes(scope_key,id) ON DELETE CASCADE)
        ''')
        db.execute('''
            INSERT INTO study_note_blocks(scope_key,note_id,id,position,author,content,locked,revision,source_json)
            SELECT scope_key,note_id,id,position,author,content,locked,revision,source_json
            FROM study_note_blocks_legacy
        ''')
        db.execute('DROP TABLE study_note_blocks_legacy')

    @staticmethod
    def _ensure_notes_v3_columns(db) -> None:
        """Add the filesystem document index without rewriting legacy rows."""
        columns = {str(row['name']) for row in db.execute('PRAGMA table_info(study_notes)')}
        additions = {
            'path': "TEXT NOT NULL DEFAULT ''",
            'parent_id': "TEXT NOT NULL DEFAULT ''",
            'content_hash': "TEXT NOT NULL DEFAULT ''",
        }
        for name, declaration in additions.items():
            if name not in columns:
                db.execute(f'ALTER TABLE study_notes ADD COLUMN {name} {declaration}')
        db.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS study_note_path '
            "ON study_notes(scope_key,path) WHERE path<>'' AND deleted_at IS NULL",
        )

    def integrity(self) -> dict[str, Any]:
        """Return SQLite integrity and foreign-key checks for a migration audit."""
        with self.db() as db:
            self._migrate_note_blocks(db)
            integrity = str(db.execute('PRAGMA integrity_check').fetchone()[0])
            foreign_keys = [dict(row) for row in db.execute('PRAGMA foreign_key_check').fetchall()]
            return {'integrity_check': integrity, 'foreign_key_check': foreign_keys}

    @contextmanager
    def db(self, *, write: bool = True):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=NORMAL')
        db.execute('PRAGMA busy_timeout=15000')
        try:
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def rows(self, db, kind: str) -> list[dict]:
        return [StudyStore._defaults(kind, json.loads(r['data'])) for r in db.execute(
            'SELECT data FROM study_records WHERE scope_key=? AND kind=? ORDER BY rowid', (self.scope.key, kind))]

    @staticmethod
    def _defaults(kind: str, item: dict) -> dict:
        if kind in ('course', 'module', 'node'):
            item.setdefault('notes', '')
        if kind in ('course', 'module'):
            item.setdefault('metadata', {})
            item.setdefault('deleted_at', None)
        if kind == 'node':
            item.setdefault('content', {})
            item.setdefault('notes_by_course', {})
            item.setdefault('evaluated', False)
            item.setdefault('passed', False)
            item.setdefault('mastery', None)
            item.setdefault('assessment', 'pass' if item.get('passed') else ('fail' if item.get('evaluated') else 'unassessed'))
            item.setdefault('learnable', True)
            item.setdefault('progress_role', 'assessed')
            item.setdefault('structure_revision', 1)
            item.setdefault('state_revision', 0)
            item.setdefault('deleted_at', None)
            item.setdefault('orphaned', False)
        return item

    def get(self, db, id: str, kind: str | None = None) -> dict:
        row = db.execute('SELECT kind,data FROM study_records WHERE scope_key=? AND id=?', (self.scope.key, id)).fetchone()
        if row is None or (kind and row['kind'] != kind):
            raise ValueError(f'Unknown {kind or "entity"}: {id}')
        return StudyStore._defaults(row['kind'], json.loads(row['data']))

    @staticmethod
    def summary(item: dict, *, entity: str | None = None) -> dict:
        hidden = {'notes', 'notes_by_course', 'content', 'metadata', 'sources'}
        result = {key: value for key, value in item.items() if key not in hidden}
        if isinstance(result.get('description'), str) and len(result['description']) > 500:
            result['description'] = result['description'][:500]
            result['description_truncated'] = True
        if entity:
            result['entity'] = entity
        return result

    def put(self, db, kind: str, item: dict):
        db.execute('INSERT INTO study_records VALUES(?,?,?,?) ON CONFLICT(scope_key,id) DO UPDATE SET kind=excluded.kind,data=excluded.data',
                   (self.scope.key, item['id'], kind, json.dumps(item, ensure_ascii=False)))

    def revision(self, db) -> int:
        row = db.execute("SELECT data FROM study_scope_meta WHERE scope_key=? AND key='structure_revision'", (self.scope.key,)).fetchone()
        return int(row[0]) if row else 0

    def state_revision(self, db) -> int:
        row = db.execute("SELECT data FROM study_scope_meta WHERE scope_key=? AND key='state_revision'", (self.scope.key,)).fetchone()
        return int(row[0]) if row else 0

    def bump(self, db, *, state: bool = False):
        key = 'state_revision' if state else 'structure_revision'
        db.execute("INSERT INTO study_scope_meta VALUES(?,?,?) ON CONFLICT(scope_key,key) DO UPDATE SET data=CAST(data AS INTEGER)+1", (self.scope.key, key, '1'))

    def read(self, p: dict) -> dict:
        limit = min(50, max(1, int(p.get('limit', 20))))
        offset = max(0, int(p.get('offset', 0)))
        include_details = p.get('include_details') is True
        with self.db(write=False) as db:
            current_revision = self.revision(db)
            fingerprint = self._cursor_fingerprint(p)
            cursor_value = p.get('cursor')
            if cursor_value is not None:
                if not isinstance(cursor_value, str) or not cursor_value:
                    raise ValueError('INVALID_CURSOR')
                cursor = self._decode_cursor(cursor_value)
                if cursor.get('fingerprint') != fingerprint:
                    raise ValueError('INVALID_CURSOR')
                if cursor.get('revision') != current_revision:
                    raise ValueError('STALE_CURSOR')
                offset = int(cursor['offset'])
            else:
                expected_revision = p.get('expected_structure_revision', p.get('expected_revision'))
                if expected_revision is not None and expected_revision != current_revision:
                    raise ValueError('STALE_CURSOR')
                # Offset remains available to the old UI only for the first
                # page or when the caller explicitly opts into the legacy
                # contract.  New callers bind every deep page to a revision.
                if offset > 0 and expected_revision is None and not (
                    p.get('legacy_offset') or p.get('allow_legacy_offset') or p.get('legacy')
                ):
                    raise ValueError('CURSOR_REQUIRED')
            result: dict[str, Any] = {
                'revision': current_revision,
                'structure_revision': current_revision,
                'state_revision': self.state_revision(db),
                'scope': self.scope.public(),
            }
            nodes = [n for n in self.rows(db, 'node') if not n.get('deleted_at')]
            active_node_ids = {n['id'] for n in nodes}
            if p.get('node_id'):
                node = self.get(db, p['node_id'], 'node')
                if node.get('deleted_at'):
                    raise ValueError(f"Unknown node: {p['node_id']}")
                direction = p.get('relation', 'all')
                relations = [r for r in self.rows(db, 'relation') if
                             r.get('source') in active_node_ids and r.get('target') in active_node_ids and (
                                 (direction == 'all' and node['id'] in (r['source'], r['target'])) or
                                 (direction == 'prerequisite' and r['target'] == node['id'] and r['type'] in ('prerequisite', 'advances')) or
                                 (direction == 'next' and r['source'] == node['id'] and r['type'] in ('prerequisite', 'advances')) or
                                 (direction == 'related' and node['id'] in (r['source'], r['target']) and r['type'] == 'related')
                             )]
                result.update(node=node, relations=relations[offset:offset + limit], total=len(relations))
                ids = {r[k] for r in result['relations'] for k in ('source', 'target')}
                result['neighbors'] = [{'id': n['id'], 'name': n['name'], 'passed': n['passed'], 'mastery': n['mastery']} for n in nodes if n['id'] in ids]
            elif p.get('course_id'):
                cid, mid = p['course_id'], p.get('module_id')
                course = self.get(db, cid, 'course')
                if course.get('deleted_at'):
                    raise ValueError(f'Unknown course: {cid}')
                result['course'] = course if include_details else self.summary(course)
                course_nodes = [n for n in nodes if cid in n['course_ids']]
                result['course'].update(total=len(course_nodes), passed=sum(n['passed'] for n in course_nodes))
                course_modules = [m for m in self.rows(db, 'module') if m['course_id'] == cid and not m.get('deleted_at')]
                module_ids = {m['id'] for m in course_modules}
                # Tool adapters and older builders may represent a root module
                # with either a missing/null parent or an empty string.  They
                # are the same hierarchy level; treating ``""`` as a real
                # parent makes a valid course appear to contain zero items.
                modules = [m for m in course_modules if (m.get('parent_id') or None) == mid]
                if mid:
                    module = self.get(db, mid, 'module')
                    if module.get('deleted_at') or module['course_id'] != cid:
                        raise ValueError('Module belongs to another course')
                    result['module'] = module if include_details else self.summary(module)
                selected = [n for n in nodes if (mid in n['module_ids'] if mid else cid in n['course_ids'] and not module_ids.intersection(n['module_ids']))]
                items = [self.summary(m, entity='module') for m in modules] + [self.summary(n, entity='node') for n in selected]
                result.update(items=items[offset:offset + limit], total=len(items))
                ids = {n['id'] for n in result['items']}
                all_relations = [r for r in self.rows(db, 'relation') if r['source'] in ids and r['target'] in ids]
                result['relations'] = all_relations[:100]
                result['relations_total'] = len(all_relations)
            else:
                courses = [c for c in self.rows(db, 'course') if not c.get('deleted_at')]
                for c in courses:
                    items = [n for n in nodes if c['id'] in n['course_ids']]
                    c.update(total=len(items), passed=sum(n['passed'] for n in items))
                result.update(courses=[self.summary(c) for c in courses[offset:offset + limit]], total=len(courses),
                              progress={'total': len(nodes), 'passed': sum(n['passed'] for n in nodes)})
                row = db.execute("SELECT data FROM study_scope_meta WHERE scope_key=? AND key='current'", (self.scope.key,)).fetchone()
                current_id = json.loads(row[0])['id'] if row else None
                current_node = next((n for n in nodes if n['id'] == current_id), None)
                result['current'] = self.summary(current_node) if current_node else None
            if p.get('node_id'):
                page_count = len(result.get('relations', []))
            elif p.get('course_id'):
                page_count = len(result.get('items', []))
            else:
                page_count = len(result.get('courses', []))
            has_more = offset + page_count < int(result.get('total') or 0)
            result.update(
                offset=offset,
                limit=limit,
                has_more=has_more,
                next_cursor=(self._encode_cursor(
                    revision=current_revision,
                    offset=offset + page_count,
                    fingerprint=fingerprint,
                ) if has_more else None),
            )
            if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 32 * 1024:
                raise ValueError('Knowledge read is too large; request a narrower layer or smaller page')
            return result

    def build(self, p: dict) -> dict:
        ops = p.get('operations')
        if not isinstance(ops, list) or not 1 <= len(ops) <= 100:
            raise ValueError('Provide 1–100 incremental operations')
        encoded_request = json.dumps(ops, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        if len(encoded_request) > 128 * 1024:
            raise ValueError('Incremental batch is too large')
        if any({'passed', 'mastery', 'assessment'} & set((op.get('data') or {}).keys()) for op in ops):
            raise ValueError('Use sign with evidence to change learning status')
        with self.db() as db:
            request_id = str(p.get('request_id') or '').strip()
            digest = hashlib.sha256(encoded_request + str(p.get('revision')).encode()).hexdigest()
            if request_id:
                receipt = db.execute('SELECT payload_hash,result_json FROM study_receipts WHERE scope_key=? AND request_id=?', (self.scope.key, request_id)).fetchone()
                if receipt:
                    if receipt['payload_hash'] != digest:
                        raise ValueError('IDEMPOTENCY_CONFLICT')
                    return json.loads(receipt['result_json'])
            if p.get('revision') != self.revision(db):
                raise ValueError('Read get_knowledge_net first; revision changed or is missing')
            changed = []
            impacts: list[dict[str, Any]] = []
            for op in ops:
                action, kind = op.get('action'), op.get('kind')
                if kind not in ('course', 'module', 'node', 'relation'):
                    raise ValueError('Unknown entity kind')
                if action == 'merge':
                    if kind != 'node':
                        raise ValueError('Only knowledge nodes can be merged')
                    source, target = self.get(db, op['id'], 'node'), self.get(db, op['target_id'], 'node')
                    if source['id'] == target['id']:
                        raise ValueError('Cannot merge a node with itself')
                    if self._has_history_reference(db, source['id']) and not (op.get('confirm_history') or p.get('confirm_history')):
                        raise ValueError('Node has historical exam/assessment references; confirm_history is required')
                    for key in ('course_ids', 'module_ids'):
                        target[key] = list(dict.fromkeys(target[key] + source[key]))
                    # Retain target assessment; do not invent mastery by combining nodes.
                    target.setdefault('merged_ids', []).append(source['id'])
                    self.put(db, 'node', target)
                    for r in self.rows(db, 'relation'):
                        if source['id'] in (r['source'], r['target']):
                            r = {**r, 'source': target['id'] if r['source'] == source['id'] else r['source'],
                                 'target': target['id'] if r['target'] == source['id'] else r['target']}
                            if r['source'] == r['target']:
                                db.execute('DELETE FROM study_records WHERE scope_key=? AND id=?', (self.scope.key, r['id']))
                            else:
                                self.put(db, 'relation', r)
                    seen_relations = set()
                    for r in self.rows(db, 'relation'):
                        key = (r['source'], r['target'], r['type'])
                        if key in seen_relations:
                            db.execute('DELETE FROM study_records WHERE scope_key=? AND id=?', (self.scope.key, r['id']))
                        seen_relations.add(key)
                    # Exam history remains immutable; aliases resolve future sign calls.
                    db.execute('INSERT OR REPLACE INTO study_scope_meta VALUES(?,?,?)', (self.scope.key, 'alias:' + source['id'], json.dumps(target['id'])))
                    db.execute('DELETE FROM study_records WHERE scope_key=? AND id=?', (self.scope.key, source['id']))
                    current = db.execute("SELECT data FROM study_scope_meta WHERE scope_key=? AND key='current'", (self.scope.key,)).fetchone()
                    if current and json.loads(current[0])['id'] == source['id']:
                        db.execute("UPDATE study_scope_meta SET data=? WHERE scope_key=? AND key='current'", (json.dumps(target, ensure_ascii=False), self.scope.key))
                    changed.append(target['id'])
                    continue
                if action == 'restore' and kind == 'course':
                    course = self.get(db, op['id'], 'course')
                    if not course.get('deleted_at'):
                        raise ValueError('Course is not removed')
                    snapshot_row = db.execute(
                        'SELECT snapshot_json FROM study_course_removals '
                        'WHERE scope_key=? AND course_id=? ORDER BY created_at DESC LIMIT 1',
                        (self.scope.key, course['id']),
                    ).fetchone()
                    snapshot = json.loads(snapshot_row['snapshot_json']) if snapshot_row else {}
                    course['deleted_at'] = None
                    self.put(db, 'course', course)
                    restored_modules = 0
                    for module in snapshot.get('modules', []):
                        if not isinstance(module, dict):
                            continue
                        module = dict(module)
                        module['deleted_at'] = None
                        self.put(db, 'module', module)
                        restored_modules += 1
                    restored_nodes = 0
                    for node_id, previous in (snapshot.get('nodes') or {}).items():
                        try:
                            node = self.get(db, node_id, 'node')
                        except ValueError:
                            continue
                        if not isinstance(previous, dict):
                            continue
                        node['course_ids'] = list(dict.fromkeys(list(node.get('course_ids') or []) + [course['id']]))
                        node['module_ids'] = list(dict.fromkeys(list(node.get('module_ids') or []) + list(previous.get('module_ids') or [])))
                        node['orphaned'] = False
                        self.put(db, 'node', node)
                        restored_nodes += 1
                    changed.extend([course['id'], *[str(module.get('id')) for module in snapshot.get('modules', []) if isinstance(module, dict) and module.get('id')]])
                    impacts.append({
                        'course_id': course['id'], 'action': 'restore',
                        'restored_module_count': restored_modules,
                        'restored_node_count': restored_nodes,
                    })
                    continue
                if action == 'restore':
                    if kind != 'node':
                        raise ValueError('Only nodes support restore')
                    item = self.get(db, op['id'], kind)
                    item['deleted_at'] = None
                    item['structure_revision'] = int(item.get('structure_revision', 1)) + 1
                    self.put(db, kind, item)
                    changed.append(item['id'])
                    continue
                if action in ('delete', 'remove'):
                    item = self.get(db, op['id'], kind)
                    if kind == 'course':
                        impact = self._remove_course(
                            db, item, confirm_history=bool(op.get('confirm_history') or p.get('confirm_history')),
                        )
                        changed.extend([item['id'], *impact['detached_node_ids']])
                        impacts.append(impact)
                        continue
                    if kind == 'module':
                        raise ValueError('Delete incorrect nodes/relations only; move contents before restructuring modules')
                    if kind == 'node' and self._has_history_reference(db, item['id']) and not (op.get('confirm_history') or p.get('confirm_history')):
                        raise ValueError('Node has historical exam/assessment references; confirm_history is required')
                    if kind == 'node':
                        item['deleted_at'] = 'soft-deleted'
                        item['structure_revision'] = int(item.get('structure_revision', 1)) + 1
                        self.put(db, kind, item)
                    else:
                        db.execute('DELETE FROM study_records WHERE scope_key=? AND id=?', (self.scope.key, item['id']))
                    if kind == 'node':
                        current = db.execute("SELECT data FROM study_scope_meta WHERE scope_key=? AND key='current'", (self.scope.key,)).fetchone()
                        if current and json.loads(current[0])['id'] == item['id']:
                            db.execute("DELETE FROM study_scope_meta WHERE scope_key=? AND key='current'", (self.scope.key,))
                    changed.append(item['id'])
                    continue
                if action not in ('create', 'update'):
                    raise ValueError('Unknown operation action')
                # Strict tool-schema adapters can materialize every optional
                # property as ``null`` even though the public schema only
                # permits the property's concrete type. Treat those values as
                # omitted so valid atomic batches survive provider adapters.
                data = {key: value for key, value in dict(op.get('data') or {}).items() if value is not None}
                if {'passed', 'mastery', 'assessment', 'evaluated', 'state_revision', 'structure_revision', 'deleted_at'} & data.keys():
                    raise ValueError('Use sign with evidence to change learning status')
                if action == 'update':
                    item = self.get(db, op['id'], kind)
                    if kind == 'node' and item.get('deleted_at'):
                        raise ValueError('Restore the deleted node before updating it')
                    for mapping_key in ('metadata', 'notes_by_course', 'content'):
                        incoming = data.get(mapping_key)
                        existing = item.get(mapping_key)
                        if isinstance(incoming, dict) and isinstance(existing, dict):
                            data[mapping_key] = {**existing, **incoming}
                    item.update({k: v for k, v in data.items() if k != 'id'})
                else:
                    item = {**data, 'id': op.get('id') or identifier()}
                    if db.execute('SELECT 1 FROM study_records WHERE scope_key=? AND id=?', (self.scope.key, item['id'])).fetchone():
                        raise ValueError('ID already exists; use update')
                    if kind == 'node':
                        item.update(passed=False, mastery=None, evaluated=False, assessment='unassessed',
                                    learnable=bool(item.get('learnable', True)), progress_role=item.get('progress_role', 'assessed'),
                                    structure_revision=1, state_revision=0, deleted_at=None)
                if kind != 'relation':
                    item['name'] = str(item.get('name', '')).strip()
                    if not item['name'] or len(item['name']) > 200:
                        raise ValueError('Name must contain 1–200 characters')
                    if len(str(item.get('description', ''))) > 4000:
                        raise ValueError('Keep knowledge descriptions under 4000 characters')
                    notes = item.get('notes', '')
                    if not isinstance(notes, str) or len(notes) > 300:
                        raise ValueError('Notes must be at most 300 characters')
                if kind in ('course', 'module'):
                    metadata = item.setdefault('metadata', {})
                    if not isinstance(metadata, dict) or len(json.dumps(metadata, ensure_ascii=False)) > 12000:
                        raise ValueError('Metadata must be a compact object')
                if kind == 'module':
                    self.get(db, item['course_id'], 'course')
                    parent = item.get('parent_id')
                    seen = {item['id']}
                    while parent:
                        if parent in seen:
                            raise ValueError('Module hierarchy cycle')
                        seen.add(parent)
                        ancestor = self.get(db, parent, 'module')
                        if ancestor['course_id'] != item['course_id']:
                            raise ValueError('Module parent must be in the same course')
                        parent = ancestor.get('parent_id')
                if kind == 'node':
                    if item.get('type') not in ('concept', 'theorem', 'method', 'skill', 'formula'):
                        raise ValueError('Invalid knowledge node type')
                    item.setdefault('module_ids', [])
                    item.setdefault('course_ids', [])
                    for mid in item['module_ids']:
                        cid = self.get(db, mid, 'module')['course_id']
                        if cid not in item['course_ids']:
                            item['course_ids'].append(cid)
                    if not item['course_ids'] and not item.get('orphaned'):
                        raise ValueError('Node requires at least one course')
                    item['orphaned'] = not bool(item['course_ids'])
                    for cid in item['course_ids']:
                        self.get(db, cid, 'course')
                    duplicate = next((n for n in self.rows(db, 'node') if n['id'] != item['id'] and n['name'].casefold() == item['name'].casefold() and n['type'] == item['type'] and n.get('sense', '') == item.get('sense', '')), None)
                    if duplicate:
                        raise ValueError(f"Existing knowledge node {duplicate['id']}; update module_ids or specify a distinct sense")
                    item.setdefault('sources', [])  # future document/PDF references, not a material system
                    content = item.setdefault('content', {})
                    if not isinstance(content, dict) or len(json.dumps(content, ensure_ascii=False)) > 16000:
                        raise ValueError('Node content must be a compact object')
                    notes_by_course = item.setdefault('notes_by_course', {})
                    if not isinstance(notes_by_course, dict) or any(
                        cid not in item['course_ids'] or not isinstance(note, str) or len(note) > 300
                        for cid, note in notes_by_course.items()
                    ):
                        raise ValueError('Per-course notes must belong to the node courses and be at most 300 characters')
                if kind == 'relation':
                    if len(str(item.get('description', ''))) > 1000:
                        raise ValueError('Keep relation descriptions under 1000 characters')
                    for key in ('source', 'target'):
                        self.get(db, item[key], 'node')
                    if item.get('type') == 'advanced':
                        item['type'] = 'advances'
                    if item['source'] == item['target'] or item.get('type') not in ('prerequisite', 'advances', 'contains', 'related'):
                        raise ValueError('Invalid relation')
                    if item['type'] == 'related' and item['source'] > item['target']:
                        item['source'], item['target'] = item['target'], item['source']
                    for r in self.rows(db, 'relation'):
                        if r['id'] != item['id'] and all(r[k] == item[k] for k in ('source', 'target', 'type')):
                            raise ValueError(f"Relation already exists: {r['id']}")
                    if item['type'] in ('prerequisite', 'contains', 'advances'):
                        directed = [r for r in self.rows(db, 'relation') if r['id'] != item['id'] and r['type'] == item['type']]
                        pending, visited = [item['target']], set()
                        while pending:
                            current = pending.pop()
                            if current == item['source']:
                                raise ValueError(f"{item['type']} cycle; use a related edge instead")
                            if current not in visited:
                                visited.add(current)
                                pending.extend(r['target'] for r in directed if r['source'] == current)
                self.put(db, kind, item)
                changed.append(item['id'])
            self.bump(db)
            result = {
                'revision': self.revision(db),
                'structure_revision': self.revision(db),
                'state_revision': self.state_revision(db),
                'changed': changed,
                'scope': self.scope.public(),
            }
            if impacts:
                result['impact'] = impacts[0] if len(impacts) == 1 else impacts
            if request_id:
                db.execute('INSERT INTO study_receipts VALUES(?,?,?,?,CURRENT_TIMESTAMP)', (self.scope.key, request_id, digest, json.dumps(result, ensure_ascii=False)))
            if changed:
                db.execute('INSERT INTO study_outbox(scope_key,id,kind,payload_json) VALUES(?,?,?,?)', (self.scope.key, identifier(), 'study.graph.changed', json.dumps(result, ensure_ascii=False)))
            return result

    @staticmethod
    def _search_text(value: Any) -> str:
        if value is None:
            return ''
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return ' '.join(StudyStore._search_text(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return ' '.join(StudyStore._search_text(item) for item in value)
        return str(value)

    @staticmethod
    def _search_snippet(text: str, query: str, width: int = 240) -> str:
        compact = ' '.join(text.split())
        if len(compact) <= width:
            return compact
        index = compact.casefold().find(query.casefold())
        if index < 0:
            return compact[:width].rstrip() + '…'
        start = max(0, index - width // 3)
        end = min(len(compact), start + width)
        prefix = '…' if start else ''
        suffix = '…' if end < len(compact) else ''
        return prefix + compact[start:end].strip() + suffix

    @classmethod
    def _note_search_text(cls, title: str, source: Any, blocks: list[Any]) -> str:
        """Return the searchable projection of one note.

        Notes are stored as a title, JSON source metadata, and ordered Markdown
        blocks.  Keeping this projection in one helper makes the list and
        global search paths agree about what a full-content note search means.
        """
        return ' '.join([
            str(title or ''),
            cls._search_text(source),
            ' '.join(str(block or '') for block in blocks),
        ])

    def search(self, p: dict) -> dict[str, Any]:
        """Search only entities owned by the current trusted Study scope.

        Session messages are owned by Core's SessionStore and are merged by
        the backend adapter.  This store handles graph nodes and durable notes,
        keeping the DB query and scope boundary in one place.
        """
        query = str(p.get('query') or '').strip()
        if not query:
            with self.db(write=False) as db:
                revision = self.revision(db)
            return {
                'results': [], 'total': 0,
                'structure_revision': revision,
                'scope': self.scope.public(),
            }
        if len(query) > 200:
            raise ValueError('Search query is too long')
        limit = min(50, max(1, int(p.get('limit', 20))))
        folded = query.casefold()
        results: list[dict[str, Any]] = []
        with self.db() as db:
            self._migrate_note_blocks(db)
            revision = self.revision(db)
            for node in sorted(self.rows(db, 'node'), key=lambda item: str(item.get('id', ''))):
                if node.get('deleted_at'):
                    continue
                searchable = ' '.join(
                    self._search_text(node.get(key))
                    for key in ('name', 'title', 'aliases', 'description', 'teaching_hint', 'content')
                )
                if folded not in searchable.casefold():
                    continue
                results.append({
                    'entity_type': 'node', 'kind': 'node',
                    'entity_id': node['id'], 'node_id': node['id'],
                    'title': str(node.get('name') or node.get('title') or node['id']),
                    'snippet': self._search_snippet(searchable, query),
                    'target': {'kind': 'node', 'id': node['id']},
                })

            note_rows = db.execute(
                'SELECT id,title,source_json,path FROM study_notes '
                'WHERE scope_key=? AND deleted_at IS NULL ORDER BY id',
                (self.scope.key,),
            ).fetchall()
            for row in note_rows:
                source = json.loads(row['source_json'])
                searchable = self._note_search_text(
                    str(row['title'] or ''),
                    source,
                    [self._document(row).content],
                )
                if folded not in searchable.casefold():
                    continue
                results.append({
                    'entity_type': 'note', 'kind': 'note',
                    'entity_id': row['id'], 'note_id': row['id'],
                    'title': str(row['title'] or row['id']),
                    'snippet': self._search_snippet(searchable, query),
                    'target': {'kind': 'note', 'id': row['id']},
                })

        return {
            'results': results[:limit],
            'total': len(results),
            'has_more': len(results) > limit,
            'structure_revision': revision,
            'scope': self.scope.public(),
        }

    def pins(
        self,
        p: dict,
        *,
        session_targets: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """List or mutate durable, scope-bound Study entity pins.

        The table stores only stable kind/id pairs.  Titles are projected at
        read time so a rename never invalidates a pin or leaves stale UI text.
        Session targets are supplied by the trusted Core SessionStore adapter;
        the request payload cannot manufacture one.
        """
        action = str(p.get('action') or 'list').strip().lower()
        if action not in ('list', 'add', 'remove'):
            raise ValueError('Unknown pin action')
        kind = str(p.get('entity_type') or p.get('kind') or '').strip().lower()
        entity_id = str(p.get('entity_id') or p.get('id') or '').strip()
        if action != 'list':
            if kind not in ('node', 'note', 'session'):
                raise ValueError('Invalid pin entity type')
            if not entity_id or len(entity_id) > 512 or any(ord(char) < 32 for char in entity_id):
                raise ValueError('Invalid pin entity id')

        session_targets = session_targets or {}
        with self.db(write=action in ('add', 'remove')) as db:
            if action == 'add':
                title = ''
                if kind == 'session':
                    target = session_targets.get(entity_id)
                    if target is None:
                        raise ValueError(f'Unknown Study session: {entity_id}')
                    title = str(target.get('title') or entity_id)
                elif kind == 'node':
                    target = self.get(db, entity_id, 'node')
                    if target.get('deleted_at'):
                        raise ValueError(f'Unknown node: {entity_id}')
                    title = str(target.get('name') or target.get('title') or entity_id)
                else:
                    target = db.execute(
                        'SELECT title FROM study_notes WHERE scope_key=? AND id=? AND deleted_at IS NULL',
                        (self.scope.key, entity_id),
                    ).fetchone()
                    if target is None:
                        raise ValueError(f'Unknown note: {entity_id}')
                    title = str(target['title'] or entity_id)
                db.execute(
                    'INSERT OR IGNORE INTO study_pins(scope_key,kind,entity_id) VALUES(?,?,?)',
                    (self.scope.key, kind, entity_id),
                )
            elif action == 'remove':
                db.execute(
                    'DELETE FROM study_pins WHERE scope_key=? AND kind=? AND entity_id=?',
                    (self.scope.key, kind, entity_id),
                )

            rows = db.execute(
                'SELECT kind,entity_id,created_at FROM study_pins '
                'WHERE scope_key=? ORDER BY created_at,kind,entity_id',
                (self.scope.key,),
            ).fetchall()
            pins: list[dict[str, Any]] = []
            for row in rows:
                row_kind, row_id = str(row['kind']), str(row['entity_id'])
                title = ''
                if row_kind == 'node':
                    target = self.get(db, row_id, 'node')
                    if target.get('deleted_at'):
                        continue
                    title = str(target.get('name') or target.get('title') or row_id)
                elif row_kind == 'note':
                    target = db.execute(
                        'SELECT title FROM study_notes WHERE scope_key=? AND id=? AND deleted_at IS NULL',
                        (self.scope.key, row_id),
                    ).fetchone()
                    if target is None:
                        continue
                    title = str(target['title'] or row_id)
                elif row_kind == 'session':
                    target = session_targets.get(row_id)
                    if target is None:
                        continue
                    title = str(target.get('title') or row_id)
                else:
                    continue
                pins.append({
                    'kind': row_kind, 'entity_type': row_kind,
                    'id': row_id, 'entity_id': row_id, 'title': title,
                    'created_at': row['created_at'],
                })
            return {
                'pins': pins,
                'scope': self.scope.public(),
                'structure_revision': self.revision(db),
            }

    def _has_history_reference(self, db, node_id: str) -> bool:
        for kind in ('exam', 'assessment'):
            for item in self.rows(db, kind):
                if node_id in item.get('node_ids', []) or item.get('node_id') == node_id:
                    return True
                if any(node_id in q.get('node_ids', []) for q in item.get('questions', [])):
                    return True
        return False

    def _remove_course(self, db, course: dict, *, confirm_history: bool) -> dict[str, Any]:
        """Detach a course while retaining shared knowledge and evidence.

        The membership snapshot is an audit/recovery record.  No node,
        session binding, note, exam, or assessment record is physically
        deleted.  Nodes left with no remaining course are retained as
        ``orphaned`` knowledge so historical references stay resolvable.
        """
        if course.get('deleted_at'):
            raise ValueError('Course is already removed')
        course_id = str(course['id'])
        modules = [
            module for module in self.rows(db, 'module')
            if module.get('course_id') == course_id
        ]
        module_ids = {str(module['id']) for module in modules}
        nodes = [
            node for node in self.rows(db, 'node')
            if course_id in (node.get('course_ids') or []) and not node.get('deleted_at')
        ]
        historical_node_ids = [node['id'] for node in nodes if self._has_history_reference(db, node['id'])]
        if historical_node_ids and not confirm_history:
            raise ValueError('Course removal has historical references; confirm_history is required')

        snapshot = {
            'course': dict(course),
            'modules': [dict(module) for module in modules],
            'nodes': {
                str(node['id']): {
                    'course_ids': list(node.get('course_ids') or []),
                    'module_ids': list(node.get('module_ids') or []),
                }
                for node in nodes
            },
        }
        db.execute(
            'INSERT INTO study_course_removals(scope_key,id,course_id,snapshot_json) VALUES(?,?,?,?)',
            (self.scope.key, identifier(), course_id, json.dumps(snapshot, ensure_ascii=False)),
        )

        course['deleted_at'] = 'soft-deleted'
        self.put(db, 'course', course)
        for module in modules:
            module['deleted_at'] = 'soft-deleted'
            self.put(db, 'module', module)

        detached_node_ids: list[str] = []
        orphaned_node_ids: list[str] = []
        for node in nodes:
            node['course_ids'] = [value for value in node.get('course_ids', []) if value != course_id]
            node['module_ids'] = [value for value in node.get('module_ids', []) if value not in module_ids]
            node['orphaned'] = not bool(node['course_ids'])
            node['structure_revision'] = int(node.get('structure_revision', 1)) + 1
            self.put(db, 'node', node)
            detached_node_ids.append(str(node['id']))
            if node['orphaned']:
                orphaned_node_ids.append(str(node['id']))

        binding_count = db.execute(
            'SELECT COUNT(*) FROM study_session_bindings WHERE scope_key=? AND kind=\'node\' AND node_id IN (%s)'
            % (','.join('?' for _ in detached_node_ids) or "''"),
            (self.scope.key, *detached_node_ids),
        ).fetchone()[0] if detached_node_ids else 0
        return {
            'course_id': course_id,
            'action': 'remove',
            'detached_node_ids': detached_node_ids,
            'orphaned_node_ids': orphaned_node_ids,
            'detached_module_ids': sorted(module_ids),
            'historical_node_ids': historical_node_ids,
            'preserved_session_binding_count': int(binding_count),
            'preserved_shared_knowledge': True,
        }

    def state(self, key: str, value: Any = None, *, write=False) -> Any:
        with self.db(write=write) as db:
            if write:
                db.execute('INSERT OR REPLACE INTO study_scope_meta VALUES(?,?,?)', (self.scope.key, key, json.dumps(value, ensure_ascii=False)))
            row = db.execute('SELECT data FROM study_scope_meta WHERE scope_key=? AND key=?', (self.scope.key, key)).fetchone()
            return json.loads(row[0]) if row else None

    def sign(self, p: dict) -> dict:
        updates = p.get('updates', [])
        if not isinstance(updates, list) or not 1 <= len(updates) <= 100:
            raise ValueError('Provide 1–100 node assessments')
        exam_id = str(p.get('exam_id') or '').strip()
        if not exam_id:
            raise ValueError('Exam-backed assessment requires exam_id')
        grading_version = p.get('grading_version')
        if type(grading_version) is not int:
            raise ValueError('Exam-backed assessment requires the current grading_version')

        with self.db() as db:
            exam = self.get(db, exam_id, 'exam')
            if exam.get('status') != 'graded':
                raise ValueError('Exam has not been graded')
            if grading_version != exam.get('grading_version'):
                raise ValueError('Exam-backed assessment requires the current grading_version')

            raw_suggestions = exam.get('suggestions')
            raw_results = exam.get('results')
            if not isinstance(raw_suggestions, list) or not raw_suggestions:
                raise ValueError('The graded exam has no signable evidence')
            if not isinstance(raw_results, list) or not raw_results:
                raise ValueError('The graded exam has no saved question evidence')

            def resolve_alias(node_id: str) -> str:
                resolved = node_id
                seen: set[str] = set()
                while resolved not in seen:
                    seen.add(resolved)
                    alias = db.execute(
                        'SELECT data FROM study_scope_meta WHERE scope_key=? AND key=?',
                        (self.scope.key, 'alias:' + resolved),
                    ).fetchone()
                    if not alias:
                        break
                    resolved = str(json.loads(alias[0]))
                return resolved

            results: dict[str, dict] = {}
            for result in raw_results:
                if not isinstance(result, dict):
                    raise ValueError('Saved exam evidence is invalid')
                question_id = str(result.get('question_id') or '').strip()
                if not question_id or question_id in results:
                    raise ValueError('Saved exam evidence has duplicate question ids')
                results[question_id] = result

            suggestions: dict[str, dict] = {}
            for suggestion in raw_suggestions:
                if not isinstance(suggestion, dict):
                    raise ValueError('Saved exam suggestion is invalid')
                suggestion_node_id = str(suggestion.get('node_id') or '').strip()
                if not suggestion_node_id or suggestion_node_id in suggestions:
                    raise ValueError('Saved exam suggestions have duplicate node ids')
                suggestions[suggestion_node_id] = suggestion

            allowed_update_keys = {
                'node_id', 'passed', 'mastery', 'reason', 'question_ids', 'grading_version',
            }
            uncertain_questions = exam.get('uncertain')
            if not isinstance(uncertain_questions, dict):
                uncertain_questions = {}
            validated: list[dict] = []
            seen_nodes: set[str] = set()
            for raw_update in updates:
                if not isinstance(raw_update, dict):
                    raise ValueError('Each assessment must be an object')
                if set(raw_update) - allowed_update_keys:
                    raise ValueError('Caller-provided evidence fields are not accepted')
                raw_node_id = raw_update.get('node_id')
                if not isinstance(raw_node_id, str) or not raw_node_id.strip():
                    raise ValueError('Each assessment requires a scoped node_id')
                raw_node_id = raw_node_id.strip()
                resolved_node_id = resolve_alias(raw_node_id)
                if resolved_node_id in seen_nodes:
                    raise ValueError('Each node may be assessed only once per sign request')
                seen_nodes.add(resolved_node_id)

                passed = raw_update.get('passed')
                mastery = raw_update.get('mastery')
                reason = raw_update.get('reason')
                if (
                    type(passed) is not bool
                    or (mastery not in ('low', 'medium', 'high') if passed else mastery is not None)
                    or not isinstance(reason, str)
                    or not reason.strip()
                ):
                    raise ValueError('Assessment requires passed, mastery and explicit reason')
                if 'grading_version' in raw_update and raw_update['grading_version'] != grading_version:
                    raise ValueError('Assessment grading_version does not match the exam')

                question_ids = raw_update.get('question_ids')
                if (
                    not isinstance(question_ids, list)
                    or not question_ids
                    or any(not isinstance(question_id, str) or not question_id.strip() for question_id in question_ids)
                ):
                    raise ValueError('Exam-backed assessment requires exact supporting question_ids')
                question_ids = [question_id.strip() for question_id in question_ids]
                if len(set(question_ids)) != len(question_ids):
                    raise ValueError('Exam-backed assessment requires exact supporting question_ids')

                suggestion = suggestions.get(raw_node_id)
                if suggestion is None:
                    resolved_matches = [
                        candidate for candidate in suggestions.values()
                        if resolve_alias(str(candidate.get('node_id') or '').strip()) == resolved_node_id
                    ]
                    if len(resolved_matches) != 1:
                        raise ValueError('Assessment must match the graded exam suggestion')
                    suggestion = resolved_matches[0]
                suggestion_node_id = str(suggestion.get('node_id') or '').strip()
                expected_question_ids = suggestion.get('question_ids')
                if (
                    not isinstance(expected_question_ids, list)
                    or not expected_question_ids
                    or any(not isinstance(question_id, str) or not question_id.strip() for question_id in expected_question_ids)
                ):
                    raise ValueError('Saved exam suggestion has invalid question evidence')
                expected_question_ids = [question_id.strip() for question_id in expected_question_ids]
                if len(set(expected_question_ids)) != len(expected_question_ids) or set(question_ids) != set(expected_question_ids):
                    raise ValueError('Exam-backed assessment requires exact supporting question_ids')
                if (
                    suggestion.get('grading_version') != grading_version
                    or suggestion.get('passed') != passed
                    or suggestion.get('mastery') != mastery
                    or str(suggestion.get('reason') or '').strip() != reason.strip()
                ):
                    raise ValueError('Conflicting retry: assessment must match the graded exam suggestion')

                evidence_node_ids = {raw_node_id, suggestion_node_id, resolved_node_id}
                for question_id in expected_question_ids:
                    result = results.get(question_id)
                    if result is None:
                        raise ValueError('Question evidence does not belong to the graded exam')
                    if result.get('state') not in ('correct', 'partial', 'incorrect'):
                        raise ValueError('Uncertain or unreadable question evidence cannot be signed')
                    if type(result.get('correct')) is not bool or result['correct'] != (result['state'] == 'correct'):
                        raise ValueError('Saved exam evidence has an invalid correctness state')
                    if result.get('helped') is not False or question_id in uncertain_questions:
                        raise ValueError('Helped or uncertain question evidence cannot be signed')
                    assessed_node_ids = result.get('assessed_node_ids')
                    incorrect_node_ids = result.get('incorrect_node_ids')
                    question_node_ids = result.get('node_ids')
                    if (
                        not isinstance(assessed_node_ids, list)
                        or not isinstance(incorrect_node_ids, list)
                        or not isinstance(question_node_ids, list)
                        or any(not isinstance(node_id, str) or not node_id.strip() for node_id in assessed_node_ids)
                        or any(not isinstance(node_id, str) or not node_id.strip() for node_id in incorrect_node_ids)
                        or any(not isinstance(node_id, str) or not node_id.strip() for node_id in question_node_ids)
                    ):
                        raise ValueError('Saved exam evidence has invalid node ids')
                    assessed_node_ids = {node_id.strip() for node_id in assessed_node_ids}
                    incorrect_node_ids = {node_id.strip() for node_id in incorrect_node_ids}
                    question_node_ids = {node_id.strip() for node_id in question_node_ids}
                    if not evidence_node_ids.intersection(assessed_node_ids) or not evidence_node_ids.intersection(question_node_ids):
                        raise ValueError('Question evidence does not assess this node')
                    if not assessed_node_ids <= question_node_ids:
                        raise ValueError('Saved exam evidence has invalid assessed node ids')
                    if not incorrect_node_ids <= assessed_node_ids:
                        raise ValueError('Saved exam evidence has invalid incorrect node ids')
                    if result['state'] == 'correct' and incorrect_node_ids:
                        raise ValueError('Saved exam evidence is inconsistent with a correct result')

                node = self.get(db, resolved_node_id, 'node')
                if node.get('deleted_at'):
                    raise ValueError('Cannot assess a deleted node')
                validated.append({
                    'node_id': resolved_node_id,
                    'passed': passed,
                    'mastery': mastery if passed else None,
                    'reason': reason.strip(),
                    'question_ids': expected_question_ids,
                    'grading_version': grading_version,
                })

            canonical_updates = sorted(validated, key=lambda update: update['node_id'])
            canonical_payload = {
                'exam_id': exam_id,
                'grading_version': grading_version,
                'updates': canonical_updates,
            }
            encoded_payload = json.dumps(
                canonical_payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
            ).encode('utf-8')
            request_hash = hashlib.sha256(encoded_payload).hexdigest()
            receipt = db.execute(
                'SELECT payload_hash,result_json FROM study_sign_receipts WHERE scope_key=? AND request_hash=?',
                (self.scope.key, request_hash),
            ).fetchone()
            if receipt:
                if receipt['payload_hash'] != request_hash:
                    raise ValueError('IDEMPOTENCY_CONFLICT')
                return json.loads(receipt['result_json'])

            plans: list[tuple[dict, dict | None, str]] = []
            for update in canonical_updates:
                assessment_id = f"assessment:{exam_id}:{update['node_id']}"
                try:
                    previous = self.get(db, assessment_id, 'assessment')
                except ValueError:
                    previous = None
                if previous and previous.get('grading_version') == grading_version:
                    comparable = {
                        'node_id': update['node_id'],
                        'passed': update['passed'],
                        'mastery': update['mastery'],
                        'reason': update['reason'],
                        'exam_id': exam_id,
                        'grading_version': grading_version,
                        'question_ids': update['question_ids'],
                    }
                    if not all(previous.get(key) == value for key, value in comparable.items()):
                        raise ValueError('Conflicting retry for the same exam grading version')
                    plans.append((update, previous, assessment_id))
                    continue
                plans.append((update, previous, assessment_id))

            changed = 0
            for update, previous, assessment_id in plans:
                if previous and previous.get('grading_version') == grading_version:
                    continue
                node = self.get(db, update['node_id'], 'node')
                if node.get('deleted_at'):
                    raise ValueError('Cannot assess a deleted node')
                node.update(
                    passed=update['passed'], mastery=update['mastery'],
                    assessment='pass' if update['passed'] else 'fail', evaluated=True,
                    state_revision=int(node.get('state_revision', 0)) + 1,
                )
                self.put(db, 'node', node)
                history = list(previous.get('history', [])) if previous else []
                if previous:
                    history.append({key: value for key, value in previous.items() if key not in ('id', 'history')})
                record = {
                    'id': assessment_id, **update, 'exam_id': exam_id,
                    'history': history,
                }
                self.put(db, 'assessment', record)
                changed += 1
            if changed:
                self.bump(db, state=True)
                db.execute('INSERT INTO study_outbox(scope_key,id,kind,payload_json) VALUES(?,?,?,?)',
                           (self.scope.key, identifier(), 'study.mastery.changed', json.dumps({'exam_id': exam_id, 'updated': changed})))
            state_row = db.execute("SELECT data FROM study_scope_meta WHERE scope_key=? AND key='state_revision'", (self.scope.key,)).fetchone()
            result = {
                'updated': changed, 'revision': self.revision(db),
                'state_revision': int(state_row[0]) if state_row else 0,
                # The response is a durable operation receipt.  Mark the
                # operation idempotent on the first call as well so an exact
                # retry can return this byte-for-byte result without
                # inventing a second response shape.
                'idempotent': True, 'scope': self.scope.public(),
            }
            db.execute(
                'INSERT INTO study_sign_receipts(scope_key,request_hash,payload_hash,result_json) VALUES(?,?,?,?)',
                (self.scope.key, request_hash, request_hash, json.dumps(result, ensure_ascii=False)),
            )
            return result

    def ensure_binding(self, kind: str, session_id: str, *, node_id: str | None = None,
                       replace_primary: bool = False) -> dict[str, Any]:
        if kind not in ('map', 'notes', 'node') or (kind == 'node') != bool(node_id):
            raise ValueError('Invalid Study session binding')
        session_id = str(session_id or '').strip()
        if not session_id or len(session_id) > 512 or any(ord(char) < 32 for char in session_id):
            raise ValueError('Invalid Study session id')
        if node_id is not None:
            node_id = str(node_id)
            if not node_id or len(node_id) > 512 or any(ord(char) < 32 for char in node_id):
                raise ValueError('Invalid Study node id')
        subject = node_id or ''
        with self.db() as db:
            current = db.execute('SELECT * FROM study_session_bindings WHERE scope_key=? AND kind=? AND node_id=? AND is_primary=1',
                                 (self.scope.key, kind, subject)).fetchone()
            existing_session = db.execute(
                'SELECT * FROM study_session_bindings WHERE scope_key=? AND session_id=?',
                (self.scope.key, session_id),
            ).fetchone()
            if existing_session and (not current or existing_session['id'] != current['id']):
                raise ValueError('Study session is already bound to another resource')
            if current and not replace_primary:
                return {**dict(current), 'created': False}
            if current and current['session_id'] == session_id:
                return {**dict(current), 'created': False}
            if current:
                db.execute('UPDATE study_session_bindings SET is_primary=0,replaced_at=CURRENT_TIMESTAMP WHERE scope_key=? AND id=?',
                           (self.scope.key, current['id']))
            binding_id = identifier()
            db.execute('INSERT INTO study_session_bindings(scope_key,id,kind,node_id,session_id,is_primary) VALUES(?,?,?,?,?,1)',
                       (self.scope.key, binding_id, kind, subject, session_id))
            return {'id': binding_id, 'kind': kind, 'node_id': node_id, 'session_id': session_id,
                    'is_primary': 1, 'created': True, 'scope': self.scope.public()}

    def primary_binding(self, kind: str, node_id: str | None = None) -> dict[str, Any] | None:
        with self.db(write=False) as db:
            row = db.execute('SELECT * FROM study_session_bindings WHERE scope_key=? AND kind=? AND node_id=? AND is_primary=1',
                             (self.scope.key, kind, node_id or '')).fetchone()
            return dict(row) if row else None

    def outbox(self, *, mark_delivered: list[str] | None = None, limit: int = 50) -> dict[str, Any]:
        with self.db(write=bool(mark_delivered)) as db:
            for event_id in mark_delivered or []:
                db.execute('UPDATE study_outbox SET delivered_at=CURRENT_TIMESTAMP WHERE scope_key=? AND id=?', (self.scope.key, event_id))
            rows = db.execute('SELECT id,kind,payload_json,created_at FROM study_outbox WHERE scope_key=? AND delivered_at IS NULL ORDER BY created_at,id LIMIT ?',
                              (self.scope.key, min(100, max(1, limit)))).fetchall()
            return {'events': [{'id': r['id'], 'kind': r['kind'], 'payload': json.loads(r['payload_json']), 'created_at': r['created_at']} for r in rows]}

    @staticmethod
    def _parse_wikilinks(markdown: str) -> list[dict[str, str]]:
        """Extract links outside Markdown fenced and inline code spans."""
        links: list[dict[str, str]] = []
        fence_char = ''
        fence_length = 0
        for line in markdown.splitlines():
            stripped = line.lstrip(' \t')
            indent = len(line) - len(stripped)
            fence = re.match(r'(`{3,}|~{3,})', stripped) if indent <= 3 else None
            if fence_char:
                if (
                    fence and fence.group(1)[0] == fence_char
                    and len(fence.group(1)) >= fence_length
                    and stripped[fence.end():].strip() == ''
                ):
                    fence_char = ''
                    fence_length = 0
                continue
            if fence:
                fence_char = fence.group(1)[0]
                fence_length = len(fence.group(1))
                continue
            # CommonMark treats a top-level line indented by four spaces or
            # one tab as code. Keep wikilink-looking examples literal there.
            if re.match(r'^(?: {4}| {0,3}\t)', line):
                continue

            # Backtick code spans may contain any number of backticks; only a
            # closing run of the same length ends the span.
            visible: list[str] = []
            index = 0
            while index < len(line):
                if line[index] != '`':
                    visible.append(line[index])
                    index += 1
                    continue
                end = index + 1
                while end < len(line) and line[end] == '`':
                    end += 1
                marker = line[index:end]
                close = line.find(marker, end)
                if close < 0:
                    visible.append(marker)
                    index = end
                    continue
                visible.append(' ' * (close + len(marker) - index))
                index = close + len(marker)

            for match in WIKILINK_RE.finditer(''.join(visible)):
                expression = match.group(1).strip()
                target, separator, label = expression.partition('|')
                target = target.strip()
                if not target:
                    continue
                label = label.strip() if separator else target
                links.append({'target': target, 'label': label or target})
        return links

    def _note_link_index(self, db) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
        """Build scoped note link and backlink views from the current rows.

        Links are deliberately derived on reads.  This keeps SQLite as the
        only write source and means edits to a block are visible immediately,
        without a link table that could drift from note Markdown.
        """
        note_rows = db.execute(
            'SELECT id,title FROM study_notes WHERE scope_key=? AND deleted_at IS NULL ORDER BY rowid',
            (self.scope.key,),
        ).fetchall()
        notes_by_id = {str(row['id']): row for row in note_rows}
        notes_by_title: dict[str, list[sqlite3.Row]] = {}
        notes_by_folded_title: dict[str, list[sqlite3.Row]] = {}
        for row in note_rows:
            title = str(row['title'])
            notes_by_title.setdefault(title, []).append(row)
            notes_by_folded_title.setdefault(title.casefold(), []).append(row)

        nodes_by_id: dict[str, dict[str, Any]] = {}
        nodes_by_title: dict[str, list[dict[str, Any]]] = {}
        nodes_by_folded_title: dict[str, list[dict[str, Any]]] = {}
        node_rows = db.execute(
            "SELECT id,data FROM study_records WHERE scope_key=? AND kind='node' ORDER BY rowid",
            (self.scope.key,),
        ).fetchall()
        for row in node_rows:
            node = self._defaults('node', json.loads(row['data']))
            if node.get('deleted_at'):
                continue
            node_id = str(node.get('id') or row['id'])
            node_title = str(node.get('title') or node.get('name') or '').strip()
            nodes_by_id[node_id] = node
            if node_title:
                nodes_by_title.setdefault(node_title, []).append(node)
                nodes_by_folded_title.setdefault(node_title.casefold(), []).append(node)

        def title_match(
            target: str,
            exact: dict[str, list[Any]],
            folded: dict[str, list[Any]],
        ) -> tuple[Any | None, bool, list[Any]]:
            """Resolve a title only when it identifies one scoped entity.

            Exact IDs are handled before this helper.  Exact title matches win
            over case-folded matches, while duplicate titles remain unresolved
            instead of silently linking to the first row.
            """
            candidates = exact.get(target)
            if candidates is None:
                candidates = folded.get(target.casefold(), [])
            if len(candidates) == 1:
                return candidates[0], False, candidates
            return None, bool(candidates), candidates

        links_by_note: dict[str, list[dict[str, Any]]] = {str(row['id']): [] for row in note_rows}
        block_rows = db.execute(
            'SELECT note_id,position,id,content FROM study_note_blocks WHERE scope_key=? ORDER BY note_id,position,id',
            (self.scope.key,),
        ).fetchall()
        for block in block_rows:
            note_id = str(block['note_id'])
            if note_id not in links_by_note:
                continue
            for raw_link in self._parse_wikilinks(str(block['content'] or '')):
                target = raw_link['target']
                explicit_kind = ''
                explicit_id = target
                prefix, separator, remainder = target.partition(':')
                if separator and prefix.casefold() in ('note', 'node'):
                    explicit_kind = prefix.casefold()
                    explicit_id = remainder.strip()
                    if not explicit_id:
                        links_by_note[note_id].append({
                            **raw_link, 'kind': 'unresolved', 'reference_kind': explicit_kind,
                        })
                        continue
                if explicit_kind == 'note':
                    note = notes_by_id.get(explicit_id)
                    if note is None:
                        links_by_note[note_id].append({
                            **raw_link, 'kind': 'unresolved', 'reference_kind': 'note',
                        })
                    else:
                        links_by_note[note_id].append({
                            **raw_link, 'kind': 'note', 'reference_kind': 'note',
                            'id': str(note['id']), 'title': str(note['title']),
                        })
                    continue
                if explicit_kind == 'node':
                    node = nodes_by_id.get(explicit_id)
                    if node is None:
                        links_by_note[note_id].append({
                            **raw_link, 'kind': 'unresolved', 'reference_kind': 'node',
                        })
                    else:
                        node_title = str(node.get('title') or node.get('name') or explicit_id)
                        links_by_note[note_id].append({
                            **raw_link, 'kind': 'node', 'reference_kind': 'node',
                            'id': explicit_id, 'title': node_title,
                        })
                    continue
                note = notes_by_id.get(target)
                if note is not None:
                    links_by_note[note_id].append({
                        **raw_link, 'kind': 'note',
                        'id': str(note['id']), 'title': str(note['title']),
                    })
                    continue
                note, note_ambiguous, note_candidates = title_match(
                    target, notes_by_title, notes_by_folded_title,
                )
                if note_ambiguous:
                    links_by_note[note_id].append({
                        **raw_link, 'kind': 'unresolved',
                        'candidates': [str(item['id']) for item in note_candidates],
                    })
                    continue
                if note is not None:
                    links_by_note[note_id].append({
                        **raw_link, 'kind': 'note',
                        'id': str(note['id']), 'title': str(note['title']),
                    })
                    continue
                node = nodes_by_id.get(target)
                if node is not None:
                    node_id = str(node.get('id') or '')
                    node_title = str(node.get('title') or node.get('name') or node_id)
                    links_by_note[note_id].append({
                        **raw_link, 'kind': 'node',
                        'id': node_id, 'title': node_title,
                    })
                    continue
                node, node_ambiguous, node_candidates = title_match(
                    target, nodes_by_title, nodes_by_folded_title,
                )
                if node_ambiguous:
                    links_by_note[note_id].append({
                        **raw_link, 'kind': 'unresolved',
                        'candidates': [str(item.get('id') or '') for item in node_candidates],
                    })
                    continue
                if node is not None:
                    node_id = str(node.get('id') or '')
                    node_title = str(node.get('title') or node.get('name') or node_id)
                    links_by_note[note_id].append({
                        **raw_link, 'kind': 'node',
                        'id': node_id, 'title': node_title,
                    })
                    continue
                links_by_note[note_id].append({**raw_link, 'kind': 'unresolved'})

        backlinks_by_note: dict[str, list[dict[str, Any]]] = {str(row['id']): [] for row in note_rows}
        for source in note_rows:
            source_id = str(source['id'])
            for link in links_by_note[source_id]:
                if link.get('kind') != 'note' or link.get('id') not in backlinks_by_note:
                    continue
                backlinks_by_note[link['id']].append({
                    'note_id': source_id,
                    'title': str(source['title']),
                    'target': link['target'],
                    'label': link['label'],
                })
        return links_by_note, backlinks_by_note

    def _node_labels(self, db, node_ids: list[str]) -> dict[str, str]:
        """Resolve stable note source ids to current scoped node names."""
        ids = list(dict.fromkeys(str(node_id).strip() for node_id in node_ids if str(node_id).strip()))
        if not ids:
            return {}
        rows = db.execute(
            "SELECT id,data FROM study_records WHERE scope_key=? AND kind='node' "
            f"AND id IN ({','.join('?' for _ in ids)})",
            (self.scope.key, *ids),
        ).fetchall()
        labels: dict[str, str] = {}
        for row in rows:
            node = self._defaults('node', json.loads(row['data']))
            if node.get('deleted_at'):
                continue
            node_id = str(node.get('id') or row['id'])
            labels[node_id] = str(node.get('name') or node.get('title') or node_id)
        return labels

    def _curation_tasks(self, p: dict) -> dict[str, Any]:
        """Compatibility state machine for resumable note-curation jobs.

        This intentionally contains no Note/NoteBlock reads or writes. Legacy
        block rows are consumed exclusively by the one-way vault migration.
        """
        action = str(p.get('action') or '')
        allowed = {
            'curate_start', 'curate_resume', 'curate_cancel', 'curate_checkpoint',
            'task_create', 'task_checkpoint', 'task_cancel', 'task_resume', 'task_get',
        }
        if action not in allowed:
            raise ValueError('Unknown curation task action')
        with self.db(write=action != 'task_get') as db:
            if action == 'curate_start':
                active = db.execute(
                    "SELECT * FROM study_curation_tasks WHERE scope_key=? "
                    "AND state IN ('pending','running') ORDER BY rowid DESC LIMIT 1",
                    (self.scope.key,),
                ).fetchone()
                if active:
                    return {
                        'task_id': active['id'], 'state': active['state'],
                        'checkpoint': json.loads(active['checkpoint_json']),
                        'cancel_requested': bool(active['cancel_requested']),
                        'revision': active['revision'], 'created': False,
                    }
                task_id = str(p.get('task_id') or identifier())
                checkpoint = p.get('checkpoint') if isinstance(p.get('checkpoint'), dict) else {}
                db.execute(
                    'INSERT INTO study_curation_tasks VALUES(?,?,?,?,0,1)',
                    (self.scope.key, task_id, 'running', json.dumps(checkpoint, ensure_ascii=False)),
                )
                return {'task_id': task_id, 'state': 'running', 'checkpoint': checkpoint,
                        'cancel_requested': False, 'revision': 1, 'created': True}
            if action in ('curate_resume', 'curate_cancel', 'curate_checkpoint'):
                task_id = str(p.get('task_id') or '').strip()
                row = db.execute(
                    'SELECT * FROM study_curation_tasks WHERE scope_key=? AND id=?',
                    (self.scope.key, task_id),
                ).fetchone() if task_id else db.execute(
                    "SELECT * FROM study_curation_tasks WHERE scope_key=? "
                    "AND state IN ('pending','running','cancelled') ORDER BY rowid DESC LIMIT 1",
                    (self.scope.key,),
                ).fetchone()
                if not row:
                    raise ValueError('Unknown curation task')
                if p.get('expected_revision', row['revision']) != row['revision']:
                    raise ValueError('REVISION_CONFLICT')
                if action == 'curate_cancel':
                    state, cancel = 'cancelled', 1
                elif action == 'curate_resume':
                    state, cancel = 'running', 0
                else:
                    state, cancel = str(p.get('state') or 'running'), row['cancel_requested']
                    if state not in ('pending', 'running', 'completed', 'cancelled', 'failed'):
                        raise ValueError('Invalid curation task state')
                checkpoint = p.get('checkpoint', json.loads(row['checkpoint_json']))
                if not isinstance(checkpoint, dict):
                    raise ValueError('Curation checkpoint must be an object')
                db.execute(
                    'UPDATE study_curation_tasks SET state=?,checkpoint_json=?,cancel_requested=?,'
                    'revision=revision+1 WHERE scope_key=? AND id=?',
                    (state, json.dumps(checkpoint, ensure_ascii=False), cancel, self.scope.key, row['id']),
                )
                return {'task_id': row['id'], 'state': state, 'checkpoint': checkpoint,
                        'cancel_requested': bool(cancel), 'revision': row['revision'] + 1}
            if action == 'task_create':
                task_id = str(p.get('task_id') or identifier())
                checkpoint = p.get('checkpoint') or {}
                if not isinstance(checkpoint, dict):
                    raise ValueError('Curation checkpoint must be an object')
                db.execute(
                    'INSERT INTO study_curation_tasks VALUES(?,?,?,?,0,1)',
                    (self.scope.key, task_id, 'pending', json.dumps(checkpoint, ensure_ascii=False)),
                )
                return {'task_id': task_id, 'state': 'pending', 'revision': 1}
            if action in ('task_checkpoint', 'task_cancel', 'task_resume'):
                task_id = str(p.get('task_id') or '')
                row = db.execute(
                    'SELECT * FROM study_curation_tasks WHERE scope_key=? AND id=?',
                    (self.scope.key, task_id),
                ).fetchone()
                if not row:
                    raise ValueError('Unknown curation task')
                if p.get('expected_revision') != row['revision']:
                    raise ValueError('REVISION_CONFLICT')
                if action == 'task_cancel':
                    state, cancel = 'cancelled', 1
                elif action == 'task_resume':
                    state, cancel = 'pending', 0
                else:
                    state, cancel = str(p.get('state') or 'running'), row['cancel_requested']
                checkpoint = p.get('checkpoint', json.loads(row['checkpoint_json']))
                if not isinstance(checkpoint, dict):
                    raise ValueError('Curation checkpoint must be an object')
                db.execute(
                    'UPDATE study_curation_tasks SET state=?,checkpoint_json=?,cancel_requested=?,'
                    'revision=revision+1 WHERE scope_key=? AND id=?',
                    (state, json.dumps(checkpoint, ensure_ascii=False), cancel, self.scope.key, task_id),
                )
                return {'task_id': task_id, 'state': state, 'checkpoint': checkpoint,
                        'cancel_requested': bool(cancel), 'revision': row['revision'] + 1}
            row = db.execute(
                'SELECT * FROM study_curation_tasks WHERE scope_key=? AND id=?',
                (self.scope.key, str(p.get('task_id') or '')),
            ).fetchone()
            if not row:
                raise ValueError('Unknown curation task')
            return {**dict(row), 'checkpoint': json.loads(row['checkpoint_json']),
                    'cancel_requested': bool(row['cancel_requested'])}
    # --- Three-layer note architecture ---------------------------------

    @staticmethod
    def _note_metadata(row: sqlite3.Row, resource_ids: list[str]) -> dict[str, Any]:
        return {
            'id': str(row['id']), 'title': str(row['title']),
            'parent_id': str(row['parent_id'] or '') or None,
            'resource_ids': resource_ids, 'revision': int(row['revision']),
        }

    @staticmethod
    def _changed_intervals(old: str, new: str) -> list[tuple[int, int]]:
        intervals: list[tuple[int, int]] = []
        for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
            if tag == 'equal':
                continue
            # Insertions occupy a zero-width point. Represent them as one code
            # point when possible so an insertion inside a lock is rejected.
            intervals.append((i1, i2 if i2 > i1 else i1))
        return intervals

    @staticmethod
    def _utf16_len(value: str) -> int:
        return len(value.encode('utf-16-le')) // 2

    @staticmethod
    def _cp_to_utf16(value: str, offset: int) -> int:
        return len(value[:offset].encode('utf-16-le')) // 2

    @staticmethod
    def _utf16_to_cp(value: str, offset: int) -> int:
        if offset < 0:
            raise StudyNoteError('INVALID_NOTE_RANGE', unit='utf16_code_unit')
        units = 0
        for index, char in enumerate(value):
            if units == offset:
                return index
            units += 2 if ord(char) > 0xFFFF else 1
            if units > offset:
                raise StudyNoteError('INVALID_NOTE_RANGE', 'Range splits a UTF-16 surrogate pair', unit='utf16_code_unit')
        if units == offset:
            return len(value)
        raise StudyNoteError('INVALID_NOTE_RANGE', unit='utf16_code_unit')

    @staticmethod
    def _lock_overlaps(start: int, end: int, changes: list[tuple[int, int]]) -> bool:
        for changed_start, changed_end in changes:
            if changed_start == changed_end:
                if start < changed_start < end:
                    return True
            elif max(start, changed_start) < min(end, changed_end):
                return True
        return False

    @staticmethod
    def _map_offset(opcodes: list[tuple[str, int, int, int, int]], offset: int, *, end: bool) -> int:
        for tag, i1, i2, j1, j2 in opcodes:
            if offset < i1:
                return j1
            if i1 <= offset <= i2:
                if tag == 'equal':
                    return j1 + (offset - i1)
                return j2 if end else j1
        return opcodes[-1][4] if opcodes else offset

    def _note_resource_ids(self, db, note_id: str) -> list[str]:
        row = db.execute(
            'SELECT source_json FROM study_notes WHERE scope_key=? AND id=?',
            (self.scope.key, note_id),
        ).fetchone()
        if not row:
            return []
        source = json.loads(row['source_json'] or '{}')
        return list(dict.fromkeys(str(v) for v in source.get('resource_ids', []) if str(v)))

    def _note_resources(self, db, note_id: str) -> list[dict[str, Any]]:
        ids = self._note_resource_ids(db, note_id)
        if not ids:
            return []
        rows = db.execute(
            'SELECT id,title,origin,revision,raw_refs_json,created_at,updated_at FROM study_note_resources '
            f"WHERE scope_key=? AND deleted_at IS NULL AND id IN ({','.join('?' for _ in ids)})",
            (self.scope.key, *ids),
        ).fetchall()
        by_id = {str(row['id']): {**dict(row), 'raw_ids': json.loads(row['raw_refs_json'])} for row in rows}
        return [by_id[value] for value in ids if value in by_id]

    def _resource_refs(self, db, resource_ids: list[str]) -> list[dict[str, str]]:
        if not resource_ids:
            return []
        rows = db.execute(
            f"SELECT id,title FROM study_note_resources WHERE scope_key=? AND id IN ({','.join('?' for _ in resource_ids)})",
            (self.scope.key, *resource_ids),
        ).fetchall()
        titles = {str(row['id']): str(row['title']) for row in rows}
        return [{'id': value, 'title': titles.get(value, value)} for value in resource_ids]

    def _validate_resources(self, db, resource_ids: Any) -> list[str]:
        if not isinstance(resource_ids, list) or not resource_ids:
            raise StudyNoteError('NOTE_RESOURCES_REQUIRED', 'Every note must cite at least one Resource')
        values = list(dict.fromkeys(str(value).strip() for value in resource_ids if str(value).strip()))
        if not values:
            raise StudyNoteError('NOTE_RESOURCES_REQUIRED', 'Every note must cite at least one Resource')
        rows = db.execute(
            'SELECT id FROM study_note_resources WHERE scope_key=? AND deleted_at IS NULL '
            f"AND id IN ({','.join('?' for _ in values)})", (self.scope.key, *values),
        ).fetchall()
        found = {str(row['id']) for row in rows}
        missing = [value for value in values if value not in found]
        if missing:
            raise StudyNoteError('UNKNOWN_NOTE_RESOURCE', resource_ids=missing)
        return values

    def _validate_parent(self, db, note_id: str, parent_id: str) -> str:
        parent_id = parent_id.strip()
        if not parent_id:
            return ''
        if parent_id == note_id:
            raise StudyNoteError('NOTE_PARENT_CYCLE')
        if not db.execute(
            'SELECT 1 FROM study_notes WHERE scope_key=? AND id=? AND deleted_at IS NULL',
            (self.scope.key, parent_id),
        ).fetchone():
            raise StudyNoteError('UNKNOWN_PARENT_NOTE')
        current = parent_id
        seen = {note_id}
        while current:
            if current in seen:
                raise StudyNoteError('NOTE_PARENT_CYCLE')
            seen.add(current)
            row = db.execute(
                'SELECT parent_id FROM study_notes WHERE scope_key=? AND id=?',
                (self.scope.key, current),
            ).fetchone()
            current = str(row['parent_id'] or '') if row else ''
        return parent_id

    def _migrate_note_blocks(self, db) -> None:
        """Idempotently convert each scoped legacy note; old tables stay read-only."""
        marker = db.execute(
            "SELECT data FROM study_scope_meta WHERE scope_key=? AND key='notes_v3_migrated'",
            (self.scope.key,),
        ).fetchone()
        if marker:
            return
        root = vault_root(self.path, self.scope.key)
        rows = db.execute(
            "SELECT * FROM study_notes WHERE scope_key=? AND deleted_at IS NULL AND (path='' OR path IS NULL) ORDER BY rowid",
            (self.scope.key,),
        ).fetchall()
        existing = {str(row['path']) for row in db.execute(
            "SELECT path FROM study_notes WHERE scope_key=? AND path<>'' AND deleted_at IS NULL", (self.scope.key,),
        )}
        for note in rows:
            blocks = db.execute(
                'SELECT * FROM study_note_blocks WHERE scope_key=? AND note_id=? ORDER BY position,id',
                (self.scope.key, note['id']),
            ).fetchall()
            body_parts, resource_ids, pending_locks = [], [], []
            offset = 0
            for block in blocks:
                content = str(block['content'] or '')
                if body_parts:
                    offset += 2
                start = offset
                body_parts.append(content)
                offset += len(content)
                # Every migrated Resource retains immutable lineage, including
                # legacy AI blocks. The stable id/origin make retries idempotent.
                raw_id = f"legacy-raw-{note['id']}-{block['id']}"
                db.execute(
                    'INSERT OR IGNORE INTO study_note_raw_sources(scope_key,id,kind,origin_id,content,metadata_json) VALUES(?,?,?,?,?,?)',
                    (self.scope.key, raw_id, 'legacy_note_block', str(block['id']), content,
                     json.dumps({'note_id': note['id'], 'block_id': block['id'],
                                 'author': block['author']}, ensure_ascii=False)),
                )
                raw_refs = [raw_id]
                resource_id = f"legacy-resource-{note['id']}-{block['id']}"
                db.execute(
                    'INSERT OR IGNORE INTO study_note_resources(scope_key,id,note_id,title,content,raw_refs_json,origin,revision,deleted_at) '
                    'VALUES(?,?,?,?,?,?,?,?,NULL)',
                    (self.scope.key, resource_id, str(note['id']), str(note['title']), content,
                     json.dumps(raw_refs, ensure_ascii=False), 'legacy_migration', 1),
                )
                db.execute(
                    'INSERT OR IGNORE INTO study_note_resource_versions(scope_key,resource_id,revision,title,content,raw_refs_json,origin) VALUES(?,?,?,?,?,?,?)',
                    (self.scope.key, resource_id, 1, str(note['title']), content,
                     json.dumps(raw_refs, ensure_ascii=False), 'legacy_migration'),
                )
                resource_ids.append(resource_id)
                if bool(block['locked']) or str(block['author']) == 'user':
                    pending_locks.append((str(block['id']), start, offset, content))
            if not resource_ids:
                raw_id = f"legacy-raw-note-{note['id']}"
                db.execute(
                    'INSERT OR IGNORE INTO study_note_raw_sources(scope_key,id,kind,origin_id,content,metadata_json) VALUES(?,?,?,?,?,?)',
                    (self.scope.key, raw_id, 'legacy_empty_note', str(note['id']), '',
                     json.dumps({'note_id': note['id'], 'empty_note': True}, ensure_ascii=False)),
                )
                resource_id = f"legacy-resource-{note['id']}"
                db.execute(
                    'INSERT OR IGNORE INTO study_note_resources(scope_key,id,note_id,title,content,raw_refs_json,origin,revision,deleted_at) '
                    'VALUES(?,?,?,?,?,?,?,?,NULL)',
                    (self.scope.key, resource_id, str(note['id']), str(note['title']), '',
                     json.dumps([raw_id], ensure_ascii=False), 'legacy_migration', 1),
                )
                db.execute(
                    'INSERT OR IGNORE INTO study_note_resource_versions(scope_key,resource_id,revision,title,content,raw_refs_json,origin) VALUES(?,?,?,?,?,?,?)',
                    (self.scope.key, resource_id, 1, str(note['title']), '',
                     json.dumps([raw_id], ensure_ascii=False), 'legacy_migration'),
                )
                resource_ids.append(resource_id)
            body = '\n\n'.join(body_parts)
            path = normalize_relative_path(None, title=str(note['title']), note_id=str(note['id']), existing=existing)
            existing.add(path)
            metadata = {'id': note['id'], 'title': note['title'], 'parent_id': None,
                        'resource_ids': resource_ids, 'resource_refs': self._resource_refs(db, resource_ids),
                        'revision': int(note['revision'])}
            document = write_document(root, path, metadata, body)
            db.execute(
                'UPDATE study_notes SET path=?,parent_id=?,content_hash=?,source_json=? WHERE scope_key=? AND id=?',
                (path, '', document.content_hash, json.dumps({'resource_ids': resource_ids}, ensure_ascii=False),
                 self.scope.key, note['id']),
            )
            for old_id, start, end, quote in pending_locks:
                lock_id = f'legacy-lock-{note["id"]}-{old_id}'
                db.execute(
                    'INSERT OR IGNORE INTO study_note_locks(scope_key,id,note_id,start_offset,end_offset,quote,prefix,suffix,reason,state,revision) '
                    'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (self.scope.key, lock_id, note['id'], self._cp_to_utf16(body, start), self._cp_to_utf16(body, end), quote,
                     body[max(0, start-32):start], body[end:end+32], 'Migrated protected content', 'active', 1),
                )
        db.execute(
            'INSERT OR REPLACE INTO study_scope_meta(scope_key,key,data) VALUES(?,?,?)',
            (self.scope.key, 'notes_v3_migrated', '1'),
        )

    def _document(self, row: sqlite3.Row):
        return read_document(vault_root(self.path, self.scope.key), str(row['path']))

    def _note_links(self, db) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
        rows = db.execute(
            'SELECT * FROM study_notes WHERE scope_key=? AND deleted_at IS NULL ORDER BY path,id',
            (self.scope.key,),
        ).fetchall()
        by_id = {str(row['id']): row for row in rows}
        by_title: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            by_title.setdefault(str(row['title']).casefold(), []).append(row)
        node_by_id: dict[str, dict[str, Any]] = {}
        node_by_title: dict[str, list[dict[str, Any]]] = {}
        for node_row in db.execute(
            "SELECT id,data FROM study_records WHERE scope_key=? AND kind='node' ORDER BY rowid",
            (self.scope.key,),
        ):
            node = self._defaults('node', json.loads(node_row['data']))
            if node.get('deleted_at'):
                continue
            node_id = str(node.get('id') or node_row['id'])
            title = str(node.get('name') or node.get('title') or '').strip()
            node_by_id[node_id] = node
            if title:
                node_by_title.setdefault(title.casefold(), []).append(node)
        links = {str(row['id']): [] for row in rows}
        for row in rows:
            for item in self._parse_wikilinks(self._document(row).content):
                target, explicit_kind = item['target'], ''
                prefix, sep, remainder = target.partition(':')
                if sep and prefix.casefold() in ('note', 'node'):
                    explicit_kind = prefix.casefold()
                    target = remainder.strip()
                note_candidates = by_title.get(target.casefold(), [])
                candidate = by_id.get(target) or (note_candidates[0] if len(note_candidates) == 1 else None)
                if explicit_kind != 'node' and candidate:
                    links[str(row['id'])].append({**item, 'kind': 'note', 'id': candidate['id'], 'title': candidate['title']})
                    continue
                if explicit_kind != 'node' and len(note_candidates) > 1:
                    links[str(row['id'])].append({**item, 'kind': 'unresolved',
                                                  'candidates': [str(value['id']) for value in note_candidates]})
                    continue
                node_candidates = node_by_title.get(target.casefold(), [])
                node = node_by_id.get(target) or (node_candidates[0] if len(node_candidates) == 1 else None)
                if explicit_kind != 'note' and node:
                    node_id = str(node.get('id') or target)
                    links[str(row['id'])].append({**item, 'kind': 'node', 'id': node_id,
                                                  'title': str(node.get('name') or node.get('title') or node_id)})
                    continue
                candidates = [str(value.get('id') or '') for value in node_candidates] if len(node_candidates) > 1 else []
                links[str(row['id'])].append({**item, 'kind': 'unresolved',
                                              **({'candidates': candidates} if candidates else {})})
        backlinks = {str(row['id']): [] for row in rows}
        for source in rows:
            for link in links[str(source['id'])]:
                if link.get('kind') == 'note':
                    backlinks[str(link['id'])].append({'note_id': source['id'], 'title': source['title'], 'target': link['target'], 'label': link['label']})
        return links, backlinks

    def notes(self, p: dict, *, writer: str = 'agent') -> dict[str, Any]:
        """Operate on immutable Raw, versioned Resource, and Markdown Note layers."""
        if writer not in ('user', 'agent'):
            raise ValueError('Invalid note writer')
        action = str(p.get('action') or 'list')
        if action.startswith('task_') or action.startswith('curate_'):
            return self._curation_tasks(p)
        reads = {'raw_list', 'raw_get', 'resource_list', 'resource_get', 'list', 'tree', 'get', 'graph', 'backlinks', 'task_get'}
        with self.db(write=action not in reads) as db:
            self._migrate_note_blocks(db)
            if action == 'raw_capture':
                if writer != 'user' or p.get('_trusted_capture') is not self:
                    raise StudyNoteError('RAW_CAPTURE_FORBIDDEN', 'Raw snapshots can only be captured by the trusted host')
                raw_id = str(p.get('raw_id') or identifier()).strip()
                kind, origin_id = str(p.get('kind') or '').strip(), str(p.get('origin_id') or '').strip()
                if not kind or not origin_id or 'content' not in p:
                    raise ValueError('Raw kind, origin_id and content are required')
                metadata = p.get('metadata') or {}
                if not isinstance(metadata, dict):
                    raise ValueError('Raw metadata must be an object')
                try:
                    db.execute('INSERT INTO study_note_raw_sources(scope_key,id,kind,origin_id,content,metadata_json) VALUES(?,?,?,?,?,?)',
                               (self.scope.key, raw_id, kind, origin_id, str(p['content']), json.dumps(metadata, ensure_ascii=False)))
                except sqlite3.IntegrityError as exc:
                    raise StudyNoteError('RAW_EXISTS') from exc
                return {'raw_id': raw_id, 'immutable': True}
            if action in ('raw_list', 'raw_get'):
                if action == 'raw_get':
                    row = db.execute('SELECT * FROM study_note_raw_sources WHERE scope_key=? AND id=?', (self.scope.key, str(p.get('raw_id') or ''))).fetchone()
                    if not row: raise StudyNoteError('UNKNOWN_RAW_SOURCE')
                    return {'raw': {**dict(row), 'metadata': json.loads(row['metadata_json']), 'immutable': True}}
                offset = max(0, int(p.get('offset', 0)))
                limit = min(50, max(1, int(p.get('limit', 20))))
                total = int(db.execute(
                    'SELECT COUNT(*) FROM study_note_raw_sources WHERE scope_key=?', (self.scope.key,),
                ).fetchone()[0])
                rows = db.execute(
                    'SELECT * FROM study_note_raw_sources WHERE scope_key=? '
                    'ORDER BY captured_at DESC,id LIMIT ? OFFSET ?',
                    (self.scope.key, limit, offset),
                ).fetchall()
                return {
                    'raw_sources': [{**dict(row), 'metadata': json.loads(row['metadata_json']), 'immutable': True} for row in rows],
                    'total': total, 'offset': offset, 'limit': limit,
                    'has_more': offset + limit < total,
                }
            if action in ('resource_list', 'resource_get', 'resource_create', 'resource_update'):
                if action in ('resource_create', 'resource_update') and writer != 'agent':
                    raise StudyNoteError(
                        'RESOURCE_AGENT_ONLY',
                        'Resources are AI-authored session notes and can only be written by the trusted Agent path',
                    )
                if action == 'resource_list':
                    offset = max(0, int(p.get('offset', 0)))
                    limit = min(50, max(1, int(p.get('limit', 20))))
                    total = int(db.execute(
                        'SELECT COUNT(*) FROM study_note_resources WHERE scope_key=? AND deleted_at IS NULL',
                        (self.scope.key,),
                    ).fetchone()[0])
                    rows = db.execute(
                        'SELECT * FROM study_note_resources WHERE scope_key=? AND deleted_at IS NULL '
                        'ORDER BY updated_at DESC,id LIMIT ? OFFSET ?',
                        (self.scope.key, limit, offset),
                    ).fetchall()
                    return {
                        'resources': [{**dict(row), 'raw_ids': json.loads(row['raw_refs_json'])} for row in rows],
                        'total': total, 'offset': offset, 'limit': limit,
                        'has_more': offset + limit < total,
                    }
                resource_id = str(p.get('resource_id') or (identifier() if action == 'resource_create' else '')).strip()
                if action == 'resource_get':
                    requested_revision = p.get('revision')
                    if requested_revision is not None:
                        row = db.execute('SELECT resource_id AS id,title,content,raw_refs_json,origin,revision,created_at FROM study_note_resource_versions WHERE scope_key=? AND resource_id=? AND revision=?',
                                         (self.scope.key, resource_id, int(requested_revision))).fetchone()
                    else:
                        row = db.execute('SELECT * FROM study_note_resources WHERE scope_key=? AND id=? AND deleted_at IS NULL', (self.scope.key, resource_id)).fetchone()
                    if not row: raise StudyNoteError('UNKNOWN_NOTE_RESOURCE')
                    history = [int(item['revision']) for item in db.execute(
                        'SELECT revision FROM study_note_resource_versions WHERE scope_key=? AND resource_id=? ORDER BY revision',
                        (self.scope.key, resource_id))]
                    return {'resource': {**dict(row), 'raw_ids': json.loads(row['raw_refs_json']), 'available_revisions': history}}
                title, content = str(p.get('title') or '').strip(), str(p.get('content') or '')
                raw_ids = list(dict.fromkeys(str(v) for v in (p.get('raw_ids') or []) if str(v)))
                if not title or not content:
                    raise ValueError('Resource title and content are required')
                if not raw_ids:
                    raise StudyNoteError('RESOURCE_RAW_REQUIRED', 'Every Resource must cite at least one immutable Raw source')
                if raw_ids:
                    found = {str(row['id']) for row in db.execute(
                        f"SELECT id FROM study_note_raw_sources WHERE scope_key=? AND id IN ({','.join('?' for _ in raw_ids)})", (self.scope.key, *raw_ids))}
                    missing = [value for value in raw_ids if value not in found]
                    if missing: raise StudyNoteError('UNKNOWN_RAW_SOURCE', raw_ids=missing)
                if action == 'resource_create':
                    try:
                        db.execute('INSERT INTO study_note_resources(scope_key,id,note_id,title,content,raw_refs_json,origin,revision,deleted_at) VALUES(?,?,?,?,?,?,?,?,NULL)',
                                   (self.scope.key, resource_id, '', title, content, json.dumps(raw_ids), 'agent' if writer == 'agent' else 'user', 1))
                    except sqlite3.IntegrityError as exc:
                        raise StudyNoteError('RESOURCE_EXISTS', resource_id=resource_id) from exc
                    db.execute('INSERT INTO study_note_resource_versions(scope_key,resource_id,revision,title,content,raw_refs_json,origin) VALUES(?,?,?,?,?,?,?)',
                               (self.scope.key, resource_id, 1, title, content, json.dumps(raw_ids), 'agent' if writer == 'agent' else 'user'))
                    return {'resource_id': resource_id, 'revision': 1}
                row = db.execute('SELECT revision FROM study_note_resources WHERE scope_key=? AND id=? AND deleted_at IS NULL', (self.scope.key, resource_id)).fetchone()
                if not row: raise StudyNoteError('UNKNOWN_NOTE_RESOURCE')
                if p.get('expected_revision') != row['revision']: raise StudyNoteError('REVISION_CONFLICT')
                revision = int(row['revision']) + 1
                origin = 'agent' if writer == 'agent' else 'user'
                db.execute('UPDATE study_note_resources SET title=?,content=?,raw_refs_json=?,revision=?,updated_at=CURRENT_TIMESTAMP WHERE scope_key=? AND id=?',
                           (title, content, json.dumps(raw_ids), revision, self.scope.key, resource_id))
                db.execute('INSERT INTO study_note_resource_versions(scope_key,resource_id,revision,title,content,raw_refs_json,origin) VALUES(?,?,?,?,?,?,?)',
                           (self.scope.key, resource_id, revision, title, content, json.dumps(raw_ids), origin))
                return {'resource_id': resource_id, 'revision': revision}
            if action in ('list', 'tree'):
                rows = db.execute('SELECT * FROM study_notes WHERE scope_key=? AND deleted_at IS NULL ORDER BY path,id', (self.scope.key,)).fetchall()
                notes = []
                query = str(p.get('q') or p.get('query') or '').casefold()
                for row in rows:
                    document = self._document(row)
                    if query and query not in (str(row['title']) + '\n' + document.content).casefold(): continue
                    item = {**dict(row), 'resource_ids': self._note_resource_ids(db, str(row['id'])),
                            'resources': self._note_resources(db, str(row['id'])),
                            'external_change': document.content_hash != row['content_hash']}
                    notes.append(item)
                if action == 'tree':
                    # This is the physical Markdown file tree. ``parent_id``
                    # remains a semantic Note relation used by graph views and
                    # must not turn every Note into a folder in the navigator.
                    tree: list[dict[str, Any]] = []
                    folders: dict[str, dict[str, Any]] = {}
                    for item in notes:
                        parts = [part for part in str(item['path']).split('/') if part]
                        children = tree
                        directory_parts: list[str] = []
                        for segment in parts[:-1]:
                            directory_parts.append(segment)
                            directory_path = '/'.join(directory_parts)
                            folder = folders.get(directory_path.casefold())
                            if folder is None:
                                folder = {
                                    'kind': 'folder', 'id': f'folder:{directory_path.casefold()}',
                                    'name': segment, 'path': directory_path, 'children': [],
                                }
                                folders[directory_path.casefold()] = folder
                                children.append(folder)
                            children = folder['children']
                        children.append({**item, 'kind': 'note', 'note_id': str(item['id'])})
                    return {'tree': tree, 'notes': notes}
                offset, limit = max(0, int(p.get('offset', 0))), min(50, max(1, int(p.get('limit', 20))))
                return {'notes': notes[offset:offset+limit], 'total': len(notes), 'offset': offset, 'limit': limit,
                        'has_more': offset + limit < len(notes), 'scope': self.scope.public()}
            if action == 'get':
                note_id = str(p.get('note_id') or '')
                row = db.execute('SELECT * FROM study_notes WHERE scope_key=? AND id=? AND deleted_at IS NULL', (self.scope.key, note_id)).fetchone()
                if not row: raise StudyNoteError('UNKNOWN_NOTE')
                document = self._document(row)
                links, backlinks = self._note_links(db)
                locks = [{**dict(lock), 'unit': 'utf16_code_unit'} for lock in db.execute(
                    "SELECT * FROM study_note_locks WHERE scope_key=? AND note_id=? AND state IN ('active','orphaned') ORDER BY start_offset,id", (self.scope.key, note_id))]
                return {'note': {**dict(row), 'body_md': document.content, 'content_hash': document.content_hash,
                                 'indexed_content_hash': row['content_hash'], 'external_change': document.content_hash != row['content_hash'],
                                 'resource_ids': self._note_resource_ids(db, note_id),
                                 'resources': self._note_resources(db, note_id), 'locks': locks,
                                 'links': links.get(note_id, []), 'backlinks': backlinks.get(note_id, [])}}
            if action == 'create':
                note_id, title = str(p.get('note_id') or identifier()).strip(), str(p.get('title') or '').strip()
                if not note_id or not title: raise ValueError('Note id and title are required')
                if db.execute('SELECT 1 FROM study_notes WHERE scope_key=? AND id=?', (self.scope.key, note_id)).fetchone(): raise StudyNoteError('NOTE_EXISTS')
                resource_ids = self._validate_resources(db, p.get('resource_ids'))
                parent_id = self._validate_parent(db, note_id, str(p.get('parent_id') or ''))
                existing = {str(row['path']) for row in db.execute("SELECT path FROM study_notes WHERE scope_key=? AND deleted_at IS NULL AND path<>''", (self.scope.key,))}
                path = normalize_relative_path(p.get('path'), title=title, note_id=note_id, existing=existing)
                body = str(p.get('body_md') or '')
                metadata = {'id': note_id, 'title': title, 'parent_id': parent_id or None,
                            'resource_ids': resource_ids, 'resource_refs': self._resource_refs(db, resource_ids), 'revision': 1}
                document = write_document(vault_root(self.path, self.scope.key), path, metadata, body)
                try:
                    db.execute('INSERT INTO study_notes(scope_key,id,title,revision,source_json,deleted_at,path,parent_id,content_hash) VALUES(?,?,?,?,?,NULL,?,?,?)',
                               (self.scope.key, note_id, title, 1, json.dumps({'resource_ids': resource_ids}), path, parent_id, document.content_hash))
                except Exception:
                    # The path did not exist before this create. Compensate the
                    # cross-medium write if the SQLite index cannot commit.
                    resolve_document_path(vault_root(self.path, self.scope.key), path).unlink(missing_ok=True)
                    raise
                return {'note_id': note_id, 'revision': 1, 'content_hash': document.content_hash, 'path': path}
            if action == 'update':
                note_id = str(p.get('note_id') or '')
                row = db.execute('SELECT * FROM study_notes WHERE scope_key=? AND id=? AND deleted_at IS NULL', (self.scope.key, note_id)).fetchone()
                if not row: raise StudyNoteError('UNKNOWN_NOTE')
                current = self._document(row)
                if current.content_hash != row['content_hash']:
                    if writer == 'agent':
                        raise StudyNoteError('NOTE_EXTERNAL_CHANGE', 'The Markdown file changed outside LamTools', content_hash=current.content_hash)
                    # A filesystem edit is a user edit because the Markdown
                    # file is the canonical Note body. The UI may adopt it
                    # only after reading that exact hash; a stale draft still
                    # fails below instead of overwriting the external change.
                    if p.get('expected_content_hash') != current.content_hash:
                        raise StudyNoteError('CONTENT_HASH_CONFLICT', content_hash=current.content_hash)
                if p.get('expected_revision') != row['revision']: raise StudyNoteError('REVISION_CONFLICT')
                if p.get('expected_content_hash') != current.content_hash: raise StudyNoteError('CONTENT_HASH_CONFLICT', content_hash=current.content_hash)
                body = str(p.get('body_md') or '')
                resource_ids = self._validate_resources(db, p.get('resource_ids'))
                title = str(p.get('title') if p.get('title') is not None else row['title']).strip()
                if not title: raise ValueError('Note title is required')
                parent_id = self._validate_parent(db, note_id, str(p.get('parent_id') if p.get('parent_id') is not None else row['parent_id']))
                changes = self._changed_intervals(current.content, body)
                locks = db.execute("SELECT * FROM study_note_locks WHERE scope_key=? AND note_id=? AND state IN ('active','orphaned')", (self.scope.key, note_id)).fetchall()
                if writer == 'agent':
                    overlaps = []
                    for lock in locks:
                        lock_start = self._utf16_to_cp(current.content, int(lock['start_offset']))
                        lock_end = self._utf16_to_cp(current.content, int(lock['end_offset']))
                        if lock['state'] == 'orphaned' or self._lock_overlaps(lock_start, lock_end, changes):
                            overlaps.append({**dict(lock), 'start': lock['start_offset'], 'end': lock['end_offset'],
                                             'overlap_start': 0 if lock['state'] == 'orphaned' else lock['start_offset'],
                                             'overlap_end': self._utf16_len(current.content) if lock['state'] == 'orphaned' else lock['end_offset']})
                    if overlaps:
                        for overlap in overlaps:
                            overlap['lock_id'] = overlap.pop('id')
                            overlap.pop('scope_key', None); overlap.pop('note_id', None)
                        raise StudyNoteError('NOTE_REGION_LOCKED', 'Agent edits overlap user-locked text', overlaps=overlaps)
                revision = int(row['revision']) + 1
                metadata = {'id': note_id, 'title': title, 'parent_id': parent_id or None,
                            'resource_ids': resource_ids, 'resource_refs': self._resource_refs(db, resource_ids), 'revision': revision}
                document = write_document(vault_root(self.path, self.scope.key), str(row['path']), metadata, body)
                try:
                    db.execute('UPDATE study_notes SET title=?,revision=?,source_json=?,parent_id=?,content_hash=? WHERE scope_key=? AND id=?',
                               (title, revision, json.dumps({'resource_ids': resource_ids}), parent_id, document.content_hash, self.scope.key, note_id))
                except Exception:
                    # Restore the previous canonical document before allowing
                    # the database transaction to roll back.
                    old_ids = self._note_resource_ids(db, note_id)
                    old_metadata = {**self._note_metadata(row, old_ids), 'resource_refs': self._resource_refs(db, old_ids)}
                    write_document(vault_root(self.path, self.scope.key), str(row['path']), old_metadata, current.content)
                    raise
                if writer == 'user' and locks:
                    opcodes = difflib.SequenceMatcher(None, current.content, body, autojunk=False).get_opcodes()
                    try:
                        for lock in locks:
                            old_start = self._utf16_to_cp(current.content, int(lock['start_offset']))
                            old_end = self._utf16_to_cp(current.content, int(lock['end_offset']))
                            old_quote = str(lock['quote'] or '')
                            candidates = [match.start() for match in re.finditer(re.escape(old_quote), body)] if old_quote else []
                            if len(candidates) == 1:
                                start, end = candidates[0], candidates[0] + len(old_quote)
                                reanchored = True
                            else:
                                start = self._map_offset(opcodes, old_start, end=False)
                                end = self._map_offset(opcodes, old_end, end=True)
                                reanchored = not self._lock_overlaps(old_start, old_end, changes)
                            start, end = max(0, min(start, len(body))), max(0, min(end, len(body)))
                            state = 'active' if reanchored and end > start and body[start:end] else 'orphaned'
                            db.execute('UPDATE study_note_locks SET start_offset=?,end_offset=?,quote=?,prefix=?,suffix=?,state=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE scope_key=? AND id=?',
                                       (self._cp_to_utf16(body, start), self._cp_to_utf16(body, end), body[start:end],
                                        body[max(0,start-32):start], body[end:end+32], state, self.scope.key, lock['id']))
                    except Exception:
                        old_ids = self._note_resource_ids(db, note_id)
                        write_document(vault_root(self.path, self.scope.key), str(row['path']),
                                       {**self._note_metadata(row, old_ids), 'resource_refs': self._resource_refs(db, old_ids)}, current.content)
                        raise
                return {'note_id': note_id, 'revision': revision, 'content_hash': document.content_hash}
            if action in ('lock_range', 'unlock_range'):
                if writer != 'user': raise StudyNoteError('NOTE_LOCK_FORBIDDEN', 'Only the user can manage note locks')
                note_id = str(p.get('note_id') or '')
                row = db.execute('SELECT * FROM study_notes WHERE scope_key=? AND id=? AND deleted_at IS NULL', (self.scope.key, note_id)).fetchone()
                if not row: raise StudyNoteError('UNKNOWN_NOTE')
                if action == 'unlock_range':
                    lock_id = str(p.get('lock_id') or '')
                    changed = db.execute("UPDATE study_note_locks SET state='released',revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE scope_key=? AND note_id=? AND id=? AND state='active'", (self.scope.key, note_id, lock_id)).rowcount
                    if not changed: raise StudyNoteError('UNKNOWN_NOTE_LOCK')
                    return {'note_id': note_id, 'lock_id': lock_id, 'unlocked': True}
                document = self._document(row)
                start_units, end_units = int(p.get('start', -1)), int(p.get('end', -1))
                if p.get('unit', 'utf16_code_unit') != 'utf16_code_unit' or start_units < 0 or end_units <= start_units:
                    raise StudyNoteError('INVALID_NOTE_RANGE', unit='utf16_code_unit')
                start, end = self._utf16_to_cp(document.content, start_units), self._utf16_to_cp(document.content, end_units)
                lock_id = str(p.get('lock_id') or identifier())
                db.execute('INSERT INTO study_note_locks(scope_key,id,note_id,start_offset,end_offset,quote,prefix,suffix,reason,state,revision) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           (self.scope.key, lock_id, note_id, start_units, end_units, document.content[start:end], document.content[max(0,start-32):start], document.content[end:end+32], str(p.get('reason') or 'User locked'), 'active', 1))
                return {'note_id': note_id, 'lock_id': lock_id, 'start': start_units, 'end': end_units, 'quote': document.content[start:end], 'unit': 'utf16_code_unit'}
            if action in ('graph', 'backlinks'):
                links, backlinks = self._note_links(db)
                rows = db.execute('SELECT id,title,parent_id,path FROM study_notes WHERE scope_key=? AND deleted_at IS NULL ORDER BY path,id', (self.scope.key,)).fetchall()
                if action == 'backlinks':
                    note_id = str(p.get('note_id') or '')
                    return {'note_id': note_id, 'backlinks': backlinks.get(note_id, [])}
                nodes = [{'id': row['id'], 'title': row['title'], 'path': row['path']} for row in rows]
                edges = []
                for row in rows:
                    if row['parent_id']:
                        edges.append({'source': row['parent_id'], 'target': row['id'], 'kind': 'parent'})
                    edges.extend({'source': row['id'], 'target': link['id'], 'kind': 'wikilink'} for link in links[str(row['id'])] if link.get('kind') == 'note')
                return {'nodes': nodes, 'edges': edges}
            raise ValueError('Unknown note action')
