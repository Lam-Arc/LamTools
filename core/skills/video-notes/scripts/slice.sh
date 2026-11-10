#!/usr/bin/env bash
# 整页 PNG 切片：ffmpeg crop，相邻片保留约 100px 重叠，切点吸附到章节标题上方，避免切断标题
# 用法: bash slice.sh <整页png> <输出目录> [单片高度=2000] [重叠=100] [cuts.json]
# 例子: bash slice.sh out/shots/page.png out/shots/slices 2000 100 out/shots/page.cuts.json
set -euo pipefail

IMG="${1:?用法: bash slice.sh <整页png> <输出目录> [单片高度] [重叠] [cuts.json]}"
OUT="${2:?需要输出目录}"
SLICE_H="${3:-2000}"
OVERLAP="${4:-100}"
CUTS="${5:-}"

[ -f "$IMG" ] || { echo "找不到图片: $IMG" >&2; exit 1; }
mkdir -p "$OUT"

SIZE="$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0:s=x "$IMG" | tr -d '\r')"
W="${SIZE%%x*}"
H="${SIZE##*x}"
[ -n "$W" ] && [ -n "$H" ] || { echo "读不到图片尺寸: $SIZE" >&2; exit 1; }

# 章节标题的 y 坐标，用于把切点向上吸附（Python 在 Windows 会输出 CRLF，统一去掉）
CUT_LIST=""
if [ -n "$CUTS" ] && [ -f "$CUTS" ]; then
  CUT_LIST="$(python -c "
import json
d = json.load(open(r'$CUTS', encoding='utf-8'))
print(' '.join(str(c) for c in d.get('cuts', [])), end='')
" 2>/dev/null | tr -d '\r' || true)"
fi

SNAP=$(( SLICE_H / 8 ))
[ "$SNAP" -lt 120 ] && SNAP=120

echo "[info] 整页 ${W}x${H}，切片高度 ${SLICE_H}，重叠 ${OVERLAP}"
MANIFEST="$OUT/slices.txt"
: > "$MANIFEST"

i=0
while read -r y end; do
  # 数值校验：非数字行直接跳过，防止把脏数据丢进算术表达式
  case "$y" in ''|*[!0-9]*) continue ;; esac
  case "$end" in ''|*[!0-9]*) continue ;; esac

  i=$(( i + 1 ))
  h=$(( end - y ))
  [ "$h" -le 0 ] && continue

  out_file="$(printf "%s/%02d.png" "$OUT" "$i")"
  ffmpeg -v error -i "$IMG" -vf "crop=${W}:${h}:0:${y}" -y "$out_file"
  printf '%s\ty=%s..%s (%spx)\n' "$out_file" "$y" "$end" "$h" | tee -a "$MANIFEST"
done < <(python - "$H" "$SLICE_H" "$OVERLAP" "$SNAP" $CUT_LIST <<'PY' | tr -d '\r'
import sys

H = int(sys.argv[1])
slice_h = int(sys.argv[2])
overlap = int(sys.argv[3])
snap = int(sys.argv[4])
cuts = [int(x) for x in sys.argv[5:]]

plan = []
y = 0
while y < H:
    end = min(y + slice_h, H)
    snapped = y
    if y > 0:
        best = None
        for c in cuts:
            cand = max(0, c - 16)          # 往上留一点，标题整段留给下一片
            if cand <= y and abs(cand - y) <= snap:
                if best is None or abs(cand - y) < abs(best - y):
                    best = cand
        if best is not None:
            snapped = best
    plan.append([snapped, end])
    nxt = end - overlap
    if nxt <= y:
        nxt = y + max(200, slice_h // 2)
    y = nxt

# 末尾剩下一条薄片就并进上一片，避免出现 100px 的碎尾
thin = max(200, overlap)
if len(plan) > 1 and plan[-1][1] - plan[-1][0] <= thin:
    plan[-2][1] = H
    plan.pop()

for a, b in plan:
    print(f"{a} {b}")
PY
)

echo "[ok] 切片完成，共 ${i} 片，清单: $MANIFEST"
echo "[next] 抽查首片、末片和中间一片，确认没有切断标题或截图"
