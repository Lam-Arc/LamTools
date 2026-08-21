"""Run a small, non-paper-quality smoke test against an OpenAI-compatible API.

The API key is read only from LAMTOOLS_OPENAI_API_KEY.  It is never printed,
serialized, or included in error text.  This script is intentionally separate
from the product and from the paper's deterministic evaluation harness.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_ENDPOINT = "https://opencode.ai/zen/go/v1/chat/completions"
DEFAULT_MODELS = ["deepseek-v4-flash", "mimo-v2.5"]
DEFAULT_PROMPT = "Reply with exactly: LamTools smoke test passed."


def request_json(url: str, headers: dict[str, str], payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers=headers, method="POST" if payload else "GET")
    try:
        with urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body or "{}")
    except HTTPError as exc:
        return exc.code, {}


def run_one(endpoint: str, api_key: str, model: str, prompt: str) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 32,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    started = time.perf_counter()
    try:
        status, response = request_json(endpoint, headers, payload)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        usage = response.get("usage") if isinstance(response, dict) else None
        choices = response.get("choices") if isinstance(response, dict) else None
        return {
            "model": model,
            "endpoint": endpoint,
            "transport": "chat_completions",
            "status": status,
            "ok": 200 <= status < 300 and bool(choices),
            "latency_ms": elapsed_ms,
            "usage": usage if isinstance(usage, dict) else None,
            "response_shape": "choices" if choices else "no_choices",
        }
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return {
            "model": model,
            "endpoint": endpoint,
            "transport": "chat_completions",
            "status": None,
            "ok": False,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "error_type": type(exc).__name__,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default=os.getenv("LAMTOOLS_OPENAI_BASE_URL", DEFAULT_ENDPOINT))
    parser.add_argument("--output", type=Path, default=Path("docs/paper/provider-smoke-results.json"))
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    args = parser.parse_args()

    api_key = os.getenv("LAMTOOLS_OPENAI_API_KEY", "")
    if not api_key:
        print("LAMTOOLS_OPENAI_API_KEY is not set; no network request was made.")
        return 2

    results = [run_one(args.endpoint, api_key, model, args.prompt) for model in DEFAULT_MODELS]
    record = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": args.endpoint,
        "models": DEFAULT_MODELS,
        "prompt_policy": "fixed smoke prompt; response text intentionally not retained",
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
