#!/usr/bin/env python3
"""Background novel generation launcher.

Usage:
  python novel_launcher.py [--chapters N] [--words W]

This starts the E2E script as a fully detached background process
that writes chapters to novel_output/ independently.

Use novel_monitor.py in another terminal to watch progress.
"""

import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
E2E_SCRIPT = BACKEND_DIR / "tests" / "run_novel_e2e.py"
OUTPUT_DIR = BACKEND_DIR / "novel_output"
PID_FILE = BACKEND_DIR / ".novel_pid"
STDOUT_LOG = OUTPUT_DIR / "gen_stdout.log"
STDERR_LOG = OUTPUT_DIR / "gen_stderr.log"

def start(chapters: int = 50, words: int = 5000):
    """Launch novel generation as detached process."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Modify TOTAL_CHAPTERS in the script before launching
    script = E2E_SCRIPT.read_text(encoding="utf-8")
    script = __import__('re').sub(
        r'TOTAL_CHAPTERS = \d+',
        f'TOTAL_CHAPTERS = {chapters}', script)
    script = __import__('re').sub(
        r'WORDS_PER_CHAPTER = \d+',
        f'WORDS_PER_CHAPTER = {words}', script)
    E2E_SCRIPT.write_text(script, encoding="utf-8")

    # Launch detached process
    if sys.platform == "win32":
        proc = subprocess.Popen(
            [sys.executable, "-u", str(E2E_SCRIPT)],
            cwd=str(BACKEND_DIR),
            stdout=open(str(STDOUT_LOG), "w", encoding="utf-8"),
            stderr=open(str(STDERR_LOG), "w", encoding="utf-8"),
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP
                | 0x00000008
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            ),
        )
    else:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(E2E_SCRIPT)],
            cwd=str(BACKEND_DIR),
            stdout=open(str(STDOUT_LOG), "w", encoding="utf-8"),
            stderr=open(str(STDERR_LOG), "w", encoding="utf-8"),
            start_new_session=True,
        )

    # Write PID for stop script
    PID_FILE.write_text(str(proc.pid))

    print(f"✓ Novel generation started (PID: {proc.pid})")
    print(f"  Chapters: {chapters} × ~{words} chars = ~{chapters * words:,} chars")
    print(f"  Output:   {OUTPUT_DIR}")
    print(f"  Log:      {STDOUT_LOG}")
    print(f"  Monitor:  python novel_monitor.py")
    print(f"  Stop:     python novel_launcher.py --stop")

def stop():
    """Stop the running generation process."""
    if not PID_FILE.exists():
        print("No running process found.")
        return
    pid = int(PID_FILE.read_text().strip())
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            import signal
            os.kill(pid, signal.SIGTERM)
        print(f"✓ Process {pid} stopped.")
    except Exception as e:
        print(f"Failed to stop: {e}")
    PID_FILE.unlink(missing_ok=True)

def status():
    """Check if generation is running."""
    if not PID_FILE.exists():
        print("No generation process found.")
        return
    pid = int(PID_FILE.read_text().strip())
    try:
        import psutil
        proc = psutil.Process(pid)
        print(f"Running (PID: {pid}, CPU: {proc.cpu_percent()}%, mem: {proc.memory_info().rss // 1024 // 1024}MB)")
    except ImportError:
        # Fallback: check if process exists via tasklist
        import subprocess
        result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
        if str(pid) in result.stdout:
            print(f"Running (PID: {pid})")
        else:
            print(f"Process {pid} not running (crashed or completed).")
            PID_FILE.unlink(missing_ok=True)
    except Exception:
        print(f"Process {pid} not running (crashed or completed).")
        PID_FILE.unlink(missing_ok=True)

if __name__ == "__main__":
    if "--stop" in sys.argv:
        stop()
    elif "--status" in sys.argv:
        status()
    else:
        chapters = 50
        words = 5000
        for i, arg in enumerate(sys.argv):
            if arg == "--chapters" and i + 1 < len(sys.argv):
                chapters = int(sys.argv[i + 1])
            if arg == "--words" and i + 1 < len(sys.argv):
                words = int(sys.argv[i + 1])
        start(chapters=chapters, words=words)
