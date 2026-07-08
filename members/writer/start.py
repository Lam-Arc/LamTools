from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


WRITER_DIR = Path(__file__).resolve().parent
REPO_ROOT = WRITER_DIR.parent.parent
BACKEND_DIR = WRITER_DIR / "backend"
FRONTEND_DIR = WRITER_DIR / "frontend"
CORE_SRC_DIR = REPO_ROOT / "core" / "src"
DATA_DIR = WRITER_DIR / "data"
VENV_DIR = WRITER_DIR / "venv"
BACKEND_URL = "http://127.0.0.1:6173"
FRONTEND_URL = "http://127.0.0.1:6174"


def _creationflags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return 200 <= response.status < 500
    except OSError:
        return False


def _run_setup_command(args: list[str], *, cwd: Path) -> None:
    completed = subprocess.run(args, cwd=str(cwd), check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(args)}")


def _ensure_environment() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    python_exe = VENV_DIR / "Scripts" / "python.exe"
    if not python_exe.exists():
        _run_setup_command(["py", "-3.14", "-m", "venv", str(VENV_DIR)], cwd=WRITER_DIR)
        _run_setup_command(
            [str(python_exe), "-m", "pip", "install", "-r", str(BACKEND_DIR / "requirements.txt")],
            cwd=WRITER_DIR,
        )
    if not (FRONTEND_DIR / "node_modules").exists():
        _run_setup_command(["npm", "install"], cwd=FRONTEND_DIR)
    return python_exe


def _wait_until(url: str, *, seconds: int) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _http_ok(url):
            return True
        time.sleep(0.5)
    return False


def main() -> int:
    if _port_open(6173) and _port_open(6174):
        webbrowser.open(FRONTEND_URL)
        return 0

    try:
        python_exe = _ensure_environment()
    except Exception as exc:
        print(f"[ERROR] Setup failed: {exc}")
        return 1

    env = os.environ.copy()
    env["LAMWRITER_DATA_DIR"] = str(DATA_DIR)
    env["PYTHONPATH"] = str(CORE_SRC_DIR)

    backend = subprocess.Popen(
        [
            str(python_exe),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "6173",
        ],
        cwd=str(BACKEND_DIR),
        env=env,
        creationflags=_creationflags(),
    )
    if not _wait_until(f"{BACKEND_URL}/api/health", seconds=30):
        backend.terminate()
        print("[ERROR] Backend failed to start.")
        return 1

    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    frontend = subprocess.Popen(
        [npm_cmd, "run", "dev", "--", "--host", "127.0.0.1", "--port", "6174"],
        cwd=str(FRONTEND_DIR),
        creationflags=_creationflags(),
    )
    if not _wait_until(FRONTEND_URL, seconds=30):
        frontend.terminate()
        backend.terminate()
        print("[ERROR] Frontend failed to start.")
        return 1

    webbrowser.open(FRONTEND_URL)
    print("LamWriter started. Close this window to stop the services.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        frontend.terminate()
        backend.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
