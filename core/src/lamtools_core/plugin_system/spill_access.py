"""user:“继续，把 2 阶段都做完”+(长文本保存至原插件数据根，返回真实可取回位置，取消后不遗弃未结束的磁盘写入)。"""
from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from lamtools_core.tool.workspace_files import atomic_write_bytes
from .manifest import _validate_name
from .durable_access import _json


class SpillAccessError(RuntimeError):
    def __init__(self, code, message, *, may_have_changed=False):
        self.code, self.may_have_changed = code, may_have_changed
        super().__init__(message)


@dataclass(frozen=True)
class SpillReference:
    locator: str
    bytes: int
    retrieval_hint: str


class PluginSpillAPI:
    def __init__(self, context, scope):
        self._scope = scope
        self._root = Path(context.data_dir) / "plugin-data" if context.data_dir is not None else None

    def _save(self, payload, session_id, suggested_name):
        try:
            root = self._root
            owner = _validate_name(self._scope.owner, root)
            directory = root / owner / "spill" / hashlib.sha256(session_id.encode("utf-8")).hexdigest()
            # Reject known redirects, including ancestor symlinks, before and after mkdir.
            # Like other native plugin paths, this is not a hostile filesystem race barrier.
            if directory.resolve() != directory:
                raise SpillAccessError("spill/path", "Spill storage must not redirect")
            directory.mkdir(parents=True, exist_ok=True)
            if directory.resolve() != directory:
                raise SpillAccessError("spill/path", "Spill storage must not redirect")
            name = re.sub(r"[^A-Za-z0-9._-]+", "_", suggested_name.replace("\\", "/").split("/")[-1]).strip("._")[:80] or "output.txt"
            path = directory / (uuid.uuid4().hex + "-" + name)
            atomic_write_bytes(path, payload)
            return SpillReference(str(path), len(payload), "Read or search this local UTF-8 file using an authorized file reader: " + str(path))
        except SpillAccessError:
            raise
        except Exception:
            raise SpillAccessError("spill/write-failed", "Spill publication failed; a file may have been published", may_have_changed=True) from None

    async def save_text(self, content, *, session_id, suggested_name="output.txt", source=None):
        self._scope.acquire()
        try:
            if self._root is None:
                raise SpillAccessError("spill/unavailable", "Spill requires the host data directory")
            try:
                if type(content) is not str:
                    raise ValueError
                payload = content.encode("utf-8")
                if len(payload) > 8 * 1024 * 1024:
                    raise ValueError
                if type(session_id) is not str or not session_id or len(session_id) > 256 or "\x00" in session_id:
                    raise ValueError
                session_id.encode("utf-8")
                if type(suggested_name) is not str or len(suggested_name) > 1024 or "\x00" in suggested_name:
                    raise ValueError
                # Source is descriptive only; do not treat identifiers as grants or persist secret metadata.
                if source is not None and type(source) is not dict:
                    raise ValueError
                _json(source, maximum=8192)
            except Exception:
                raise SpillAccessError("spill/invalid-request", "Use UTF-8 text up to 8 MiB, bounded session/name and finite descriptive JSON") from None
            task = asyncio.create_task(asyncio.to_thread(self._save, payload, session_id, suggested_name), name="plugin-spill-publish")
            cancelled = False
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    cancelled = True
                except Exception:
                    break
            if cancelled:
                # Consume failure while preserving cancellation; publication may have survived.
                if not task.cancelled():
                    task.exception()
                raise asyncio.CancelledError
            return task.result()
        finally:
            self._scope.release()
