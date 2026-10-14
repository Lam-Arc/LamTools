"""Private snapshot benchmark. Source database is opened strictly read-only."""
import json
from pathlib import Path
import sqlite3
from time import perf_counter

root = Path('E:/setuptest/task-3b-private-clone-v3')
root.mkdir(parents=True,exist_ok=True)
target = root/'core.db'
assert target.resolve().is_relative_to(Path('E:/setuptest'))
assert not target.exists(), 'Keep existing private evidence; do not overwrite'
started=perf_counter()
with sqlite3.connect('file:E:/LamTools/data/core.db?mode=ro',uri=True) as source, sqlite3.connect(target) as clone:
    # One backup step pins a consistent snapshot; incremental steps restart
    # repeatedly when the live WAL is being updated.
    source.backup(clone,pages=-1)
copy_seconds=perf_counter()-started
query='SELECT * FROM core_app_events WHERE thread_id=? AND client_message_id=? AND method IN (?) ORDER BY seq LIMIT 1'
params=('5545f1e3cc4f41fea09bac0ac675a8fb','task-3b-benchmark-not-a-submission','turn/accepted')
with sqlite3.connect(target) as clone:
    plan_before=clone.execute('EXPLAIN QUERY PLAN '+query,params).fetchall()
    started=perf_counter(); assert clone.execute(query,params).fetchone() is None
    before=perf_counter()-started
    started=perf_counter()
    clone.execute('CREATE INDEX IF NOT EXISTS idx_core_events_client_message ON core_app_events(thread_id,client_message_id,seq) WHERE client_message_id IS NOT NULL')
    clone.commit(); index_seconds=perf_counter()-started
    plan_after=clone.execute('EXPLAIN QUERY PLAN '+query,params).fetchall()
    started=perf_counter(); assert clone.execute(query,params).fetchone() is None
    after=perf_counter()-started
result={'private_clone':str(target),'source_open_mode':'ro','clone_size':target.stat().st_size,'copy_seconds':copy_seconds,
        'before_seconds':before,'index_creation_seconds':index_seconds,'after_seconds':after,
        'plan_before':plan_before,'plan_after':plan_after}
Path(__file__).with_name('benchmark-clone.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2),flush=True)
