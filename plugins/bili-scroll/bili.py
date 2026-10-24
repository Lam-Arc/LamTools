"""bili-scroll 的工具处理器。

复刻自 dsh-bili-scroll（MIT）的只读能力层：按公开 Web API 实现，
不内置 Python 运行时、不装第三方包。登录态来自配置里的 Cookie 字段；
没有凭证时各工具返回可读的说明，绝不编造内容。

user:“每天替你刷一轮 B站”+搜索/字幕/评论/信息四类只读能力、
写日报与判重两只窄口工具（路径固定）、发评论一只带审批的写工具。
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
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


_WBI_MIXIN_TAB = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
)
_WBI_CACHE: dict[str, Any] = {"key": "", "ts": 0.0}


def _wbi_mixin_key(client: httpx.Client) -> str:
    """从 nav 取 img/sub key，按官方重排表拼出 32 位 mixin key，缓存一小时。"""
    now = datetime.now().timestamp()
    if _WBI_CACHE["key"] and now - float(_WBI_CACHE["ts"]) < 3600:
        return str(_WBI_CACHE["key"])
    nav = client.get(f"{_API}/x/web-interface/nav").json()
    wbi = (nav.get("data") or {}).get("wbi_img") or {}
    img = str(wbi.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
    sub = str(wbi.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
    raw = img + sub
    if len(raw) < 64:
        return ""
    key = "".join(raw[i] for i in _WBI_MIXIN_TAB)[:32]
    _WBI_CACHE.update({"key": key, "ts": now})
    return key


def _wbi_signed(client: httpx.Client, params: dict[str, Any]) -> dict[str, Any]:
    """给参数补 wts 与 w_rid；拿不到 key 时只补 wts，交给上游如实报失败。"""
    signed = {k: v for k, v in params.items() if v is not None}
    signed["wts"] = int(datetime.now().timestamp())
    key = _wbi_mixin_key(client)
    if not key:
        return signed
    query = urllib.parse.urlencode(sorted(signed.items()))
    signed["w_rid"] = hashlib.md5((query + key).encode()).hexdigest()
    return signed



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


# ── 值班简报（工具与操作共用一份载荷）────────────────────────────────

def duty_brief_payload() -> dict[str, Any]:
    cfg = _config()
    today = datetime.now().strftime("%Y-%m-%d")
    today_report = _OUT_DIR / f"{today}.md"
    seen = list(reversed(_dedup_rows()))[:40]
    return {
        "keywords": cfg.get("keywords") or [],
        "per_day": cfg.get("per_day", 5),
        "comment_per_round": cfg.get("comment_per_round", 1),
        "auto_comment": bool(cfg.get("auto_comment")),
        "mention_name": cfg.get("mention_name") or "",
        "report_level": cfg.get("report_level") or "full",
        "logged_in": bool(_cookies().get("SESSDATA")),
        "seen_recent": seen,
        "seen_total": len(_dedup_rows()),
        "today_report": str(today_report) if today_report.exists() else "",
    }


async def bili_brief(call: ToolCall) -> ToolResult:
    # user:“章程第一步拿参数”+操作是命令/面板的通道，模型调不了；
    # 简报必须是模型工具列表里的真工具。
    return _result(call, duty_brief_payload())


# ── 只读：搜索 / 信息 / 字幕 / 评论 ─────────────────────────────────

async def bili_search(call: ToolCall) -> ToolResult:
    args = _args(call)
    keyword = str(args.get("keyword") or "").strip()
    if not keyword:
        return _result(call, "keyword is required", failed=True)
    days = max(1, min(int(args.get("days") or 3), 14))
    last_note = ""
    body: Any = None
    try:
        with _client() as client:
            # 先种官方指纹：buvid3/4 缺失时 wbi 搜索同样会被挑战
            try:
                spi = client.get(f"{_API}/x/frontend/finger/spi").json()
                spi_data = spi.get("data") or {}
                if spi_data.get("b_3"):
                    client.cookies.set("buvid3", str(spi_data["b_3"]), domain=".bilibili.com")
                if spi_data.get("b_4"):
                    client.cookies.set("buvid4", str(spi_data["b_4"]), domain=".bilibili.com")
            except Exception:  # noqa: BLE001 — 指纹失败不影响签名主路径
                pass
            # user:“老接口 search/type 现在直接吐挑战页”+改走 wbi 签名接口，
            # 缺 w_rid 一律被挡；登录态仍从配置里的 Cookie 来。
            response = client.get(
                f"{_API}/x/web-interface/wbi/search/type",
                params=_wbi_signed(
                    client,
                    {
                        "search_type": "video",
                        "keyword": keyword,
                        "order": "pubdate",
                        "page": 1,
                    },
                ),
                headers={"User-Agent": _UA},
            )
            try:
                body = response.json()
            except ValueError:
                last_note = f"HTTP {response.status_code}，返回了挑战页而不是数据"
    except Exception as exc:  # noqa: BLE001 — 网络失败要可读，不能炸
        return _result(call, f"搜索失败：{type(exc).__name__}: {exc}", failed=True)
    if body is None:
        return _result(
            call,
            f"搜索被 B站 风控（{last_note}）。已改用 wbi 签名接口，仍失败多半是"
            "WBI key 过期或指纹被盯上；隔一会儿重试，别连刷。",
            failed=True,
        )
    if body.get("code") != 0:
        return _result(call, f"搜索失败：B站 返回 code={body.get('code')}（{body.get('message')}）", failed=True)

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


# ── 私信：投递与收件箱（原版 dm.mjs 的端点与闸门，窄口收件人）────────

def _receiver_mid(cfg: dict[str, Any], own_mid: int) -> int:
    # user:“私信发给谁（UID）可留空”+留空发给登录账号自己，不开放任意收件人。
    uid = int(cfg.get("dm_uid") or 0)
    return uid if uid > 0 else own_mid


async def bili_send_dm(call: ToolCall) -> ToolResult:
    args = _args(call)
    content = str(args.get("content") or "").strip()
    cfg = _config()
    cookies = _cookies()
    if not content:
        return _result(call, "content 不能为空", failed=True)
    if not cookies.get("SESSDATA") or not str(cfg.get("bili_jct") or "").strip():
        return _result(call, "未配置登录凭证（SESSDATA 与 bili_jct）", failed=True)
    if str(cfg.get("dm_mode") or "only").strip().lower() == "off":
        return _result(call, "私信投递未开启（配置里 dm_mode=off）", failed=True)
    try:
        with _client() as client:
            nav = client.get(f"{_API}/x/web-interface/nav").json()
            own_mid = int(((nav.get("data") or {}).get("mid")) or 0)
            if own_mid <= 0:
                return _result(call, "Cookie 已失效，无法投递私信", failed=True)
            dev_id = str(__import__("uuid").uuid4())
            response = client.post(
                "https://api.vc.bilibili.com/web_im/v1/web_im/send_msg",
                data={
                    "sender_uid": own_mid,
                    "receiver_id": _receiver_mid(cfg, own_mid),
                    "receiver_type": 1,
                    "msg_type": 1,
                    "msg_status": 1,
                    "content": json.dumps({"content": content}, ensure_ascii=False),
                    "csrf_token": str(cfg.get("bili_jct")),
                    "csrf": str(cfg.get("bili_jct")),
                    "dev_id": dev_id,
                    "from_firework": 0,
                    "build": 0,
                    "mobi_app": "web",
                },
                headers={"Referer": "https://message.bilibili.com/"},
            )
            body = response.json()
    except Exception as exc:  # noqa: BLE001
        return _result(call, f"私信发送失败：{type(exc).__name__}: {exc}", failed=True)
    if body.get("code") != 0:
        return _result(call, f"私信被 B站 拒绝：code={body.get('code')}（{body.get('message')}）", failed=True)
    msg_key = ((body.get("data") or {}).get("msg_key")) or ""
    if not msg_key:
        # user:“接口回了成功但没有投递回执 ⇒ 可能没真正送到”+原版踩过的坑照搬。
        return _result(call, "接口回了成功但没有投递回执（msg_key）：可能没真正送到，不要重复发送。", failed=True)
    return _result(call, {"sent": True, "msg_key": str(msg_key)[:16]})


async def bili_dm_inbox(call: ToolCall) -> ToolResult:
    # user:“私信双向”+默认关闭；开关打开后读最近会话预览，回话决策按章程。
    cfg = _config()
    if not bool(cfg.get("dm_reply")):
        return _result(call, "私信双向未开启（配置里 dm_reply=false）", failed=True)
    cookies = _cookies()
    if not cookies.get("SESSDATA"):
        return _result(call, "未配置登录凭证（SESSDATA）", failed=True)
    try:
        with _client() as client:
            sessions = client.get(
                "https://api.vc.bilibili.com/session_svr/v1/session_svr/get_sessions",
                params={"session_type": 1, "group_id": 0, "build": 0, "mobi_app": "web"},
            ).json()
    except Exception as exc:  # noqa: BLE001
        return _result(call, f"收件箱读取失败：{type(exc).__name__}: {exc}", failed=True)
    if sessions.get("code") != 0:
        return _result(call, f"收件箱读取失败：code={sessions.get('code')}", failed=True)
    items = []
    for session in ((sessions.get("data") or {}).get("session_list") or [])[:10]:
        preview = ""
        try:
            last = json.loads((session.get("last_msg") or {}).get("content") or "{}")
            preview = str(last.get("content") or last.get("text") or "")[:80]
        except (ValueError, TypeError):
            preview = ""
        items.append(
            {
                "uid": session.get("talker_id"),
                "unread": session.get("unread_count"),
                "preview": preview,
            }
        )
    return _result(call, {"count": len(items), "sessions": items})


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
