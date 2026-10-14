"""Release 0.3.17 deployment entry point; only read-only preflight is enabled."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import cloud  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "preflight":
        raise SystemExit("Only the read-only action is enabled: preflight")
    cloud.preflight()