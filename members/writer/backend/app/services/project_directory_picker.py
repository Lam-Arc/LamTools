from __future__ import annotations

import os
import subprocess
import sys


class ProjectDirectoryPickerUnavailable(RuntimeError):
    pass


def pick_project_directory() -> str:
    if os.name == "nt":
        return _pick_directory_windows()
    return _pick_directory_tk()


def _pick_directory_windows() -> str:
    script = r"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '选择 Writer 项目目录'
$dialog.ShowNewFolderButton = $true
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
  Write-Output $dialog.SelectedPath
}
"""
    startupinfo = None
    creationflags = 0
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-STA",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        startupinfo=startupinfo,
        creationflags=creationflags,
        check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "目录选择器不可用").strip()
        raise ProjectDirectoryPickerUnavailable(message)
    return (completed.stdout or "").strip()


def _pick_directory_tk() -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise ProjectDirectoryPickerUnavailable("当前环境不支持本机目录选择") from exc

    root = tk.Tk()
    root.withdraw()
    try:
        return filedialog.askdirectory(title="选择 Writer 项目目录") or ""
    finally:
        root.destroy()


__all__ = ["ProjectDirectoryPickerUnavailable", "pick_project_directory"]
