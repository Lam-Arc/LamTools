"""Read-only probe: is the gateway still uninitialised, and are default credentials live?"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud import command  # noqa: E402

SCRIPT = r"""set -u
curl -s -m 8 http://127.0.0.1:3000/api/status -o /tmp/s.json
python3 - <<'REMOTE1'
import json
d = json.load(open('/tmp/s.json')).get('data', {})
print("=== security-relevant status flags ===")
for k in sorted(d):
    lk = k.lower()
    if any(t in lk for t in ('setup', 'regist', 'oauth', 'login', 'self_use', 'turnstile',
                             'checkin', 'invite', 'captcha', 'email_ver', 'demo', 'telegram',
                             'wechat', 'oidc', 'version', 'serveraddress', 'quota_per_unit')):
        print("  %s = %s" % (k, d[k]))
REMOTE1

echo "=== setup endpoint state ==="
curl -s -o /tmp/setup.json -w 'GET /api/setup -> %{http_code}\n' -m 8 http://127.0.0.1:3000/api/setup
python3 - <<'REMOTE2'
import json
try:
    d = json.load(open('/tmp/setup.json'))
    print("  success:", d.get('success'), "| message:", str(d.get('message'))[:120])
    data = d.get('data')
    if isinstance(data, dict):
        print("  data keys:", sorted(data))
    elif data is not None:
        print("  data:", str(data)[:200])
except Exception as exc:
    print("  (unparsable)", type(exc).__name__)
REMOTE2

echo "=== are default root credentials still live? ==="
curl -s -o /tmp/login.json -w 'POST /api/user/login -> %{http_code}\n' -m 10 \
  -H 'Content-Type: application/json' \
  -d '{"username":"root","password":"123456"}' http://127.0.0.1:3000/api/user/login
python3 - <<'REMOTE3'
import json
try:
    d = json.load(open('/tmp/login.json'))
    # Only the boolean outcome is printed; no token, cookie or user record.
    print("  login success flag:", d.get('success'), "| message:", str(d.get('message'))[:120])
except Exception as exc:
    print("  (unparsable)", type(exc).__name__)
REMOTE3
echo "=== done ==="
"""

if __name__ == "__main__":
    command(
        "probe-init",
        "Read-only probe of gateway initialisation state and whether default credentials are live",
        SCRIPT,
        timeout=180,
    )
