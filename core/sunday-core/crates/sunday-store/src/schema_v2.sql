-- v2: pending user guidance (steer) and sub-agent bookkeeping.
CREATE TABLE IF NOT EXISTS guidance (
    guidance_id TEXT PRIMARY KEY,
    thread_id   TEXT NOT NULL,
    text        TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    consumed_at INTEGER
);
CREATE INDEX IF NOT EXISTS ix_guidance_pending ON guidance (thread_id, consumed_at);

CREATE TABLE IF NOT EXISTS sub_agents (
    child_id        TEXT PRIMARY KEY,
    parent_thread   TEXT NOT NULL,
    child_thread    TEXT NOT NULL,
    model_id        TEXT NOT NULL,
    guide           TEXT NOT NULL,
    granted_tools   TEXT NOT NULL,
    status          TEXT NOT NULL,
    result          TEXT,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sub_agents_parent ON sub_agents (parent_thread);
