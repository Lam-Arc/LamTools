import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Launcher entry point that delegates to members/writer/start.py."""
    # Determine repository root (directory containing this script/exe)
    if getattr(sys, "frozen", False):
        # PyInstaller bundle: executable directory
        repo_root = Path(sys.executable).resolve().parent
    else:
        # Development: script directory
        repo_root = Path(__file__).resolve().parent

    start_script = repo_root / "members" / "writer" / "start.py"

    if not start_script.exists():
        print(f"[ERROR] Start script not found: {start_script}")
        return 1

    # Delegate to the actual start script using system Python
    return subprocess.run(
        ["py", "-3.14", str(start_script)],
        cwd=str(repo_root),
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
