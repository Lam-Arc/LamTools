set -u
PUB=api.47.114.43.99.nip.io
BRIDGE=$(ip -o -4 addr show | awk '$4 ~ /^172\.30\.0\./ {print $4}' | cut -d/ -f1 | head -1)
echo "  bridge gateway: $BRIDGE"
mkdir -p /tmp/jr

cat > /tmp/jr/lib.py <<'LIBEOF'
import http.cookiejar, json, subprocess, time, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(method, path, body=None, headers=None, opener=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    op = opener or OPENER
    try:
        with op.open(r, timeout=40) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def items_of(d):
    if not isinstance(d, dict):
        return []
    data = d.get("data")
    return data.get("items") if isinstance(data, dict) else data


def pw_read():
    for line in open("/opt/lamtools-api/admin-credentials.txt", encoding="utf-8"):
        if line.startswith("password :"):
            return line.split(":", 1)[1].strip()
    return ""


def admin_headers():
    uid = None
    for _ in range(8):
        code, d = call("POST", "/api/user/login", {"username": "root", "password": pw_read()})
        uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
        if uid:
            break
        time.sleep(12)
    if not uid:
        raise SystemExit("admin login failed")
    h = {"New-Api-User": str(uid)}
    code, d = call("GET", "/api/user/token", headers=h)
    t = d.get("data")
    t = (t.get("token") or t.get("access_token")) if isinstance(t, dict) else t
    if isinstance(t, str) and t:
        h["Authorization"] = "Bearer " + t
    return h


def sql(q):
    out = subprocess.run(["docker", "exec", "lamtools-api-db", "psql", "-U", "lamtools_api",
                          "-d", "lamtools_api", "-tAc", q], capture_output=True, text=True)
    return (out.stdout or out.stderr).strip()


def purge(prefix, verbose=True):
    """Delete users, tokens and channels whose name starts with prefix."""
    AH = admin_headers()
    for label in ("user", "token", "channel"):
        code, d = call("GET", "/api/%s/?p=0&size=200" % label, headers=AH)
        field = "username" if label == "user" else "name"
        for it in [i for i in (items_of(d) or []) if isinstance(i, dict)
                   and str(it.get(field, "")).startswith(prefix)]:
            code, r = call("DELETE", "/api/%s/%s" % (label, it.get("id")), headers=AH)
            if verbose:
                print("    delete %s %s (%s) -> http %s success=%s"
                      % (label, it.get("id"), it.get(field), code, r.get("success")))
    return AH
LIBEOF

cat > /tmp/jr/mock.py <<'MOCKEOF'
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, obj):
        d = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def do_GET(self):
        self._json({"object": "list", "data": [{"id": "gpt-4o-mini", "object": "model"}]})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        model = body.get("model") or "gpt-4o-mini"
        self._json({"id": "chatcmpl-mock", "object": "chat.completion", "created": 0,
                    "model": model,
                    "choices": [{"index": 0,
                                 "message": {"role": "assistant", "content": "journey ok"},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


ThreadingHTTPServer((sys.argv[1], int(sys.argv[2])), H).serve_forever()
MOCKEOF

cat > /tmp/jr/clean.py <<'CLEANEOF'
import http.cookiejar, json, subprocess, time, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(method, path, body=None, headers=None, opener=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    op = opener or OPENER
    try:
        with op.open(r, timeout=40) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def items_of(d):
    if not isinstance(d, dict):
        return []
    data = d.get("data")
    return data.get("items") if isinstance(data, dict) else data


def pw_read():
    for line in open("/opt/lamtools-api/admin-credentials.txt", encoding="utf-8"):
        if line.startswith("password :"):
            return line.split(":", 1)[1].strip()
    return ""


def admin_headers():
    uid = None
    for _ in range(8):
        code, d = call("POST", "/api/user/login", {"username": "root", "password": pw_read()})
        uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
        if uid:
            break
        time.sleep(12)
    if not uid:
        raise SystemExit("admin login failed")
    h = {"New-Api-User": str(uid)}
    code, d = call("GET", "/api/user/token", headers=h)
    t = d.get("data")
    t = (t.get("token") or t.get("access_token")) if isinstance(t, dict) else t
    if isinstance(t, str) and t:
        h["Authorization"] = "Bearer " + t
    return h


def sql(q):
    out = subprocess.run(["docker", "exec", "lamtools-api-db", "psql", "-U", "lamtools_api",
                          "-d", "lamtools_api", "-tAc", q], capture_output=True, text=True)
    return (out.stdout or out.stderr).strip()


def purge(prefix, verbose=True):
    """Delete users, tokens and channels whose name starts with prefix."""
    AH = admin_headers()
    for label in ("user", "token", "channel"):
        code, d = call("GET", "/api/%s/?p=0&size=200" % label, headers=AH)
        field = "username" if label == "user" else "name"
        for it in [i for i in (items_of(d) or []) if isinstance(i, dict)
                   and str(it.get(field, "")).startswith(prefix)]:
            code, r = call("DELETE", "/api/%s/%s" % (label, it.get("id")), headers=AH)
            if verbose:
                print("    delete %s %s (%s) -> http %s success=%s"
                      % (label, it.get("id"), it.get(field), code, r.get("success")))
    return AH


print("  removing anything left by the earlier rehearsal")
purge("zz")
print("  database state: users=%s tokens=%s channels=%s"
      % (sql("select count(*) from users where deleted_at is null"),
         sql("select count(*) from tokens where deleted_at is null"),
         sql("select count(*) from channels where deleted_at is null")))
print("  live usernames:", sql("select string_agg(username, ',') from users where deleted_at is null"))
CLEANEOF

cat > /tmp/jr/grant.py <<'GRANTEOF'
import http.cookiejar, json, subprocess, time, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(method, path, body=None, headers=None, opener=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    op = opener or OPENER
    try:
        with op.open(r, timeout=40) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def items_of(d):
    if not isinstance(d, dict):
        return []
    data = d.get("data")
    return data.get("items") if isinstance(data, dict) else data


def pw_read():
    for line in open("/opt/lamtools-api/admin-credentials.txt", encoding="utf-8"):
        if line.startswith("password :"):
            return line.split(":", 1)[1].strip()
    return ""


def admin_headers():
    uid = None
    for _ in range(8):
        code, d = call("POST", "/api/user/login", {"username": "root", "password": pw_read()})
        uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
        if uid:
            break
        time.sleep(12)
    if not uid:
        raise SystemExit("admin login failed")
    h = {"New-Api-User": str(uid)}
    code, d = call("GET", "/api/user/token", headers=h)
    t = d.get("data")
    t = (t.get("token") or t.get("access_token")) if isinstance(t, dict) else t
    if isinstance(t, str) and t:
        h["Authorization"] = "Bearer " + t
    return h


def sql(q):
    out = subprocess.run(["docker", "exec", "lamtools-api-db", "psql", "-U", "lamtools_api",
                          "-d", "lamtools_api", "-tAc", q], capture_output=True, text=True)
    return (out.stdout or out.stderr).strip()


def purge(prefix, verbose=True):
    """Delete users, tokens and channels whose name starts with prefix."""
    AH = admin_headers()
    for label in ("user", "token", "channel"):
        code, d = call("GET", "/api/%s/?p=0&size=200" % label, headers=AH)
        field = "username" if label == "user" else "name"
        for it in [i for i in (items_of(d) or []) if isinstance(i, dict)
                   and str(it.get(field, "")).startswith(prefix)]:
            code, r = call("DELETE", "/api/%s/%s" % (label, it.get("id")), headers=AH)
            if verbose:
                print("    delete %s %s (%s) -> http %s success=%s"
                      % (label, it.get("id"), it.get(field), code, r.get("success")))
    return AH


AH = admin_headers()
USER = "zztest2"

print("  create a user without quota in the payload")
code, d = call("POST", "/api/user/", {"username": USER, "password": "Zz" + os.urandom(9).hex(),
                                      "display_name": "journey test", "role": 1,
                                      "group": "default"}, AH)
print("    create -> http %s success=%s %s" % (code, d.get("success"), str(d.get("message"))[:60]))
print("    quota in database:", sql("select quota from users where username='%s'" % USER))
print("    new-user default (QuotaForNewUser):",
      sql("select value from options where key='QuotaForNewUser'"))

code, d = call("GET", "/api/user/?p=0&size=100", headers=AH)
u = next((i for i in (items_of(d) or []) if isinstance(i, dict)
          and i.get("username") == USER), None)
if not u:
    print("  FATAL: user not found")
    raise SystemExit(1)

PW = "Zz" + os.urandom(9).hex()
body = dict(u)
body["quota"] = 2000000
body["password"] = PW
code, r = call("PUT", "/api/user/", body, AH)
print("  grant quota + set handover password -> http %s success=%s %s"
      % (code, r.get("success"), str(r.get("message"))[:60]))
print("    quota now:", sql("select quota from users where username='%s'" % USER))
open("/tmp/journey-user-pw", "w").write(PW)
open("/tmp/journey-user-id", "w").write(str(u.get("id")))
print("    user id:", u.get("id"), "| group:", u.get("group"))
GRANTEOF

cat > /tmp/jr/run.py <<'RUNEOF'
import http.cookiejar, json, subprocess, time, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(method, path, body=None, headers=None, opener=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    op = opener or OPENER
    try:
        with op.open(r, timeout=40) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def items_of(d):
    if not isinstance(d, dict):
        return []
    data = d.get("data")
    return data.get("items") if isinstance(data, dict) else data


def pw_read():
    for line in open("/opt/lamtools-api/admin-credentials.txt", encoding="utf-8"):
        if line.startswith("password :"):
            return line.split(":", 1)[1].strip()
    return ""


def admin_headers():
    uid = None
    for _ in range(8):
        code, d = call("POST", "/api/user/login", {"username": "root", "password": pw_read()})
        uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
        if uid:
            break
        time.sleep(12)
    if not uid:
        raise SystemExit("admin login failed")
    h = {"New-Api-User": str(uid)}
    code, d = call("GET", "/api/user/token", headers=h)
    t = d.get("data")
    t = (t.get("token") or t.get("access_token")) if isinstance(t, dict) else t
    if isinstance(t, str) and t:
        h["Authorization"] = "Bearer " + t
    return h


def sql(q):
    out = subprocess.run(["docker", "exec", "lamtools-api-db", "psql", "-U", "lamtools_api",
                          "-d", "lamtools_api", "-tAc", q], capture_output=True, text=True)
    return (out.stdout or out.stderr).strip()


def purge(prefix, verbose=True):
    """Delete users, tokens and channels whose name starts with prefix."""
    AH = admin_headers()
    for label in ("user", "token", "channel"):
        code, d = call("GET", "/api/%s/?p=0&size=200" % label, headers=AH)
        field = "username" if label == "user" else "name"
        for it in [i for i in (items_of(d) or []) if isinstance(i, dict)
                   and str(it.get(field, "")).startswith(prefix)]:
            code, r = call("DELETE", "/api/%s/%s" % (label, it.get("id")), headers=AH)
            if verbose:
                print("    delete %s %s (%s) -> http %s success=%s"
                      % (label, it.get("id"), it.get(field), code, r.get("success")))
    return AH


AH = admin_headers()
USER = "zztest2"
CH = "zz-journey-channel"

code, d = call("POST", "/api/channel/", {"mode": "single", "channel": {
    "name": CH, "type": 1, "key": "sk-mock-upstream", "base_url": sys.argv[1],
    "models": "gpt-4o-mini", "group": "default", "status": 1, "weight": 1, "priority": 0}}, AH)
print("  provider added:", d.get("success"))

PW = open("/tmp/journey-user-pw").read().strip()
UOP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
code, d = call("POST", "/api/user/login", {"username": USER, "password": PW}, opener=UOP)
uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
print("  user signs in with the handed-over password:", d.get("success"), "| id:", uid)
UH = {"New-Api-User": str(uid)}

# variant A: a key with its own quota
code, d = call("POST", "/api/token/", {"name": "zz-key-a", "remain_quota": 100000,
                                      "expired_time": -1, "unlimited_quota": False,
                                      "model_limits_enabled": False, "group": "default",
                                      "status": 1}, UH, opener=UOP)
print("  key A (own quota 100000) created:", d.get("success"), str(d.get("message"))[:60])
# variant B: an unlimited key
code, d = call("POST", "/api/token/", {"name": "zz-key-b", "remain_quota": 0,
                                      "expired_time": -1, "unlimited_quota": True,
                                      "model_limits_enabled": False, "group": "default",
                                      "status": 1}, UH, opener=UOP)
print("  key B (unlimited) created:", d.get("success"), str(d.get("message"))[:60])

code, d = call("GET", "/api/token/?p=0&size=50", headers=UH, opener=UOP)
for it in [i for i in (items_of(d) or []) if isinstance(i, dict)
           and str(i.get("name", "")).startswith("zz-key")]:
    key = it.get("key") or ""
    if not key or "*" in key:
        code, d2 = call("POST", "/api/token/%s/key" % it.get("id"), {}, UH, opener=UOP)
        cand = (d2.get("data") or {})
        key = cand.get("key") if isinstance(cand, dict) else cand
    if key and not key.startswith("sk-"):
        key = "sk-" + key
    if key:
        open("/tmp/%s" % it.get("name"), "w").write(key)
        print("  retrieved %s: length %d, own quota %s, unlimited %s"
              % (it.get("name"), len(key), it.get("remain_quota"), it.get("unlimited_quota")))
RUNEOF

cat > /tmp/jr/after.py <<'AFTEREOF'
import http.cookiejar, json, subprocess, time, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(method, path, body=None, headers=None, opener=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    op = opener or OPENER
    try:
        with op.open(r, timeout=40) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def items_of(d):
    if not isinstance(d, dict):
        return []
    data = d.get("data")
    return data.get("items") if isinstance(data, dict) else data


def pw_read():
    for line in open("/opt/lamtools-api/admin-credentials.txt", encoding="utf-8"):
        if line.startswith("password :"):
            return line.split(":", 1)[1].strip()
    return ""


def admin_headers():
    uid = None
    for _ in range(8):
        code, d = call("POST", "/api/user/login", {"username": "root", "password": pw_read()})
        uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
        if uid:
            break
        time.sleep(12)
    if not uid:
        raise SystemExit("admin login failed")
    h = {"New-Api-User": str(uid)}
    code, d = call("GET", "/api/user/token", headers=h)
    t = d.get("data")
    t = (t.get("token") or t.get("access_token")) if isinstance(t, dict) else t
    if isinstance(t, str) and t:
        h["Authorization"] = "Bearer " + t
    return h


def sql(q):
    out = subprocess.run(["docker", "exec", "lamtools-api-db", "psql", "-U", "lamtools_api",
                          "-d", "lamtools_api", "-tAc", q], capture_output=True, text=True)
    return (out.stdout or out.stderr).strip()


def purge(prefix, verbose=True):
    """Delete users, tokens and channels whose name starts with prefix."""
    AH = admin_headers()
    for label in ("user", "token", "channel"):
        code, d = call("GET", "/api/%s/?p=0&size=200" % label, headers=AH)
        field = "username" if label == "user" else "name"
        for it in [i for i in (items_of(d) or []) if isinstance(i, dict)
                   and str(it.get(field, "")).startswith(prefix)]:
            code, r = call("DELETE", "/api/%s/%s" % (label, it.get("id")), headers=AH)
            if verbose:
                print("    delete %s %s (%s) -> http %s success=%s"
                      % (label, it.get("id"), it.get(field), code, r.get("success")))
    return AH


print("  quota accounting after the calls:")
print("   ", sql("select 'user quota=' || quota || ' used=' || used_quota"
                  " || ' requests=' || request_count from users where username='zztest2'"))
print("   ", sql("select coalesce(string_agg(name || ': used=' || used_quota"
                  " || ' remain=' || remain_quota, ', '), 'none') from tokens"
                  " where deleted_at is null and name like 'zz-key%'"))

print("  cleanup")
purge("zz")
print("  final database state: users=%s tokens=%s channels=%s"
      % (sql("select count(*) from users where deleted_at is null"),
         sql("select count(*) from tokens where deleted_at is null"),
         sql("select count(*) from channels where deleted_at is null")))
print("  live usernames:", sql("select string_agg(username, ',') from users where deleted_at is null"))
AFTEREOF

cat > /tmp/jr/console.py <<'CONSOLEEOF'
import http.cookiejar, json, subprocess, time, urllib.error, urllib.request

BASE = "http://127.0.0.1:3000"
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(method, path, body=None, headers=None, opener=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    op = opener or OPENER
    try:
        with op.open(r, timeout=40) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def items_of(d):
    if not isinstance(d, dict):
        return []
    data = d.get("data")
    return data.get("items") if isinstance(data, dict) else data


def pw_read():
    for line in open("/opt/lamtools-api/admin-credentials.txt", encoding="utf-8"):
        if line.startswith("password :"):
            return line.split(":", 1)[1].strip()
    return ""


def admin_headers():
    uid = None
    for _ in range(8):
        code, d = call("POST", "/api/user/login", {"username": "root", "password": pw_read()})
        uid = (d.get("data") or {}).get("id") if isinstance(d, dict) else None
        if uid:
            break
        time.sleep(12)
    if not uid:
        raise SystemExit("admin login failed")
    h = {"New-Api-User": str(uid)}
    code, d = call("GET", "/api/user/token", headers=h)
    t = d.get("data")
    t = (t.get("token") or t.get("access_token")) if isinstance(t, dict) else t
    if isinstance(t, str) and t:
        h["Authorization"] = "Bearer " + t
    return h


def sql(q):
    out = subprocess.run(["docker", "exec", "lamtools-api-db", "psql", "-U", "lamtools_api",
                          "-d", "lamtools_api", "-tAc", q], capture_output=True, text=True)
    return (out.stdout or out.stderr).strip()


def purge(prefix, verbose=True):
    """Delete users, tokens and channels whose name starts with prefix."""
    AH = admin_headers()
    for label in ("user", "token", "channel"):
        code, d = call("GET", "/api/%s/?p=0&size=200" % label, headers=AH)
        field = "username" if label == "user" else "name"
        for it in [i for i in (items_of(d) or []) if isinstance(i, dict)
                   and str(it.get(field, "")).startswith(prefix)]:
            code, r = call("DELETE", "/api/%s/%s" % (label, it.get("id")), headers=AH)
            if verbose:
                print("    delete %s %s (%s) -> http %s success=%s"
                      % (label, it.get("id"), it.get(field), code, r.get("success")))
    return AH


AH = admin_headers()
code, d = call("GET", "/api/status")
data = d.get("data") or {} if isinstance(d, dict) else {}
print("  quota_per_unit (quota units per currency unit):", data.get("quota_per_unit"))
print("  display_in_currency:", data.get("display_in_currency"))
print("  price option (currency per USD):", sql("select value from options where key='Price'"))
print("  Language option:", sql("select coalesce(value,'(unset)') from options where key='Language'"))
print("  root user locale setting:", sql("select coalesce(setting,'(null)') from users where username='root'"))
CONSOLEEOF

echo "=== stage 1: remove leftovers from the earlier rehearsal ==="
python3 /tmp/jr/clean.py

echo "=== stage 2: how is quota granted to a new user? ==="
python3 /tmp/jr/grant.py

echo "=== stage 3: the user's side of the journey ==="
setsid nohup python3 /tmp/jr/mock.py "$BRIDGE" 8323 >/tmp/jr/mock.log 2>&1 < /dev/null &
echo $! > /tmp/jr/mock.pid
sleep 2
if ss -tln | grep -q 8323; then echo "  mock provider listening"; else echo "  MOCK FAILED"; cat /tmp/jr/mock.log; fi
python3 /tmp/jr/run.py "http://$BRIDGE:8323"

echo "=== stage 4: reload, then call with each key the user made ==="
/usr/local/bin/lamtools-api-reload >/dev/null 2>&1
for i in $(seq 1 40); do
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:3000/api/status || true)
  [ "$c" = "200" ] && break
  sleep 2
done
sleep 5
RES="--resolve $PUB:443:127.0.0.1"
for k in zz-key-a zz-key-b; do
  if [ -s "/tmp/$k" ]; then
    KEY=$(cat "/tmp/$k")
    printf '  %-10s -> ' "$k"
    curl -s -o /tmp/jr/resp.json -w '%{http_code}
' -m 60 $RES       -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json'       -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}],"stream":false}'       "https://$PUB/v1/chat/completions"
    python3 -c "
import json
d = json.load(open('/tmp/jr/resp.json'))
if d.get('error'):
    print('      error:', str(d['error'])[:150])
else:
    print('      reply:', ((d.get('choices') or [{}])[0].get('message') or {}).get('content'))
"
  else
    echo "  $k: not retrieved"
  fi
done

echo "=== stage 5: accounting, cleanup, console facts ==="
python3 /tmp/jr/after.py
python3 /tmp/jr/console.py
[ -f /tmp/jr/mock.pid ] && kill "$(cat /tmp/jr/mock.pid)" 2>/dev/null && echo "  mock provider stopped"
rm -rf /tmp/jr /tmp/zz-key-a /tmp/zz-key-b /tmp/journey-user-pw /tmp/journey-user-id
echo "=== done ==="
