#!/usr/bin/env python3
"""LamWriter Launcher - 一键启动前后端（带进程控制）"""

import subprocess
import os
import time
import sys
import webbrowser
import socket

# 获取项目根目录（start.py 所在目录）
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(PROJECT_DIR, "backend")
FRONTEND_DIR = os.path.join(PROJECT_DIR, "frontend")
CORE_DIR = os.path.join(PROJECT_DIR, "..", "..", "core", "src")
DATA_DIR = os.path.join(PROJECT_DIR, "data")
VENV_DIR = os.path.join(PROJECT_DIR, "venv")

BACKEND_URL = "http://127.0.0.1:6173"
FRONTEND_URL = "http://localhost:6174"


def is_port_open(port, host="127.0.0.1"):
    """检查端口是否被占用"""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except:
        return False


def check_backend():
    import urllib.request
    try:
        urllib.request.urlopen(BACKEND_URL + "/api/projects", timeout=2)
        return True
    except:
        return False


def check_frontend():
    import urllib.request
    try:
        urllib.request.urlopen(FRONTEND_URL, timeout=2)
        return True
    except:
        return False


def hide_console():
    try:
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except:
        pass


def main():
    print("=" * 50)
    print("  LamWriter Web Launcher")
    print("=" * 50)
    
    # 检查是否已有服务在运行
    backend_running = is_port_open(6173)
    frontend_running = is_port_open(6174)
    
    if backend_running and frontend_running:
        print("\n[OK] LamWriter is already running!")
        print(f"\nOpening browser...")
        webbrowser.open(FRONTEND_URL)
        hide_console()
        return 0
    
    # 创建数据目录
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"\nData: {DATA_DIR}")
    
    # 环境变量
    env = os.environ.copy()
    env["LAMWRITER_DATA_DIR"] = DATA_DIR
    env["PYTHONPATH"] = os.path.abspath(CORE_DIR)
    
    # 检查虚拟环境
    python_exe = os.path.join(VENV_DIR, "Scripts", "python.exe")
    if not os.path.exists(python_exe):
        print("\n[ERROR] Virtual environment not found!")
        print("Please run setup.bat first.")
        input("\nPress Enter to exit...")
        return 1
    
    # 启动后端
    print("\n[1/2] Starting backend (port 6173)...")
    core_path = os.path.abspath(CORE_DIR)
    backend_proc = subprocess.Popen(
        [
            python_exe, "-c",
            f"import sys; sys.path.insert(0, r'{core_path}'); import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port=6173)"
        ],
        cwd=BACKEND_DIR,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    
    # 等待后端启动
    for i in range(10):
        time.sleep(1)
        if check_backend():
            break
    else:
        print("[ERROR] Backend failed to start!")
        input("Press Enter to exit...")
        return 1
    
    print("Backend: OK")
    
    # 启动前端
    print("\n[2/2] Starting frontend (port 6174)...")
    npm_cmd = os.path.join(FRONTEND_DIR, "node_modules", ".bin", "vite.cmd")
    if not os.path.exists(npm_cmd):
        npm_cmd = "npm"
    
    frontend_proc = subprocess.Popen(
        [npm_cmd, "--port", "6174"],
        cwd=FRONTEND_DIR,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    
    # 等待前端启动
    for i in range(10):
        time.sleep(1)
        if check_frontend():
            break
    else:
        print("[ERROR] Frontend failed to start!")
        input("Press Enter to exit...")
        return 1
    
    print("Frontend: OK")
    
    # 打开浏览器
    print("\nOpening browser...")
    webbrowser.open(FRONTEND_URL)
    
    print("\n" + "=" * 50)
    print("LamWriter started successfully!")
    print("You can close this window now.")
    print("=" * 50)
    
    # 隐藏启动器窗口
    hide_console()
    
    # 等待关闭
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nStopping services...")
        backend_proc.terminate()
        frontend_proc.terminate()
        backend_proc.wait(timeout=5)
        frontend_proc.wait(timeout=5)
        print("Stopped.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
