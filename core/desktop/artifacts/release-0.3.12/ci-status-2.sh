set -eu
curl -sSL -m 60 'https://api.github.com/repos/Lam-Arc/LamTools/actions/runs?per_page=10' -o /tmp/runs.json
python3 - <<'EOF'
import json
d=json.load(open('/tmp/runs.json'))
for w in d.get('workflow_runs',[]):
    if w.get('head_branch')=='v0.3.12':
        print('RUN', w['id'], w['status'], w['conclusion'], w['created_at'], w['updated_at'])
EOF
curl -sSL -m 60 'https://api.github.com/repos/Lam-Arc/LamTools/releases/tags/v0.3.12' -o /tmp/rel.json
python3 - <<'EOF'
import json
r=json.load(open('/tmp/rel.json'))
for a in r.get('assets',[]):
    print('ASSET', a['name'], a['size'], (a.get('digest') or '')[:19])
EOF
