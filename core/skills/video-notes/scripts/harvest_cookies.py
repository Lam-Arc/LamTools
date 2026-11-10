#!/usr/bin/env python3
"""用本机 Chromium 访问站点并导出 Netscape 格式 cookies.txt，交给 yt-dlp 用。

用途：B 站/YouTube 遇 412 或要求登录时，浏览器 cookie 库被 App-Bound 加密读不出来
（yt-dlp 报 Failed to decrypt with DPAPI），就用这个脚本走浏览器本身拿 cookie。

用法:
    # 匿名取 cookie（B 站首次访问会下发 buvid3，通常足够过 412）
    python harvest_cookies.py --url "https://www.bilibili.com/video/BVxxxx" --out out/cookies.txt
    # 需要登录态（高清、会员内容）：开有头浏览器，人工登录后回车/等够时间
    python harvest_cookies.py --url "https://www.bilibili.com/video/BVxxxx" --out out/cookies.txt --login 120
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HEADER = "# Netscape HTTP Cookie File\n# 由 harvest_cookies.py 生成，供 yt-dlp --cookies 使用\n\n"


def to_netscape(cookies: list[dict]) -> str:
    lines = [HEADER]
    for c in cookies:
        domain = c.get("domain") or ""
        include_sub = "TRUE" if domain.startswith(".") else "FALSE"
        path = c.get("path") or "/"
        secure = "TRUE" if c.get("secure") else "FALSE"
        expires = c.get("expires")
        expires = int(expires) if isinstance(expires, (int, float)) and expires and expires > 0 else 0
        name = c.get("name") or ""
        value = c.get("value") or ""
        lines.append(f"{domain}\t{include_sub}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
    return "".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="要访问的站点地址（给视频页最好）")
    ap.add_argument("--out", required=True, help="cookies.txt 输出路径")
    ap.add_argument("--login", type=int, default=0, help=">0 时开有头浏览器，等这么多秒供人工登录")
    ap.add_argument("--wait", type=int, default=6, help="打开页面后等几秒再取 cookie")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    headed = args.login > 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(
            locale="zh-CN",
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        print(f"[info] 打开 {args.url}")
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(args.wait * 1000)

        if headed:
            print(f"[login] 浏览器已打开，请在 {args.login} 秒内完成登录")
            for left in range(args.login, 0, -10):
                print(f"[login] 剩余 {left} 秒")
                time.sleep(min(10, left))
            page.wait_for_timeout(1000)

        cookies = context.cookies()
        browser.close()

    out.write_text(to_netscape(cookies), encoding="utf-8")
    names = {c["name"] for c in cookies}
    print(f"[ok] 导出 {len(cookies)} 条 cookie 到 {out}")
    for key in ("SESSDATA", "buvid3", "buvid4", "bili_jct", "DedeUserID"):
        if key in names:
            print(f"     含 {key}")
    if "SESSDATA" not in names:
        print("[hint] 没有登录态 cookie（SESSDATA），能拿元数据和普通清晰度音频；需要高清就加 --login 重跑")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
