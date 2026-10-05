set -u
echo "=== docker info ==="
docker info --format '{{.ServerVersion}} storage={{.Driver}} cgroup={{.CgroupVersion}} root={{.DockerRootDir}}' 2>&1
echo "=== registry mirrors ==="
cat /etc/docker/daemon.json 2>/dev/null || echo "(no daemon.json)"
echo "=== disk ==="
df -h /var/lib/docker | tail -1
echo "=== pull test: alpine (small) ==="
timeout 90 docker pull alpine:3.20 2>&1 | tail -5
echo "=== docker hub api reachability ==="
timeout 20 curl -s -o /dev/null -w 'hub_auth=%{http_code}\n' https://auth.docker.io/token || echo "auth.docker.io unreachable"
timeout 20 curl -s -o /dev/null -w 'registry=%{http_code}\n' https://registry-1.docker.io/v2/ || echo "registry unreachable"
echo "=== compose plugin ==="
docker compose version 2>&1 | head -2
echo "=== memory headroom ==="
free -m | head -2
echo "=== done ==="
