"""Measure the desktop UI's own share of the send path, in a real browser.

Drives the shipped SPA against the harness backend with Playwright and records,
per send:

* Enter -> the sent text is visible in the transcript (the UI's own feedback)
* Enter -> the composer is empty again
* every long task the main thread ran during the window

The composer is a CodeMirror editor, so the harness types through the real
keyboard path instead of assigning ``value``.

Usage:
  python core/scripts/send_latency/measure_ui.py --url http://127.0.0.1:5921/ --title perf-long --rounds 8
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

from playwright.async_api import async_playwright

PROBE_JS = """
window.__sendProbe = { longTasks: [] };
try {
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) window.__sendProbe.longTasks.push(entry.duration);
  }).observe({ entryTypes: ['longtask'] });
} catch (error) {
  window.__sendProbe.longTasksError = String(error);
}
"""

MEASURE_JS = """
async ({ marker }) => {
  window.__sendProbe.longTasks.length = 0;
  const editor = document.querySelector('.cm-content');
  const seenBefore = new Set(
    Array.from(document.querySelectorAll('*')).filter((node) =>
      node.children.length === 0 && String(node.textContent || '').includes(marker)
    )
  );
  const start = performance.now();
  // Feedback = the marker becomes visible somewhere in the page (the user's
  // own bubble, or a pending row) without waiting for Core.
  let feedback = -1;
  let cleared = -1;
  const deadline = start + 4000;
  while (performance.now() < deadline) {
    const empty = !String(editor?.innerText || '').trim();
    if (cleared < 0 && empty) cleared = performance.now() - start;
    const visible = Array.from(document.querySelectorAll('*')).some(
      (node) => node.children.length === 0
        && String(node.textContent || '').includes(marker)
        && !seenBefore.has(node)
    );
    if (visible) { feedback = performance.now() - start; break; }
    await new Promise((resolve) => requestAnimationFrame(resolve));
  }
  let accepted = -1;
  const acceptDeadline = performance.now() + 20000;
  while (performance.now() < acceptDeadline) {
    const visible = Array.from(document.querySelectorAll('*')).some(
      (node) => node.children.length === 0
        && String(node.textContent || '').includes(marker)
        && !seenBefore.has(node)
    );
    if (visible) { accepted = performance.now() - start; break; }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  return {
    feedback,
    cleared,
    accepted,
    longTasks: window.__sendProbe.longTasks.slice(),
  };
}
"""


async def run(args: argparse.Namespace) -> int:
    results: list[dict[str, object]] = []
    console_errors: list[str] = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        page.on(
            "console",
            lambda message: console_errors.append(message.text) if message.type == "error" else None,
        )
        await page.add_init_script(PROBE_JS)
        await page.goto(args.url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        await page.get_by_role("button", name=args.title).first.click(timeout=30000)
        await page.wait_for_timeout(args.settle_ms)
        editor = page.locator(".cm-content").first
        await editor.wait_for(state="visible", timeout=30000)

        for round_index in range(args.rounds):
            marker = f"UI-LAT-{int(time.time() * 1000)}-{round_index}"
            await editor.click()
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Delete")
            await page.keyboard.type(f"{marker} 界面发送延迟测量", delay=0)
            await page.wait_for_timeout(120)
            await page.evaluate("() => { window.__sendProbe.longTasks.length = 0; }")
            # The measurement polls in the page while the real Enter key is
            # dispatched from Playwright, so the two run concurrently.
            measuring = asyncio.create_task(
                page.evaluate(MEASURE_JS, {"marker": marker})
            )
            await asyncio.sleep(0.05)
            await page.keyboard.press("Enter")
            measurement = await measuring
            await page.wait_for_timeout(args.gap_ms)
            results.append(measurement)
            print(f"  round {round_index:02d}: {json.dumps(measurement)}", flush=True)
        await browser.close()

    def stats(values: list[float]) -> dict[str, float]:
        ordered = sorted(value for value in values if value >= 0)
        if not ordered:
            return {"n": 0, "p50": 0.0, "p95": 0.0, "max": 0.0}
        index = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
        return {
            "n": len(ordered),
            "p50": round(statistics.median(ordered), 1),
            "p95": round(ordered[index], 1),
            "max": round(ordered[-1], 1),
        }

    long_tasks = [float(value) for result in results for value in result["longTasks"]]
    summary = {
        "enter_to_visible_ms": stats([float(result["feedback"]) for result in results]),
        "enter_to_composer_clear_ms": stats([float(result["cleared"]) for result in results]),
        "long_tasks_ms": stats(long_tasks),
        "long_task_count": len(long_tasks),
        "console_errors": console_errors[:5],
    }
    print("UI_RESULT " + json.dumps(summary, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--settle-ms", type=int, default=3000)
    parser.add_argument("--gap-ms", type=int, default=2500)
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
