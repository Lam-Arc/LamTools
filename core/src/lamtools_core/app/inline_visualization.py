"""An inert, isolated runtime; conversation content never goes into URLs or storage."""
from __future__ import annotations

import json

from fastapi.responses import HTMLResponse

RUNTIME_PATH = "/api/core/inline-visualizations/runtime"

# user:“不要出错”+(运行生成代码的文档必须从响应头隔离，不能放宽主窗口策略)。
RUNTIME_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data:; font-src 'none'; connect-src 'none'; frame-src 'none'; "
    "worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; "
    "sandbox allow-scripts; "
    "frame-ancestors http://127.0.0.1:* http://localhost:* tauri://localhost http://tauri.localhost"
)

_MONITOR = r"""
(() => {
  const send = (type, extra = {}) => parent.postMessage({type: 'sunday-visualization:' + type, ...extra}, '*');
  let scheduled = false;
  const resize = () => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      send('resize', {height: Math.ceil(document.body?.scrollHeight || 160) + 24});
    });
  };
  addEventListener('error', () => send('error'));
  addEventListener('unhandledrejection', () => send('error'));
  addEventListener('DOMContentLoaded', () => {
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(resize).observe(document.body);
    send('loaded'); resize();
  }, {once: true});
  addEventListener('message', event => {
    if (event.source !== parent || event.data?.type !== 'sunday-visualization:theme') return;
    for (const name of ['background', 'foreground', 'control', 'control-text', 'border']) {
      const value = event.data.theme?.[name];
      if (typeof value === 'string' && CSS.supports('color', value)) document.documentElement.style.setProperty('--' + name, value);
    }
  });
})();
"""

_STYLE = """
:root { color-scheme: dark light; }
* { box-sizing: border-box; }
body { margin: 0; padding: 12px; font: 14px system-ui, sans-serif; color: var(--foreground); background: var(--background); overflow-wrap: anywhere; }
button, input, select, textarea { font: inherit; }
button, select, input[type=range] { color: var(--control-text); background: var(--control); }
button { border: 0; border-radius: 6px; padding: 8px 12px; }
input, textarea { color: var(--foreground); background: var(--background); border: 1px solid var(--border); border-radius: 6px; padding: 8px; }
svg, canvas, img { max-width: 100%; }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }
"""


def runtime_response() -> HTMLResponse:
    # user:“Sunday也可以实现吗？去实现”+(用固定空运行页接收父窗口传入的交互内容，不接收路径或执行后台操作)。
    prefix = "<!doctype html><html><head><meta charset=utf-8><script>" + _MONITOR + "</script><style>" + _STYLE + "</style></head><body>"
    boot = """
    (() => {
      let started = false;
      addEventListener('message', event => {
        const data = event.data;
        if (started || event.source !== parent || data?.type !== 'sunday-visualization:init' || typeof data.html !== 'string' || data.html.length > 262144) return;
        started = true;
        document.open();
        document.write(PREFIX + data.html + '</body></html>');
        document.close();
      });
      parent.postMessage({type: 'sunday-visualization:ready'}, '*');
    })();
    """.replace("PREFIX", json.dumps(prefix).replace("<", "\\u003c"))
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><script>" + boot + "</script>",
        headers={
            "Content-Security-Policy": RUNTIME_CSP,
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Cross-Origin-Resource-Policy": "cross-origin",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=(), clipboard-read=(), clipboard-write=()",
        },
    )
