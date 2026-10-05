"""Mutation: deploy the LamTools API gateway stack on the instance.

Credentials are generated on the server and stay there; this script never
prints, transmits or logs a secret value.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud import command  # noqa: E402

ROOT = Path(__file__).resolve().parent
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8").rstrip("\n")

SCRIPT = (
    """set -eu
APP=/opt/lamtools-api
cd "$APP"

echo "=== 1) generate secrets on-server (values never printed) ==="
if [ -f "$APP/.env" ]; then
  echo "REFUSING: $APP/.env already exists; nothing changed"
  exit 1
fi
umask 077
PG_PASSWORD=$(openssl rand -hex 24)
REDIS_PASSWORD=$(openssl rand -hex 24)
SESSION_SECRET=$(openssl rand -hex 32)
CRYPTO_SECRET=$(openssl rand -hex 32)
cat > "$APP/.env" <<ENVEOF
COMPOSE_PROJECT_NAME=lamtools-api
PG_PASSWORD=$PG_PASSWORD
REDIS_PASSWORD=$REDIS_PASSWORD
SESSION_SECRET=$SESSION_SECRET
CRYPTO_SECRET=$CRYPTO_SECRET
ENVEOF
chmod 600 "$APP/.env"
chown root:root "$APP/.env"
unset PG_PASSWORD REDIS_PASSWORD SESSION_SECRET CRYPTO_SECRET
echo "env written: mode $(stat -c %a "$APP/.env"), $(wc -l < "$APP/.env") keys"

echo "=== 2) write compose file ==="
cat > "$APP/docker-compose.yml" <<'COMPOSEEOF'
"""
    + COMPOSE
    + """
COMPOSEEOF
chmod 640 "$APP/docker-compose.yml"
sha256sum "$APP/docker-compose.yml"

echo "=== 3) validate compose ==="
docker compose config --quiet && echo "compose config OK"

echo "=== 4) bring stack up ==="
docker compose up -d --wait 2>&1 | tail -25 || docker compose up -d 2>&1 | tail -25

echo "=== 5) wait for gateway on loopback ==="
code=""
for i in $(seq 1 40); do
  code=$(curl -s -o /tmp/gw-status.json -w '%{http_code}' -m 5 http://127.0.0.1:3000/api/status || true)
  if [ "$code" = "200" ]; then echo "gateway HTTP 200 after $((i*3))s"; break; fi
  sleep 3
done
echo "last status code: ${code:-none}"
echo "--- /api/status ---"
head -c 1500 /tmp/gw-status.json 2>/dev/null || echo "(no body)"
echo

echo "=== 6) containers ==="
docker compose ps

echo "=== 7) port binding check (must be loopback only) ==="
ss -tlnp | grep -E ':3000|:5432|:6379' || echo "no published db/cache ports (expected)"

echo "=== 8) resources ==="
free -m | head -2
df -h / | tail -1
echo "=== done ==="
"""
)

if __name__ == "__main__":
    command(
        "deploy-stack",
        "Generate on-server credentials, install compose definition and start LamTools API gateway stack",
        SCRIPT,
        timeout=900,
    )
