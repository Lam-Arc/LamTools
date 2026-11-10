#!/usr/bin/env bash
# 精确抽一帧（-ss 定位 + -q:v 1 最高质量），可选同时抽邻近秒做备选
# 用法: bash frame_at.sh <video> <秒> <输出jpg> [宽度=1280] [备选帧数=0]
# 例子: bash frame_at.sh out/video/BV1xx.mp4 754 out/frames/参数面板-754s.jpg 1280
#       bash frame_at.sh out/video/BV1xx.mp4 754 out/frames/参数面板-754s.jpg 1280 2   # 额外抽 754.5s / 755s
set -euo pipefail

VID="${1:?用法: bash frame_at.sh <video> <秒> <输出jpg> [宽度] [备选帧数]}"
T="${2:?需要秒数，支持小数}"
OUT="${3:?需要输出 jpg 路径}"
W="${4:-1280}"
ALTS="${5:-0}"

[ -f "$VID" ] || { echo "找不到视频: $VID" >&2; exit 1; }
mkdir -p "$(dirname "$OUT")"

grab() {
  local t="$1" dest="$2"
  [ -n "$W" ] && SCALE=(-vf "scale=${W}:-2") || SCALE=()
  ffmpeg -v error -nostdin -ss "$t" -i "$VID" -frames:v 1 "${SCALE[@]}" -q:v 1 -y "$dest"
  local size
  size="$(stat -c %s "$dest" 2>/dev/null || echo 0)"
  echo "[ok] ${t}s -> $dest ($((size / 1024)) KB)"
  if [ "$size" -lt 8000 ]; then
    echo "[warn] 文件太小，可能是黑帧或纯色帧，换 ±2 秒重抽" >&2
  fi
}

grab "$T" "$OUT"

if [ "$ALTS" -gt 0 ]; then
  base="${OUT%.jpg}"
  for i in $(seq 1 "$ALTS"); do
    alt_t="$(awk -v t="$T" -v i="$i" 'BEGIN{printf "%.1f", t + i * 0.5}')"
    grab "$alt_t" "${base}-alt${i}-${alt_t}s.jpg"
  done
fi

echo "[next] 打开看一眼，黑帧 / 转场糊帧 / 弹幕遮挡都要换"
