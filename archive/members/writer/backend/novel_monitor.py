#!/usr/bin/env python3
"""Novel progress monitor — reads state from disk, displays live dashboard.

Usage:
  python novel_monitor.py                    # monitor current OUTPUT_DIR
  python novel_monitor.py --dir ../other     # monitor another directory

The generation process writes to novel_output/ independently.
This monitor reads the files and displays progress.
"""

import json
import os
import sys
import time
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "novel_output"

def clear():
    os.system("cls" if os.name == "nt" else "clear")

def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}m{s}s"

def load_state():
    state_file = OUTPUT_DIR / "state_latest.json"
    if not state_file.exists():
        return None
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

def load_metrics():
    report_file = OUTPUT_DIR / "report.json"
    if not report_file.exists():
        return None
    try:
        return json.loads(report_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

def count_chapters():
    return len(list(OUTPUT_DIR.glob("chapter_*.txt")))

def total_words():
    total = 0
    for f in OUTPUT_DIR.glob("chapter_*.txt"):
        total += f.stat().st_size
    return total

def main():
    print("  LamWriter Novel Monitor")
    print("  Watching:", OUTPUT_DIR)
    print()

    last_count = 0
    start_time = time.time()
    
    try:
        while True:
            clear()
            chapters = count_chapters()
            words = total_words()
            state = load_state()
            metrics = load_metrics()
            elapsed = time.time() - start_time

            # Header
            print(f"  LamWriter Novel Monitor  |  {format_duration(elapsed)} elapsed")
            print("  " + "─" * 55)

            # Chapter progress
            bar_width = 30
            if metrics and metrics.get("total_chapters"):
                total_ch = metrics["total_chapters"]
                filled = int(chapters / max(total_ch, 1) * bar_width)
            else:
                total_ch = "?"
                filled = min(chapters, bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)
            print(f"  Chapters:  [{bar}]  {chapters}/{total_ch}")
            print(f"  Words:     {words:>10,}  (~{words//3:,} chars)")
            if chapters > 0:
                avg = words // chapters
                print(f"  Avg/ch:    {avg:>10,} chars")

            # State
            if state:
                ch = state.get("current_chapter", 0)
                saved = state.get("saved_at", "")[:19]
                print(f"  State:     ch{ch} saved @ {saved}")

            # Metrics
            if metrics:
                style = metrics.get("style_score", 0)
                cont = metrics.get("continuity_score", 0)
                fs = metrics.get("foreshadow_score", 0)
                unified = metrics.get("unified_score", 0)
                verdict = metrics.get("verdict", "?")
                print(f"  Style:     {style:.3f}  |  Continuity: {cont:.3f}  |  FS: {fs:.3f}")
                print(f"  Score:     {unified:.3f}  [{verdict}]")

            # Recent chapters
            if metrics and metrics.get("chapter_metrics"):
                recent = metrics["chapter_metrics"][-10:]
                if recent:
                    print()
                    print("  Recent:")
                    for m in recent:
                        ch = m["chapter"]
                        w = m["word_count"]
                        d = m["drift_score"]
                        r = m["review_quality"]
                        flag = "⚠" if m.get("drift_exceeded") else " "
                        print(f"    Ch{ch:3d}  w={w:5d}  d={d:.2f}{flag}  r={r:.2f}")

            # Footer
            print()
            if chapters == 0:
                print("  Waiting for generation to start...")
            elif state is None:
                print("  Chapters being generated (no state yet)...")
            elif chapters >= (total_ch if isinstance(total_ch, int) else 999):
                print("  ✓ ALL CHAPTERS COMPLETE!")
            else:
                speed = (chapters - last_count) / max(elapsed, 1) * 60 if chapters > last_count else 0
                if speed > 0:
                    remaining = (total_ch - chapters) if isinstance(total_ch, int) else 50 - chapters
                    eta = remaining / max(speed, 0.01) if isinstance(total_ch, int) else "?"
                    print(f"  Speed: {speed:.1f} ch/min  |  ETA: {eta if isinstance(eta, str) else format_duration(eta*60)}")

            last_count = chapters
            print()
            print("  Ctrl+C to exit")
            time.sleep(3)

    except KeyboardInterrupt:
        print("\n  Monitor stopped.")
        sys.exit(0)

if __name__ == "__main__":
    if "--dir" in sys.argv:
        idx = sys.argv.index("--dir")
        OUTPUT_DIR = Path(sys.argv[idx + 1]).resolve()
    main()
