# Observer signal protocol

An observer is a long-running Python process managed by Core. Core supplies:

- `LAMTOOLS_OBSERVER_ID`: observer identity;
- `LAMTOOLS_OBSERVER_JOB_ID`: bound Arrange job;
- `LAMTOOLS_OBSERVER_WORK_ROOT`: project workspace;
- `LAMTOOLS_OBSERVER_STATE_DIR`: persistent private cursor directory;
- `LAMTOOLS_OBSERVER_EVENT_TYPE`: event type required by the Arrange.

Emit one UTF-8 JSON object per stdout line:

```json
{
  "protocol": "lamtools.signal.v1",
  "event_id": "bilibili:creator-42:BV123",
  "event_type": "content.published",
  "occurred_at": "2026-07-17T14:00:00Z",
  "source": "bilibili",
  "subject": "creator:42",
  "data": {
    "title": "New video"
  },
  "references": [
    {
      "url": "https://www.bilibili.com/video/BV123"
    }
  ],
  "metadata": {}
}
```

Required fields:

- `protocol`: exactly `lamtools.signal.v1`;
- `event_id`: deterministic and source-scoped; retries for the same source event must reuse it;
- `event_type`: exactly `LAMTOOLS_OBSERVER_EVENT_TYPE`;
- `occurred_at`: source occurrence time with timezone.

Core binds the source event ID to the Arrange job, persists the Signal, deduplicates retries, and passes the full envelope to the execution session. `metadata.source_event_id` retains the observer's original ID.

Use stderr for logs. Keep each stdout line below 1 MB. Do not emit prose, Markdown, progress text, or source content outside the JSON envelope.

## Offline recovery

State belongs under `LAMTOOLS_OBSERVER_STATE_DIR`, not the workspace. Establish a baseline on the first run. On subsequent starts, fetch history beginning slightly before the saved cursor and re-emit overlap items with stable IDs. This gives restart catch-up and safe deduplication.

Recovery is possible only when the source exposes history, retains a durable queue, retries a webhook, or has another replay mechanism. A source that exposes only a transient live notification cannot be recovered while the computer is off.
