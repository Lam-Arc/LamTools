"""Copy this file into .lamtools/observers and adapt the two marked functions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any


POLL_SECONDS = 60.0
OVERLAP_SECONDS = 300.0
MAX_BASELINE_IDS = 5_000
STATE_DIR = Path(os.environ["LAMTOOLS_OBSERVER_STATE_DIR"])
STATE_PATH = STATE_DIR / "cursor.json"
EVENT_TYPE = os.environ["LAMTOOLS_OBSERVER_EVENT_TYPE"]


def fetch_events(since: str | None) -> list[dict[str, Any]]:
    """SOURCE-SPECIFIC: return source records at or after `since`, oldest first."""
    raise NotImplementedError("implement the source history query")


def normalize_event(record: dict[str, Any]) -> dict[str, Any]:
    """SOURCE-SPECIFIC: return a stable source ID, time, subject, data and references."""
    raise NotImplementedError("normalize the source record")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("occurred_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def iso_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_state() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        return {"initialized": False, "cursor": None, "baseline_event_ids": []}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, STATE_PATH)


def query_start(cursor: str | None) -> str | None:
    if not cursor:
        return None
    return iso_time(parse_time(cursor) - timedelta(seconds=OVERLAP_SECONDS))


def emit(event: dict[str, Any]) -> None:
    source_event_id = str(event["event_id"]).strip()
    occurred_at = iso_time(parse_time(str(event["occurred_at"])))
    signal = {
        "protocol": "lamtools.signal.v1",
        "event_id": source_event_id,
        "event_type": EVENT_TYPE,
        "occurred_at": occurred_at,
        "source": str(event.get("source") or "observer"),
        "subject": str(event.get("subject") or ""),
        "data": dict(event.get("data") or {}),
        "references": list(event.get("references") or []),
        "metadata": dict(event.get("metadata") or {}),
    }
    print(json.dumps(signal, ensure_ascii=False, separators=(",", ":")), flush=True)


def scan_once(state: dict[str, Any]) -> None:
    records = fetch_events(query_start(state.get("cursor")))
    events = [normalize_event(record) for record in records]
    events.sort(key=lambda item: (parse_time(str(item["occurred_at"])), str(item["event_id"])))

    if not state.get("initialized"):
        state["initialized"] = True
        state["baseline_event_ids"] = [
            str(item["event_id"]) for item in events[-MAX_BASELINE_IDS:]
        ]
        state["cursor"] = iso_time(
            parse_time(str(events[-1]["occurred_at"])) if events else utc_now()
        )
        save_state(state)
        return

    baseline_ids = set(str(item) for item in state.get("baseline_event_ids") or [])
    for event in events:
        if str(event["event_id"]) not in baseline_ids:
            emit(event)
    if events:
        latest = max(parse_time(str(item["occurred_at"])) for item in events)
        previous = parse_time(str(state["cursor"])) if state.get("cursor") else latest
        state["cursor"] = iso_time(max(previous, latest))
    save_state(state)


def main() -> None:
    state = load_state()
    delay = POLL_SECONDS
    while True:
        try:
            scan_once(state)
            delay = POLL_SECONDS
        except Exception as exc:  # keep the observer alive; Core also restarts process failures
            print(f"observer scan failed: {exc}", file=sys.stderr, flush=True)
            delay = min(max(delay * 2, POLL_SECONDS), 900.0)
        time.sleep(delay)


if __name__ == "__main__":
    main()
