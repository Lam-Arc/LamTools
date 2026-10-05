"""Read-only inspection of the pre-existing codex-api service and related units.

Secret values are masked; only key names and file metadata are printed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud import command  # noqa: E402

SCRIPT = r"""set -u
echo "=== codex-api unit ==="
systemctl cat codex-api.service --no-pager 2>/dev/null
echo "=== process cmdline ==="
tr '\0' ' ' < /proc/730/cmdline 2>/dev/null; echo
echo "=== /opt/lamtools ==="
ls -la /opt/lamtools 2>/dev/null
echo "=== /etc/lamtools (names + modes only) ==="
ls -la /etc/lamtools 2>/dev/null
echo "=== env files: KEY NAMES ONLY ==="
for f in /etc/lamtools/*.env; do
  [ -f "$f" ] || continue
  echo "--- $f ($(stat -c %a "$f"))"
  sed -E 's/=.*/=<masked>/' "$f"
done
echo "=== codex-api tree (depth 2) ==="
find /opt/lamtools/codex-api -maxdepth 2 -printf '%y %p %s\n' 2>/dev/null | head -40
echo "=== unit execstart ==="
systemctl show codex-api -p ExecStart -p User -p Group -p WorkingDirectory -p EnvironmentFiles --no-pager
echo "=== frps ==="
systemctl cat frps --no-pager 2>/dev/null | head -25
echo "=== cloudflared ==="
systemctl cat lamtools-cloudflared --no-pager 2>/dev/null | head -25
echo "=== local probe: codex-api ==="
curl -s -o /dev/null -w 'root=%{http_code}\n' -m 8 http://127.0.0.1:8322/ || true
curl -s -o /dev/null -w 'models_noauth=%{http_code}\n' -m 8 http://127.0.0.1:8322/v1/models || true
curl -s -m 8 http://127.0.0.1:8322/ | head -c 400; echo
echo "=== docker disk ==="
docker system df 2>&1 | head -10
echo "=== done ==="
"""

if __name__ == "__main__":
    command("inspect-services", "Read-only inspection of pre-existing codex-api service, frps, cloudflared units and local probe", SCRIPT, timeout=180)
