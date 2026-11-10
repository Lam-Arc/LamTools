#!/usr/bin/env python3
"""阶段门 2：用 ffprobe 校验音频真实时长与元数据时长的差异（默认 5%）。

用法:
    python check_duration.py <音频或视频文件> <info.json> [--tol 0.05] [--json-out check.json]
退出码:
    0 通过, 2 超过容差（需要重下或标记异常）, 3 找不到可比对的时长
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def ffprobe_duration(path: Path) -> float | None:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"[error] ffprobe 读取失败: {exc}", file=sys.stderr)
        return None
    try:
        return float(out)
    except ValueError:
        return None


def pick_meta_duration(media: Path, data: dict) -> tuple[float | None, str]:
    """从 info.json 里挑出与该媒体文件对应的条目时长。"""
    entries = data.get("entries")
    stem = media.name
    if entries:
        for e in entries:
            if not isinstance(e, dict):
                continue
            eid = str(e.get("id") or "")
            if eid and eid in stem and e.get("duration"):
                return float(e["duration"]), f"分P条目 id={eid}"
        durs = [e.get("duration") for e in entries if isinstance(e, dict) and e.get("duration")]
        if len(entries) == 1 and durs:
            return float(durs[0]), "唯一分P条目"
        if durs:
            return None, f"多P视频（{len(entries)} 个 P）无法确定对应条目，请用 --p N 单独抓取"
    if data.get("duration"):
        return float(data["duration"]), "顶层 duration"
    return None, "info.json 没有 duration 字段"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("info_json")
    ap.add_argument("--tol", type=float, default=0.05, help="允许的相对差异，默认 0.05")
    ap.add_argument("--json-out", default="", help="把校验结果写成 json")
    args = ap.parse_args()

    media = Path(args.media)
    if not media.is_file():
        print(f"[error] 找不到媒体文件: {media}", file=sys.stderr)
        return 1
    info_path = Path(args.info_json)
    if not info_path.is_file():
        print(f"[error] 找不到 info.json: {info_path}", file=sys.stderr)
        return 1

    actual = ffprobe_duration(media)
    data = json.loads(info_path.read_text(encoding="utf-8"))
    meta, source = pick_meta_duration(media, data)

    result = {
        "media": str(media),
        "info_json": str(info_path),
        "ffprobe_duration": actual,
        "meta_duration": meta,
        "meta_source": source,
        "tol": args.tol,
    }

    if actual is None:
        print("[error] ffprobe 没读到时长", file=sys.stderr)
        return 3
    if meta is None:
        result["verdict"] = "unknown"
        result["note"] = source
        print(f"[gate] 无法比对：{source}")
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 3

    diff = abs(actual - meta)
    ratio = diff / meta if meta else 0.0
    result.update({"diff_seconds": round(diff, 3), "diff_ratio": round(ratio, 5)})

    print(f"文件: {media.name}")
    print(f"ffprobe 时长: {actual:.3f} 秒")
    print(f"元数据时长:   {meta:.3f} 秒（{source}）")
    print(f"差异:         {diff:.3f} 秒 / {ratio * 100:.2f}%（容差 {args.tol * 100:.1f}%）")

    if ratio > args.tol:
        result["verdict"] = "fail"
        result["action"] = "重下音频；仍不一致则在报告页头标记异常，时间戳以 ffprobe 为准"
        print("[gate] 失败：差异超过容差，按 SKILL.md 第 3 节处理")
        code = 2
    else:
        result["verdict"] = "pass"
        print("[gate] 通过")
        code = 0

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
