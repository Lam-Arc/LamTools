"""Bounded, streaming inventory of installed backend log records."""
import collections
import json
import re
from pathlib import Path

ROOT = Path('E:/setuptest/constant')
OUT = Path(__file__).parent
HEADER = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)?) \[(\w+)\] \[([^]]+)\] (.*)')

def normalize(s):
    s = re.sub(r'[0-9a-f]{24,}', '<id>', s, flags=re.I)
    s = re.sub(r'\b\d+(?:\.\d+)?\b', '<n>', s)
    return s[:900]

files = sorted(set(ROOT.glob('*.log')) | set((ROOT / '.lam').glob('*.log')))
groups = {}
inventory = []
def lines_bounded(f, size):
    pending = b''
    remaining = size
    while remaining:
        block = f.read(min(4 * 1024 * 1024, remaining))
        if not block:
            break
        remaining -= len(block)
        rows = (pending + block).split(b'\n')
        pending = rows.pop()
        yield from rows
    if pending:
        yield pending

for path in files:
    print('Scanning', path, flush=True)
    size = path.stat().st_size
    counts = collections.Counter()
    record = None
    def flush():
        if not record:
            return
        timestamp, level, logger, message, trace = record
        if level not in ('WARNING', 'ERROR', 'CRITICAL') and not trace:
            return
        tail = [x for x in trace if re.match(r'^[\w.]+(?:Error|Exception|Warning)(?::|$)', x)]
        key = f'{level} {logger} {normalize(message)}' + (' | ' + normalize(tail[-1]) if tail else '')
        g = groups.setdefault(key, dict(count=0, first=timestamp, last=timestamp, source=str(path), message=message[:1600], trace=trace[:80]))
        g['count'] += 1
        g['last'] = timestamp
    with path.open('rb') as f:
        for raw in lines_bounded(f, size):
            line = raw.decode('utf-8', errors='replace').rstrip()
            match = HEADER.match(line)
            counts['lines'] += 1
            if match:
                flush()
                timestamp, level, logger, message = match.groups()
                counts[level] += 1
                record = [timestamp, level, logger, message, []]
            elif record and line and len(record[4]) < 100:
                record[4].append(line[:2000])
        flush()
    inventory.append(dict(path=str(path), scanned_bytes=size, counts=dict(counts)))
result = dict(files=inventory, groups=sorted((dict(signature=k, **v) for k,v in groups.items()), key=lambda x: -x['count']))
(OUT / 'log-inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(dict(files=inventory, group_count=len(groups)), ensure_ascii=False))
for g in result['groups'][:70]:
    print(g['count'], g['signature'][:650])
