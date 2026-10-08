"""Report what a take actually did, straight from the recorded traffic.

Answers questions like: which tools did the agent call, did it write a
checklist, did it delegate to a sub-agent, and did the auto-title call return
anything usable.

    py -3.14 scripts/demo-video/analyze-take.py --take E:/LamDemo/takes/calendar
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def stream_parts(raw: bytes) -> tuple[str, str, list[dict]]:
    """Return (visible text, reasoning text, tool calls) from a streamed body.

    Streamed tool calls arrive as one opening delta carrying the id and name,
    followed by many deltas that only append argument fragments — so calls are
    counted once, by id.
    """
    text, reasoning = "", ""
    tools: list[dict] = []
    seen: set[str] = set()
    try:
        decoded = raw.decode("utf-8", errors="ignore")
    except Exception:
        return text, reasoning, tools
    for line in decoded.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        for choice in payload.get("choices") or []:
            delta = choice.get("delta") or choice.get("message") or {}
            if delta.get("content"):
                text += str(delta["content"])
            if delta.get("reasoning_content"):
                reasoning += str(delta["reasoning_content"])
            for call in delta.get("tool_calls") or []:
                call_id = call.get("id") or call.get("index")
                function = call.get("function") or {}
                name = function.get("name") or call.get("name")
                if not name:
                    continue
                key = f"{call_id}:{name}"
                if key in seen:
                    continue
                seen.add(key)
                tools.append({"name": name, "id": call_id})
    return text, reasoning, tools


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--take", required=True)
    parser.add_argument("--show-text", type=int, default=0, help="print first N chars of text")
    args = parser.parse_args(argv)

    take = Path(args.take).resolve()
    cassette = take / "cassette"
    metas = sorted(cassette.glob("*.meta.json"))
    if not metas:
        print(f"no cassette in {cassette}")
        return 2

    tool_counter: Counter[str] = Counter()
    print(f"take: {take.name}   calls: {len(metas)}")
    for meta_path in metas:
        index = int(meta_path.name.split(".")[0])
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        raw = (cassette / f"{index:04d}.response.bin").read_bytes()
        text, reasoning, tools = stream_parts(raw)
        for tool in tools:
            tool_counter[tool["name"]] += 1
        names = ", ".join(t["name"] for t in tools) or "-"
        print(
            f"  #{index:>2} {meta['kind']:<5} {meta['total_ms']/1000:>6.1f}s "
            f"{meta['response_bytes']/1024:>7.1f}KB chunks={meta['chunk_count']:>5} "
            f"text={len(text):>5} think={len(reasoning):>6} tools=[{names}]"
        )
        if args.show_text and text:
            print(f"        text: {' '.join(text.split())[: args.show_text]}")

    print("\ntool usage:")
    if not tool_counter:
        print("  (no tool calls in this take)")
    for name, count in tool_counter.most_common():
        print(f"  {name}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
