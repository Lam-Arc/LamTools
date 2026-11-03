-- Schema v1. Append-only; new columns and tables are added by bumping
-- SCHEMA_VERSION and appending a migration step, never by editing this text.
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thread_revisions (
    thread_id TEXT PRIMARY KEY,
    revision  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS journal_events (
    workspace_id TEXT NOT NULL,
    thread_id    TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    event_id     TEXT NOT NULL UNIQUE,
    kind         TEXT NOT NULL,
    payload      TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    PRIMARY KEY (workspace_id, thread_id, seq)
);

CREATE TABLE IF NOT EXISTS command_receipts (
    request_id     TEXT PRIMARY KEY,
    command_kind   TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    status         TEXT NOT NULL,
    thread_id      TEXT NOT NULL,
    seq            INTEGER,
    revision       INTEGER NOT NULL,
    created_at     INTEGER NOT NULL,
    updated_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_call_stages (
    tool_call_id TEXT PRIMARY KEY,
    thread_id    TEXT NOT NULL,
    tool_id      TEXT NOT NULL,
    args_digest  TEXT NOT NULL,
    args_json    TEXT NOT NULL,
    side_effect  TEXT NOT NULL,
    stage        TEXT NOT NULL,
    result_json  TEXT,
    updated_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS turn_continuations (
    thread_id       TEXT PRIMARY KEY,
    turn_id         TEXT NOT NULL,
    model_id        TEXT NOT NULL,
    messages_json   TEXT NOT NULL,
    pending_call_id TEXT,
    updated_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id  TEXT PRIMARY KEY,
    thread_id    TEXT NOT NULL,
    tool_call_id TEXT NOT NULL,
    args_digest  TEXT NOT NULL,
    status       TEXT NOT NULL,
    expires_at   INTEGER NOT NULL,
    created_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS thread_projection (
    thread_id TEXT PRIMARY KEY,
    last_seq  INTEGER NOT NULL,
    revision  INTEGER NOT NULL,
    body      TEXT NOT NULL
);
