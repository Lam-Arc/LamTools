"""user:“该重建就重建”+(代码可回滚替换，数据保存在独立稳定目录，兼容 data/ 路径)。"""
from __future__ import annotations

import os
import json
import shutil
import tempfile
import uuid
from pathlib import Path


def remove_tree(path: Path) -> None:
    # Windows junctions must be removed as links, never followed into user data.
    if path.is_symlink():
        path.unlink()
    elif path.is_junction():
        path.rmdir()
    elif path.exists():
        shutil.rmtree(path)


def link_data(link: Path, data: Path) -> None:
    data.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(data), str(link))
    else:
        link.symlink_to(data, target_is_directory=True)


def prepare_data(root: Path, data: Path) -> Path:
    """Migrate existing inline data once; a failed migration restores its path."""
    link = root / "data"
    if link.exists() and link.resolve() == data.resolve():
        return data
    backup = root / f".data-migration-{uuid.uuid4().hex}"
    if link.exists():
        if data.exists() and any(data.iterdir()):
            raise ValueError(f"both inline and shared plugin data exist: {link}; resolve before loading")
        # Copy before unlinking anything. Disk-full and copy failures leave the
        # original untouched, including plugin-owned environments and reports.
        shutil.copytree(link, data, dirs_exist_ok=True)
        link.rename(backup)
    try:
        link_data(link, data)
    except BaseException:
        if backup.exists():
            backup.rename(link)
        raise
    remove_tree(backup)
    return data


class CodeTransaction:
    """A same-volume code swap kept reversible until runtime validation commits."""
    def __init__(self, target: Path, source: Path, data: Path) -> None:
        self.target = target
        self.work = Path(tempfile.mkdtemp(prefix=".plugin-txn-", dir=target.parent))
        self.staging = self.work / "new"
        self.backup = self.work / "old"
        self.installed = False
        self.had_old = target.exists()
        self.record = {"format": 1, "target": target.name, "had_old": self.had_old, "pid": os.getpid(), "committed": False}
        self._journal()
        try:
            shutil.copytree(source, self.staging, ignore=shutil.ignore_patterns("data", "__pycache__", ".pytest_cache"))
            if self.had_old:
                prepare_data(target, data)
            link_data(self.staging / "data", data)
            if self.had_old:
                os.replace(target, self.backup)
            try:
                os.replace(self.staging, target)
                self.installed = True
            except BaseException:
                if self.backup.exists():
                    os.replace(self.backup, target)
                raise
        except BaseException:
            # A backup is recovery material, never sweep it after a failed
            # rollback. Leave its exact location in the raised exception.
            if not self.backup.exists():
                remove_tree(self.work)
            raise

    def rollback(self) -> None:
        if self.installed:
            failed = self.work / "failed"
            os.replace(self.target, failed)
            if self.backup.exists():
                try:
                    os.replace(self.backup, self.target)
                except BaseException:
                    os.replace(failed, self.target)
                    raise
            self.installed = False
        remove_tree(self.work)

    def _journal(self):
        # user:“该重建就重建”+(崩溃时保留完整账本，不能截断唯一恢复记录)。
        path = self.work / "transaction.json"
        temporary = self.work / "transaction.tmp"
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(self.record, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def commit(self) -> None:
        self.record["committed"] = True
        self._journal()
        # user:“该重建就重建”+(提交成功后旧目录占用只延后清理，不能回滚新版本)。
        try:
            for child in self.work.iterdir():
                if child.is_dir():
                    remove_tree(child)
            remove_tree(self.work)
        except OSError:
            pass


def recover_transactions(root):
    # user:“该重建就重建”+(只恢复已退出进程的有账本事务，绝不盲删备份)。
    for work in root.glob(".plugin-txn-*"):
        journal = work / "transaction.json"
        if not journal.is_file():
            continue
        record = json.loads(journal.read_text(encoding="utf-8"))
        name = str(record.get("target", ""))
        if record.get("format") != 1 or not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError(f"invalid plugin recovery journal: {journal}")
        if record.get("committed"):
            # user:“该重建就重建”+(旧文件仍被占用时不得阻塞已提交版本启动)。
            try:
                for child in work.iterdir():
                    if child.is_dir():
                        remove_tree(child)
                remove_tree(work)
            except OSError:
                pass
            continue
        pid = int(record.get("pid") or 0)
        if pid > 0:
            try:
                if os.name == "nt":
                    import ctypes
                    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                    kernel.OpenProcess.restype = ctypes.c_void_p
                    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                    process = kernel.OpenProcess(0x1000, False, pid)
                    if process:
                        kernel.CloseHandle(process)
                        continue
                else:
                    os.kill(pid, 0)
                    continue
            except ProcessLookupError:
                pass
        target = root / name
        backup = work / "old"
        if backup.exists():
            if target.exists():
                os.replace(target, work / "interrupted")
            os.replace(backup, target)
        elif not record.get("had_old") and target.exists():
            remove_tree(target)
        remove_tree(work)
