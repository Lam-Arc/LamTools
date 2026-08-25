"""Deterministic checks for paper-facing text and figure-caption consistency."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ZH = ROOT / "docs" / "paper" / "lamtools-technical-paper-zh.md"
EN = ROOT / "docs" / "paper" / "lamtools-technical-paper.md"


def captions(path: Path) -> list[str]:
    return re.findall(r"!\[(.*?)\]\([^)]*\)", path.read_text(encoding="utf-8"))


def main() -> int:
    zh_caps = captions(ZH)
    en_caps = captions(EN)
    errors: list[str] = []
    if len(zh_caps) != 4 or len(en_caps) != 4:
        errors.append(f"expected 4 captions per language; zh={len(zh_caps)}, en={len(en_caps)}")
    for caption in zh_caps:
        if not caption.endswith("。"):
            errors.append(f"zh caption does not end with Chinese full stop: {caption}")
        if caption.endswith("."):
            errors.append(f"zh caption ends with ASCII period: {caption}")
    for caption in en_caps:
        if not caption.endswith("."):
            errors.append(f"en caption does not end with ASCII period: {caption}")
        if "。" in caption:
            errors.append(f"en caption contains Chinese full stop: {caption}")
    joined = (ZH.read_text(encoding="utf-8") + EN.read_text(encoding="utf-8"))
    for forbidden in (
        "21071",
        "21.1 ms",
        "1.5 ms",
        "6.5 ms",
        "4.3 times",
        "4.3 倍",
        "5.0 ms",
        "modelcontextprotocol.com",
    ):
        if forbidden in joined:
            errors.append(f"forbidden stale text: {forbidden}")
    for required in (
        "deepseek-v4-flash",
        "mimo-v2.5",
        "/chat/completions",
        "0.071",
        "0.143",
        "0.096",
        "1.75",
        "6.67",
        "retrieval-derived-v0.2.6",
        "Any-gold",
        "任一黄金文档",
    ):
        if required not in joined:
            errors.append(f"missing required paper evidence: {required}")
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"PASS: {len(zh_caps)} Chinese and {len(en_caps)} English captions; evidence text consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
