set -u
echo "=== prepare service dir (0700, root) ==="
install -d -m 0750 -o root -g root /opt/lamtools-api
install -d -m 0750 -o root -g root /opt/lamtools-api/data
install -d -m 0750 -o root -g root /opt/lamtools-api/logs
ls -ld /opt/lamtools-api /opt/lamtools-api/data /opt/lamtools-api/logs

echo "=== disk before ==="; df -h / | tail -1

echo "=== pull new-api (pinned rc, fallback latest) ==="
API_IMG="calciumion/new-api:v1.0.0-rc.40"
if timeout 600 docker pull "$API_IMG" >/tmp/pull_api.log 2>&1; then
  echo "new-api tag OK: $API_IMG"
else
  echo "pinned tag unavailable, falling back to latest"
  tail -3 /tmp/pull_api.log
  API_IMG="calciumion/new-api:latest"
  timeout 600 docker pull "$API_IMG" >/tmp/pull_api.log 2>&1 && echo "new-api latest OK" || { echo "new-api PULL FAILED"; tail -5 /tmp/pull_api.log; }
fi

echo "=== pull postgres + redis ==="
for img in postgres:16-alpine redis:7-alpine; do
  if timeout 600 docker pull "$img" >/tmp/pull_$(echo $img | tr ':/' '__').log 2>&1; then
    echo "OK $img"
  else
    echo "FAILED $img"; tail -3 /tmp/pull_$(echo $img | tr ':/' '__').log
  fi
done

echo "=== resolved digests ==="
for img in "$API_IMG" postgres:16-alpine redis:7-alpine; do
  d=$(docker image inspect --format '{{index .RepoDigests 0}}' "$img" 2>/dev/null)
  printf '%s -> %s\n' "$img" "${d:-MISSING}"
done

echo "=== image sizes ==="
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | head -10

echo "=== disk after ==="; df -h / | tail -1
echo "=== done ==="
