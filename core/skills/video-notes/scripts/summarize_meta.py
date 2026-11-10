#!/usr/bin/env python3
"""把 yt-dlp 的 info.json 汇总成中文清单，并生成 meta.md。

用法:
    python summarize_meta.py <meta目录或单个info.json> [--out meta.md]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def hms(sec) -> str:
    try:
        sec = float(sec)
    except (TypeError, ValueError):
        return "未知"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def load_infos(target: Path) -> list[dict]:
    if target.is_file():
        files = [target]
    else:
        files = sorted(target.glob("*.info.json"))
    infos = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 解析失败 {f}: {exc}", file=sys.stderr)
            continue
        data["_file"] = str(f)
        infos.append(data)
    return infos


def entry_lines(data: dict) -> list[dict]:
    """把 info.json 归一化成条目列表，多 P 视频每个 P 一条。"""
    uploader = (
        data.get("uploader")
        or data.get("channel")
        or (data.get("owner") or {}).get("name")
        or "未知"
    )
    tags = data.get("tags") or []
    desc = (data.get("description") or "").strip()
    thumb = data.get("thumbnail") or ""
    entries = data.get("entries")
    if entries:
        out = []
        for i, e in enumerate(entries, 1):
            if not isinstance(e, dict):
                continue
            out.append(
                {
                    "index": i,
                    "id": e.get("id") or data.get("id") or "",
                    "title": e.get("title") or "",
                    "duration": e.get("duration"),
                    "url": e.get("webpage_url") or e.get("url") or "",
                    "uploader": e.get("uploader") or uploader,
                    "tags": e.get("tags") or tags,
                    "description": (e.get("description") or desc).strip(),
                    "thumbnail": e.get("thumbnail") or thumb,
                }
            )
        return out
    return [
        {
            "index": 1,
            "id": data.get("id") or "",
            "title": data.get("title") or "",
            "duration": data.get("duration"),
            "url": data.get("webpage_url") or data.get("original_url") or "",
            "uploader": uploader,
            "tags": tags,
            "description": desc,
            "thumbnail": thumb,
        }
    ]


def top_meta(data: dict, items: list[dict]) -> dict:
    """整片层级的信息：多 P 视频要用合集自己的标题和地址，不能拿第一个 P 顶替。"""
    first = items[0]
    return {
        "title": data.get("title") or first["title"],
        "uploader": data.get("uploader")
        or data.get("channel")
        or (data.get("owner") or {}).get("name")
        or first["uploader"],
        "url": data.get("webpage_url") or data.get("original_url") or first["url"],
        "tags": data.get("tags") or first["tags"],
        "thumbnail": data.get("thumbnail") or first["thumbnail"],
        "description": (data.get("description") or first["description"]).strip(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="meta 目录或 info.json 路径")
    ap.add_argument("--out", default="", help="写出 meta.md 的路径")
    ap.add_argument("--desc-limit", type=int, default=800, help="简介截断长度")
    args = ap.parse_args()

    infos = load_infos(Path(args.target))
    if not infos:
        print("没有找到任何 info.json", file=sys.stderr)
        return 1

    lines: list[str] = []
    bad = 0
    for data in infos:
        items = entry_lines(data)
        head = top_meta(data, items)
        lines.append(f"# {head['title'] or '（无标题）'}")
        lines.append("")
        lines.append(f"- UP 主: {head['uploader']}")
        total = data.get("duration")
        lines.append(f"- 时长: {hms(total)}（{total} 秒）" if total else "- 时长: 未知")
        lines.append(f"- 分 P 数: {len(items)}")
        lines.append(f"- 标签: {', '.join(head['tags']) if head['tags'] else '无'}")
        lines.append(f"- 封面: {head['thumbnail'] or '无'}")
        if head["url"]:
            lines.append(f"- 源地址: {head['url']}")
        lines.append(f"- 元数据文件: {data.get('_file', '')}")
        lines.append("")
        if len(items) > 1:
            lines.append("## 分 P")
            lines.append("")
            lines.append("| # | 标题 | 时长 | id |")
            lines.append("|---|---|---|---|")
            for it in items:
                lines.append(
                    f"| {it['index']} | {it['title']} | {hms(it['duration'])} | {it['id']} |"
                )
            lines.append("")
        desc = head["description"]
        if desc:
            lines.append("## 简介")
            lines.append("")
            lines.append(desc[: args.desc_limit] + ("…" if len(desc) > args.desc_limit else ""))
            lines.append("")

        for it in items:
            if not it["title"] or not it["duration"]:
                bad += 1
                print(f"[warn] 条目缺标题或时长: index={it['index']} id={it['id']}", file=sys.stderr)

    text = "\n".join(lines) + "\n"
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"[ok] 已写出 {args.out}", file=sys.stderr)

    if bad:
        print(f"[gate] 有 {bad} 个条目缺标题或时长，触发阶段门 1 失败", file=sys.stderr)
        return 2
    print("[gate] 元数据阶段门通过", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
