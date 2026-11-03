-- Schema v3: the queue a user types into while a turn is running, and the
-- command catalogue the composer offers.
--
-- Both were previously only in the Python implementation. They are added here as
-- real tables rather than answered with a friendly-looking empty result, because
-- an empty queue object would make the UI show "nothing queued" while silently
-- dropping what the user typed.

CREATE TABLE IF NOT EXISTS queue_items (
    queue_item_id TEXT PRIMARY KEY,
    thread_id     TEXT NOT NULL,
    -- Preserves the user's ordering. Reordering rewrites these values.
    position      INTEGER NOT NULL,
    input_json    TEXT NOT NULL,
    status        TEXT NOT NULL,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS queue_items_by_thread
    ON queue_items (thread_id, position);
