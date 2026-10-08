"""Prove that a replay reproduced the recorded run.

Compares the newest session's message sequence in two Core databases (one
snapshotted after the record take, one after the replay take).  The model's
output is served from the cassette byte-for-byte, so the transcripts must match
exactly; anything else means the take cannot be trusted as footage.

    py -3.14 scripts/demo-video/verify.py --record <db> --replay <db>
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def newest_thread(connection: sqlite3.Connection) -> tuple[str, str] | None:
    row = connection.execute(
        "select thread_id, max(created_at) as latest from core_history_entries "
        "group by thread_id order by latest desc limit 1"
    ).fetchone()
    if not row:
        return None
    return str(row[0]), str(row[1])


def transcript(db: Path, thread: str | None = None) -> list[dict]:
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        selected = thread
        if not selected:
            found = newest_thread(connection)
            if not found:
                return []
            selected = found[0]
        rows = connection.execute(
            "select seq, revision, message_json from core_history_entries "
            "where thread_id = ? order by seq asc",
            (selected,),
        ).fetchall()
        result = []
        for row in rows:
            message = json.loads(row["message_json"])
            result.append(
                {
                    "seq": row["seq"],
                    "role": message.get("role"),
                    "content": message.get("content") or "",
                }
            )
        return result
    finally:
        connection.close()


def summarize(entries: list[dict]) -> str:
    lines = []
    for entry in entries:
        text = " ".join(str(entry["content"]).split())
        lines.append(f"  [{entry['seq']:>3}] {entry['role']:<9} {text[:110]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True, help="database snapshot after the record take")
    parser.add_argument("--replay", required=True, help="database snapshot after the replay take")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    recorded = transcript(Path(args.record))
    replayed = transcript(Path(args.replay))

    if not recorded:
        print("FAIL: the record snapshot has no messages", file=sys.stderr)
        return 2
    if not replayed:
        print("FAIL: the replay snapshot has no messages", file=sys.stderr)
        return 2

    problems: list[str] = []
    if len(recorded) != len(replayed):
        problems.append(f"message count differs: recorded {len(recorded)} vs replayed {len(replayed)}")

    for index, (left, right) in enumerate(zip(recorded, replayed)):
        if left["role"] != right["role"]:
            problems.append(f"#{index} role differs: {left['role']} vs {right['role']}")
        if left["content"] != right["content"]:
            left_text = " ".join(str(left["content"]).split())[:160]
            right_text = " ".join(str(right["content"]).split())[:160]
            problems.append(
                f"#{index} ({left['role']}) content differs:\n"
                f"      recorded: {left_text}\n"
                f"      replayed: {right_text}"
            )

    if args.verbose:
        print("recorded:")
        print(summarize(recorded))
        print("replayed:")
        print(summarize(replayed))

    if problems:
        print(f"FAIL: replay does not reproduce the recorded run ({len(problems)} problem(s))")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(
        f"OK: replay reproduces the recorded run — {len(recorded)} messages, "
        f"{sum(len(str(e['content'])) for e in recorded)} chars identical"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
