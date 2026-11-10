#!/usr/bin/env bash
# 长视频分片并行抽候选帧：文件名就是秒数，方便挑完直接精确重抽
# 用法: bash frames_candidates.sh <video> <候选帧目录> [间隔秒=20] [最大帧数=800] [并发=8] [宽度=640]
# 例子: bash frames_candidates.sh out/video/BV1xx.mp4 out/frames/_cand 20 800 8 640
set -euo pipefail

VID="${1:?用法: bash frames_candidates.sh <video> <候选帧目录> [间隔秒] [最大帧数] [并发] [宽度]}"
OUT="${2:?需要候选帧输出目录}"
STEP="${3:-20}"
MAXF="${4:-800}"
JOBS="${5:-8}"
W="${6:-640}"

[ -f "$VID" ] || { echo "找不到视频: $VID" >&2; exit 1; }
mkdir -p "$OUT"

DUR="$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$VID")"
DUR_I="${DUR%.*}"

TS_FILE="$(mktemp)"
MANIFEST="$OUT/manifest.txt"
: > "$MANIFEST"

awk -v d="$DUR_I" -v s="$STEP" -v m="$MAXF" 'BEGIN{ n=0; for(t=0; t<d && n<m; t+=s){ printf "%d\n", t; n++ } }' > "$TS_FILE"
COUNT="$(wc -l < "$TS_FILE" | tr -d ' ')"
echo "[info] 时长 ${DUR_I}s，间隔 ${STEP}s，候选 ${COUNT} 帧，并发 ${JOBS}"

while read -r t; do
  printf '%ss\t%s/cand_%ss.jpg\n' "$t" "$OUT" "$t" >> "$MANIFEST"
done < "$TS_FILE"

xargs -a "$TS_FILE" -P "$JOBS" -I TS bash -c '
  t="$1"; out="$2"; vid="$3"; w="$4"
  ffmpeg -v error -nostdin -ss "$t" -i "$vid" -frames:v 1 -vf "scale=${w}:-2" -q:v 4 -y "$out/cand_${t}s.jpg" \
    || echo "[warn] 抽帧失败 t=${t}s" >&2
' _ TS "$OUT" "$VID" "$W"

rm -f "$TS_FILE"
made="$(ls -1 "$OUT"/cand_*.jpg 2>/dev/null | wc -l | tr -d ' ')"
echo "[ok] 生成 $made 张候选帧，清单: $MANIFEST"
echo "[next] 看完候选后用 frame_at.sh 精确重抽，文件名建议 <阶段名>-<秒>s.jpg"
