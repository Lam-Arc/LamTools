"""离线复现：把「另存为」下来的搜索结果页 HTML 喂给适配器，看它到底提取出什么。

user:“我边测边改，你快修快改”+
(真页面上某个引擎不对时，把那一页 Ctrl+S 存下来，跑这个脚本就能复现：
 选择器命中了几张卡片、哪张被判成广告、哪个字段是空的、页面是不是被验证码拦了。
 不用重启桌面端，也不用联网)。

用法：
    python core/scripts/browser_search_extract.py --html E:/tmp/bing.html --engine bing
    python core/scripts/browser_search_extract.py --html E:/tmp/g.html --engine generic --limit 5

说明：这里只做「页面侧取片段 + Python 清洗」两段，等价于桌面端的 browser_html + pipeline；
不打开浏览器、不访问网络，因此结果与真机一致（差异只可能来自页面本身有没有加载完）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from lamtools_core.browser.search import dom, pipeline  # noqa: E402
from lamtools_core.browser.search import adapters  # noqa: E402
from lamtools_core.browser.search.adapters.generic import GENERIC  # noqa: E402


def page_nodes(html: str, selectors: tuple[str, ...]) -> tuple[list[dict], list[str]]:
    """模拟页面桥的 `extractHtml`：选择器取并集、文档顺序、父子只留外层。"""
    root = dom.parse(html)
    skipped: list[str] = []
    seen: set[int] = set()
    picked: list[tuple[dom.Node, str]] = []
    for selector in selectors:
        try:
            found = root.select(selector)
        except dom.SelectorError:
            skipped.append(selector)
            continue
        for node in found:
            if id(node) in seen:
                continue
            seen.add(id(node))
            picked.append((node, selector))
    kept: list[tuple[dom.Node, str]] = []
    for node, selector in picked:
        parent = node.parent
        nested = False
        while parent is not None:
            if any(parent is other for other, _ in kept):
                nested = True
                break
            parent = parent.parent
        if not nested:
            kept.append((node, selector))
    return [{"selector": selector, "html": node.to_html()} for node, selector in kept], skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="用一份保存下来的结果页 HTML 复现提取过程")
    parser.add_argument("--html", required=True, help="保存下来的页面 HTML 路径")
    parser.add_argument("--engine", default="generic", help="bing / google / baidu / generic")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--base-url", default="", help="页面原始地址（相对链接按它补全）")
    parser.add_argument("--include-ads", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    html = Path(args.html).read_text(encoding="utf-8", errors="replace")
    if args.engine == "generic":
        adapter = GENERIC
        mode = "l2"
    else:
        adapter = adapters.get(args.engine)
        mode = "l1"
    base_url = args.base_url or {
        "bing": "https://www.bing.com/search",
        "google": "https://www.google.com/search",
        "baidu": "https://www.baidu.com/s",
    }.get(adapter.name, "https://example.com/")

    root = dom.parse(html)
    page_text = root.text[:2000]
    block = adapter.detect_block(base_url, root.first("title").text if root.first("title") else "", page_text)
    no_results = adapter.has_no_results(page_text)

    selectors = adapter.card_selectors if mode == "l1" else adapter.container_selectors
    nodes, skipped = page_nodes(html, selectors)
    outcome = pipeline.extract(
        adapter,
        nodes,
        base_url=base_url,
        limit=args.limit,
        include_ads=args.include_ads,
        mode=mode,
    )
    report = {
        "engine": adapter.name,
        "mode": mode,
        "block": block,
        "noResults": no_results,
        "selectors": list(selectors),
        "skippedSelectors": skipped,
        "fetchedNodes": len(nodes),
        "stats": outcome.stats(),
        "results": outcome.results,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(f"[{adapter.name}/{mode}] 取回片段 {len(nodes)} 个；block={block or '无'} noResults={no_results}")
    print(f"  统计：{outcome.stats()}")
    if skipped:
        print(f"  被拒选择器：{skipped}")
    for item in outcome.results:
        flag = " [广告]" if item["sponsored"] else ""
        pending = " [中转未解]" if item.get("urlPending") else ""
        print(f"  #{item['rank']} {item['title'][:60]}{flag}{pending}")
        print(f"      {item['url']}")
        if item["snippet"]:
            print(f"      {item['snippet'][:90]}")
        if item["sitelinks"]:
            print(f"      子链接：{', '.join(link['title'] for link in item['sitelinks'])}")
    if not outcome.results:
        print("  没有提取到结果：先看 stats.invalid（字段配对失败）还是 fetchedNodes=0（选择器全没中）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
