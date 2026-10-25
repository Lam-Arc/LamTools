"""bili-scroll 核心逻辑（独立模块：仅依赖标准库与 httpx）。

被 MCP 服务端（server/bili_server.py）共享；服务端跑在插件自管的 venv 里，
因此本模块**不得导入宿主**。data 目录按本文件位置推导。

约定：预期失败抛 ValueError（message 可读），成功返回 dict/str。
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

_PLUGIN_ROOT = Path(__file__).resolve().parent
_DATA_DIR = _PLUGIN_ROOT / "data"
_OUT_DIR = _DATA_DIR / "out"
_DEDUP_PATH = _DATA_DIR / "dedup.json"
# user:“搜索接口对非浏览器 UA 直接 412 风控”+UA 必须是完整浏览器形态。
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_API = "https://api.bilibili.com"
_BV_RE = re.compile(r"^BV[0-9A-Za-z]{8,}$")  # BV 号大小写敏感，禁止归一化
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_jsonc(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(nxt)
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def load_jsonc(path: Path) -> dict[str, Any]:
    data = json.loads(_strip_jsonc(path.read_text(encoding="utf-8-sig")))
    return data if isinstance(data, dict) else {}


def _config() -> dict[str, Any]:
    path = _DATA_DIR / "config.jsonc"
    if not path.exists():
        return {}
    try:
        return load_jsonc(path)
    except (OSError, ValueError):
        return {}


def _cookies() -> dict[str, str]:
    cfg = _config()
    cookies: dict[str, str] = {}
    if str(cfg.get("sessdata") or "").strip():
        cookies["SESSDATA"] = str(cfg["sessdata"]).strip()
    if str(cfg.get("bili_jct") or "").strip():
        cookies["bili_jct"] = str(cfg["bili_jct"]).strip()
    return cookies


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": _UA, "Referer": "https://www.bilibili.com"},
        cookies=_cookies() or None,
        timeout=12.0,
    )


def _bvid(value: Any) -> str:
    text = str(value or "").strip()
    if not _BV_RE.match(text):
        raise ValueError("bvid 必须是 BV 号（BV 开头）")
    return text


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


def duty_brief_payload() -> dict[str, Any]:
    cfg = _config()
    today = datetime.now().strftime("%Y-%m-%d")
    today_report = _OUT_DIR / f"{today}.md"
    return {
        "keywords": cfg.get("keywords") or [],
        "per_day": cfg.get("per_day", 5),
        "comment_per_round": cfg.get("comment_per_round", 1),
        "auto_comment": bool(cfg.get("auto_comment")),
        "mention_name": cfg.get("mention_name") or "",
        "report_level": cfg.get("report_level") or "full",
        "logged_in": bool(_cookies().get("SESSDATA")),
        "seen_recent": list(reversed(_dedup_rows()))[:40],
        "seen_total": len(_dedup_rows()),
        "today_report": str(today_report) if today_report.exists() else "",
    }


# ── 只读：搜索 / 信息 / 字幕 / 评论 ─────────────────────────────────


async def bili_search(keyword: str, days: int = 3) -> dict[str, Any]:
    keyword = str(keyword or "").strip()
    if not keyword:
        raise ValueError("keyword is required")
    days = max(1, min(int(days or 3), 14))
    try:
        with _client() as client:
            body = None
            for attempt in (1, 2):
                # user:“B站 对无 Cookie 的搜索间歇性 412 风控”+先取官方指纹
                # Cookie 再搜；仍被风控就如实说，不硬刷。
                if attempt == 1 and "buvid3" not in (client.cookies or {}):
                    try:
                        spi = client.get(f"{_API}/x/frontend/finger/spi").json()
                        data = spi.get("data") or {}
                        if data.get("b_3"):
                            client.cookies.set("buvid3", str(data["b_3"]), domain=".bilibili.com")
                        if data.get("b_4"):
                            client.cookies.set("buvid4", str(data["b_4"]), domain=".bilibili.com")
                    except Exception:  # noqa: BLE001 — 引导失败交给搜索本身的报错
                        pass
                response = client.get(
                    f"{_API}/x/web-interface/search/type",
                    params={"search_type": "video", "keyword": keyword, "order": "pubdate"},
                    headers={"User-Agent": _UA},
                )
                try:
                    body = response.json()
                    break
                except ValueError:
                    last_note = f"HTTP {response.status_code}，返回了挑战页而不是数据"
                    if attempt == 1:
                        continue
                    raise ValueError(
                        f"搜索被 B站 风控（{last_note}）。匿名搜索时灵时不灵；"
                        "在插件配置里填 SESSDATA 后最稳。"
                    ) from None
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 — 网络失败要可读，不能炸
        raise ValueError(f"搜索失败：{type(exc).__name__}: {exc}") from exc
    if body is None or body.get("code") != 0:
        detail = (body or {}).get("message") if isinstance(body, dict) else "无响应"
        raise ValueError(f"搜索失败：B站 返回 code={(body or {}).get('code')}（{detail}）")
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
    return {"keyword": keyword, "days": days, "count": len(items), "videos": items}


async def bili_video_info(bvid: str) -> dict[str, Any]:
    bvid = _bvid(bvid)
    try:
        with _client() as client:
            body = client.get(f"{_API}/x/web-interface/view", params={"bvid": bvid}).json()
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"读取失败：{type(exc).__name__}: {exc}") from exc
    if body.get("code") != 0:
        raise ValueError(f"读取失败：B站 返回 code={body.get('code')}（{body.get('message')}）")
    data = body.get("data") or {}
    stat = data.get("stat") or {}
    return {
        "bvid": data.get("bvid"),
        "title": data.get("title"),
        "up": (data.get("owner") or {}).get("name"),
        "duration_sec": data.get("duration"),
        "desc": str(data.get("desc") or "")[:400],
        "cover": data.get("pic"),
        "views": stat.get("view"),
        "replies": stat.get("reply"),
        "pubdate": datetime.fromtimestamp(data.get("pubdate", 0)).strftime("%Y-%m-%d"),
    }


async def bili_subtitles(bvid: str) -> dict[str, Any]:
    bvid = _bvid(bvid)
    try:
        with _client() as client:
            view = client.get(f"{_API}/x/web-interface/view", params={"bvid": bvid}).json()
            if view.get("code") != 0:
                raise ValueError(f"读取失败：B站 返回 code={view.get('code')}")
            cid = (view.get("data") or {}).get("cid")
            player = client.get(
                f"{_API}/x/player/v2", params={"bvid": bvid, "cid": cid}
            ).json()
            subtitles = ((player.get("data") or {}).get("subtitle") or {}).get("subtitles") or []
            if not subtitles:
                # user:“空是一种结果，不是坏了”+没字幕如实说明，值班轮据此
                # 按“跳过（无字幕）”记账继续下一条，绝不编造内容。
                logged_in = bool(_cookies().get("SESSDATA"))
                reason = (
                    "这条视频没有可读的字幕（B站 AI 字幕需要登录态，当前未配置 Cookie）。"
                    if not logged_in
                    else "这条视频没有字幕（可能是无语音的演示/纯音乐视频）。"
                )
                return {"bvid": bvid, "subtitles": "", "note": reason}
            url = str(subtitles[0].get("subtitle_url") or "")
            if url.startswith("//"):
                url = f"https:{url}"
            body = client.get(url).json()
            lines = [entry.get("content", "") for entry in (body.get("body") or [])]
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"字幕读取失败：{type(exc).__name__}: {exc}") from exc
    return {"bvid": bvid, "subtitles": "\n".join(lines)[:8000], "lines": len(lines)}


async def bili_comments(bvid: str) -> dict[str, Any]:
    bvid = _bvid(bvid)
    try:
        with _client() as client:
            view = client.get(f"{_API}/x/web-interface/view", params={"bvid": bvid}).json()
            if view.get("code") != 0:
                raise ValueError(f"读取失败：B站 返回 code={view.get('code')}")
            aid = (view.get("data") or {}).get("aid")
            reply = client.get(
                f"{_API}/x/v2/reply",
                params={"type": 1, "oid": aid, "ps": 20, "sort": 1},
            ).json()
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"评论读取失败：{type(exc).__name__}: {exc}") from exc
    if reply.get("code") != 0:
        raise ValueError(f"评论读取失败：B站 返回 code={reply.get('code')}")
    items = [
        {
            "user": (item.get("member") or {}).get("uname"),
            "text": str((item.get("content") or {}).get("message") or "")[:200],
            "likes": item.get("like"),
        }
        for item in ((reply.get("data") or {}).get("replies") or [])[:20]
    ]
    return {"bvid": bvid, "count": len(items), "comments": items}


# ── 窄口：写日报 / 判重（路径固定，不接受路径参数）──────────────────


async def bili_save_report(bvid: str, text: str) -> dict[str, Any]:
    bvid = _bvid(bvid)
    text = str(text or "").strip()
    if not text:
        raise ValueError("text 不能为空")
    today = datetime.now().strftime("%Y-%m-%d")
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = _OUT_DIR / f"{today}.md"
    if not path.exists():
        path.write_text(f"# 刷B站日报 {today}\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"### {bvid}\n{text}\n\n")
    return {"saved": True, "file": str(path), "section": f"### {bvid}"}


async def bili_dedup(action: str, bvid: str = "", title: str = "", up: str = "", status: str = "") -> dict[str, Any]:
    action = str(action or "").strip()
    if action == "list":
        rows = list(reversed(_dedup_rows()))[:40]
        return {"count": len(rows), "recent": rows}
    if action == "mark":
        bvid = _bvid(bvid)
        status = str(status or "").strip()
        if status not in {"picked", "skipped", "commented"}:
            raise ValueError("mark 需要 status（picked/skipped/commented）")
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        rows = _dedup_rows()
        rows.append(
            {
                "bvid": bvid,
                "title": str(title or "")[:120],
                "up": str(up or "")[:60],
                "status": status,
                "date": datetime.now().strftime("%Y-%m-%d"),
            }
        )
        _DEDUP_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"marked": bvid, "status": status, "total": len(rows)}
    raise ValueError("action 必须是 list 或 mark")


# ── 写：发评论（同意权在配置开关，处理器硬闸兜底）────────────────────


async def bili_post_comment(bvid: str, content: str) -> dict[str, Any]:
    bvid = _bvid(bvid)
    content = str(content or "").strip()
    cfg = _config()
    if not content:
        raise ValueError("content 不能为空")
    if len(content) > 300:
        raise ValueError("评论超过 300 字，请精简后再发")
    # user:“你收到的每一条 @，都是它先筛过一遍的”+发评论必须显式打开开关、
    # 同一视频只发一次；这两道闸在处理器里硬性生效，不靠提示词自觉。
    if not bool(cfg.get("auto_comment")):
        raise ValueError("自动评论未开启（配置里 auto_comment=false）。要替使用者发言，先在插件页打开开关。")
    if _dedup_find(bvid, "commented"):
        raise ValueError(f"判重表显示 {bvid} 已经评论过，同一视频只发一次。")
    cookies = _cookies()
    csrf = str(cfg.get("bili_jct") or "").strip()
    if not cookies.get("SESSDATA") or not csrf:
        raise ValueError("未配置登录凭证：需要在插件配置里填 SESSDATA 与 bili_jct（浏览器 Cookie 里的两个值）。")
    try:
        with _client() as client:
            view = client.get(f"{_API}/x/web-interface/view", params={"bvid": bvid}).json()
            aid = (view.get("data") or {}).get("aid")
            body = client.post(
                f"{_API}/x/v2/reply/add",
                data={"oid": aid, "type": 1, "message": content, "csrf": csrf, "csrf_token": csrf},
            ).json()
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"评论发送失败：{type(exc).__name__}: {exc}") from exc
    if body.get("code") != 0:
        raise ValueError(
            f"评论被 B站 拒绝：code={body.get('code')}（{body.get('message')}）。"
            "凭证可能过期，或触发了风控；不要重试刷屏。"
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
    return {"posted": True, "bvid": bvid, "rpid": rpid}


async def bili_account_status() -> dict[str, Any]:
    if not _cookies().get("SESSDATA"):
        return {
            "logged_in": False,
            "note": "未配置 SESSDATA：字幕读不到、评论发不了；搜索/信息/评论（看）不受影响。",
        }
    try:
        with _client() as client:
            body = client.get(f"{_API}/x/web-interface/nav").json()
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"状态查询失败：{type(exc).__name__}: {exc}") from exc
    data = body.get("data") or {}
    if not data.get("isLogin"):
        return {"logged_in": False, "note": "Cookie 已失效，请重新填写。"}
    return {"logged_in": True, "mid": data.get("mid"), "uname": data.get("uname")}


# ── 私信：投递与收件箱（原版 dm.mjs 的端点与闸门，窄口收件人）────────


def _receiver_mid(cfg: dict[str, Any], own_mid: int) -> int:
    # user:“私信发给谁（UID）可留空”+留空发给登录账号自己，不开放任意收件人。
    uid = int(cfg.get("dm_uid") or 0)
    return uid if uid > 0 else own_mid


async def bili_send_dm(content: str) -> dict[str, Any]:
    content = str(content or "").strip()
    cfg = _config()
    cookies = _cookies()
    if not content:
        raise ValueError("content 不能为空")
    if not cookies.get("SESSDATA") or not str(cfg.get("bili_jct") or "").strip():
        raise ValueError("未配置登录凭证（SESSDATA 与 bili_jct）")
    if str(cfg.get("dm_mode") or "only").strip().lower() == "off":
        raise ValueError("私信投递未开启（配置里 dm_mode=off）")
    try:
        with _client() as client:
            nav = client.get(f"{_API}/x/web-interface/nav").json()
            own_mid = int(((nav.get("data") or {}).get("mid")) or 0)
            if own_mid <= 0:
                raise ValueError("Cookie 已失效，无法投递私信")
            body = client.post(
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
                    "dev_id": str(uuid.uuid4()),
                    "from_firework": 0,
                    "build": 0,
                    "mobi_app": "web",
                },
                headers={"Referer": "https://message.bilibili.com/"},
            ).json()
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"私信发送失败：{type(exc).__name__}: {exc}") from exc
    if body.get("code") != 0:
        raise ValueError(f"私信被 B站 拒绝：code={body.get('code')}（{body.get('message')}）")
    msg_key = ((body.get("data") or {}).get("msg_key")) or ""
    if not msg_key:
        # user:“接口回了成功但没有投递回执 ⇒ 可能没真正送到”+原版踩过的坑照搬。
        raise ValueError("接口回了成功但没有投递回执（msg_key）：可能没真正送到，不要重复发送。")
    return {"sent": True, "msg_key": str(msg_key)[:16]}


async def bili_dm_inbox() -> dict[str, Any]:
    # user:“私信双向”+默认关闭；开关打开后读最近会话预览，回话决策按章程。
    cfg = _config()
    if not bool(cfg.get("dm_reply")):
        raise ValueError("私信双向未开启（配置里 dm_reply=false）")
    if not _cookies().get("SESSDATA"):
        raise ValueError("未配置登录凭证（SESSDATA）")
    try:
        with _client() as client:
            sessions = client.get(
                "https://api.vc.bilibili.com/session_svr/v1/session_svr/get_sessions",
                params={"session_type": 1, "group_id": 0, "build": 0, "mobi_app": "web"},
            ).json()
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"收件箱读取失败：{type(exc).__name__}: {exc}") from exc
    if sessions.get("code") != 0:
        raise ValueError(f"收件箱读取失败：code={sessions.get('code')}")
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
    return {"count": len(items), "sessions": items}
