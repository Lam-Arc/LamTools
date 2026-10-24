"""bili-scroll 的工具处理器。

复刻自 dsh-bili-scroll（MIT）的只读能力层：按公开 Web API 实现，
不内置 Python 运行时、不装第三方包。登录态来自配置里的 Cookie 字段；
没有凭证时各工具返回可读的说明，绝不编造内容。

user:“每天替你刷一轮 B站”+搜索/字幕/评论/信息四类只读能力、
写日报与判重两只窄口工具（路径固定）、发评论一只带审批的写工具。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from lamtools_core.plugin_system.jsonc import load_jsonc_text
from lamtools_core.tool import ToolCall, ToolResult

_PLUGIN_ROOT = Path(__file__).resolve().parent
_DATA_DIR = _PLUGIN_ROOT / "data"
_OUT_DIR = _DATA_DIR / "out"
_DEDUP_PATH = _DATA_DIR / "dedup.json"
# user:“搜索接口对非浏览器 UA 直接 412”+UA 必须是完整浏览器形态。
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_API = "https://api.bilibili.com"
_BV_RE = re.compile(r"^BV[0-9A-Za-z]{8,}$")  # BV 号大小写敏感，禁止归一化
_TAG_RE = re.compile(r"<[^>]+>")


def _config() -> dict[str, Any]:
    path = _DATA_DIR / "config.jsonc"
    try:
        data = load_jsonc_text(path)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _cookies() -> dict[str, str]:
    cfg = _config()
    cookies: dict[str, str] = {}
    if str(cfg.get("sessdata") or "").strip():
        cookies["SESSDATA"] = str(cfg["sessdata"]).strip()
    if str(cfg.get("bili_jct") or "").strip():
        cookies["bili_jct"] = str(cfg["bili_jct"]).strip()
    return cookies


def _client(ua: str = _UA) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": ua, "Referer": "https://www.bilibili.com"},
        cookies=_cookies() or None,
        timeout=12.0,
    )


def _result(call: ToolCall, payload: Any, *, failed: bool = False) -> ToolResult:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=1)
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="failed" if failed else "ok",
        content=text,
        error=text if failed else "",
    )


def _args(call: ToolCall) -> dict[str, Any]:
    return call.arguments if isinstance(call.arguments, dict) else {}


def _bvid(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if _BV_RE.match(text) else None


def _dedup_rows() -> list[dict[str, Any]]:
    try:
        rows = json.loads(_DEDUP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


def _dedup_find(bvid: str, status: str | None = None) -> dict[str, Any] | None:
    for row in reversed(_dedup_rows()):
        if row.get("bvid") == bvid and (status is None or row.get("status") == status):
            return row
    return None


# ── 只读：搜索 / 信息 / 字幕 / 评论 ─────────────────────────────────

async def bili_search(call: ToolCall) -> ToolResult:
    args = _args(call)
    keyword = str(args.get("keyword") or "").strip()
    if not keyword:
        return _result(call, "keyword is required", failed=True)
    days = max(1, min(int(args.get("days") or 3), 14))
    last_note = ""
    try:
        # user:“B站 对匿名搜索的挑战页只认 UA+指纹组合且随时会漂”+按 UA
        # 阶梯逐级重试（浏览器形态 → 朴素客户端），每级先种官方指纹 Cookie；
        # 全被挑战时如实说明，配置 SESSDATA 后最稳。
        for ua in (_UA, "curl/8.0.1"):
            with _client(ua) as client:
                body = None
                for attempt in (1, 2):
                    if attempt == 1 and "buvid3" not in (client.cookies or {}):
                        try:
                            spi = client.get(f"{_API}/x/frontend/finger/spi").json()
                            data = spi.get("data") or {}
                            if data.get("b_3"):
                                client.cookies.set("buvid3", str(data["b_3"]), domain=".bilibili.com")
                            if data.get("b_4"):
                                client.cookies.set("buvid4", str(data["b_4"]), domain=".bilibili.com")
                        except Exception:  # noqa: BLE001 — 引导失败交给下一级
                            pass
                    response = client.get(
                        f"{_API}/x/web-interface/search/type",
                        params={"search_type": "video", "keyword": keyword, "order": "pubdate"},
                        headers={"User-Agent": ua},
                    )
                    try:
                        body = response.json()
                        break
                    except ValueError:
                        last_note = f"HTTP {response.status_code}，返回了挑战页而不是数据"
                        if attempt == 1:
                            continue
        if body is None or body.get("code") != 0:
            if body is None:
                return _result(
                    call,
                    f"搜索被 B站 风控（{last_note}）。匿名搜索时灵时不灵；"
                    "在插件配置里填 SESSDATA 后最稳。",
                    failed=True,
                )
            return _result(call, f"搜索失败：B站 返回 code={body.get('code')}（{body.get('message')}）", failed=True)
    except Exception as exc:  # noqa: BLE001 — 网络失败要可读，不能炸
        return _result(call, f"搜索失败：{type(exc).__name__}: {exc}", failed=True)
    if body is None:
        return _result(call, "搜索失败：未拿到有效响应", failed=True)
    if body.get("code") != 0:
        return _result(call, f"搜索失败：B站 返回 code={body.get('code')}（{body.get('message')}）", failed=True)
    cutoff = datetime.now().timestamp() - days * 86400
    items = []
    for item in (body.get("data") or {}).get("result") or []:
        if item.get("pubdate", 0) < cutoff:
            continue
        items.append(
            {
                "bvid": item.get("bvid"),
                "title": _TAG_RE.sub("", str(item.get("title") or "")),
                "up": item.get("author"),
                "length": item.get("length"),
                "description": str(item.get("description") or "")[:120],
            }
        )
        if len(items) >= 15:
            break
    return _result(call, {"keyword": keyword, "days": days, "count": len(items), "videos": items})


async def bili_video_info(call: ToolCall) -> ToolResult:
    bvid = _bvid(_args(call).get("bvid"))
    if not bvid:
        return _result(call, "bvid 必须是 BV 号（BV 开头）", failed=True)
    try:
        with _client() as client:
            response = client.get(f"{_API}/x/web-interface/view", params={"bvid": bvid})
            response.raise_for_status()
            body = response.json()
    except Exception as exc:  # noqa: BLE001
        return _result(call, f"读取失败：{type(exc).__name__}: {exc}", failed=True)
    if body.get("code") != 0:
        return _result(call, f"读取失败：B站 返回 code={body.get('code')}（{body.get('message')}）", failed=True)
    data = body.get("data") or {}
    stat = data.get("stat") or {}
    return _result(
        call,
        {
            "bvid": data.get("bvid"),
            "title": data.get("title"),
            "up": (data.get("owner") or {}).get("name"),
            "duration_sec": data.get("duration"),
            "desc": str(data.get("desc") or "")[:400],
            "cover": data.get("pic"),
            "views": stat.get("view"),
            "replies": stat.get("reply"),
            "pubdate": datetime.fromtimestamp(data.get("pubdate", 0)).strftime("%Y-%m-%d"),
        },
    )


async def bili_subtitles(call: ToolCall) -> ToolResult:
    bvid = _bvid(_args(call).get("bvid"))
    if not bvid:
        return _result(call, "bvid 必须是 BV 号（BV 开头）", failed=True)
    try:
        with _client() as client:
            view = client.get(f"{_API}/x/web-interface/view", params={"bvid": bvid}).json()
            if view.get("code") != 0:
                return _result(call, f"读取失败：B站 返回 code={view.get('code')}", failed=True)
            cid = (view.get("data") or {}).get("cid")
            player = client.get(
                f"{_API}/x/player/v2", params={"bvid": bvid, "cid": cid}
            ).json()
            subtitles = ((player.get("data") or {}).get("subtitle") or {}).get("subtitles") or []
            if not subtitles:
                # user:“空是一种结果，不是坏了”+没字幕如实说明，值班轮据此按
                # “跳过（无字幕）”记账继续下一条，绝不编造内容。
                logged_in = bool(_cookies().get("SESSDATA"))
                reason = (
                    "这条视频没有可读的字幕（B站 AI 字幕需要登录态，当前未配置 Cookie）。"
                    if not logged_in
                    else "这条视频没有字幕（可能是无语音的演示/纯音乐视频）。"
                )
                return _result(call, {"bvid": bvid, "subtitles": "", "note": reason})
            url = str(subtitles[0].get("subtitle_url") or "")
            if url.startswith("//"):
                url = f"https:{url}"
            body = client.get(url).json()
            lines = [entry.get("content", "") for entry in (body.get("body") or [])]
    except Exception as exc:  # noqa: BLE001
        return _result(call, f"字幕读取失败：{type(exc).__name__}: {exc}", failed=True)
    return _result(call, {"bvid": bvid, "subtitles": "\n".join(lines)[:8000], "lines": len(lines)})


async def bili_comments(call: ToolCall) -> ToolResult:
    bvid = _bvid(_args(call).get("bvid"))
    if not bvid:
        return _result(call, "bvid 必须是 BV 号（BV 开头）", failed=True)
    try:
        with _client() as client:
            view = client.get(f"{_API}/x/web-interface/view", params={"bvid": bvid}).json()
            if view.get("code") != 0:
                return _result(call, f"读取失败：B站 返回 code={view.get('code')}", failed=True)
            aid = (view.get("data") or {}).get("aid")
            reply = client.get(
                f"{_API}/x/v2/reply",
                params={"type": 1, "oid": aid, "ps": 20, "sort": 1},
            ).json()
    except Exception as exc:  # noqa: BLE001
        return _result(call, f"评论读取失败：{type(exc).__name__}: {exc}", failed=True)
    if reply.get("code") != 0:
        return _result(call, f"评论读取失败：B站 返回 code={reply.get('code')}", failed=True)
    items = [
        {
            "user": (item.get("member") or {}).get("uname"),
            "text": str((item.get("content") or {}).get("message") or "")[:200],
            "likes": item.get("like"),
        }
        for item in ((reply.get("data") or {}).get("replies") or [])[:20]
    ]
    return _result(call, {"bvid": bvid, "count": len(items), "comments": items})


# ── 窄口：写日报 / 判重（路径固定，不接受路径参数）───────────────────

async def bili_save_report(call: ToolCall) -> ToolResult:
    args = _args(call)
    bvid = _bvid(args.get("bvid"))
    text = str(args.get("text") or "").strip()
    if not bvid:
        return _result(call, "bvid 必须是 BV 号（BV 开头）", failed=True)
    if not text:
        return _result(call, "text 不能为空", failed=True)
    today = datetime.now().strftime("%Y-%m-%d")
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = _OUT_DIR / f"{today}.md"
    if not path.exists():
        path.write_text(f"# 刷B站日报 {today}\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"### {bvid}\n{text}\n\n")
    return _result(call, {"saved": True, "file": str(path), "section": f"### {bvid}"})


async def bili_dedup(call: ToolCall) -> ToolResult:
    args = _args(call)
    action = str(args.get("action") or "").strip()
    if action == "list":
        rows = list(reversed(_dedup_rows()))[:40]
        return _result(call, {"count": len(rows), "recent": rows})
    if action == "mark":
        bvid = _bvid(args.get("bvid"))
        status = str(args.get("status") or "").strip()
        if not bvid or status not in {"picked", "skipped", "commented"}:
            return _result(call, "mark 需要 bvid 与 status（picked/skipped/commented）", failed=True)
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        rows = _dedup_rows()
        rows.append(
            {
                "bvid": bvid,
                "title": str(args.get("title") or "")[:120],
                "up": str(args.get("up") or "")[:60],
                "status": status,
                "date": datetime.now().strftime("%Y-%m-%d"),
            }
        )
        _DEDUP_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        return _result(call, {"marked": bvid, "status": status, "total": len(rows)})
    return _result(call, "action 必须是 list 或 mark", failed=True)


# ── 写：发评论（需要登录凭证 + 用户确认 + 判重与限额由配置管）────────

async def bili_post_comment(call: ToolCall) -> ToolResult:
    args = _args(call)
    bvid = _bvid(args.get("bvid"))
    content = str(args.get("content") or "").strip()
    cfg = _config()
    if not bvid:
        return _result(call, "bvid 必须是 BV 号（BV 开头）", failed=True)
    if not content:
        return _result(call, "content 不能为空", failed=True)
    if len(content) > 300:
        return _result(call, "评论超过 300 字，请精简后再发", failed=True)
    # user:“你收到的每一条 @，都是它先筛过一遍的”+发评论必须显式打开开关、
    # 同一视频只发一次；这两道闸在处理器里硬性生效，不靠提示词自觉。
    if not bool(cfg.get("auto_comment")):
        return _result(
            call,
            "自动评论未开启（配置里 auto_comment=false）。要替使用者发言，先在插件页打开开关。",
            failed=True,
        )
    if _dedup_find(bvid, "commented"):
        return _result(call, f"判重表显示 {bvid} 已经评论过，同一视频只发一次。", failed=True)
    cookies = _cookies()
    csrf = str(cfg.get("bili_jct") or "").strip()
    if not cookies.get("SESSDATA") or not csrf:
        return _result(
            call,
            "未配置登录凭证：需要在插件配置里填 SESSDATA 与 bili_jct（浏览器 Cookie 里的两个值）。",
            failed=True,
        )
    try:
        with _client() as client:
            view = client.get(f"{_API}/x/web-interface/view", params={"bvid": bvid}).json()
            aid = (view.get("data") or {}).get("aid")
            response = client.post(
                f"{_API}/x/v2/reply/add",
                data={"oid": aid, "type": 1, "message": content, "csrf": csrf, "csrf_token": csrf},
            )
            body = response.json()
    except Exception as exc:  # noqa: BLE001
        return _result(call, f"评论发送失败：{type(exc).__name__}: {exc}", failed=True)
    if body.get("code") != 0:
        return _result(
            call,
            f"评论被 B站 拒绝：code={body.get('code')}（{body.get('message')}）。"
            "凭证可能过期，或触发了风控；不要重试刷屏。",
            failed=True,
        )
    rpid = ((body.get("data") or {}).get("rpid")) or ""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows = _dedup_rows()
    rows.append(
        {
            "bvid": bvid,
            "title": "",
            "up": "",
            "status": "commented",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "rpid": rpid,
            "excerpt": content[:20],
        }
    )
    _DEDUP_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return _result(call, {"posted": True, "bvid": bvid, "rpid": rpid})


async def bili_account_status(call: ToolCall) -> ToolResult:
    if not _cookies().get("SESSDATA"):
        return _result(
            call,
            {
                "logged_in": False,
                "note": "未配置 SESSDATA：字幕读不到、评论发不了；搜索/信息/评论（看）不受影响。",
            },
        )
    try:
        with _client() as client:
            response = client.get(f"{_API}/x/web-interface/nav")
            body = response.json()
    except Exception as exc:  # noqa: BLE001
        return _result(call, f"状态查询失败：{type(exc).__name__}: {exc}", failed=True)
    data = body.get("data") or {}
    if not data.get("isLogin"):
        return _result(call, {"logged_in": False, "note": "Cookie 已失效，请重新填写。"})
    return _result(call, {"logged_in": True, "mid": data.get("mid"), "uname": data.get("uname")})
