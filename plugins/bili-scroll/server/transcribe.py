"""bili-scroll 本地转写脚本。

user:“本地转写”+把无字幕视频的语音用 Whisper 转成文字，供值班轮阅读。
环境自检先行：缺什么如实报告（whisper / ffmpeg / SESSDATA），绝不半途炸掉。
用法：python transcribe.py <bvid>（由 MCP 的 transcribe 工具或 run_command 调起）
依赖（装转写依赖操作写入插件 venv）：openai-whisper、httpx；ffmpeg 需在 PATH。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bili_core  # noqa: E402


def _check() -> list[str]:
    missing = []
    if shutil.which("whisper") is None:
        missing.append("whisper 命令未找到（在插件 venv 里 pip install openai-whisper，或装转写依赖）")
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg 不在 PATH（Whisper 解码音频需要它）")
    if not bili_core._cookies().get("SESSDATA"):
        missing.append("未配置 SESSDATA（下载音频流需要登录态）")
    return missing


async def _audio_url(bvid: str) -> tuple[str, int]:
    data = await bili_core.bili_video_info(bvid)
    import httpx

    with bili_core._client() as client:
        view = client.get(f"{bili_core._API}/x/web-interface/view", params={"bvid": bvid}).json()
        cid = (view.get("data") or {}).get("cid")
        play = client.get(
            f"{bili_core._API}/x/player/playurl",
            params={"bvid": bvid, "cid": cid, "fnval": 16},
        ).json()
    if play.get("code") != 0:
        raise ValueError(f"取音频地址失败：code={play.get('code')}（{play.get('message')}）")
    dash = (play.get("data") or {}).get("dash") or {}
    audio = next((a for a in dash.get("audio", []) if a), None)
    if audio is None:
        raise ValueError("该视频没有可下载的音频流")
    return audio["baseUrl"], int(data.get("duration_sec") or 0)


async def run_transcribe(bvid: str) -> str:
    missing = _check()
    if missing:
        return "转写环境未就绪：\n- " + "\n- ".join(missing)
    bvid = bili_core._bvid(bvid)
    url, _duration = await _audio_url(bvid)
    out = bili_core._DATA_DIR / "transcripts"
    out.mkdir(parents=True, exist_ok=True)
    audio_file = out / f"{bvid}.m4a"
    text_file = out / f"{bvid}.txt"
    import httpx

    # user:“该修修”+(下载统一异步客户端，避免同步流误用异步迭代并阻塞服务)。
    async with httpx.AsyncClient(headers={"User-Agent": bili_core._UA, "Referer": "https://www.bilibili.com"}, cookies=bili_core._cookies(), timeout=30) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with audio_file.open("wb") as sink:
                async for chunk in response.aiter_bytes():
                    sink.write(chunk)
    proc = await asyncio.create_subprocess_exec(
        "whisper",
        str(audio_file),
        "--model",
        "small",
        "--output_format",
        "txt",
        "--output_dir",
        str(out),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        output, _ = await proc.communicate()
    except asyncio.CancelledError:
        proc.terminate()
        await proc.wait()
        audio_file.unlink(missing_ok=True)
        raise
    if proc.returncode != 0 or not text_file.exists():
        detail = output.decode("utf-8", "ignore")[-400:] if output else ""
        return f"转写失败（whisper 退出码 {proc.returncode}）：{detail}"
    text = text_file.read_text(encoding="utf-8").strip()
    audio_file.unlink(missing_ok=True)
    return json.dumps({"bvid": bvid, "transcript": text[:8000], "chars": len(text)}, ensure_ascii=False)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: transcribe.py <bvid>")
        raise SystemExit(2)
    print(asyncio.run(run_transcribe(sys.argv[1])))
