"""bili-scroll MCP 服务端（stdio）。

user:“能力面全 MCP”+11 个能力与转写慢工具以 MCP 工具暴露；服务端跑在
插件自管的 venv 里（仅依赖 httpx 与 mcp 包），**不得导入宿主**——业务
逻辑全部来自 bili_core（与宿主侧共享的独立模块）。

启动：由宿主按 mcp/mcp.json 的 command 拉起（stdio）。预期失败抛出的
ValueError 转成可读文本返回，模型据此决定下一步。
"""

from __future__ import annotations

from functools import wraps
from typing import Any
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bili_core  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("bilibili")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


def _guard(func):
    """ValueError（预期失败）转可读文本；其余异常带类型原样抛出。"""

    # user:“该修修”+(保留原始签名，协议能正确发现每个工具的参数)。
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except ValueError as exc:
            return f"错误：{exc}"

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


@mcp.tool()
@_guard
async def brief() -> str:
    """取今日值班参数：关键词、挑选限额、评论预算、判重表近况、日报位置与登录状态。值班第一件事就是调它。"""
    return _json(bili_core.duty_brief_payload())


@mcp.tool()
@_guard
async def search(keyword: str, days: int = 3) -> str:
    """按关键词搜索 B站 最近几天的视频，返回 BV号、标题、UP主与简介。days 只看最近几天（1-14，默认 3）。"""
    return _json(await bili_core.bili_search(keyword, days))


@mcp.tool()
@_guard
async def video_info(bvid: str) -> str:
    """读一条 B站 视频的完整信息：标题、简介、UP主、时长、播放/评论数、封面地址。"""
    return _json(await bili_core.bili_video_info(bvid))


@mcp.tool()
@_guard
async def subtitles(bvid: str) -> str:
    """读一条 B站 视频的字幕原文（逐句拼接）。无字幕时返回可读说明——按“跳过（无字幕）”记账，绝不编造。"""
    return _json(await bili_core.bili_subtitles(bvid))


@mcp.tool()
@_guard
async def comments(bvid: str) -> str:
    """读一条 B站 视频的热门评论（按热度排序，前 20 条）。"""
    return _json(await bili_core.bili_comments(bvid))


@mcp.tool()
@_guard
async def save_report(bvid: str, text: str) -> str:
    """把一条视频的评估写进今天的日报（data/out/<日期>.md），段首固定 “### BV号”。路径固定，不接受路径参数。"""
    return _json(await bili_core.bili_save_report(bvid, text))


@mcp.tool()
@_guard
async def dedup(action: str, bvid: str = "", title: str = "", up: str = "", status: str = "") -> str:
    """判重表：action="list" 看最近记了什么（先看再挑）；action="mark" 记一条（status = picked / skipped / commented）。"""
    return _json(await bili_core.bili_dedup(action, bvid, title, up, status))


@mcp.tool()
@_guard
async def post_comment(bvid: str, content: str) -> str:
    """在一条 B站 视频下发评论。同意权 = 配置里的 auto_comment 开关；同一视频只发一次、受每轮限额约束；凭证缺失或开关关闭时拒绝。"""
    return _json(await bili_core.bili_post_comment(bvid, content))


@mcp.tool()
@_guard
async def account_status() -> str:
    """查当前 B站 登录状态。值班开始前看一眼，决定能不能读字幕、能不能发评论。"""
    return _json(await bili_core.bili_account_status())


@mcp.tool()
@_guard
async def send_dm(content: str) -> str:
    """把值班日报或摘要以私信投递给配置的收件人（默认登录账号自己）。收件人固定，不开放任意发送；dm_mode=off 或未登录时拒绝。"""
    return _json(await bili_core.bili_send_dm(content))


@mcp.tool()
@_guard
async def dm_inbox() -> str:
    """读最近私信会话预览（仅 dm_reply 开关打开时可用；默认关闭）。"""
    return _json(await bili_core.bili_dm_inbox())


@mcp.tool()
@_guard
async def transcribe(bvid: str) -> str:
    """本地转写一条无字幕视频的语音为文字（慢，分钟级）。需要先装转写依赖（Whisper）并配置登录凭证；未就绪时返回缺什么。"""
    from transcribe import run_transcribe  # 延迟导入：转写依赖单独装

    return await run_transcribe(bvid)


if __name__ == "__main__":
    mcp.run()
