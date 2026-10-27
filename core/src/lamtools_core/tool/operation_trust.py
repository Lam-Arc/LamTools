"""user:“一次性处理干净 不要留尾巴”+(全局精确信任账可持久化、逐级降低并撤销)。"""
from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

_lock = threading.RLock()


class OperationTrustStore:
    def __init__(self, path: Path | None = None):
        if path is None:
            from lamtools_core.config.root import core_config_file
            path = core_config_file("operation-trust.json")
        self.path = Path(path)

    @staticmethod
    def selector(root: Path, tool: str, params: dict) -> str:
        root = Path(root).resolve()
        if tool in {"run_command", "command"}:
            value = str(params.get("command") or "")
        elif tool in {"write_file", "edit_file", "write", "edit"}:
            value = str((root / str(params.get("path") or "")).resolve().parent)
        elif tool in {"web_fetch", "web"} and (tool == "web_fetch" or params.get("action") == "fetch"):
            value = urlsplit(str(params.get("url") or "")).netloc.lower()
        else:
            value = str(params.get("action") or "")
        return json.dumps([str(root), tool, value], ensure_ascii=False, separators=(",", ":"))

    @contextmanager
    def _locked(self):
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.with_suffix(".lock").open("a+b") as stream:
                stream.seek(0, 2)
                if not stream.tell():
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    stream.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(stream, fcntl.LOCK_UN)

    def _read(self):
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return rows if isinstance(rows, dict) else {}

    def _write(self, rows):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def level(self, key: str, base: int) -> int:
        if base == 0 or not self.path.exists():
            return base
        with self._locked():
            stored = (self._read().get(key) or {}).get("level")
        if not isinstance(stored, int) or isinstance(stored, bool):
            return base
        return max(1, min(base, stored))

    def lower(self, key: str, level: int) -> int:
        if level <= 0:
            raise ValueError("Hard-blocked operations cannot be trusted")
        target = max(1, level - 1)
        with self._locked():
            rows = self._read()
            rows[key] = {"key": key, "level": target}
            self._write(rows)
        return target

    def list(self):
        if not self.path.exists():
            return []
        with self._locked():
            return list(self._read().values())

    def revoke(self, key: str) -> None:
        with self._locked():
            rows = self._read()
            rows.pop(key, None)
            self._write(rows)
