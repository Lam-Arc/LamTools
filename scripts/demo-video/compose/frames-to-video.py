"""Turn a take's captured frames into a watchable clip.

The screencast emits frames when the compositor produces them, so the timeline
is variable: each frame owns the time until the next one.  That timeline is
rebuilt here into a constant-frame-rate clip so the rest of the pipeline (and
any editor) sees normal video.

    py -3.14 scripts/demo-video/compose/frames-to-video.py --take E:/LamDemo/takes/smoke-replay
    ... --fps 60 --crf 16            # delivery quality
    ... --fps 30 --crf 23 --preview  # quick look
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def load_frames(take: Path) -> list[dict]:
    frames_json = take / "frames.json"
    if not frames_json.exists():
        raise FileNotFoundError(f"no frames.json in {take}")
    frames = json.loads(frames_json.read_text(encoding="utf-8"))
    if not frames:
        raise ValueError(f"{take} has no captured frames")
    return frames


def build_concat(take: Path, frames: list[dict], fps: float) -> Path:
    frames_dir = take / "frames"
    default_duration = 1.0 / fps
    lines: list[str] = []
    for index, frame in enumerate(frames):
        path = frames_dir / frame["file"]
        if not path.exists():
            raise FileNotFoundError(f"missing frame {path}")
        if index + 1 < len(frames):
            duration = max((frames[index + 1]["t"] - frame["t"]) / 1000.0, 1.0 / 240.0)
        else:
            duration = default_duration
        lines.append(f"file '{path.as_posix()}'")
        lines.append(f"duration {duration:.6f}")
    # The concat demuxer drops the final image unless it is repeated.
    lines.append(f"file '{(frames_dir / frames[-1]['file']).as_posix()}'")
    concat = take / "concat.txt"
    concat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return concat


def first_frame_size(frames_dir: Path, name: str) -> tuple[int, int]:
    import struct

    data = (frames_dir / name).read_bytes()
    offset = 2
    while offset < len(data) - 9:
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        length = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[offset + 5 : offset + 9])
            return width, height
        offset += 2 + length
    raise ValueError("could not read the frame size")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--take", required=True, help="take directory")
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument("--crf", type=int, default=16)
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--out", default="")
    parser.add_argument("--preview", action="store_true", help="fast, small encode")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if not shutil.which("ffmpeg"):
        print("ffmpeg not found on PATH", file=sys.stderr)
        return 2

    take = Path(args.take).resolve()
    frames = load_frames(take)
    concat = build_concat(take, frames, args.fps)

    width, height = first_frame_size(take / "frames", frames[0]["file"])
    duration = (frames[-1]["t"] - frames[0]["t"]) / 1000.0
    out = Path(args.out) if args.out else take / ("preview.mp4" if args.preview else "clip.mp4")

    crf = 23 if args.preview else args.crf
    preset = "veryfast" if args.preview else args.preset
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat),
        "-fps_mode",
        "cfr",
        "-r",
        str(args.fps),
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(out),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr[-4000:], file=sys.stderr)
        return result.returncode

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,nb_frames",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    info = json.loads(probe.stdout or "{}")
    stream = (info.get("streams") or [{}])[0]
    fmt = info.get("format") or {}
    size_mb = int(fmt.get("size", 0)) / 1e6
    if not args.quiet:
        print(
            f"{out.name}: {stream.get('width')}x{stream.get('height')} "
            f"{stream.get('r_frame_rate')} {stream.get('nb_frames')} frames "
            f"{float(fmt.get('duration', 0)):.2f}s {size_mb:.1f}MB "
            f"(source {len(frames)} frames over {duration:.2f}s, {width}x{height})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
