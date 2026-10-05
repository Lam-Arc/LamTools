"""Mutation: publish the gateway through Caddy with TLS, without disturbing other sites."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud import command  # noqa: E402

SITE = """api.47.114.43.99.nip.io {
	header {
		-Server
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "no-referrer"
	}
	reverse_proxy 127.0.0.1:3000 {
		# Replace, never append: an appended X-Forwarded-For would let a caller
		# inject a fake client address that the gateway is configured to trust.
		header_up X-Forwarded-For {remote_host}
		header_up X-Real-IP {remote_host}
		# LLM responses stream; buffering here would stall tokens.
		flush_interval -1
	}
}
"""

SCRIPT = (
    r"""set -eu
CFG=/etc/caddy/Caddyfile
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

echo "=== 1) pre-change baseline ==="
ls -l "$CFG"
echo "--- caddy unit reload capability ---"
systemctl show caddy-lamtools -p ExecStart -p ExecReload --no-pager
echo "--- caddy binary ---"
command -v caddy || echo "(caddy not on PATH)"
echo "--- current config validates? ---"
caddy validate --config "$CFG" --adapter caddyfile 2>&1 | tail -3

echo "=== 2) guard + backup ==="
if grep -qE '^api\.47\.114\.43\.99\.nip\.io' "$CFG"; then
  echo "REFUSING: site already present in Caddyfile; nothing changed"
  exit 1
fi
cp -p "$CFG" "$CFG.before-api-gateway-$STAMP"
echo "  backup: $CFG.before-api-gateway-$STAMP"
sha256sum "$CFG" | sed 's/^/  old sha256: /'

echo "=== 3) append new site block ==="
cp "$CFG" /tmp/Caddyfile.new
cat >> /tmp/Caddyfile.new <<'SITEEOF'
"""
    + SITE
    + """SITEEOF
install -m 0644 -o root -g root /tmp/Caddyfile.new "$CFG"
rm -f /tmp/Caddyfile.new
sha256sum "$CFG" | sed 's/^/  new sha256: /'

echo "=== 4) validate new config ==="
caddy validate --config "$CFG" --adapter caddyfile 2>&1 | tail -3

echo "=== 5) graceful reload (no restart of the web server) ==="
rm -f /tmp/reload.err
if systemctl reload caddy-lamtools 2>/tmp/reload.err; then
  echo "  systemctl reload caddy-lamtools: OK"
elif caddy reload --config "$CFG" --adapter caddyfile 2>/tmp/reload.err; then
  echo "  caddy reload: OK"
else
  echo "  graceful reload unavailable:"
  tail -5 /tmp/reload.err 2>/dev/null || true
  echo "  falling back to restart"
  systemctl restart caddy-lamtools
fi
sleep 2
echo "  unit state: $(systemctl is-active caddy-lamtools)"

echo "=== 6) wait for certificate issuance ==="
code=""
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 8 \
    --resolve api.47.114.43.99.nip.io:443:127.0.0.1 \
    https://api.47.114.43.99.nip.io/api/status || true)
  if [ "$code" = "200" ]; then echo "  gateway reachable over TLS after $((i*4))s"; break; fi
  sleep 4
done
echo "  last code: ${code:-none}"

echo "=== 7) certificate served for the new name ==="
echo | timeout 20 openssl s_client -connect 127.0.0.1:443 -servername api.47.114.43.99.nip.io 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates 2>/dev/null || echo "  (could not read certificate)"

echo "=== 8) regression check: every pre-existing site still answers ==="
check() { # label domain path
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 12 --resolve "$2:443:127.0.0.1" "https://$2$3" || true)
  echo "  $1 -> $c"
}
check "homepage"           47.114.43.99.nip.io ""
check "downloads manifest" 47.114.43.99.nip.io "/downloads/mobile-update.json"
check "desktop installer"  47.114.43.99.nip.io "/downloads/Sunday-latest-x64-setup.exe"
check "mobile relay health" 47.114.43.99.nip.io "/health"
check "codex mock api"     codex-api.47.114.43.99.nip.io ""
check "new api gateway"    api.47.114.43.99.nip.io "/api/status"

echo "=== 9) log directory inventory (for later client-IP verification) ==="
ls -la /opt/lamtools-api/logs 2>/dev/null | head -10
echo "=== done ==="
"""
)

if __name__ == "__main__":
    command(
        "publish-caddy",
        "Back up Caddyfile, add api gateway vhost with streamed reverse proxy, reload gracefully and regression-check all sites",
        SCRIPT,
        timeout=600,
    )
