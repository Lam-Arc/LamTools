#!/usr/bin/env python3
"""scripts/bootstrap_env.py —— 「装主依赖 / 装转写依赖」真正干活的那段。

原版是 index.js 里的 runInstall / runInstallAsr（uv 优先、镜像轮换、venv 建在插件家里）。
这里按同样的行为重写，只用标准库：

  1. 找一个能建环境的东西：`uv`（PATH → 插件家 bin/ → 自己下）→ 退到 `py -3.12` / `python`
  2. 在 <插件>/data/duty/.venv 建环境（uv 带 --seed；pip 装失败还能靠 -m pip 补救）
  3. 按 requirements.txt 装依赖，镜像轮换：清华 → 中科大 → 阿里 → 官方
  4. 装完 import 验一遍，成功就写 .venv/requirements.ok
  5. 把 mcp/mcp.json 里三处占位换成真实路径

用法：
    python scripts/bootstrap_env.py            # 主依赖（MCP 服务器）
    python scripts/bootstrap_env.py --asr      # 转写依赖（faster-whisper + yt-dlp）
    python scripts/bootstrap_env.py --check    # 只报状态
进度全部写 <插件>/logs/install.log（设置页看的就是它）。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DUTY = DATA / "duty"
LOGS = DATA / "logs"
BIN = DATA / "bin"
REQ = ROOT / "vendor" / "bilibili-mcp" / "requirements.txt"
UV_MIRRORS = ["https://github.com/astral-sh/uv/releases/latest/download/", "https://gh-proxy.com/https://github.com/astral-sh/uv/releases/latest/download/"]
UV_ASSET = "uv-x86_64-pc-windows-msvc.zip"
PYPI_SIMPLE = "https://pypi.tuna.tsinghua.edu.cn/simple/uv/"
PIP_MIRRORS = [
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.ustc.edu.cn/pypi/simple",
    "https://mirrors.aliyun.com/pypi/simple",
    "https://pypi.org/simple",
]


def log_path(mode: str) -> Path:
    return LOGS / ("install-asr.log" if mode == "asr" else "install.log")


def say(log, text: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {text}"
    try:
        log.write_text(log.read_text(encoding="utf-8") + line + "\n" if log.exists() else line + "\n", encoding="utf-8")
    except Exception:
        try:
            with log.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass
    print(line, flush=True)


def run(cmd: list[str], log, timeout: int = 1800) -> int:
    say(log, "$ " + " ".join(str(c) for c in cmd))
    creation = 0x08000000 if os.name == "nt" else 0
    try:
        proc = subprocess.Popen(
            [str(c) for c in cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation,
        )
    except Exception as exc:
        say(log, f"起不来：{exc}")
        return 1
    deadline = time.time() + timeout
    assert proc.stdout
    for line in proc.stdout:
        say(log, line.rstrip())
        if time.time() > deadline:
            proc.kill()
            say(log, "超时，已中止")
            return 1
    return proc.wait()


def download(url: str, target: Path, log) -> bool:
    try:
        say(log, f"下载 {url}")
        with urllib.request.urlopen(url, timeout=60) as resp, target.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
        return target.stat().st_size > 0
    except Exception as exc:
        say(log, f"下载失败：{exc}")
        try:
            target.unlink()
        except Exception:
            pass
        return False


def verify_sha(url: str, target: Path, log) -> None:
    """有 .sha256 就核对；没有就如实写"未校验"（原版同样的口径：拿不到不拦着，但要记下来）。"""
    try:
        with urllib.request.urlopen(url + ".sha256", timeout=20) as resp:
            expected = (resp.read().decode("utf-8", "replace").strip().split() or [""])[0].lower()
        if not expected:
            return
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != expected:
            say(log, f"sha256 对不上（期望 {expected[:12]}…，实际 {digest[:12]}…）⇒ 丢弃")
            target.unlink()
            return
        say(log, "sha256 已核对通过")
    except Exception:
        say(log, "拿不到官方 sha256，跳过校验（下载源可能没有 .sha256）")


def find_uv_on_path() -> str:
    for name in ("uv.exe", "uv"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def install_uv(log) -> str:
    local = BIN / "uv.exe"
    if local.exists():
        return str(local)
    BIN.mkdir(parents=True, exist_ok=True)
    for base in UV_MIRRORS:
        url = base + UV_ASSET
        zip_path = BIN / UV_ASSET
        if not download(url, zip_path, log):
            continue
        verify_sha(url, zip_path, log)
        if not zip_path.exists():
            continue
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(BIN)
        except Exception as exc:
            say(log, f"解压失败：{exc}")
            continue
        for found in BIN.rglob("uv.exe"):
            if found != local:
                try:
                    shutil.move(str(found), str(local))
                except Exception:
                    pass
            if local.exists():
                say(log, f"uv 就绪：{local}")
                return str(local)
    return ""


def find_base_python(log) -> list[str]:
    for candidate in (["py", "-3.12"], ["py", "-3"], ["python"], ["python3"]):
        try:
            out = subprocess.run(candidate + ["--version"], capture_output=True, text=True, timeout=30)
        except Exception:
            continue
        if out.returncode == 0:
            say(log, f"基础解释器：{' '.join(candidate)} → {out.stdout.strip() or out.stderr.strip()}")
            return candidate
    return []


def venv_python(venv: Path):
    for cand in (venv / "Scripts" / "python.exe", venv / "bin" / "python"):
        if cand.exists():
            return cand
    return None


def ensure_venv(venv: Path, log) -> Path:
    py = venv_python(venv)
    if py:
        return py
    uv = find_uv_on_path() or install_uv(log)
    if uv:
        if run([uv, "venv", "--seed", "--python", "3.12", str(venv)], log) != 0 or not venv_python(venv):
            say(log, "uv 带 --python 3.12 没成 ⇒ 退回 uv 默认 Python")
            run([uv, "venv", "--seed", str(venv)], log)
        py = venv_python(venv)
        if py:
            return py
    base = find_base_python(log)
    if not base:
        raise SystemExit("这台机器上既没有 uv 也没有可用的 python（装一个 uv 或 Python 3.10+ 再来）")
    if run(base + ["-m", "venv", str(venv)], log) != 0:
        raise SystemExit("建 venv 失败")
    py = venv_python(venv)
    if not py:
        raise SystemExit("建 venv 后找不到解释器")
    return py


def pip_install(py: Path, args: list[str], log, uv: str = "") -> int:
    code = 1
    for mirror in PIP_MIRRORS:
        say(log, f"--- 镜像：{mirror}")
        if uv:
            code = run([uv, "pip", "install", "--python", str(py), "-i", mirror] + args, log)
        if code != 0:
            code = run([str(py), "-m", "pip", "install", "-i", mirror] + args, log)
        if code == 0:
            return 0
    return code


def check(mode: str, log) -> int:
    venv = DUTY / (".venv-asr" if mode == "asr" else ".venv")
    py = venv_python(venv)
    if not py:
        say(log, f"{venv} 还没建好")
        return 1
    modules = ["faster_whisper", "yt_dlp"] if mode == "asr" else ["mcp", "bilibili_api", "aiohttp", "qrcode", "browser_cookie3"]
    code = 0
    for mod in modules:
        probe = subprocess.run([str(py), "-c", f"import {mod}"], capture_output=True, text=True)
        if probe.returncode != 0:
            say(log, f"缺依赖：{mod}（{probe.stderr.strip().splitlines()[-1:] or ''}）")
            code = 1
    return code


def write_mcp_paths(log):
    # user:“该重建就重建”+(配置模板由宿主运行时展开，安装绝不改发布文件)。
    say(log, "MCP 路径由宿主解析，模板保持不变")


def main(argv: list[str]) -> int:
    mode = "asr" if "--asr" in argv else "main"
    for d in (DATA, DUTY, LOGS, BIN):
        d.mkdir(parents=True, exist_ok=True)
    log = log_path(mode)
    say(log, f"\n=== 开始装{'转写' if mode == 'asr' else '主'}依赖 ===")

    if "--check" in argv:
        return check(mode, log)

    try:
        venv = DUTY / (".venv-asr" if mode == "asr" else ".venv")
        py = ensure_venv(venv, log)
        uv = find_uv_on_path()
        if mode == "asr":
            code = pip_install(py, ["-r", str(ROOT / "config" / "asr-requirements.txt")], log, uv)
        else:
            code = pip_install(py, ["-r", str(REQ), "browser_cookie3>=0.19"], log, uv)
        ok = code == 0 and check(mode, log) == 0
        if ok:
            (venv / "requirements.ok").write_text(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S")}), encoding="utf-8")
            say(log, f"=== 完成：{py} ===")
            if mode != "asr":
                # ⚠️ 先把 vendored 的运行时代码铺进家里，再写 mcp.json 的绝对路径 ——
                #    顺序反了会写出"指向不存在的 mcp_server.py"的配置（首轮实测踩过）
                sys.path.insert(0, str(ROOT))
                import common  # noqa: PLC0415
                say(log, f"铺运行时代码：{common.ensure_duty_files()}")
                write_mcp_paths(log)
        else:
            say(log, f"=== 结束但没成功（exit {code}）—— 换个网络或手动装 uv 再来一次 ===")
        return 0 if ok else 1
    except SystemExit as exc:
        say(log, f"中止：{exc}")
        return 1
    except Exception as exc:
        say(log, f"崩了：{exc!r}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
