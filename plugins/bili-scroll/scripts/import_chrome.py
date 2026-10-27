#!/usr/bin/env python3
"""从本机 Chrome 的 B 站登录态导入凭证。

用法：
    <插件>/data/duty/.venv/Scripts/python.exe <插件>/scripts/import_chrome.py --write
    ... --json          # 只打印，不落盘（不要把带有 cookie 的输出贴进对话）

--write 直接写 <插件>/data/duty/bili_credential.json，字段与 MCP 服务器一致：
sessdata / bili_jct / buvid3 / dedeuserid。
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DUTY = ROOT / "data" / "duty"
CRED = DUTY / "bili_credential.json"
WANT = {
    "SESSDATA": "sessdata",
    "bili_jct": "bili_jct",
    "DedeUserID": "dedeuserid",
    "buvid3": "buvid3",
}


def _buvid3() -> str:
    try:
        req = urllib.request.Request(
            "https://api.bilibili.com/x/frontend/finger/spi",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return str((data.get("data") or {}).get("b_3") or "")
    except Exception:
        return ""


def main(argv: list[str]) -> int:
    try:
        import browser_cookie3
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"browser_cookie3 没装：{exc}"}, ensure_ascii=False))
        return 1
    try:
        jar = browser_cookie3.chrome(domain_name="bilibili.com")
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"读 Chrome cookie 失败：{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2
    values: dict[str, str] = {}
    for cookie in jar:
        key = WANT.get(cookie.name)
        if key and cookie.value:
            values[key] = cookie.value
    if not values.get("sessdata"):
        print(json.dumps({"ok": False, "error": "Chrome 里没有找到 B 站 SESSDATA；先在 Chrome 登录 B 站"}, ensure_ascii=False))
        return 3
    if not values.get("buvid3"):
        values["buvid3"] = _buvid3()
    payload = {
        "sessdata": values.get("sessdata", ""),
        "bili_jct": values.get("bili_jct", ""),
        "buvid3": values.get("buvid3", ""),
        "dedeuserid": values.get("dedeuserid", ""),
    }
    if "--write" not in argv:
        print(json.dumps({"ok": True, "source": "chrome", "fields": sorted(payload), "account": payload.get("dedeuserid", "")}, ensure_ascii=False))
        return 0
    DUTY.mkdir(parents=True, exist_ok=True)
    CRED.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        if sys.platform == "win32":
            user = __import__("os").environ.get("USERNAME") or ""
            subprocess.run(["icacls", str(CRED), "/inheritance:r", "/grant:r", f"{user}:F"],
                           capture_output=True, timeout=30)
    except Exception:
        pass
    print(json.dumps({"ok": True, "source": "chrome", "file": str(CRED), "account": payload.get("dedeuserid", "")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
