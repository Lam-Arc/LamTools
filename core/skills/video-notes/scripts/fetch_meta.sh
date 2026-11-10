#!/usr/bin/env bash
# 抓完整元数据（B 站尽量保留标题/UP/分P/简介/标签/封面/时长）
# 用法: bash fetch_meta.sh <视频URL> <输出目录> [cookies文件|cookies来源浏览器]
# 例子: bash fetch_meta.sh "https://www.bilibili.com/video/BVxxxx" out/meta "chrome"
#       bash fetch_meta.sh "https://www.bilibili.com/video/BVxxxx" out/meta cookies.txt
#       bash fetch_meta.sh "https://www.bilibili.com/video/BVxxxx" out/meta ""
set -euo pipefail

URL="${1:?用法: bash fetch_meta.sh <视频URL> <输出目录> [cookies文件|cookies来源浏览器]}"
OUT="${2:-.}"
CKARG="${3:-}"

mkdir -p "$OUT"

# yt-dlp 可能只以 Python 模块形式装着，命令不在 PATH 就退回 python -m yt_dlp
if command -v yt-dlp >/dev/null 2>&1; then
  YTDLP=(yt-dlp)
elif python -c "import yt_dlp" >/dev/null 2>&1; then
  YTDLP=(python -m yt_dlp)
else
  echo "没找到 yt-dlp，先装: python -m pip install -U yt-dlp" >&2
  exit 3
fi

CK=()
if [ -n "$CKARG" ]; then
  if [ -f "$CKARG" ]; then
    CK=(--cookies "$CKARG")
  else
    CK=(--cookies-from-browser "$CKARG")
  fi
fi

yt-dlp "${CK[@]}" \
  --skip-download \
  --write-info-json \
  --write-thumbnail --convert-thumbnails jpg \
  --no-warnings --no-check-certificates \
  -o "%(id)s.%(ext)s" -P "$OUT" "$URL"

echo "--- 抓到的文件 ---"
ls -1 "$OUT"
