"""Read-only: enumerate available New API versions from the server's network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud import command  # noqa: E402

SCRIPT = r"""set -u
echo "=== github tags (api) ==="
timeout 30 curl -s "https://api.github.com/repos/Calcium-Ion/new-api/tags?per_page=100" -o /tmp/tags.json || echo "  github api unreachable"
python3 - <<'PYEOF'
import json
try:
    tags = json.load(open('/tmp/tags.json'))
except Exception as exc:
    print("  could not read tags:", type(exc).__name__)
    raise SystemExit(0)
if not isinstance(tags, list):
    print("  unexpected payload:", str(tags)[:200])
    raise SystemExit(0)
names = [t.get('name') for t in tags if isinstance(t, dict)]
print("  total:", len(names))
print("  all:", names)
stable = [n for n in names if n and 'rc' not in n]
print("  non-rc:", stable)
PYEOF

echo "=== docker hub tags for calciumion/new-api ==="
timeout 40 curl -s "https://hub.docker.com/v2/repositories/calciumion/new-api/tags?page_size=100&ordering=last_updated" -o /tmp/dhtags.json || echo "  docker hub api unreachable"
python3 - <<'PYEOF'
import json
try:
    d = json.load(open('/tmp/dhtags.json'))
except Exception as exc:
    print("  could not read:", type(exc).__name__)
    raise SystemExit(0)
rows = d.get('results')
if not rows:
    print("  unexpected payload:", str(d)[:200])
    raise SystemExit(0)
print("  count:", len(rows))
for r in rows:
    print("    %-28s %s" % (r.get('name'), r.get('last_updated')))
PYEOF
echo "=== done ==="
"""

if __name__ == "__main__":
    command(
        "list-versions",
        "Read-only enumeration of available New API release and image versions from the server",
        SCRIPT,
        timeout=200,
    )
