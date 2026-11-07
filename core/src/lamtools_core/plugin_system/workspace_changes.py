"""user:“继续，无人值守模式，不要停下来”+(工作区Git状态通过原进程所有者读取，固定仓库根和路径编码，不伪造内容历史)。"""
import hashlib
import os
from pathlib import Path


class WorkspaceChangesError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class PluginWorkspaceChangesAPI:
    def __init__(self, context, scope):
        self._context, self._scope, self._root = context, scope, Path(context.work_root).resolve()

    async def _git(self, *args):
        environment = {key: None for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_COUNT")}
        environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
        outcome, output = await self._context.processes.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "-C", str(self._root), *args],
            cwd=self._root, env=environment, timeout=20, max_output_bytes=1048576)
        if outcome.status != "exited" or outcome.exit_code != 0:
            raise WorkspaceChangesError("workspace/git-failed", "Git status is unavailable; no file mutations were requested")
        if output.stdout_lost:
            raise WorkspaceChangesError("workspace/status-too-large", "Git status exceeds 1 MiB; partial state is not returned")
        return output.stdout

    async def snapshot(self, *, limit=1000):
        self._scope.acquire()
        try:
            if type(limit) is not int or not 1 <= limit <= 1000:
                raise ValueError("Workspace status limit is 1–1000")
            top = (await self._git("rev-parse", "--show-toplevel")).decode("utf8").strip()
            if Path(top).resolve() != self._root:
                raise WorkspaceChangesError("workspace/repository-root-mismatch", "The original project must be the repository root; parent repositories are not queried")
            raw = await self._git("status", "--porcelain=v1", "-z", "--untracked-files=normal")
            records, index, items = raw.split(b"\0"), 0, []
            while index < len(records) and records[index]:
                record = records[index]
                index += 1
                if len(record) < 4 or record[2:3] != b" ":
                    raise WorkspaceChangesError("workspace/invalid-status", "Git returned an invalid status record")
                entry = {"status": record[:2].decode("ascii"), "path": record[3:].decode("utf8")}
                if "R" in entry["status"] or "C" in entry["status"]:
                    if index >= len(records) or not records[index]:
                        raise WorkspaceChangesError("workspace/invalid-status", "Git rename/copy source is missing")
                    entry["original_path"] = records[index].decode("utf8")
                    index += 1
                items.append(entry)
            items.sort(key=lambda item: item["path"])
            return {"project_root": str(self._root), "items": items[:limit], "truncated": len(items) > limit,
                    "status_revision": hashlib.sha256(raw).hexdigest(), "content_fingerprint": False}
        finally:
            self._scope.release()

    async def compare_status(self, previous):
        if (type(previous) is not dict or previous.get("project_root") != str(self._root)
                or previous.get("truncated") is not False or type(previous.get("items")) is not list
                or len(previous["items"]) > 1000 or any(type(item) is not dict or type(item.get("path")) is not str for item in previous["items"])):
            raise ValueError("Compare an untruncated snapshot from this original project")
        current = await self.snapshot()
        if current["truncated"]:
            raise WorkspaceChangesError("workspace/status-too-large", "A complete status comparison exceeds 1000 items")
        before, after = {row["path"]: row for row in previous["items"]}, {row["path"]: row for row in current["items"]}
        return {"added": [after[key] for key in sorted(after.keys() - before.keys())],
                "removed": [before[key] for key in sorted(before.keys() - after.keys())],
                "changed": [after[key] for key in sorted(before.keys() & after.keys()) if before[key] != after[key]],
                "snapshot": current}
