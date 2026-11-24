"""Everything 接入：用本机已有索引做全盘文件名/路径检索。

user:“自动检测本机 Everything 可用状态；对已安装且运行的兼容版本直接连接；
使用 Everything 现有索引，不重新扫描整个硬盘”+(这里只做一件事：把用户
的搜索意图翻译成 Everything 查询，再把结果读回来。索引、变更追踪、磁盘
扫描都归 Everything，Sunday 不建第二套索引)。

接入方式是 voidtools 官方命令行 ES。它通过 Everything 自己的 IPC 查询，
不需要开 HTTP 服务、不装额外服务、不碰用户配置；ES 不在时明确报告原因。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import csv
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Iterable
import urllib.request
import zipfile

_CREATE_NO_WINDOW = 0x08000000
# voidtools 官方发布的 ES 命令行包；只在用户点「下载查询工具」时使用。
ES_DOWNLOAD_URL = "https://www.voidtools.com/ES-1.1.0.26.zip"
ES_MIN_BYTES = 20_000
ES_MAX_BYTES = 10 * 1024 * 1024

# 文件类型 → 扩展名。搜索时合并成一条 ext: 条件，交给 Everything 过滤。
KIND_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "image": (
        "jpg", "jpeg", "png", "gif", "webp", "bmp", "avif", "tif", "tiff",
        "svg", "heic", "heif", "ico", "psd", "ai", "raw", "cr2", "nef", "arw", "dng",
    ),
    "video": ("mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg", "ts", "3gp"),
    "audio": ("mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "opus", "aiff", "ape"),
    "document": (
        "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md", "rtf",
        "csv", "json", "xml", "html", "htm", "epub", "log", "yaml", "yml", "toml",
        "py", "js", "ts", "vue", "rs", "go", "java", "c", "cpp", "h", "css", "scss",
    ),
    "archive": ("zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso", "cab", "zst"),
}

SORT_KEYS = {
    "relevance": "name",
    "name": "name",
    "path": "path",
    "size": "size",
    "date_modified": "date-modified",
    "date_created": "date-created",
}

_MAX_COUNT_CACHE = 256
_COUNT_TTL_SECONDS = 4.0


class EverythingError(RuntimeError):
    """查询失败；``code`` 供上层区分“没装 / 没跑 / 查询失败”。"""

    def __init__(self, code: str, message: str, *, hint: str = "", detail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.hint = hint
        self.detail = detail

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": str(self),
            "hint": self.hint,
            "detail": self.detail,
        }


@dataclass(slots=True)
class SearchSpec:
    query: str = ""
    kinds: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    scope: str = ""
    size_min: int | None = None
    size_max: int | None = None
    modified_within_days: int | None = None
    created_within_days: int | None = None
    sort: str = "relevance"
    descending: bool = False
    offset: int = 0
    limit: int = 60
    match_path: bool = False
    regex: bool = False
    case_sensitive: bool = False

    @property
    def folders_only(self) -> bool:
        return len(self.kinds) == 1 and self.kinds[0] == "folder"

    @property
    def file_kinds(self) -> list[str]:
        return [kind for kind in self.kinds if kind in KIND_EXTENSIONS]

    def normalized(self) -> "SearchSpec":
        return SearchSpec(
            query=str(self.query or "").strip(),
            kinds=[str(item).strip().lower() for item in self.kinds if str(item).strip()],
            extensions=[str(item).strip().lstrip(".").lower() for item in self.extensions if str(item).strip()],
            scope=str(self.scope or "").strip(),
            size_min=max(0, int(self.size_min)) if self.size_min is not None else None,
            size_max=max(0, int(self.size_max)) if self.size_max is not None else None,
            modified_within_days=max(1, int(self.modified_within_days)) if self.modified_within_days else None,
            created_within_days=max(1, int(self.created_within_days)) if self.created_within_days else None,
            sort=str(self.sort or "relevance").strip().lower(),
            descending=bool(self.descending),
            offset=max(0, int(self.offset or 0)),
            limit=min(500, max(1, int(self.limit or 60))),
            match_path=bool(self.match_path),
            regex=bool(self.regex) or str(self.query or "").strip().lower().startswith("regex:"),
            case_sensitive=bool(self.case_sensitive),
        )


@dataclass(slots=True)
class FileHit:
    path: str
    name: str
    directory: str
    extension: str
    size: int
    modified_at: str
    created_at: str
    attributes: str
    is_dir: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "directory": self.directory,
            "extension": self.extension,
            "size": self.size,
            "modified_at": self.modified_at,
            "created_at": self.created_at,
            "is_dir": self.is_dir,
        }


@dataclass(slots=True)
class SearchPage:
    items: list[FileHit]
    total: int | None
    offset: int
    limit: int
    elapsed_ms: int
    query: str
    count_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "total": self.total,
            "offset": self.offset,
            "limit": self.limit,
            "elapsed_ms": self.elapsed_ms,
            "query": self.query,
            "count_error": self.count_error,
        }


def _format_date(value: date | None) -> str:
    return value.isoformat() if value is not None else ""


def compile_query(spec: SearchSpec) -> str:
    """把结构化筛选合并进 Everything 查询表达式。

    user:“高级表达式与普通筛选控件应能协同工作，且不会意外改变搜索含义”
    +(用户自己写的 size:/dm:/regex: 原样保留，界面筛选只追加自己那一部分，
    不覆盖、不改写用户表达式)。
    """
    normalized = spec.normalized()
    tokens: list[str] = []
    query = normalized.query
    if query.lower().startswith("regex:"):
        query = query[len("regex:"):].strip()
    if query:
        tokens.append(query)
    if not normalized.folders_only:
        extensions = list(normalized.extensions)
        for kind in normalized.file_kinds:
            extensions.extend(KIND_EXTENSIONS.get(kind, ()))
        seen: list[str] = []
        for ext in extensions:
            if ext and ext not in seen:
                seen.append(ext)
        if seen:
            tokens.append("ext:" + ";".join(seen))
    if normalized.size_min is not None:
        tokens.append(f"size:>={normalized.size_min}")
    if normalized.size_max is not None:
        tokens.append(f"size:<={normalized.size_max}")
    today = date.today()
    if normalized.modified_within_days:
        cutoff = today - timedelta(days=normalized.modified_within_days)
        tokens.append(f"dm:>={_format_date(cutoff)}")
    if normalized.created_within_days:
        cutoff = today - timedelta(days=normalized.created_within_days)
        tokens.append(f"dc:>={_format_date(cutoff)}")
    return " ".join(token for token in tokens if token).strip()


def _decode_output(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "mbcs"):
        try:
            return payload.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", "replace")


def default_es_dir(data_dir: str | Path | None = None) -> Path:
    """应用自己的工具目录；安装版指向可写的用户数据目录，不写 Program Files。"""
    if data_dir:
        return Path(data_dir) / "tools"
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "Sunday" / "tools"


def _is_pe_file(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(2) == b"MZ"
    except OSError:
        return False


def install_es(
    target_dir: str | Path,
    *,
    url: str | None = None,
    zip_bytes: bytes | None = None,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """把官方 ES 下载并放到应用数据目录；只在用户明确点击时调用。

    user:“支持经过验证的安装引导或合法打包分发”“不静默安装第三方服务”
    +(下载的是 voidtools 官方发布的单文件命令行工具，不装服务、不改 Everything
    配置；失败时保留原状并说明原因，用户仍可手工放置 es.exe)。
    """
    target_dir = Path(target_dir)
    target = target_dir / "es.exe"
    if target.is_file() and target.stat().st_size >= ES_MIN_BYTES and _is_pe_file(target):
        return {
            "installed": False,
            "already_present": True,
            "path": str(target),
            "bytes": target.stat().st_size,
            "version": "",
        }
    target_dir.mkdir(parents=True, exist_ok=True)
    payload = zip_bytes
    if payload is None:
        source = url or os.environ.get("SUNDAY_EVERYTHING_ES_URL") or ES_DOWNLOAD_URL
        headers = {"User-Agent": "Sunday/1.0 (+https://lamtools.local)"}
        try:
            # 打包版用 requests（随包带 certifi），避免冻结解释器没有系统 CA。
            import requests

            # user:“全部审查，提交，发布”+(下载到上限即停止读流，避免把超大响应装进内存)。
            collected = bytearray()
            with requests.get(source, timeout=(10.0, timeout), headers=headers, stream=True) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    collected.extend(chunk)
                    if len(collected) > ES_MAX_BYTES:
                        break
            payload = collected
        except ImportError:
            try:
                request = urllib.request.Request(source, headers=headers)
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    payload = response.read(ES_MAX_BYTES + 1)
            except Exception as exc:  # noqa: BLE001
                raise EverythingError(
                    "install_failed",
                    "下载 Everything 查询工具失败",
                    hint="检查网络或代理后重试；也可以把官方 ES.exe 放到应用数据目录的 tools 文件夹。",
                    detail=f"{type(exc).__name__}: {exc}",
                ) from exc
        except Exception as exc:  # noqa: BLE001 - 网络栈异常类型很多，统一给出可操作提示
            raise EverythingError(
                "install_failed",
                "下载 Everything 查询工具失败",
                hint="检查网络或代理后重试；也可以把官方 ES.exe 放到应用数据目录的 tools 文件夹。",
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc
    if len(payload) > ES_MAX_BYTES:
        raise EverythingError(
            "install_failed",
            "下载内容异常（超过预期大小）",
            hint="稍后重试，或手工放置官方 ES.exe。",
        )
    if not payload:
        raise EverythingError("install_failed", "下载内容为空", hint="稍后重试。")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            member = next(
                (name for name in archive.namelist() if name.lower().endswith("es.exe")),
                "",
            )
            if not member:
                raise EverythingError(
                    "install_failed",
                    "下载包里没有找到 es.exe",
                    hint="稍后重试，或手工放置官方 ES.exe。",
                )
            if archive.getinfo(member).file_size > ES_MAX_BYTES:
                raise EverythingError("install_failed", "下载内容异常（超过预期大小）")
            data = archive.read(member)
    except zipfile.BadZipFile as exc:
        raise EverythingError(
            "install_failed",
            "下载内容不是有效的压缩包",
            hint="稍后重试，或手工放置官方 ES.exe。",
            detail=str(exc),
        ) from exc
    if len(data) < ES_MIN_BYTES or data[:2] != b"MZ":
        raise EverythingError(
            "install_failed",
            "下载到的查询工具不可用",
            hint="稍后重试，或从 voidtools 官方下载 ES.exe 手工放置。",
        )
    temporary = target.with_name("es.exe.download")
    temporary.write_bytes(data)
    os.replace(temporary, target)
    version = ""
    try:
        completed = subprocess.run(
            [str(target), "-version"],
            capture_output=True,
            timeout=10.0,
            creationflags=_CREATE_NO_WINDOW if os.name == "nt" else 0,
            check=False,
        )
        version = _decode_output(completed.stdout).strip().splitlines()[0] if completed.stdout else ""
    except (OSError, subprocess.SubprocessError):
        version = ""
    return {
        "installed": True,
        "already_present": False,
        "path": str(target),
        "bytes": len(data),
        "version": version,
    }


class EverythingProvider:
    """A thin, replaceable client over the local Everything index."""

    def __init__(
        self,
        *,
        data_dir: str | Path | None = None,
        es_path: str | Path | None = None,
        timeout: float = 8.0,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir else None
        self._explicit_es = str(es_path) if es_path else os.environ.get("SUNDAY_EVERYTHING_ES", "")
        self.timeout = max(1.0, float(timeout))
        self._es_path: str | None = None
        self._es_resolved = False
        self._status: dict[str, Any] | None = None
        self._status_at = 0.0
        self._count_cache: dict[str, tuple[float, int | None]] = {}
        self._count_lock = threading.Lock()

    # -- discovery -----------------------------------------------------
    def es_install_dir(self) -> Path:
        return default_es_dir(self.data_dir)

    def refresh(self) -> None:
        """安装/移动 ES 后重新探测，不重启后端。"""
        self._es_path = None
        self._es_resolved = False
        self._status = None
        self._status_at = 0.0
        with self._count_lock:
            self._count_cache.clear()

    def _candidates(self) -> Iterable[Path]:
        if self._explicit_es:
            yield Path(self._explicit_es)
        yield self.es_install_dir() / "es.exe"
        # Everything 安装目录：有些用户会把 ES.exe 放在 Everything.exe 旁边。
        installed = self._everything_install_path()
        if installed:
            yield Path(installed).parent / "es.exe"
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env_name)
            if base:
                yield Path(base) / "Everything" / "es.exe"
        local = os.environ.get("LOCALAPPDATA")
        if local:
            yield Path(local) / "Programs" / "Everything" / "es.exe"
        # 打包版资源目录：安装器可以把 ES.exe 放在 resources/everything 下。
        executable = Path(sys.executable).resolve().parent
        bundle = getattr(sys, "_MEIPASS", "")
        for base in (
            Path(bundle) if bundle else None,
            executable,
            executable / "resources",
            executable / "resources" / "everything",
            executable / "everything",
        ):
            if base is not None:
                yield base / "es.exe"
        # 开发/本机验证路径；发布版不依赖仓库位置。
        repo_root = Path(__file__).resolve().parents[4]
        yield repo_root / ".tools" / "everything" / "es.exe"
        found = shutil.which("es.exe")
        if found:
            yield Path(found)

    def resolve_es_path(self) -> str | None:
        if self._es_resolved:
            return self._es_path
        self._es_resolved = True
        for candidate in self._candidates():
            try:
                if candidate.is_file():
                    self._es_path = str(candidate)
                    break
            except OSError:
                continue
        return self._es_path

    @staticmethod
    def _everything_install_path() -> str:
        candidates = []
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env_name)
            if base:
                candidates.append(Path(base) / "Everything" / "Everything.exe")
        try:
            import winreg

            for root, key in (
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\voidtools\Everything"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\voidtools\Everything"),
            ):
                try:
                    with winreg.OpenKey(root, key) as handle:
                        value, _ = winreg.QueryValueEx(handle, "InstallLocation")
                        if value:
                            candidates.append(Path(value) / "Everything.exe")
                except OSError:
                    continue
        except ImportError:
            pass
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return str(candidate)
            except OSError:
                continue
        return ""

    # -- process -------------------------------------------------------
    def _run(self, args: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[bytes]:
        es_path = self.resolve_es_path()
        if not es_path:
            raise EverythingError(
                "missing_cli",
                "没有找到 Everything 命令行工具（ES），暂时无法全盘搜索",
                hint=f"在 Library 状态条点「下载查询工具」，或把官方 ES.exe 放到 {self.es_install_dir()}。",
            )
        creationflags = _CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            return subprocess.run(
                [es_path, *args],
                capture_output=True,
                timeout=timeout or self.timeout,
                creationflags=creationflags,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise EverythingError(
                "timeout",
                "Everything 没有在预期时间内返回结果",
                hint="稍后重试；如果正在重建索引，等索引完成后再搜。",
                detail=str(exc),
            ) from exc
        except OSError as exc:
            raise EverythingError("launch_failed", "无法启动 Everything 查询工具", detail=str(exc)) from exc

    @staticmethod
    def _error_from(result: subprocess.CompletedProcess[bytes], *, action: str) -> EverythingError:
        detail = (_decode_output(result.stderr) or _decode_output(result.stdout)).strip()
        lowered = detail.lower()
        if "not running" in lowered or "unable to connect" in lowered or "ipc" in lowered:
            return EverythingError(
                "not_running",
                "Everything 没有在运行，无法全盘搜索",
                hint="启动 Everything 后重试；普通文件浏览和已保存的资产信息不受影响。",
                detail=detail,
            )
        if "unknown" in lowered and "switch" in lowered:
            return EverythingError(
                "incompatible",
                "当前 Everything 命令行工具版本与查询方式不兼容",
                hint="更新 Everything 与 ES 后再试。",
                detail=detail,
            )
        return EverythingError("query_failed", f"{action}失败", hint="稍后重试。", detail=detail)

    # -- status --------------------------------------------------------
    def status(self, *, refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if not refresh and self._status is not None and now - self._status_at < 5.0:
            return dict(self._status)
        es_path = self.resolve_es_path()
        installed = self._everything_install_path()
        payload: dict[str, Any] = {
            "state": "ready",
            "available": False,
            "es_path": es_path or "",
            "es_install_dir": str(self.es_install_dir()),
            "can_install": bool(not es_path and os.name == "nt"),
            "everything_path": installed,
            "everything_version": "",
            "cli_version": "",
            "message": "",
            "hint": "",
            "indexed_items": None,
        }
        if not es_path:
            payload.update(
                state="missing_cli" if installed else "not_installed",
                message=(
                    "已安装 Everything，但还没有可用的命令行查询工具"
                    if installed
                    else "这台电脑上没有检测到 Everything"
                ),
                hint=(
                    f"点「下载查询工具」自动安装到 {self.es_install_dir()}，"
                    "或把 voidtools 官方的 ES.exe 放到这个目录后重试。"
                    if installed
                    else "安装 Everything 后即可在 Library 内搜索整台电脑；目录浏览与资产功能不受影响。"
                ),
            )
            self._status, self._status_at = payload, now
            return dict(payload)
        try:
            cli = self._run(["-version"], timeout=4.0)
            payload["cli_version"] = _decode_output(cli.stdout).strip().splitlines()[0] if cli.stdout else ""
        except EverythingError:
            pass
        probe = self._run(["-get-everything-version"], timeout=4.0)
        version = _decode_output(probe.stdout).strip()
        if probe.returncode != 0 or not version:
            error = self._error_from(probe, action="连接 Everything")
            payload.update(
                state=error.code if error.code in {"not_running", "incompatible"} else "error",
                message=str(error),
                hint=error.hint,
            )
            self._status, self._status_at = payload, now
            return dict(payload)
        payload["everything_version"] = version
        try:
            major_minor = tuple(int(part) for part in version.split(".")[:2])
            if major_minor < (1, 4):
                payload.update(
                    state="incompatible",
                    message=f"Everything 版本 {version} 过旧，无法稳定支持当前查询",
                    hint="升级到 Everything 1.4 或更新版本。",
                )
                self._status, self._status_at = payload, now
                return dict(payload)
        except ValueError:
            pass
        payload.update(state="ready", available=True, message="Everything 索引可用")
        try:
            payload["indexed_items"] = self._count_uncached("*", SearchSpec())
        except EverythingError:
            payload["indexed_items"] = None
        self._status, self._status_at = payload, now
        return dict(payload)

    # -- query ---------------------------------------------------------
    def _filter_args(self, spec: SearchSpec) -> list[str]:
        args: list[str] = []
        normalized = spec.normalized()
        if normalized.scope:
            args.extend(["-path", normalized.scope])
        if normalized.folders_only:
            args.append("/ad")
        if normalized.match_path:
            args.append("-p")
        if normalized.case_sensitive:
            args.append("-i")
        return args

    def _count_uncached(self, query: str, spec: SearchSpec) -> int | None:
        cache_key = query + "\x00" + "\x00".join(self._filter_args(spec))
        now = time.monotonic()
        with self._count_lock:
            cached = self._count_cache.get(cache_key)
            if cached and now - cached[0] < _COUNT_TTL_SECONDS:
                return cached[1]
        result = self._run(["-get-result-count", *self._filter_args(spec), query or "*"])
        if result.returncode != 0:
            return None
        text = _decode_output(result.stdout).strip()
        try:
            total = int(text)
        except ValueError:
            total = None
        with self._count_lock:
            if len(self._count_cache) >= _MAX_COUNT_CACHE:
                self._count_cache.clear()
            self._count_cache[cache_key] = (now, total)
        return total

    def count(self, query: str, *, spec: SearchSpec | None = None) -> int | None:
        """按已经编译好的查询计数；不再二次拼接 ext，避免同类条件互相 AND。"""
        base = (spec or SearchSpec()).normalized()
        if not query.strip():
            return 0
        return self._count_uncached(query, base)

    def search(self, spec: SearchSpec) -> SearchPage:
        started = time.perf_counter()
        normalized = spec.normalized()
        query = compile_query(normalized)
        if not query:
            return SearchPage(
                items=[],
                total=0,
                offset=normalized.offset,
                limit=normalized.limit,
                elapsed_ms=0,
                query="",
            )
        sort_key = SORT_KEYS.get(normalized.sort, "name")
        args: list[str] = []
        with tempfile.NamedTemporaryFile(prefix="sunday-es-", suffix=".csv", delete=False) as handle:
            export_path = handle.name
        try:
            args.extend([
                "-export-csv", export_path,
                "-no-header", "-utf8-bom",
                "-name", "-path-column", "-size", "-date-modified", "-date-created",
                "-extension", "-attributes",
                "-date-format", "1", "-size-format", "1",
            ])
            args.extend(["-sort", sort_key])
            if normalized.descending:
                args.append("-sort-descending")
            args.extend(["-o", str(normalized.offset), "-n", str(normalized.limit)])
            args.extend(self._filter_args(normalized))
            if normalized.regex:
                args.append("-r")
            args.append(query)
            # 计数与列表导出互不依赖：并发跑，首批结果少等一次进程启动。
            with ThreadPoolExecutor(max_workers=2) as pool:
                count_future = pool.submit(self.count, query, spec=normalized)
                result = self._run(args)
                if result.returncode != 0:
                    raise self._error_from(result, action="搜索")
                try:
                    with io.open(export_path, "r", encoding="utf-8-sig", newline="") as handle:
                        rows = list(csv.reader(handle))
                except FileNotFoundError:
                    rows = []
                count_error = ""
                try:
                    total = count_future.result()
                except EverythingError as exc:
                    total = None
                    count_error = str(exc)
        finally:
            try:
                os.unlink(export_path)
            except OSError:
                pass

        items: list[FileHit] = []
        for row in rows:
            if len(row) < 7:
                continue
            name, directory, size, modified, created, extension, attributes = row[:7]
            if not name:
                continue
            full_path = str(Path(directory) / name) if directory else name
            try:
                size_value = int(size or 0)
            except ValueError:
                size_value = 0
            items.append(FileHit(
                path=full_path,
                name=name,
                directory=directory,
                extension=extension.lower(),
                size=size_value,
                modified_at=modified,
                created_at=created,
                attributes=attributes,
                is_dir="D" in attributes.upper(),
            ))
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return SearchPage(
            items=items,
            total=total,
            offset=normalized.offset,
            limit=normalized.limit,
            elapsed_ms=elapsed_ms,
            query=query,
            count_error=count_error,
        )
