set -u
echo "=== github tags (following redirect) ==="
timeout 40 curl -sL "https://api.github.com/repositories/717197250/tags?per_page=100" -o /tmp/tags.json || echo "  unreachable"
python3 - <<'PYEOF'
import json
try:
    tags = json.load(open('/tmp/tags.json'))
except Exception as exc:
    print("  unreadable:", type(exc).__name__)
    raise SystemExit(0)
if isinstance(tags, dict):
    print("  payload:", str(tags)[:200]); raise SystemExit(0)
names = [t.get('name') for t in tags if isinstance(t, dict)]
print("  total tags returned:", len(names))
print("  non-rc:", [n for n in names if n and 'rc' not in n])
print("  sample:", names[:30])
PYEOF
echo "=== done ==="
