"""Computer Use 端到端验收：真实开记事本、点编辑区、打中文、读回内容。

这是人工跑一次的验证脚本，不进 pytest。它会真的移动鼠标和敲键盘，所以只碰
自己启动的那个记事本，结束时按进程杀掉，不留残局。

跑法：
    python core/scripts/verify_computer_use.py
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lamtools_core.computer_use import session, tools, win32  # noqa: E402
from lamtools_core.tool import ToolCall  # noqa: E402

WORK_ROOT = ROOT.parent
TEXT = "Sunday 桌面操作验收 2026-11-09"
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


async def call(action: str, **kwargs):
    return await tools.handle(
        ToolCall(id="verify", name="computer_use", arguments={"action": action, **kwargs}),
        work_root=WORK_ROOT,
    )


def find_notepad(before: set[int]) -> win32.WindowInfo | None:
    """记事本是 UWP 包装，启动器 pid 和真实窗口进程不一致，所以按“新出现的窗口”找。"""
    for _ in range(60):
        for window in win32.list_windows():
            if window.hwnd in before:
                continue
            if "Notepad" in window.class_name or "记事本" in window.title or "Notepad" in window.title:
                return window
        time.sleep(0.15)
    return None


async def main() -> int:
    print("== 启动记事本 ==")
    before = {window.hwnd for window in win32.list_windows()}
    proc = subprocess.Popen(["notepad.exe"])
    window = find_notepad(before)
    if window is None:
        print("FAIL  记事本窗口没有出现")
        proc.kill()
        return 1
    print(f"记事本 hwnd={window.hwnd} 标题={window.title!r} {window.width}x{window.height}+{window.x}+{window.y}")

    print("\n== start ==")
    result = await call("start", goal="在记事本里输入一段中文并确认内容", max_steps=12)
    check("start 成功", result.status == "ok", result.error or result.content.splitlines()[0])

    print("\n== snapshot ==")
    result = await call("snapshot", window_id=window.hwnd, max_nodes=200)
    check("snapshot 成功", result.status == "ok", result.error)
    check("读到元素树", result.metadata.get("tree_nodes", 0) > 0, f"节点数={result.metadata.get('tree_nodes')}")
    tree_body = result.content

    document_ref = ""
    for line in tree_body.splitlines():
        if " Document " in line or line.strip().startswith("Document"):
            document_ref = line.split()[0]
            break
    check("找到编辑区元素", bool(document_ref), document_ref or "没有 Document 节点")

    print("\n== click 编辑区 ==")
    if document_ref:
        result = await call("click", ref=document_ref)
        check("click 成功", result.status == "ok", result.error or result.content)

    print("\n== type 中文 ==")
    # 记事本是 WinUI，类名分流会自动走前台，这里不传 background 验证分流生效。
    result = await call("type", text=TEXT)
    check("type 成功", result.status == "ok", result.error or result.content)

    time.sleep(0.6)

    print("\n== 读回内容 ==")
    if document_ref:
        result = await call("snapshot", window_id=window.hwnd, max_nodes=200)
        title_ok = TEXT.split()[0] in (win32.window_info(window.hwnd).title or "")
        check("窗口标题反映输入", title_ok, win32.window_info(window.hwnd).title)
        # 用 ref 读文本更直接：重新 snapshot 后按 Document 再取一次
        new_doc = ""
        for line in result.content.splitlines():
            if " Document " in line or line.strip().startswith("Document"):
                new_doc = line.split()[0]
                break
        if new_doc:
            from lamtools_core.computer_use.uia import shared_helper

            data = shared_helper().value(new_doc)
            text = str(data.get("text") or "")
            check("编辑区内容包含输入文本", TEXT in text, repr(text[:80]))

    print("\n== screenshot ==")
    result = await call("screenshot", target="window", window_id=window.hwnd, annotate="target")
    check("screenshot 成功", result.status == "ok", result.error)
    check("截图落盘", bool(result.metadata.get("path")), str(result.metadata.get("path")))
    check("截图给到模型", bool(result.model_image_data_url), f"{len(result.model_image_data_url)} 字节 data url")

    print("\n== 后台注入：被遮挡的窗口，鼠标不动 ==")
    target_result = WORK_ROOT / ".lam" / "tmp" / "tk_result.txt"
    target_result.parent.mkdir(parents=True, exist_ok=True)
    target = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "verify_background_target.py"), str(target_result)])
    tk_window = None
    for _ in range(60):
        for window in win32.list_windows():
            if "CU Background Target" in window.title:
                tk_window = window
                break
        if tk_window:
            break
        time.sleep(0.15)
    if tk_window is None:
        check("后台目标窗口启动", False)
    else:
        check("后台目标窗口启动", True, f"hwnd={tk_window.hwnd}")
        # 把 Sunday 拉到前台，让目标窗口被遮住
        for window in win32.list_windows():
            if window.title.strip().lower() == "sunday" and window.class_name == "Tauri Window":
                win32.activate_window(window.hwnd)
                break
        time.sleep(0.3)
        cursor_before = win32.cursor_position()
        await call("snapshot", window_id=tk_window.hwnd)
        shot = await call("screenshot", target="window", window_id=tk_window.hwnd)
        check("后台窗口截图成功", shot.status == "ok", shot.error)
        clicked = await call("click", x=120, y=60)
        cursor_after_click = win32.cursor_position()
        check("后台点击", clicked.status == "ok", clicked.content)
        check("后台点击没有移动鼠标", cursor_before == cursor_after_click, f"{cursor_before} -> {cursor_after_click}")
        cursor_before_type = win32.cursor_position()
        typed = await call("type", text="后台注入 OK")
        cursor_after_type = win32.cursor_position()
        check("后台输入", typed.status == "ok", typed.content)
        check("后台输入没有移动鼠标", cursor_before_type == cursor_after_type, f"{cursor_before_type} -> {cursor_after_type}")
        time.sleep(0.4)
        body = target_result.read_text(encoding="utf-8") if target_result.is_file() else ""
        check("目标窗口收到文字", "后台注入 OK" in body, repr(body[:60]))
    target.kill()
    target.wait(timeout=10)

    print("\n== 任务不会因为用户动鼠标而暂停 ==")
    win32.move_mouse(win32.cursor_position()[0] + 30, win32.cursor_position()[1] + 30)
    time.sleep(0.4)
    status = await call("status")
    check("任务仍在运行", status.metadata.get("state") == "running", str(status.metadata.get("state")))

    print("\n== pause 与 stop ==")
    result = await call("pause", reason="验收暂停")
    check("pause 成功", result.status == "ok", result.error)
    result = await call("resume")
    check("resume 成功", result.status == "ok", result.error)
    result = await call("stop", reason="验收完成")
    check("stop 成功", result.status == "ok", result.error)

    print("\n== 清理 ==")
    proc.kill()
    proc.wait(timeout=10)
    session.clear()
    from lamtools_core.computer_use import shutdown

    shutdown()

    print("\n== 汇总 ==")
    if failures:
        print(f"{len(failures)} 项失败: {failures}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
