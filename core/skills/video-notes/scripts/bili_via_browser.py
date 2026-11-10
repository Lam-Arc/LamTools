#!/usr/bin/env python3
"""yt-dlp 被 B 站风控（HTTP 412）挡住时的兜底：用真实 Chromium 拿元数据并下音频。

原理：412 是冲着非浏览器客户端来的，浏览器能过。脚本用 Playwright 打开视频页，读
window.__INITIAL_STATE__ 拿元数据，捕获 playurl 响应拿音频流地址，再借浏览器上下文把
音频下下来，最后转 mp3。产出的 info.json 字段和 yt-dlp 对齐，后续脚本可直接复用。

用法:
    python bili_via_browser.py --url "https://www.bilibili.com/video/BVxxxx" --out out/ [--page 1]
    # 需要登录（高清/会员）：开有头浏览器人工登录
    python bili_via_browser.py --url "..." --out out/ --login 120
产出:
    <out>/meta/<bvid>.info.json   与 yt-dlp 兼容（含 title/uploader/duration/tags/description/thumbnail/entries）
    <out>/meta/<bvid>.jpg         封面
    <out>/audio/<bvid>.mp3        音频（转码后）
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

STATE_JS = r"""
() => {
  const st = window.__INITIAL_STATE__ || {};
  const vd = st.videoData || {};
  return {
    bvid: vd.bvid, aid: vd.aid, cid: vd.cid,
    title: vd.title, desc: vd.desc, duration: vd.duration,
    uploader: vd.owner && vd.owner.name,
    pubdate: vd.pubdate, tname: vd.tname,
    pic: vd.pic,
    pages: (vd.pages || []).map(p => ({page: p.page, part: p.part, duration: p.duration, cid: p.cid})),
    playinfo: window.__playinfo__ || null
  };
}
"""


def fetch_playinfo(page, ctx, url: str, page_no: int, login_wait: int) -> dict:
    """打开视频页并拿到 playurl 的响应体（浏览器自己会带上完整的签名与 cookie）。"""
    captured: dict = {}

    def on_response(resp):
        if "playurl" in resp.url and resp.status == 200:
            try:
                captured["data"] = resp.json()
            except Exception:  # noqa: BLE001
                pass

    page.on("response", on_response)
    target = url if page_no <= 1 else f"{url}?p={page_no}"
    page.goto(target, wait_until="load", timeout=90000)
    page.wait_for_timeout(4000 if not login_wait else int(login_wait * 1000))

    if "data" not in captured:
        # 播放器没自动请求 playurl，就点一下播放，逼它发请求
        for attempt in range(3):
            try:
                page.click(".bpx-player-video-wrap, video, #bilibili-player", timeout=4000)
            except Exception:  # noqa: BLE001
                pass
            try:
                page.keyboard.press("k")
            except Exception:  # noqa: BLE001
                pass
            for _ in range(8):
                page.wait_for_timeout(1500)
                if "data" in captured:
                    break
            if "data" in captured:
                break
    return captured.get("data") or {}


def pick_audio(playinfo: dict) -> dict | None:
    dash = ((playinfo or {}).get("data") or {}).get("dash") or {}
    audio = dash.get("audio") or []
    if audio:
        return max(audio, key=lambda a: a.get("bandwidth") or 0)
    durl = ((playinfo or {}).get("data") or {}).get("durl") or []
    if durl:
        return {"baseUrl": durl[0].get("url"), "bandwidth": 0, "codecs": "durl"}
    return None


def browser_download(ctx, media_url: str, referer: str, dest: Path) -> int:
    resp = ctx.request.get(
        media_url,
        headers={"Referer": referer, "User-Agent": UA, "Range": "bytes=0-"},
        timeout=300000,
    )
    if not resp.ok:
        raise RuntimeError(f"下载失败 {resp.status} {media_url[:80]}")
    body = resp.body()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return len(body)


def pick_video(playinfo: dict, max_height: int) -> dict | None:
    """挑一路视频流：高度不超上限，同高度优先 avc（ffmpeg 抽帧最稳）。"""
    dash = ((playinfo or {}).get("data") or {}).get("dash") or {}
    videos = dash.get("video") or []
    ok = [v for v in videos if (v.get("height") or 0) <= max_height] or videos
    if not ok:
        return None

    def rank(v: dict):
        codecs = (v.get("codecs") or "").lower()
        avc = 1 if codecs.startswith("avc") else 0
        return (v.get("height") or 0, avc, v.get("bandwidth") or 0)

    return max(ok, key=rank)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--login", type=int, default=0, help=">0 时开有头浏览器人工登录")
    ap.add_argument("--keep-m4a", action="store_true")
    ap.add_argument("--want", default="audio", choices=["audio", "video", "both"],
                    help="下音频、下视频（抽真实帧用）还是都要")
    ap.add_argument("--max-height", type=int, default=720, help="视频流高度上限")
    args = ap.parse_args()

    out = Path(args.out)
    meta_dir, audio_dir = out / "meta", out / "audio"
    meta_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.login <= 0)
        ctx = browser.new_context(
            locale="zh-CN", viewport={"width": 1440, "height": 900}, user_agent=UA
        )
        page = ctx.new_page()

        playinfo = fetch_playinfo(page, ctx, args.url, args.page, args.login)
        state = page.evaluate(STATE_JS)
        if args.login > 0:
            print(f"[login] 已留 {args.login} 秒给人工登录（若已登录可忽略）")

        bvid = state.get("bvid") or "unknown"
        print(f"[meta] 标题: {state.get('title')}")
        print(f"[meta] UP: {state.get('uploader')} 时长: {state.get('duration')}s 分P: {len(state.get('pages') or [])}")

        tags: list[str] = []
        try:
            r = ctx.request.get(
                f"https://api.bilibili.com/x/tag/archive/tags?bvid={bvid}",
                headers={"Referer": args.url, "User-Agent": UA},
                timeout=30000,
            )
            tj = r.json()
            if tj.get("code") == 0:
                tags = [t.get("tag_name") for t in tj.get("data") or [] if t.get("tag_name")]
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 标签没取到（不致命）: {exc}")

        pic = state.get("pic") or ""
        if pic:
            cover = meta_dir / f"{bvid}.jpg"
            try:
                browser_download(ctx, "https:" + pic if pic.startswith("//") else pic, args.url, cover)
                print(f"[meta] 封面已存: {cover}")
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] 封面没下下来（不致命）: {exc}")

        pages = state.get("pages") or []
        entries = [
            {
                "id": f"{bvid}_p{pg['page']}",
                "title": pg.get("part") or state.get("title"),
                "duration": pg.get("duration") or state.get("duration"),
                "webpage_url": f"https://www.bilibili.com/video/{bvid}?p={pg['page']}",
            }
            for pg in pages
        ] or None

        info = {
            "id": bvid,
            "title": state.get("title"),
            "uploader": state.get("uploader"),
            "duration": state.get("duration"),
            "description": state.get("desc"),
            "tags": tags,
            "thumbnail": pic,
            "webpage_url": f"https://www.bilibili.com/video/{bvid}" + (f"?p={args.page}" if args.page > 1 else ""),
            "extractor": "bilibili-browser-fallback",
            "playinfo_present": bool(playinfo),
        }
        if entries:
            info["entries"] = entries
        (meta_dir / f"{bvid}.info.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[ok] info.json: {meta_dir / (bvid + '.info.json')}")

        audio = pick_audio(playinfo) if args.want in ("audio", "both") else None
        video = pick_video(playinfo, args.max_height) if args.want in ("video", "both") else None

        if args.want in ("audio", "both") and (not audio or not audio.get("baseUrl")):
            print("[error] 没拿到音频流地址：可能未登录或视频需付费，加 --login 重试", flush=True)
            browser.close()
            return 2
        if args.want in ("video", "both") and (not video or not video.get("baseUrl")):
            print("[error] 没拿到视频流地址：可能未登录或视频需付费，加 --login 重试", flush=True)
            browser.close()
            return 2

        raw = None
        if audio and audio.get("baseUrl"):
            raw = audio_dir / f"{bvid}.m4a"
            size = browser_download(ctx, audio["baseUrl"], args.url, raw)
            print(f"[ok] 音频 {size / 1048576:.1f} MB ({audio.get('codecs')} {round((audio.get('bandwidth') or 0)/1000)}kbps) -> {raw}")

        if video and video.get("baseUrl"):
            vdir = out / "video"
            vfile = vdir / f"{bvid}.mp4"
            size = browser_download(ctx, video["baseUrl"], args.url, vfile)
            print(f"[ok] 视频 {size / 1048576:.1f} MB ({video.get('codecs')} {video.get('height')}p) -> {vfile}")

        browser.close()

    if raw is None:
        print(f"[next] 用帧脚本抽帧: bash scripts/frames_candidates.sh {out / 'video' / (bvid + '.mp4')} ...")
        return 0

    mp3 = audio_dir / f"{bvid}.mp3"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(raw), "-vn", "-c:a", "libmp3lame",
         "-q:a", "0", "-y", str(mp3)],
        check=True,
    )
    print(f"[ok] mp3: {mp3}")
    if not args.keep_m4a:
        raw.unlink(missing_ok=True)
    print(f"[next] python scripts/check_duration.py {mp3} {meta_dir / (bvid + '.info.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
