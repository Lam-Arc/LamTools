#!/usr/bin/env python3
"""scripts/qr.py —— 用 venv 里的 qrcode 把登录 URL 画成 PNG（原版 renderQrPng 的等价物）。

用法：<venv>/python.exe scripts/qr.py <url> <输出 png 路径>
没装 qrcode 时退出码非 0 —— 调用方会退回"只给 URL"。
"""

import sys


def main() -> int:
    if len(sys.argv) < 3:
        print("用法：qr.py <url> <out.png>", file=sys.stderr)
        return 2
    url, out = sys.argv[1], sys.argv[2]
    try:
        import qrcode  # noqa: PLC0415
    except Exception as exc:  # 没装就是没装，别装作画好了
        print(f"没有 qrcode：{exc}", file=sys.stderr)
        return 3
    img = qrcode.make(url)
    img.save(out)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
