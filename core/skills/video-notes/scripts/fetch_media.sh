#!/usr/bin/env bash
# 下载音频（转 mp3）或下载视频（抽真实帧用）
# 用法:
#   bash fetch_media.sh audio <视频URL> <输出目录> [cookies文件|浏览器] [分P, 如 1 或 1,3]
#   bash fetch_media.sh video <视频URL> <输出目录> [cookies文件|浏览器] [最大高度默认720] [分P]
# 例子:
#   bash fetch_media.sh audio "https://www.bilibili.com/video/BVxxxx?p=1" out/audio "" 1
#   bash fetch_media.sh video "https://www.bilibili.com/video/BVxxxx" out/video "chrome" 720
set -euo pipefail

MODE="${1:?用法: bash fetch_media.sh <audio|video> <URL> <输出目录> [cookies] [高度|分P] [分P]}"
URL="${2:?需要视频URL}"
OUT="${3:-.}"
CKARG="${4:-}"
EXTRA="${5:-}"
PARTS="${6:-}"

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

PART_ARG=()
if [ -n "$PARTS" ]; then
  PART_ARG=(--playlist-items "$PARTS")
fi

case "$MODE" in
  audio)
    yt-dlp "${CK[@]}" "${PART_ARG[@]}" \
      -f "bestaudio/best" -x --audio-format mp3 --audio-quality 0 \
      --embed-metadata \
      --no-warnings --no-check-certificates \
      -o "%(id)s.%(ext)s" -P "$OUT" "$URL"
    ;;
  video)
    H="${EXTRA:-720}"
    yt-dlp "${CK[@]}" "${PART_ARG[@]}" \
      -f "bv*[height<=${H}]+ba/b[height<=${H}]/b" \
      --merge-output-format mp4 \
      --no-warnings --no-check-certificates \
      -o "%(id)s.%(ext)s" -P "$OUT" "$URL"
    ;;
  *)
    echo "未知模式: $MODE（只支持 audio / video）" >&2
    exit 2
    ;;
esac

echo "--- 下载结果 ---"
ls -lh "$OUT"
