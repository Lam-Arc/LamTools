"""Cassette storage for the demo-video record/replay proxy.

A *take* is one scripted demo run (e.g. "calendar", "workflow").  Every model
call that happens during that run is stored as an ordered cassette entry so the
same run can be replayed later without touching the real provider.

Layout under ``<take>/cassette/``::

    manifest.json         take metadata (mode, upstream, model, counts, timing)
    NNNN.meta.json        request line/headers, response status/headers, timing
    NNNN.request.bin      raw request body bytes (what the app sent)
    NNNN.request.json     parsed request body, secrets redacted, for inspection
    NNNN.response.bin     raw response body bytes (chunks concatenated)
    NNNN.chunks.json      arrival offsets: [{"o": ms_since_response_start, "n": bytes}]

Byte fidelity is the point: replay hands the app the exact bytes the provider
produced, so the UI re-renders the identical stream.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# Request/response headers that must never be written to disk in clear.
_SECRET_HEADERS = {
    "authorization",
    "x-api-key",
    "x-goog-api-key",
    "api-key",
    "cookie",
    "set-cookie",
    "proxy-authorization",
}

# Request body keys that hold credentials in some providers.
_SECRET_BODY_KEYS = {"api_key", "apikey", "key", "token", "access_token"}


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, value in headers.items():
        if name.lower() in _SECRET_HEADERS:
            out[name] = _mask(value)
        else:
            out[name] = value
    return out


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 12:
        return "********"
    return f"{value[:6]}...{value[-4:]} ({len(value)} chars)"


def redact_body(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: ("********" if k.lower() in _SECRET_BODY_KEYS else redact_body(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_body(item) for item in obj]
    return obj


def classify_request(body: dict[str, Any] | None, path: str) -> str:
    """Split calls into streams that replay independently and in order.

    The agent loop, the auto-title call and any background summariser all hit
    the same endpoint.  Ordering them as one queue would let an interleaved
    title call steal a main-loop response, so each kind gets its own pointer.
    """
    if not isinstance(body, dict):
        return "other"
    if path.endswith("/chat/completions") or path.endswith("/responses"):
        if body.get("tools"):
            return "loop"
        messages = body.get("messages")
        if isinstance(messages, list):
            if len(messages) <= 3:
                # Short transcript with no tools: title / summarise style call.
                return "aux"
        return "loop"
    return "other"


@dataclass
class CallRecord:
    index: int
    kind: str
    method: str
    path: str
    request_headers: dict[str, str]
    request_body: bytes
    request_json: Any
    status: int
    response_headers: dict[str, str]
    response_body: bytes
    chunks: list[dict[str, int]] = field(default_factory=list)
    started_at: float = 0.0
    ttfb_ms: float = 0.0
    total_ms: float = 0.0

    # -- serialisation ----------------------------------------------------

    def write(self, directory: Path) -> None:
        stem = f"{self.index:04d}"
        (directory / f"{stem}.request.bin").write_bytes(self.request_body)
        (directory / f"{stem}.response.bin").write_bytes(self.response_body)
        (directory / f"{stem}.chunks.json").write_text(
            json.dumps(self.chunks), encoding="utf-8"
        )
        (directory / f"{stem}.request.json").write_text(
            json.dumps(self.request_json, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        meta = {
            "index": self.index,
            "kind": self.kind,
            "method": self.method,
            "path": self.path,
            "request_headers": self.request_headers,
            "request_bytes": len(self.request_body),
            "status": self.status,
            "response_headers": self.response_headers,
            "response_bytes": len(self.response_body),
            "started_at": self.started_at,
            "ttfb_ms": round(self.ttfb_ms, 3),
            "total_ms": round(self.total_ms, 3),
            "chunk_count": len(self.chunks),
        }
        (directory / f"{stem}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def read(cls, directory: Path, index: int) -> "CallRecord":
        stem = f"{index:04d}"
        meta = json.loads((directory / f"{stem}.meta.json").read_text(encoding="utf-8"))
        chunks_path = directory / f"{stem}.chunks.json"
        chunks = (
            json.loads(chunks_path.read_text(encoding="utf-8"))
            if chunks_path.exists()
            else []
        )
        request_json_path = directory / f"{stem}.request.json"
        return cls(
            index=index,
            kind=meta.get("kind", "other"),
            method=meta.get("method", "POST"),
            path=meta.get("path", ""),
            request_headers=meta.get("request_headers", {}),
            request_body=(directory / f"{stem}.request.bin").read_bytes(),
            request_json=(
                json.loads(request_json_path.read_text(encoding="utf-8"))
                if request_json_path.exists()
                else None
            ),
            status=int(meta.get("status", 200)),
            response_headers=meta.get("response_headers", {}),
            response_body=(directory / f"{stem}.response.bin").read_bytes(),
            chunks=chunks,
            started_at=float(meta.get("started_at", 0.0)),
            ttfb_ms=float(meta.get("ttfb_ms", 0.0)),
            total_ms=float(meta.get("total_ms", 0.0)),
        )


class Cassette:
    """Read/write side of a take's recorded model traffic."""

    def __init__(self, take_dir: Path, *, mode: str = "record") -> None:
        self.take_dir = Path(take_dir)
        self.dir = self.take_dir / "cassette"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        self._records: list[CallRecord] = []
        self._next_index = 0

    # -- record -----------------------------------------------------------

    def append(self, record: CallRecord) -> None:
        record.index = self._next_index
        self._next_index += 1
        record.write(self.dir)
        self._records.append(record)
        self.write_manifest()

    def write_manifest(self, **extra: Any) -> None:
        kinds: dict[str, int] = {}
        for record in self._records:
            kinds[record.kind] = kinds.get(record.kind, 0) + 1
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "take": self.take_dir.name,
            "mode": self.mode,
            "updated_at": time.time(),
            "call_count": len(self._records),
            "calls_by_kind": kinds,
            "total_ms": round(sum(r.total_ms for r in self._records), 3),
        }
        manifest.update(extra)
        (self.dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # -- replay -----------------------------------------------------------

    def load(self) -> list[CallRecord]:
        if not self.dir.is_dir():
            raise FileNotFoundError(f"no cassette directory at {self.dir}")
        indices: list[int] = []
        for path in self.dir.glob("*.meta.json"):
            match = re.fullmatch(r"(\d+)", path.name.split(".")[0])
            if match:
                indices.append(int(match.group(1)))
        indices.sort()
        self._records = [CallRecord.read(self.dir, i) for i in indices]
        self._next_index = len(self._records)
        return self._records

    def load_or_empty(self) -> list[CallRecord]:
        try:
            return self.load()
        except FileNotFoundError:
            self._records = []
            return self._records

    def records(self) -> list[CallRecord]:
        return self._records

    def kinds(self) -> list[str]:
        seen: list[str] = []
        for record in self._records:
            if record.kind not in seen:
                seen.append(record.kind)
        return seen
