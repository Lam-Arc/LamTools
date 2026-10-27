# user:“对比原版，能力应当只增不减”+(保留完整移植能力，并使用宿主独立模块空间)。
"""bili-scroll —— 业务层（工具与操作共用这一份实现，两个薄壳再包一层）。

原版的宿主侧代码在 index.js 里（runDuty / runInstall / loginStart / checkUp / favops ...）。
这里按同样的行为重写；MCP 那半边（搜索 / 字幕 / 评论 / 发评论 / 日报 / 判重表 / 转写）
**仍然在随包内置的 bilibili-mcp 服务器里**，没有搬进来 —— 本文件只管包不住的那层：
环境、登录、配置、状态、报告、时间窗口、诊断。
"""

from __future__ import annotations

import base64
import hashlib
import uuid
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent

from . import common  # noqa: E402

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
QR_GEN = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate?source=main-fe-header"
QR_POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key={key}&source=main-fe-header"
SPI = "https://api.bilibili.com/x/frontend/finger/spi"
CRED_FIELDS = {"SESSDATA": "sessdata", "bili_jct": "bili_jct", "DeduUserID": "dedeuserid", "DedeUserID": "dedeuserid", "buvid3": "buvid3"}

# 后台运行时（backend）注册进来；没注册时 run_round 只能把指令落盘
RUNTIME = None
PROCESSES = set()


def set_runtime(runtime) -> None:
    global RUNTIME
    RUNTIME = runtime


# ── 状态 ────────────────────────────────────────────────────────────────────
def status() -> dict:
    cfg = common.load_config()
    now = datetime.now()
    day = common.day_key(now)
    py = common.venv_python()
    picked = common.count_picked_today(now)
    per_day = int(cfg.get("perDay") or 0)
    windows = {}
    for key, win in common.WINDOWS.items():
        windows[key] = {
            "label": win["label"],
            "start": win["start"],
            "end": win["end"],
            "switchOn": bool(cfg.get(key)),
            "opening": common.in_window(now, win),
        }
    return {
        "ok": True,
        "today": day,
        "pickedToday": picked,
        "remaining": max(0, per_day - picked) if per_day else None,
        "perDay": per_day,
        "roundsToday": common.rounds_today(now),
        "peakValley": bool(cfg.get("peakValley")),
        "openWindows": common.open_windows(now),
        "windows": windows,
        "delivery": {
            "dmMode": cfg.get("dmMode"),
            "autoComment": bool(cfg.get("autoComment")),
            "mentionName": cfg.get("mentionName"),
            "commentPerRound": cfg.get("commentPerRound"),
            "replyToComments": bool(cfg.get("replyToComments")),
        },
        "env": {
            "venv": str(py) if py else "",
            "venvReady": common.venv_ready(),
            "asrReady": common.asr_ready(),
            "loggedIn": common.has_credential(),
            "mcpScript": str(common.mcp_script()),
            "mcpJson": str(ROOT / "mcp" / "mcp.json"),
        },
        "home": str(common.DUTY),
        "report": str(common.report_path(day)),
        "logFile": str(common.log_file()),
        "roundInstruction": str(common.DUTY / "round.md"),
        "runtime": {
            "scheduler": bool(RUNTIME and getattr(RUNTIME, "running", False)),
            "runner": str(getattr(RUNTIME, "runner_mode", "") or ""),
            "canSpawnRound": bool(RUNTIME and getattr(RUNTIME, "can_spawn", False)),
            "roundRunning": bool(
                RUNTIME is not None
                and getattr(RUNTIME, "_current", None) is not None
                and not RUNTIME._current.done()
            ),
            "spawnError": str(getattr(RUNTIME, "spawn_error", "") or ""),
        },
        "configFile": str(common.config_file()),
    }


# ── 装依赖 ──────────────────────────────────────────────────────────────────
def _spawn_detached(script: str, extra: list[str], log_name: str) -> dict:
    """后台起一个安装进程：起完就返回（原版一样，不等几分钟的活）。"""
    common.ensure_dirs()
    log = common.LOGS / log_name
    script_path = ROOT / "scripts" / script
    if not script_path.exists():
        return {"ok": False, "error": f"缺脚本 {script_path}"}
    base = _base_python() or [sys.executable]
    creation = 0
    if os.name == "nt":
        creation = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        with (common.LOGS / "spawn.log").open("a", encoding="utf-8") as spawn_log:
            proc = subprocess.Popen(
                [*base, str(script_path), *extra],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=spawn_log,
                stderr=spawn_log,
                creationflags=creation,
                close_fds=True,
            )
        PROCESSES.add(proc)
        common.log(f"已起安装进程 pid={proc.pid}（{script} {' '.join(extra)}），日志 {log}")
        return {"ok": True, "started": True, "pid": proc.pid, "log": str(log),
                "hint": "正在后台装，进度看这个日志文件（设置页「装主依赖」下面会显示它）"}
    except Exception as exc:
        return {"ok": False, "error": f"起不来：{exc}"}


def _base_python() -> list[str]:
    for candidate in (["py", "-3"], ["python"], ["python3"]):
        try:
            probe = subprocess.run(candidate + ["--version"], capture_output=True, text=True, timeout=20)
            if probe.returncode == 0:
                return candidate
        except Exception:
            continue
    return []


def setup_deps() -> dict:
    notes = common.ensure_duty_files()
    result = _spawn_detached("bootstrap_env.py", [], "install.log")
    result["notes"] = notes
    return result


def install_asr() -> dict:
    common.ensure_duty_files()
    return _spawn_detached("bootstrap_env.py", ["--asr"], "install-asr.log")


def install_log(kind: str = "main", tail: int = 40) -> dict:
    path = common.LOGS / ("install-asr.log" if kind == "asr" else "install.log")
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]
    except Exception:
        lines = []
    return {"ok": True, "file": str(path), "lines": lines}


# ── 扫码登录（原版 lib/login.mjs 的行为；不用 vendored 的 bili_login）────────
def _http_get(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout)


def login_start() -> dict:
    cfg = common.load_config()
    try:
        with _http_get(QR_GEN + "&_t=" + str(time.time_ns())) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        return {"ok": False, "error": f"生成二维码失败：{exc}"}
    data = body.get("data") or {}
    key, url = data.get("qrcode_key"), data.get("url")
    if not key or not url:
        return {"ok": False, "error": f"生成二维码失败：{body.get('message') or '返回里没有 qrcode_key'}"}
    png = _render_qr(cfg, url, key)
    # user:“没找着扫码键”+(桌面窗口的 CSP 不许 file:// 图片；这里直接把二维码
    # 编成 data URL，窗口点「扫码登录」就能看到，不用再开文件。)
    png_data = ""
    if png:
        try:
            png_data = "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode("ascii")
        except Exception as exc:
            common.log(f"读二维码图片失败：{exc}")
    return {
        "ok": True,
        "key": key,
        "url": url,
        "png": str(png) if png else "",
        "png_data": png_data,
        "png_ready": bool(png),
        "hint": "用手机 B站 → 我的 → 扫一扫；手机确认时选「记住我/长期」。扫完调 bili-scroll.login_poll 或点窗口里的「查扫码结果」。",
    }


def _render_qr(cfg: dict, url: str, identity: str = "") -> Path | None:
    py = common.venv_python()
    script = ROOT / "scripts" / "qr.py"
    png = common.DUTY / ("qrcode_login_" + hashlib.sha256(identity.encode()).hexdigest()[:16] + ".png")
    if not py or not py.exists() or not script.exists():
        return None
    try:
        proc = subprocess.run([str(py), str(script), url, str(png)], capture_output=True, text=True, timeout=60)
        if proc.returncode == 0 and png.exists():
            return png
        common.log(f"画二维码失败：{proc.stderr.strip()[:200]}")
    except Exception as exc:
        common.log(f"画二维码失败：{exc}")
    return None


def login_poll(key: str) -> dict:
    if not key:
        return {"ok": False, "state": "unknown", "error": "要给 bili-scroll.login_start 返回的那个 key"}
    url = QR_POLL.format(key=urllib.parse.quote(key)) + "&_t=" + str(time.time_ns())
    try:
        with _http_get(url) as resp:
            cookies = resp.headers.get_all("Set-Cookie") or []
            raw = resp.read().decode("utf-8", "replace")
    except Exception as exc:
        return {"ok": False, "state": "unknown", "error": f"查询扫码结果失败：{exc}"}
    try:
        body = json.loads(raw) if raw.strip() else {}
    except Exception:
        body = {}
    code = (body.get("data") or {}).get("code")
    if code == 0:
        jar = _pick_cookies(cookies)
        if not jar.get("sessdata"):
            return {"ok": False, "state": "unknown", "code": code,
                    "error": "登录成功了，但响应里没有 SESSDATA —— 把这次结果记下来再排查"}
        jar = _ensure_buvid3(jar)
        file = _save_credential(jar)
        common.log(f"登录成功，凭证已写入 {file}")
        return {"ok": True, "state": "ok", "file": str(file)}
    state = {86101: "waiting", 86090: "scanned", 86038: "expired"}.get(code, "unknown")
    return {"ok": state != "unknown", "state": state, "code": code, "message": body.get("message") or ""}


def _pick_cookies(list_: list[str]) -> dict:
    jar: dict[str, str] = {}
    for raw in list_:
        first = str(raw).split(";")[0]
        if "=" not in first:
            continue
        name, value = first.split("=", 1)
        field = CRED_FIELDS.get(name.strip())
        if field:
            jar[field] = value.strip()
    return jar


def _ensure_buvid3(jar: dict) -> dict:
    if jar.get("buvid3"):
        return jar
    try:
        with _http_get(SPI) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
        value = (body.get("data") or {}).get("b_3")
        if value:
            jar["buvid3"] = value
    except Exception:
        pass
    return jar


def _save_credential(jar: dict) -> Path:
    common.ensure_dirs()
    file = common.DUTY / "bili_credential.json"
    payload = {
        "sessdata": jar.get("sessdata", ""),
        "bili_jct": jar.get("bili_jct", ""),
        "buvid3": jar.get("buvid3", ""),
        "dedeuserid": str(jar.get("dedeuserid", "")),
    }
    temporary = file.with_suffix(".tmp-" + uuid.uuid4().hex)
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _harden(temporary)
    os.replace(temporary, file)
    _harden(file)
    return file


def _harden(file: Path) -> None:
    """凭证文件权限收紧到"只有自己能读"（原版 2026-10-23 的加固；失败不影响登录）。"""
    try:
        if os.name == "nt":
            command = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/whoami.exe")
            probe = subprocess.run([command, "/user", "/fo", "csv", "/nh"], capture_output=True, text=True,
                                   timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            sid = re.search(r"S-1-[0-9-]+", probe.stdout or "")
            who = "*" + sid.group(0) if sid else os.environ.get("USERDOMAIN", "") + "\\" + os.environ.get("USERNAME", "")
            subprocess.run(["icacls", str(file), "/inheritance:r", "/grant:r", who + ":F"],
                           capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                file.read_bytes()
            except OSError:
                subprocess.run(["icacls", str(file), "/reset"], capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.chmod(file, 0o600)
    except Exception:
        pass


def import_cookie(sessdata: str, bili_jct: str = "", dedeuserid: str = "", buvid3: str = "") -> dict:
    """user:“Chrome 里面应该存了我的 Bilibili 账号，应该也有 cookie”+(从浏览器
    导入登录：写同一份 bili_credential.json，之后 MCP 服务器直接复用)。"""
    jar = {
        "sessdata": str(sessdata or "").strip(),
        "bili_jct": str(bili_jct or "").strip(),
        "dedeuserid": str(dedeuserid or "").strip(),
        "buvid3": str(buvid3 or "").strip(),
    }
    if not jar["sessdata"]:
        return {"ok": False, "error": "缺 sessdata（Chrome 里 B 站登录态的 SESSDATA）"}
    jar = _ensure_buvid3({key: value for key, value in jar.items() if value})
    file = _save_credential(jar)
    common.log(f"已从浏览器 cookie 导入登录凭证：{file}")
    return {"ok": True, "file": str(file), "loggedIn": True,
            "account": {"mid": jar.get("dedeuserid", ""), "source": "chrome-cookie"}}


# ── 配置 ────────────────────────────────────────────────────────────────────
ALLOWED_KEYS = set(common.DEFAULTS.keys())


def config_get() -> dict:
    return {"ok": True, "config": common.load_config(), "defaults": common.DEFAULTS,
            "file": str(common.config_file()), "windows": common.WINDOWS}


def config_update(patch: dict) -> dict:
    if not isinstance(patch, dict) or not patch:
        return {"ok": False, "error": "要给一个 patch 对象"}
    unknown = [k for k in patch if k not in ALLOWED_KEYS]
    if unknown:
        return {"ok": False, "error": f"这些字段不存在：{unknown}"}
    path = common.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = common.load_jsonc(path)
    current.update(patch)
    tmp = path.with_suffix(".jsonc.tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    after = common.load_config()
    common.log(f"配置已更新：{sorted(patch)}")
    return {"ok": True, "config": after, "file": str(path)}


# ── 报告 / 判重表 / 视频墙 ───────────────────────────────────────────────────
def report_read(day: str = "") -> dict:
    day = day or common.day_key()
    path = common.report_path(day)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {"ok": False, "day": day, "error": "这一天还没有报告", "file": str(path)}
    return {"ok": True, "day": day, "file": str(path), "text": text, "picked": common.count_picks(day)}


def reports_list() -> dict:
    out_dir = common.DUTY / "out"
    items = []
    try:
        for path in sorted(out_dir.glob("*.md"), reverse=True)[:60]:
            items.append({"day": path.stem, "file": str(path), "picked": common.count_picks(path.stem)})
    except Exception:
        pass
    return {"ok": True, "items": items}


PICK_BLOCK = None


def seen_list(day: str = "", status: str = "", limit: int = 200) -> dict:
    """「它刷过的视频」—— 从判重表读，按天/状态筛。"""
    rows = common.parse_seen()
    if day:
        rows = [r for r in rows if r.get("day") == day]
    if status:
        rows = [r for r in rows if status in str(r.get("raw") or "")]
    return {"ok": True, "count": len(rows), "items": rows[: max(1, min(limit, 500))]}


def pick_cards(day: str = "") -> dict:
    """报告里的 `### BV号` 段 → 卡片（标题 / UP / 档位 / 链接 / 为什么值得）。"""
    day = day or common.day_key()
    result = report_read(day)
    if not result.get("ok"):
        return {"ok": False, "day": day, "cards": [], "error": result.get("error")}
    # 围栏里的 BV 是"看过的"，不是"挑出来的"（跟配额计数同一个口径）
    text = re.sub(r"```[\s\S]*?```", "", result["text"])
    cards = []
    for chunk in ("\n" + text).split("\n### ")[1:]:
        lines = chunk.splitlines()
        head = lines[0].strip()
        bv = head.split()[0] if head else ""
        if not bv.upper().startswith("BV"):
            continue
        body = "\n".join(lines[1:]).strip()
        grade = ""
        for line in lines[1:]:
            if "档位" in line:
                for word in ("值得看", "可以看", "不值当"):
                    if word in line:
                        grade = word
                        break
                break
        title = next((ln.strip("# ").strip() for ln in lines[1:] if ln.strip() and "档位" not in ln), "")
        cards.append({"bvid": bv, "grade": grade, "title": title[:120],
                      "body": body[:1500], "url": f"https://www.bilibili.com/video/{bv}"})
    return {"ok": True, "day": day, "cards": cards, "count": len(cards)}


def run_instruction() -> dict:
    """把"这一轮的完整指令"落盘并返回 —— 自动轮跑不起来时，人和模型都还能用它。"""
    text = common.duty_instruction("manual")
    path = common.DUTY / "round.md"
    try:
        path.write_text(text, encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "error": f"写 round.md 失败：{exc}"}
    return {"ok": True, "file": str(path), "chars": len(text)}


def run_round(why: str = "manual") -> dict:
    cfg = common.load_config()
    now = datetime.now()
    picked = common.count_picked_today(now)
    per_day = int(cfg.get("perDay") or 0)
    if per_day and picked >= per_day:
        return {"ok": True, "started": False, "skipped": True,
                "reason": f"今天已经挑满 {picked}/{per_day} 条，不跑了（「每天最多挑几条」是全天总量）"}
    prepared = run_instruction()
    if not prepared.get("ok"):
        return {"ok": False, "started": False, "error": prepared.get("error")}
    if RUNTIME is None:
        return {"ok": True, "started": False, "prepared": True, "instruction": prepared["file"],
                "reason": "插件后台运行时没起来，这一轮没法自动起会话 —— 指令已经写到 round.md，"
                          "可以让助手按「刷B站」技能跑这一轮（工具走 MCP，行为跟自动轮一样）"}
    if not getattr(RUNTIME, "can_spawn", False):
        return {"ok": True, "started": False, "prepared": True, "instruction": prepared["file"],
                "reason": getattr(RUNTIME, "spawn_error", "") or "宿主没提供 sub-agent 运行器，这一轮没法自动起会话"}
    try:
        result = RUNTIME.run_duty(why)
        return {"ok": True, "prepared": True, "instruction": prepared["file"], **result}
    except Exception as exc:
        common.log(f"起值班轮失败：{exc!r}")
        return {"ok": False, "started": False, "error": f"起值班轮失败：{exc}"}


# ── 收藏（宿主侧的手，模型拿不到）──────────────────────────────────────────
def fav_call(args: list[str], timeout: int = 120) -> dict:
    if not common.fav_ready():
        return {"ok": False, "error": "依赖没装好（先点「装主依赖」）"}
    py = common.venv_python()
    script = common.DUTY / "favops.py"
    try:
        # user:“都试一试”+(Windows 中文回执统一 UTF-8，避免成功结果被解码错误吞掉)。
        proc = subprocess.run([str(py), str(script), *args], cwd=str(common.DUTY),
                              capture_output=True, text=True, encoding="utf-8",
                              env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                              timeout=timeout)
    except Exception as exc:
        return {"ok": False, "error": f"调 favops 失败：{exc}"}
    tail = (proc.stdout or "").strip().splitlines()
    if not tail:
        return {"ok": False, "error": (proc.stderr or "没有输出").strip()[:400]}
    try:
        return json.loads(tail[-1])
    except Exception:
        return {"ok": False, "error": tail[-1][:400], "stderr": (proc.stderr or "")[:400]}


def fav_add_today() -> dict:
    cfg = common.load_config()
    fid = int(cfg.get("favFolderId") or 0)
    if fid <= 0:
        return {"ok": False, "error": "设置里还没选收藏夹（favFolderId=0）"}
    cards = pick_cards().get("cards") or []
    if not cards:
        return {"ok": False, "error": "今天的报告里没有挑中的视频"}
    added, failed = [], []
    for card in cards:
        result = fav_call(["add", card["bvid"], str(fid)])
        (added if result.get("ok") else failed).append(card["bvid"])
    return {"ok": True, "folder": fid, "added": added, "failed": failed}


# ── 私信监听（只读、纯代码；原版 lib/dm.mjs 的三条接口）──────────────────────
def _cred() -> dict | None:
    path = common.DUTY / "bili_credential.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if data.get("sessdata") else None


def _dm_headers(cred: dict) -> dict:
    return {
        "User-Agent": UA,
        "Referer": "https://message.bilibili.com/",
        "Origin": "https://message.bilibili.com",
        "Cookie": f"SESSDATA={cred.get('sessdata','')}; bili_jct={cred.get('bili_jct','')}; buvid3={cred.get('buvid3','')}",
    }


def _dm_get(url: str, cred: dict) -> dict:
    req = urllib.request.Request(url, headers=_dm_headers(cred))
    with urllib.request.urlopen(req, timeout=25) as resp:
        body = json.loads(resp.read().decode("utf-8", "replace"))
    if body.get("code") != 0:
        raise RuntimeError(f"code={body.get('code')} msg={body.get('message')}")
    return body.get("data") or {}


def dm_scan() -> dict:
    """扫一遍私信会话：有没有主人发来的未读。"""
    cred = _cred()
    if not cred:
        return {"ok": False, "error": "还没扫码登录"}
    cfg = common.load_config()
    owner = int(cfg.get("dmOwnerUid") or cfg.get("dmUidResolved") or cfg.get("dmUid") or 0)
    if not owner:
        return {"ok": True, "owner": 0, "unreadSessions": [], "needsReply": False, "hint": "请先指定主人 UID"}
    try:
        data = _dm_get(
            "https://api.vc.bilibili.com/session_svr/v1/session_svr/get_sessions"
            "?session_type=1&group_id=0&Build=0&mobi_app=web",
            cred,
        )
    except Exception as exc:
        return {"ok": False, "error": f"读会话列表失败：{exc}"}
    sessions = []
    for item in data.get("session_list") or []:
        uid = int(item.get("talker_id") or 0)
        unread = int(item.get("unread_count") or 0)
        if uid <= 0:
            continue
        if owner and uid != owner:
            continue
        sessions.append({"uid": uid, "unread": unread,
                         "lastTs": int((item.get("last_msg") or {}).get("timestamp") or 0)})
    sessions = [s for s in sessions if s["unread"] > 0]
    for item in sessions:
        raw = _dm_get("https://api.vc.bilibili.com/svr_sync/v1/svr_sync/fetch_session_msgs?talker_id=" + str(item["uid"]) + "&session_type=1&size=10&build=0&mobi_app=web", cred)
        messages = []
        for message in reversed(raw.get("messages", [])):
            content = message.get("content") or "{}"
            try:
                content = json.loads(content) if isinstance(content, str) else content
                if message.get("msg_type") in {7, 8}:
                    text = "[分享视频] " + str(content.get("title") or content.get("headline") or "") + " " + str(content.get("bvid") or content.get("jump_url") or "")
                else:
                    text = str(content.get("content") or content.get("text") or "[非文字消息]")
            except ValueError:
                text = str(content)
            messages.append({"key": str(message.get("msg_key") or message.get("msg_seqno") or message.get("timestamp")),
                             "fromMe": str(message.get("sender_uid")) == str(cred.get("dedeuserid")), "text": text[:600]})
        item["messages"] = messages
    if sessions:
        common.append(common.DUTY / "dm-inbox.jsonl",
                      json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "sessions": sessions},
                                 ensure_ascii=False) + "\n")
        common.log(f"私信：{len(sessions)} 个会话有未读（已记进 dm-inbox.jsonl）")
    return {"ok": True, "owner": owner, "unreadSessions": sessions,
            "needsReply": bool(sessions),
            "hint": "要回一句就让助手跑一轮值班（私信双向开着时它会读并回）。"}


# ── 诊断 ────────────────────────────────────────────────────────────────────
def diagnose() -> dict:
    cfg = common.load_config()
    st = status()
    st["config"] = cfg
    st["files"] = {name: str(common.DUTY / name) for name in ("mcp_server.py", "asr.py", "favops.py", "duty.md")}
    st["exists"] = {str(p): p.exists() for p in (common.DUTY / "mcp_server.py", common.DUTY / "duty.md")}
    try:
        st["logTail"] = common.log_file().read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
    except Exception:
        st["logTail"] = []
    try:
        st["installTail"] = (common.LOGS / "install.log").read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
    except Exception:
        st["installTail"] = []
    return st


def open_home(what="home") -> dict:
    """打开它的地盘（报告 / 判据 / 日志都在里面）。"""
    # user:“就移植原版就行”+(保留原版打开报告文件夹与家目录两个入口)。
    path = common.DUTY / "out" if what == "out" else common.DUTY
    try:
        if os.name == "nt":
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return {"ok": True, "path": str(path)}
    except Exception as exc:
        return {"ok": False, "path": str(path), "error": str(exc)}


def cover_data(bvid):
    # user:“就移植原版就行”+(原版卡片封面通过宿主代理读取，适配为 data URL)。
    import base64
    from urllib.parse import urlparse
    if not re.fullmatch(r"BV[0-9A-Za-z]{10}", str(bvid)):
        return {"ok": False, "error": "视频编号格式错误"}
    try:
        info = _dm_get("https://api.bilibili.com/x/web-interface/view?bvid=" + bvid, {})
        url = str(info.get("pic") or "")
        if url.startswith("//"):
            url = "https:" + url
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not (parsed.hostname or "").endswith(".hdslb.com"):
            return {"ok": False, "error": "封面地址无效"}
        # user:“就移植原版就行”+(B站接口仍返回 http CDN 地址，读取前统一升级为 HTTPS)。
        url = parsed._replace(scheme="https").geturl()
        with _http_get(url) as response:
            content_type = response.headers.get("Content-Type", "image/jpeg").split(";")[0]
            data = response.read(2 * 1024 * 1024 + 1)
        if content_type not in {"image/jpeg", "image/png", "image/webp"} or len(data) > 2 * 1024 * 1024:
            return {"ok": False, "error": "封面格式或大小不支持"}
        return {"ok": True, "data_url": "data:" + content_type + ";base64," + base64.b64encode(data).decode("ascii")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


# user:“对比原版，能力应当只增不减”+(补齐卡片筛选分页、空轮记录、复核和诊断入口)。
def watched(tier="", state="", offset=0, limit=60):
    sync_notes()
    rows = common.read_watched()
    if not rows:
        cards = {card["bvid"]: card for card in pick_cards().get("cards", [])}
        seen = common.parse_seen()
        known = {item.get("bvid") for item in seen}
        seen.extend({"bvid": key, "picked": True} for key in cards if key not in known)
        for item in seen:
            card = cards.get(item.get("bvid"), {})
            raw = str(item.get("raw") or "")
            rows.append({**item, **card, "tier": card.get("grade", ""),
                         "state": "commented" if "rpid" in raw else "picked" if item.get("picked") else "skipped"})
    for row in rows:
        row["note"] = bool((common.DUTY / "reports" / (str(row.get("bvid")) + ".md")).is_file())
    if tier:
        rows = [item for item in rows if item.get("tier") == tier]
    if state:
        rows = [item for item in rows if item.get("state") == state]
    offset, limit = max(0, int(offset)), max(1, min(200, int(limit)))
    return {"ok": True, "total": len(rows), "items": rows[offset:offset+limit], "offset": offset, "limit": limit}


def finalize_round(why, error=""):
    cfg = common.load_config()
    path = common.report_path()
    if cfg.get("reportLevel") != "off":
        common.append(path, "\n\n## 本轮结束\n" + ("未完成：" + error if error else "本轮已结束；没有选中视频时也保留记录。") + "\n")
    sync_notes()
    if cfg.get("favFolderId") and not error:
        result = fav_add_today()
        common.log("轮后收藏：" + json.dumps(result, ensure_ascii=False))
    return {"ok": not bool(error), "report": str(path)}


def verify():
    records = []
    for item in common.parse_seen():
        raw = str(item.get("raw") or "")
        ids = re.findall(r"(?:rpid[=:]\s*|\b)([0-9]{9,})", raw)
        if not ids:
            continue
        records.append({"bvid": item["bvid"], "rpid": ids[0], "root": ids[1] if len(ids)>1 else ""})
    cred = _cred()
    if not cred:
        return {"ok": False, "error": "还没扫码登录", "items": []}
    results = []
    for record in records[-20:]:
        row = {**record, "visible": None, "note": "没查到（不等于没有发出）"}
        try:
            info = _dm_get("https://api.bilibili.com/x/web-interface/view?bvid=" + record["bvid"], cred)
            aid = info["aid"]
            query = f"type=1&oid={aid}&ps=20"
            endpoint = "reply" if record["root"] else "main"
            query += "&root=" + record["root"] if record["root"] else "&mode=2&next=0"
            data = _dm_get("https://api.bilibili.com/x/v2/reply/"+endpoint+"?"+query, cred)
            hit = next((item for item in data.get("replies", []) if str(item.get("rpid")) == record["rpid"]), None)
            if hit:
                row.update(visible=True, likes=hit.get("like", 0), note="已在公开评论列表查到")
        except Exception as exc:
            row["note"] = "没查到：" + str(exc)
        results.append(row)
    if results and common.load_config().get("reportLevel") != "off":
        common.append(common.report_path(), "\n## 评论复核\n" + "\n".join("- "+r["bvid"]+"："+r["note"] for r in results)+"\n")
    return {"ok": True, "items": results}


def selfcheck():
    checks = {"mcp_script": common.mcp_script().is_file(), "venv": common.venv_ready(),
              "credential": common.has_credential(), "asr": common.asr_ready(),
              "scheduler": bool(RUNTIME and RUNTIME.running)}
    return {"ok": True, "checks": checks, "ready": checks["mcp_script"] and checks["venv"],
            "missing": [key for key, value in checks.items() if not value]}


def check():
    result = selfcheck()
    result["account"] = {"logged_in": common.has_credential()}
    if common.has_credential():
        try:
            result["account"] = _dm_get("https://api.bilibili.com/x/web-interface/nav", _cred())
        except Exception as exc:
            result["account"] = {"error": str(exc)}
    return result


def update_check():
    with _http_get("https://api.github.com/repos/c1overzz/dsh-bili-scroll/releases/latest") as response:
        data = json.loads(response.read().decode("utf-8"))
    return {"ok": True, "upstream_tag": data.get("tag_name"), "url": data.get("html_url"),
            "pinned_upstream": "4af98392ee078e02f50a7fd0bf0491033f4675ed"}


async def stop_processes():
    import asyncio
    for process in list(PROCESSES):
        if process.poll() is None:
            if os.name == "nt":
                killer = await asyncio.create_subprocess_exec("taskkill", "/PID", str(process.pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                await killer.wait()
            else:
                process.terminate()
            await asyncio.to_thread(process.wait, 10)
        PROCESSES.discard(process)


async def run_io(function, *args, **kwargs):
    # user:“该调的模块就是该写的东西”+(网络和进程探测不阻塞宿主，停止必须等本次 I/O 收尾)。
    import asyncio
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


# user:“对比原版，能力应当只增不减”+(宿主从日报拆出每视频笔记，自动解析昵称而不猜测收件人)。
def sync_notes():
    written = 0
    directory = common.DUTY / "reports"
    for report in (common.DUTY / "out").glob("*.md"):
        text = re.sub(r"```[\s\S]*?```", "", report.read_text(encoding="utf-8"))
        for match in re.finditer(r"(?ms)^### (BV[0-9A-Za-z]{10})[^\n]*\n(.*?)(?=^#{1,3} |\Z)", text):
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / (match.group(1) + ".md")
            content = "# " + match.group(1) + "\n\n" + match.group(2).strip() + "\n"
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                path.write_text(content, encoding="utf-8")
                written += 1
    return written


def resolve_recipient():
    cfg = common.load_config()
    if cfg.get("dmUidResolved"):
        return {"ok": True, "uid": cfg["dmUidResolved"]}
    name = str(cfg.get("mentionName") or "").strip()
    if not name:
        return {"ok": False, "error": "请指定私信 UID 或要 @ 的昵称"}
    url = "https://api.bilibili.com/x/web-interface/search/type?search_type=bili_user&keyword=" + urllib.parse.quote(name)
    with _http_get(url) as response:
        body = json.loads(response.read().decode("utf-8"))
    matches = [row for row in (body.get("data") or {}).get("result", []) if re.sub("<[^>]+>", "", str(row.get("uname", ""))) == name]
    if body.get("code") != 0 or len(matches) != 1:
        return {"ok": False, "error": "没有唯一匹配的昵称，请直接填写 UID"}
    uid = int(matches[0]["mid"])
    (common.DUTY / "recipient.json").write_text(json.dumps({"name": name, "uid": uid}, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "uid": uid}
