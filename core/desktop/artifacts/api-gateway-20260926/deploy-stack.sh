set -eu
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
# LamTools API gateway — public multi-tenant relay aggregating upstream API keys.
#
# Deployed to /opt/lamtools-api/docker-compose.yml on i-bp10t7y63rvbncmjstpm.
# Secrets live in /opt/lamtools-api/.env (0600, generated on the server); this
# file intentionally contains none.
#
# Exposure model: only the gateway is published, and only on the loopback
# address. Caddy terminates TLS and is the sole public entry point. The database
# and cache have no host port at all.
services:
  gateway:
    image: calciumion/new-api:v1.0.0-rc.40
    container_name: lamtools-api-gateway
    restart: unless-stopped
    command: --log-dir /app/logs
    ports:
      - "127.0.0.1:3000:3000"
    volumes:
      - ./data:/data
      - ./logs:/app/logs
    environment:
      TZ: Asia/Shanghai
      SQL_DSN: postgresql://lamtools_api:${PG_PASSWORD}@db:5432/lamtools_api
      REDIS_CONN_STRING: redis://:${REDIS_PASSWORD}@cache:6379
      SESSION_SECRET: ${SESSION_SECRET}
      CRYPTO_SECRET: ${CRYPTO_SECRET}
      # Caddy reaches the container through the bridge gateway, so that subnet is
      # the only peer allowed to assert a client IP in X-Forwarded-For. Caddy
      # rewrites the header rather than appending, so callers cannot spoof it.
      TRUSTED_PROXIES: 172.30.0.0/24
      NODE_TYPE: master
      ERROR_LOG_ENABLED: "true"
      BATCH_UPDATE_ENABLED: "true"
      STREAMING_TIMEOUT: "300"
    depends_on:
      db:
        condition: service_healthy
      cache:
        condition: service_healthy
    networks:
      - internal
    security_opt:
      - no-new-privileges:true
    mem_limit: 768m
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  db:
    image: postgres:16-alpine
    container_name: lamtools-api-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: lamtools_api
      POSTGRES_PASSWORD: ${PG_PASSWORD}
      POSTGRES_DB: lamtools_api
      TZ: Asia/Shanghai
    # Bounded for a 3.6 GB host that also runs the site, the relay and the tunnel.
    command:
      - postgres
      - -c
      - shared_buffers=128MB
      - -c
      - max_connections=60
      - -c
      - work_mem=4MB
    volumes:
      - pgdata:/var/lib/postgresql/data
    networks:
      - internal
    security_opt:
      - no-new-privileges:true
    mem_limit: 448m
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "lamtools_api", "-d", "lamtools_api"]
      interval: 15s
      timeout: 5s
      retries: 8
      start_period: 30s

  cache:
    image: redis:7-alpine
    container_name: lamtools-api-cache
    restart: unless-stopped
    # Pure cache: no snapshotting, no AOF, evict rather than fail.
    command:
      - redis-server
      - --requirepass
      - ${REDIS_PASSWORD}
      - --appendonly
      - "no"
      - --save
      - ""
      - --maxmemory
      - 128mb
      - --maxmemory-policy
      - allkeys-lru
    networks:
      - internal
    security_opt:
      - no-new-privileges:true
    mem_limit: 192m
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    healthcheck:
      test: ["CMD", "redis-cli", "--no-auth-warning", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 15s
      timeout: 5s
      retries: 8
      start_period: 15s

networks:
  internal:
    driver: bridge
    ipam:
      config:
        - subnet: 172.30.0.0/24

volumes:
  pgdata:
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
