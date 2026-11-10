#!/usr/bin/env python3
"""阶段门 5：headless Chromium 整页截图 + 页面自检，并给出切片切点。

用法:
    python page_shot.py --html out/report.html --out-dir out/shots --name page
产出:
    <out-dir>/<name>.png        整页截图
    <out-dir>/<name>.qa.json    自检报告（图片未加载、横向溢出、SVG 文字太少、可疑空白带等）
    <out-dir>/<name>.cuts.json  章节标题 y 坐标，交给 slice.sh 避免切断标题
退出码:
    0 通过, 2 发现问题（必须回 HTML 修）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CHECK_JS = r"""
() => {
  const out = {problems: [], warnings: [], images: [], svgs: [], cuts: [], docHeight: 0, docWidth: 0, viewportWidth: 0};
  const doc = document.documentElement;
  out.docHeight = doc.scrollHeight;
  out.docWidth = doc.scrollWidth;
  out.viewportWidth = window.innerWidth;
  if (doc.scrollWidth > window.innerWidth + 2) {
    out.problems.push(`页面横向溢出: scrollWidth=${doc.scrollWidth} > viewport=${window.innerWidth}`);
  }

  document.querySelectorAll('img').forEach(img => {
    const r = img.getBoundingClientRect();
    const rec = {src: img.getAttribute('src'),
                 w: Math.round(r.width), h: Math.round(r.height),
                 natural: img.naturalWidth, top: Math.round(r.top + window.scrollY)};
    out.images.push(rec);
    if (!img.complete || img.naturalWidth === 0) out.problems.push(`图片没加载出来: ${rec.src}`);
    else if (rec.w < 50 || rec.h < 50) out.warnings.push(`图片显示尺寸过小: ${rec.src} ${rec.w}x${rec.h}`);
  });

  document.querySelectorAll('svg').forEach((svg, i) => {
    const r = svg.getBoundingClientRect();
    const texts = svg.querySelectorAll('text, tspan').length;
    const shapes = svg.querySelectorAll('rect, circle, ellipse, polygon, path, line, polyline').length;
    const markers = svg.querySelectorAll('marker, defs marker, [marker-end], [stroke-dasharray]').length;
    const label = (svg.getAttribute('aria-label') || svg.getAttribute('data-title') || '').trim();
    const rec = {index: i + 1, label, texts, shapes, markers,
                 w: Math.round(r.width), h: Math.round(r.height),
                 top: Math.round(r.top + window.scrollY)};
    out.svgs.push(rec);
    if (texts < 2) out.problems.push(`第 ${i + 1} 张 SVG 文字节点只有 ${texts} 个，图形没有标签`);
    if (shapes < 3) out.problems.push(`第 ${i + 1} 张 SVG 图形元素只有 ${shapes} 个，内容过少`);
    if (markers === 0) out.warnings.push(`第 ${i + 1} 张 SVG 没有找到箭头或虚线等关系标记，确认是否只画了并列色块`);
    if (r.height < 60) out.warnings.push(`第 ${i + 1} 张 SVG 高度只有 ${Math.round(r.height)}px，可能被压扁`);
  });

  document.querySelectorAll('[data-chapter], h2, h1').forEach(h => {
    const r = h.getBoundingClientRect();
    out.cuts.push({text: (h.textContent || '').trim().slice(0, 40), top: Math.round(r.top + window.scrollY)});
  });

  const blocks = [...document.querySelectorAll('section, .chapter, figure, .fig, table, ul, ol, p, h2, h3, h4')]
    .map(el => { const r = el.getBoundingClientRect(); return {top: Math.round(r.top + window.scrollY), bottom: Math.round(r.bottom + window.scrollY)}; })
    .filter(b => b.bottom > b.top)
    .sort((a, b) => a.top - b.top);
  let cursor = 0;
  blocks.forEach(b => {
    if (b.top - cursor > 600) out.problems.push(`疑似空白带: y=${cursor} 到 y=${b.top} 之间约 ${b.top - cursor}px 没有内容`);
    cursor = Math.max(cursor, b.bottom);
  });
  return out;
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--name", default="page")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--scale", type=float, default=1.0)
    args = ap.parse_args()

    html = Path(args.html).resolve()
    if not html.is_file():
        print(f"[error] 找不到 HTML: {html}", file=sys.stderr)
        return 3
    outdir = Path(args.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    png = outdir / f"{args.name}.png"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": 1000},
                                device_scale_factor=args.scale)
        page.goto(html.as_uri(), wait_until="load")
        page.wait_for_timeout(800)
        page.evaluate("async () => { if (document.fonts) await document.fonts.ready; }")
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
        report = page.evaluate(CHECK_JS)
        page.screenshot(path=str(png), full_page=True)
        browser.close()

    qa_path = outdir / f"{args.name}.qa.json"
    qa_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    cuts = sorted({c["top"] for c in report["cuts"] if isinstance(c.get("top"), int)})
    (outdir / f"{args.name}.cuts.json").write_text(
        json.dumps({"cuts": cuts, "labels": report["cuts"]}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"整页截图: {png}")
    print(f"页面尺寸: {report['docWidth']}x{report['docHeight']}")
    print(f"图片 {len(report['images'])} 张，SVG {len(report['svgs'])} 张，切点 {len(cuts)} 个")
    for s in report["svgs"]:
        print(f"  SVG#{s['index']} {s['label'] or '(无标签)'} 文字{s['texts']} 图形{s['shapes']} {s['w']}x{s['h']}")
    for w in report["warnings"]:
        print(f"  [warn] {w}")
    for pr in report["problems"]:
        print(f"  [problem] {pr}")
    print(f"自检报告: {qa_path}")

    if report["problems"]:
        print("[gate] 失败：自检发现问题，改 HTML 后重跑", file=sys.stderr)
        return 2
    print("[gate] 机器自检通过，接下来用 read_file 打开整页 PNG 亲眼看一遍", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
