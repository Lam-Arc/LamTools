"""后台注入验收用的目标窗口：传统 Win32 控件，内容定时写到文件。"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tk_result.txt")

root = tk.Tk()
root.title("CU Background Target")
root.geometry("560x260+420+320")
entry = tk.Entry(root, font=("Segoe UI", 14))
entry.pack(fill="x", padx=20, pady=18)
text = tk.Text(root, height=6)
text.pack(fill="both", expand=True, padx=20, pady=(0, 18))
entry.focus_set()


def dump() -> None:
    OUT.write_text(
        "entry=" + entry.get() + "\n" + "text=" + text.get("1.0", "end").strip() + "\n",
        encoding="utf-8",
    )
    root.after(150, dump)


root.after(150, dump)
root.mainloop()
