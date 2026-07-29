"""Desktop entry point for LamTools Core.

On first launch this module automatically creates a user data directory
under %APPDATA%/LamCore (or the platform equivalent) and seeds a default
LLM config database with an empty API key.  The user then fills in their
key from the Settings UI.

The launcher starts the FastAPI backend in a background thread, then opens
a standalone Edge WebView2 app window pointed at the backend.  When the
window is closed and no client has connected for a while the process exits
cleanly, freeing the port for the next launch.
"""

from __future__ import annotations

import io as _io
import logging
import multiprocessing
import os
import platform
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s [%(name)s] %(message)s",
)
_log = logging.getLogger("lamcore.desktop")


# =========================================================================
# Platform helpers
# =========================================================================

def _user_data_dir() -> Path:
    """Return the per-user data directory, creating it if necessary."""
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(
            os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
        )
    d = base / "LamCore"
    d.mkdir(parents=True, exist_ok=True)
    return d


# =========================================================================
# Config DB seeding (first-run)
# =========================================================================

def _ensure_config_db(config_db: Path) -> None:
    """Create the shared config DB and seed a default provider/model if empty."""
    from lamtools_core.config.shared_database import SharedConfigBase
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{config_db}")
    SharedConfigBase.metadata.create_all(engine)

    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM llm_providers")
        ).scalar()
        if count and count > 0:
            engine.dispose()
            return

    conn_raw = sqlite3.connect(str(config_db))
    try:
        conn_raw.execute(
            "INSERT INTO llm_providers "
            "(id, name, api_type, base_url, api_key, is_default, created_at, updated_at) "
            "VALUES ('default', 'Default Provider', 'openai', '', '', 1, "
            "datetime('now'), datetime('now'))"
        )
        conn_raw.execute(
            "INSERT INTO llm_models "
            "(id, provider_id, model_id, display_name, "
            "context_window, max_output_tokens, thinking_supported, thinking_budget, "
            "temperature, is_default, created_at, updated_at) "
            "VALUES ('default-model', 'default', '', 'Default Model', "
            "128000, 16384, 1, 10000, 0.7, 1, datetime('now'), datetime('now'))"
        )
        conn_raw.commit()
    finally:
        conn_raw.close()
    engine.dispose()


# =========================================================================
# Bundled resource resolution (PyInstaller / dev)
# =========================================================================

def _bundled_path(*parts: str) -> Path:
    """Resolve a path relative to the PyInstaller bundle or source tree."""
    _meipass = getattr(sys, "_MEIPASS", None)
    if _meipass and Path(_meipass).is_dir():
        return Path(_meipass).joinpath(*parts)

    this_file = Path(__file__).resolve()
    repo_root = this_file.parent.parent

    _DEV_REMAP: dict[str, str] = {
        "frontend": "core/ui/dist-core-app",
        "skills": "core/skills",
        "command": "core/config/command",
        "llm_adapters": "core/config/llm_adapters",
    }
    first = parts[0] if parts else ""
    if first in _DEV_REMAP and len(parts) == 1:
        return repo_root / _DEV_REMAP[first]
    return repo_root.joinpath(*parts)


# =========================================================================
# Port management
# =========================================================================

_PORT_START = 5172
_PORT_MAX = 30  # scan _PORT_START … _PORT_START + _PORT_MAX - 1


def _find_free_port(start: int = _PORT_START, count: int = _PORT_MAX) -> int:
    """Return the first free port in [start, start+count)."""
    for port in range(start, start + count):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError(
        f"No free port in range {start}–{start + count - 1}"
    )


def _is_lamcore_port(port: int, timeout: float = 0.5) -> bool:
    """Check whether a running LamCore instance owns the given port."""
    import httpx

    try:
        resp = httpx.get(
            f"http://127.0.0.1:{port}/api/health", timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("status") == "ok"
    except Exception:
        return False


def _kill_port_process(port: int) -> None:
    """Kill the process listening on *port* (Windows)."""
    if platform.system() != "Windows":
        return
    _cf = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                            creationflags=_cf)
    for line in result.stdout.splitlines():
        if f"127.0.0.1:{port}" in line and "LISTENING" in line:
            pid = int(line.split()[-1])
            _log.info("Killing PID %d on port %d", pid, port)
            subprocess.run(["taskkill", "/f", "/pid", str(pid)], capture_output=True,
                           creationflags=_cf)
            return


# =========================================================================
# Server thread
# =========================================================================

def _run_server(app, host: str, port: int) -> None:
    """Run uvicorn in the current thread (intended for a daemon thread)."""
    # PyInstaller with console=False sets sys.stdout/stderr to None.
    if sys.stdout is None:
        sys.stdout = _io.StringIO()
    if sys.stderr is None:
        sys.stderr = _io.StringIO()
    try:
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        server.run()
    except Exception:
        _log.exception("uvicorn server crashed")
        raise


# =========================================================================
# Health-check wait
# =========================================================================

def _wait_for_health(url: str, timeout: float = 30.0) -> None:
    """Poll /api/health until the server responds or timeout expires."""
    import httpx

    deadline = time.monotonic() + timeout
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(url, timeout=1.0)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "ok":
                return
            last_error = f"unexpected response: {data}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(
        f"Server did not become healthy within {timeout}s: {last_error}"
    )


# =========================================================================
# Edge app window
# =========================================================================

def _find_edge() -> str:
    """Return the path to Microsoft Edge, or empty string."""
    import shutil as _shutil

    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    from_path = _shutil.which("msedge")
    if from_path:
        candidates.insert(0, from_path)
    for p in candidates:
        if Path(p).is_file():
            return p
    return ""


def _open_app_window(url: str) -> subprocess.Popen | None:
    """Open a standalone Edge app window (no browser chrome)."""
    edge = _find_edge()
    if edge:
        _cf = subprocess.CREATE_NO_WINDOW
        return subprocess.Popen(
            [edge, f"--app={url}", "--new-window"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_cf,
        )
    import webbrowser as _wb
    _wb.open(url)
    return None


# =========================================================================
# Idle detection
# =========================================================================

def _count_active_connections(port: int) -> int:
    """Count ESTABLISHED connections to *port* on 127.0.0.1."""
    count = 0
    needle = f"127.0.0.1:{port}"
    _cf = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5,
            creationflags=_cf,
        )
        for line in result.stdout.splitlines():
            if needle in line and "ESTABLISHED" in line:
                count += 1
    except Exception:
        pass
    return count


def _wait_for_idle(port: int, check_seconds: float = 5.0, idle_checks: int = 12) -> None:
    """Block until no client has connected for *idle_checks* × *check_seconds*.

    When the user closes the Edge window the WebSocket connections drop.
    After ~60 s of inactivity the process exits, freeing the port for
    the next launch.
    """
    idle_streak = 0
    while True:
        time.sleep(check_seconds)
        active = _count_active_connections(port)
        if active > 0:
            idle_streak = 0
        else:
            idle_streak += 1
            if idle_streak >= idle_checks:
                _log.info("Idle timeout — shutting down.")
                return


# =========================================================================
# Main
# =========================================================================

def main() -> None:
    if os.name == "nt":
        multiprocessing.freeze_support()

    # ------------------------------------------------------------------
    # 1. 端口寻址（第一件事）
    # ------------------------------------------------------------------
    port = _find_free_port()
    if port != _PORT_START and _is_lamcore_port(_PORT_START):
        _kill_port_process(_PORT_START)
        time.sleep(0.5)
        port = _PORT_START
    elif port != _PORT_START:
        _log.warning("Port %d occupied (non-LamCore), using %d", _PORT_START, port)
    url = f"http://127.0.0.1:{port}"

    # ------------------------------------------------------------------
    # 2. 日志文件
    # ------------------------------------------------------------------
    data_dir = _user_data_dir()
    log_file = data_dir / "lamcore.log"
    _fh = logging.FileHandler(str(log_file), encoding="utf-8", delay=True)
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    logging.getLogger().addHandler(_fh)
    for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        _ul = logging.getLogger(_name)
        _ul.addHandler(_fh)
        _ul.setLevel(logging.DEBUG)
    _log.info("=== LamCore starting on port %d (log: %s) ===", port, log_file)

    # ------------------------------------------------------------------
    # 3. 资源路径
    # ------------------------------------------------------------------
    frontend_dir = _bundled_path("frontend")
    _log.info("Frontend dir: %s", frontend_dir)

    # ------------------------------------------------------------------
    # 4. 数据目录 / DB 播种
    # ------------------------------------------------------------------
    config_db = data_dir / "config.db"
    core_db = data_dir / "core.db"
    work_root = data_dir / "workspace"
    work_root.mkdir(parents=True, exist_ok=True)
    _ensure_config_db(config_db)

    # ------------------------------------------------------------------
    # 5. 环境变量
    # ------------------------------------------------------------------
    os.environ["LAMTOOLS_LLM_CONFIG_DB"] = str(config_db)
    os.environ.setdefault("LAMTOOLS_CORE_DATA_DIR", str(data_dir))
    os.environ.setdefault("LAMTOOLS_CORE_WORK_ROOT", str(work_root))
    os.environ["LAMTOOLS_CORE_PORT"] = str(port)
    if (skills_dir := _bundled_path("skills")).is_dir():
        os.environ.setdefault("LAMTOOLS_CORE_SKILLS_DIR", str(skills_dir))
    if (command_dir := _bundled_path("command")).is_dir():
        os.environ.setdefault("LAMTOOLS_CORE_COMMAND_DIR", str(command_dir))
    if (adapters_dir := _bundled_path("llm_adapters")).is_dir():
        os.environ.setdefault("LAMTOOLS_CORE_ADAPTERS_DIR", str(adapters_dir))

    # ------------------------------------------------------------------
    # 6. 构建 FastAPI app
    # ------------------------------------------------------------------
    from lamtools_core.app.http_agent_app import create_core_agent_http_app

    app = create_core_agent_http_app(
        model_id="",
        config_db=str(config_db),
        core_db=str(core_db),
        data_dir=str(data_dir),
        work_root=str(work_root),
        frontend_dir=str(frontend_dir) if frontend_dir.is_dir() else None,
    )

    # ------------------------------------------------------------------
    # 7. 启动 uvicorn（daemon 线程）
    # ------------------------------------------------------------------
    server_thread = threading.Thread(
        target=_run_server,
        args=(app, "127.0.0.1", port),
        daemon=True,
        name="uvicorn-server",
    )
    server_thread.start()
    time.sleep(0.5)

    # ------------------------------------------------------------------
    # 8. 等就绪
    # ------------------------------------------------------------------
    _log.info("Waiting for health check (port %d) …", port)
    try:
        _wait_for_health(f"{url}/api/health", timeout=30.0)
    except RuntimeError as exc:
        _log.error("Server failed: %s", exc)
        time.sleep(10)
        sys.exit(1)
    _log.info("Server ready at %s", url)

    # ------------------------------------------------------------------
    # 9. 开 Edge 窗口
    # ------------------------------------------------------------------
    _open_app_window(url)

    # ------------------------------------------------------------------
    # 10. 空闲退出（关窗 60s 后自动释放端口）
    # ------------------------------------------------------------------
    _wait_for_idle(port)
    sys.exit(0)


if __name__ == "__main__":
    main()