"""bili-scroll 后端：峰谷定时器 + 值班轮触发。

user:“峰谷自动刷”+复刻原版的内置调度器：到点（中午 12–14 / 晚上 18–09，
配置可开关）按运行档 bili-scroll:duty 拉起值班子代理；“现在跑一轮”按钮走
同一个入口（trigger_now）。原版语义：无人值守、每窗口每天最多一轮。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

_SCHEDULE_PATH = Path(__file__).resolve().parent.parent / "data" / "schedule.json"
_CHECK_INTERVAL_SEC = 300


def _in_window(now: datetime, window: str) -> bool:
    if window == "noon":
        return 12 <= now.hour < 14
    if window == "night":
        return now.hour >= 18 or now.hour < 9
    return False


class DutyRuntime:
    """峰谷调度 + 值班轮触发（按运行档 bili-scroll:duty）。"""

    def __init__(self, context) -> None:
        self.context = context
        self.state = "loaded"
        self._task: asyncio.Task | None = None
        self._current: asyncio.Task | None = None

    # ── 生命周期 ─────────────────────────────────────────────────────

    async def start(self, context=None) -> None:
        self.context = context or self.context
        self.state = "ready"
        self._task = asyncio.get_running_loop().create_task(
            self._loop(), name="bili-scroll:peak-valley"
        )

    async def stop(self) -> None:
        self.state = "stopped"
        for task in (self._task, self._current):
            if task is not None and not task.done():
                task.cancel()

    def health_check(self) -> dict[str, Any]:
        # user:“启动期 _health 探测在 state=ready 之前”+自引用会令启动必失败；
        # 存活判据 = 峰谷循环任务存在。
        return {"ready": self._task is not None and not self._task.done()}

    # ── 触发 ─────────────────────────────────────────────────────────

    def _config(self) -> dict[str, Any]:
        from bili_core import _config

        return _config()

    def _schedule(self) -> dict[str, Any]:
        path = _SCHEDULE_PATH
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _mark_run(self, window: str, today: str) -> None:
        _SCHEDULE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = self._schedule()
        data[window] = today
        _SCHEDULE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def _profile_spec(self):
        from lamtools_core.plugin_system import resolve_profile

        host = self.context.service("plugin.v2_host")
        if host is None:
            raise RuntimeError("宿主未注入（plugin.v2_host 服务缺失）")
        return resolve_profile(host.discover(), "bili-scroll:duty")

    def trigger_now(self) -> dict[str, Any]:
        """手动/定时共用的触发入口；同一时间只允许一轮在跑。"""
        if self._current is not None and not self._current.done():
            return {"started": False, "reason": "已有一轮值班在跑"}
        spec = self._profile_spec()
        runner = self.context.service("sub_agent_runner_factory")()
        task_text = (
            "按 bili-duty 章程替使用者值一班岗：先调 bilibili 的 brief 工具取今日参数，"
            "然后按章程流程执行（搜索→读字幕判价值→写日报→判重→按开关投递）。"
        )
        self._current = asyncio.get_running_loop().create_task(
            runner.run(task=task_text, agent="bili-duty", profile_spec=spec),
            name="bili-scroll:duty-round",
        )
        self._current.add_done_callback(lambda t: self._current.__class__)  # 保持引用语义
        return {
            "started": True,
            "profile": spec.full_name,
            "note": "值班轮已在后台启动；结果见日报与判重表。",
        }

    # ── 峰谷循环 ─────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self.state == "ready":
            try:
                await asyncio.sleep(_CHECK_INTERVAL_SEC)
                cfg = self._config()
                if not bool(cfg.get("peak_valley")):
                    continue
                now = datetime.now()
                today = now.strftime("%Y-%m-%d")
                schedule = self._schedule()
                for window, switch in (("noon", "noon"), ("night", "night")):
                    if not bool(cfg.get(switch, True)):
                        continue
                    if not _in_window(now, window):
                        continue
                    if schedule.get(window) == today:
                        continue  # 每窗口每天最多一轮
                    if self._current is not None and not self._current.done():
                        continue
                    self._mark_run(window, today)
                    self.trigger_now()
                    break
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — 调度循环不能死
                await asyncio.sleep(60)


def create_plugin(context) -> dict[str, Any]:
    runtime = DutyRuntime(context)
    return {
        "runtime": runtime,
        "services": {"duty": runtime},
    }
