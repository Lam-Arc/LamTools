#!/usr/bin/env python3
"""转写音频并做阶段门 3 校验：最后一个 segment 的结束时间要和音频时长接近。

模型规则：中文用 turbo（large-v3-turbo），英文用 small.en（英文转写后再由模型翻成中文）。

用法:
    python transcribe.py --audio out/audio/BV1xx.mp3 --lang zh --outdir out/transcript
    python transcribe.py --audio out/audio/BV1xx.mp3 --lang en --outdir out/transcript
    python transcribe.py --check-only out/transcript/BV1xx.segments.json
可选:
    --model 覆盖默认模型, --engine auto|faster-whisper|whisper, --device auto|cpu|cuda,
    --compute-type int8, --tol 0.05, --json-out 校验结果路径
产出:
    <stem>.segments.json  {audio, lang, model, duration, segments:[{start,end,text}]}
    <stem>.srt / <stem>.txt
退出码:
    0 通过, 2 转写尾部与音频时长差异过大, 3 依赖缺失或读取失败
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_MODEL = {"zh": "turbo", "en": "small.en"}


def have(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def ffprobe_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return float(out)
    except Exception:  # noqa: BLE001
        return None


def fmt_ts(sec: float, comma: bool = False) -> str:
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    sep = "," if comma else "."
    return f"{h:02d}:{m:02d}:{int(s):02d}{sep}{int(round((s - int(s)) * 1000)):03d}"


def transcribe_faster(audio: Path, model: str, lang: str, device: str, compute: str) -> list[dict]:
    from faster_whisper import WhisperModel  # type: ignore

    kw = {"device": device, "compute_type": compute}
    if device == "auto":
        kw = {"device": "auto", "compute_type": "default"}
    m = WhisperModel(model, **kw)
    segments, info = m.transcribe(str(audio), language=lang, vad_filter=True, beam_size=5)
    out = []
    for seg in segments:
        out.append({"start": round(seg.start, 3), "end": round(seg.end, 3), "text": (seg.text or "").strip()})
        print(f"\r[transcribe] {fmt_ts(seg.end)}", end="", file=sys.stderr, flush=True)
    print("", file=sys.stderr)
    print(f"[info] 检测语言={getattr(info, 'language', lang)} 时长={getattr(info, 'duration', '?')}", file=sys.stderr)
    return out


def transcribe_openai(audio: Path, model: str, lang: str, device: str, compute: str) -> list[dict]:
    import whisper  # type: ignore

    m = whisper.load_model(model, device=None if device == "auto" else device)
    res = m.transcribe(str(audio), language=lang, verbose=False)
    return [
        {"start": round(s["start"], 3), "end": round(s["end"], 3), "text": s["text"].strip()}
        for s in res.get("segments", [])
    ]


def validate(audio_duration: float | None, segments: list[dict], tol: float) -> dict:
    if not segments:
        return {"verdict": "fail", "note": "没有任何 segment"}
    last_end = float(segments[-1]["end"])
    if audio_duration is None:
        return {"verdict": "unknown", "last_segment_end": last_end, "note": "没有音频时长可对比"}
    diff = abs(audio_duration - last_end)
    ratio = diff / audio_duration if audio_duration else 0.0
    ok = ratio <= tol or diff <= 10.0
    return {
        "verdict": "pass" if ok else "fail",
        "last_segment_end": last_end,
        "audio_duration": audio_duration,
        "diff_seconds": round(diff, 3),
        "diff_ratio": round(ratio, 5),
        "tol": tol,
        "note": "" if ok else "转写疑似被截断，重跑或分段转写",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", default="")
    ap.add_argument("--lang", default="zh", choices=["zh", "en"])
    ap.add_argument("--model", default="")
    ap.add_argument("--engine", default="auto", choices=["auto", "faster-whisper", "whisper"])
    ap.add_argument("--device", default="auto")
    ap.add_argument("--compute-type", default="int8")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--tol", type=float, default=0.05)
    ap.add_argument("--json-out", default="")
    ap.add_argument("--check-only", default="", help="只复检已有 segments.json")
    args = ap.parse_args()

    # 复检模式
    if args.check_only:
        p = Path(args.check_only)
        data = json.loads(p.read_text(encoding="utf-8"))
        audio = Path(data.get("audio") or "")
        dur = ffprobe_duration(audio) if audio.is_file() else data.get("duration")
        res = validate(dur, data.get("segments", []), args.tol)
        warn = validate(dur, data.get("segments", []), 0.005)
        res["strict_ratio"] = warn.get("diff_ratio")
        print(json.dumps(res, ensure_ascii=False, indent=2))
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if res["verdict"] == "pass" else 2

    if not args.audio:
        print("[error] 需要 --audio 或 --check-only", file=sys.stderr)
        return 3
    audio = Path(args.audio)
    if not audio.is_file():
        print(f"[error] 找不到音频: {audio}", file=sys.stderr)
        return 3

    model = args.model or DEFAULT_MODEL[args.lang]
    engine = args.engine
    if engine == "auto":
        if have("faster_whisper"):
            engine = "faster-whisper"
        elif have("whisper"):
            engine = "whisper"
        else:
            print(
                "[error] 没装转写引擎：pip install faster-whisper（推荐）或 openai-whisper\n"
                "        Python 太新装不上轮子时，建 3.12 虚拟环境再装",
                file=sys.stderr,
            )
            return 3

    print(f"[info] engine={engine} model={model} lang={args.lang}", file=sys.stderr)
    if engine == "faster-whisper":
        segments = transcribe_faster(audio, model, args.lang, args.device, args.compute_type)
    else:
        segments = transcribe_openai(audio, model, args.lang, args.device, args.compute_type)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = audio.stem
    duration = ffprobe_duration(audio)

    payload = {
        "audio": str(audio),
        "lang": args.lang,
        "model": model,
        "engine": engine,
        "duration": duration,
        "segments": segments,
    }
    (outdir / f"{stem}.segments.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (outdir / f"{stem}.txt").write_text("\n".join(s["text"] for s in segments) + "\n", encoding="utf-8")
    srt = []
    for i, s in enumerate(segments, 1):
        srt.append(f"{i}\n{fmt_ts(s['start'], True)} --> {fmt_ts(s['end'], True)}\n{s['text']}\n")
    (outdir / f"{stem}.srt").write_text("\n".join(srt), encoding="utf-8")

    res = validate(duration, segments, args.tol)
    res["segments"] = len(segments)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    if res["verdict"] == "fail":
        print("[gate] 失败：最后一段结束时间与音频时长差得太多", file=sys.stderr)
        return 2
    print("[gate] 通过", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
