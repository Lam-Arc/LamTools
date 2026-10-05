"""Read-only inspection of the LamTools instance before any API gateway change."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud import command  # noqa: E402

SCRIPT = r"""set -u
echo "=== time ==="; date -u +%Y-%m-%dT%H:%M:%SZ
echo "=== host ==="; uname -srmo; . /etc/os-release; echo "$PRETTY_NAME"
echo "=== cpu/mem/disk ==="; nproc; free -m | head -2; df -h / /var /srv 2>/dev/null | tail -3
echo "=== running services ==="
systemctl list-units --type=service --state=running --no-pager --no-legend | awk '{print $1}'
echo "=== docker ==="
if command -v docker >/dev/null 2>&1; then
  docker --version; docker compose version 2>/dev/null || echo "no compose plugin"
  echo "--- containers ---"; docker ps -a --format '{{.Names}} | {{.Image}} | {{.Status}} | {{.Ports}}'
  echo "--- volumes ---"; docker volume ls --format '{{.Name}}' | head -20
else
  echo "docker NOT installed"
fi
echo "=== listeners ==="; ss -tlnp
echo "=== runtimes ==="
python3 --version 2>&1 | head -1
node --version 2>&1 | head -1
(go version 2>&1 | head -1) || true
echo "=== unit states ==="
systemctl is-active caddy-lamtools lamtools-relay 2>&1
echo "=== caddy config dirs ==="
ls -la /etc/caddy 2>/dev/null
echo "--- Caddyfile ---"
cat /etc/caddy/Caddyfile 2>/dev/null || echo "(no /etc/caddy/Caddyfile)"
echo "=== web root ==="
readlink -f /var/www/lamtools 2>/dev/null
ls -la /var/www/lamtools 2>/dev/null | head -25
echo "=== relay unit ==="
systemctl cat lamtools-relay --no-pager 2>/dev/null | head -30
echo "=== users with shells ==="
awk -F: '$3>=1000 && $7!~/nologin|false/ {print $1}' /etc/passwd
echo "=== ssh ==="
wc -l /root/.ssh/authorized_keys 2>/dev/null || echo "no authorized_keys"
echo "=== ufw ==="
ufw status 2>/dev/null || echo "ufw not active/installed"
echo "=== done ==="
"""

if __name__ == "__main__":
    command("inspect", "Read-only baseline inspection of LamTools instance before API gateway rollout", SCRIPT, timeout=180)
