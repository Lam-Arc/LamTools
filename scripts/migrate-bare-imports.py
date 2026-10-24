"""One-shot migration: relative module imports -> `@/` bare specifiers.

user:“import map 只拦裸说明符”+把 ui/src 与 desktop/src 里指向 ui/src 的相对
导入改写成 `@/<路径>.<真实扩展名>`；CSS/静态资源保持相对。映射键必须与
构建期 importmap.base.json 的键一致（带扩展名、posix 路径）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

CORE = Path(__file__).resolve().parents[1] / "core"
UI_SRC = CORE / "ui" / "src"
DESKTOP_SRC = CORE / "desktop" / "src"

SKIP_SUFFIXES = {".css", ".scss", ".sass", ".less", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".woff", ".woff2", ".json"}
CODE_SUFFIXES = [".ts", ".tsx", ".vue", ".js", ".mjs"]

FROM_RE = re.compile(r"(\bfrom\s+)(['\"])(\.[^'\"]+)\2")
DYNAMIC_RE = re.compile(r"(\bimport\s*\(\s*)(['\"])(\.[^'\"]+)\2")
IMPORT_RE = re.compile(r"(\bimport\s+)(['\"])(\.[^'\"]+)\2")


def resolve_specifier(base_dir: Path, spec: str) -> Path | None:
    """Resolve a relative specifier to a real source file (with extension)."""
    cleaned = spec.split("?")[0].split("#")[0]
    candidate = (base_dir / cleaned).resolve()
    if candidate.suffix.lower() in SKIP_SUFFIXES:
        return None
    trials = [candidate]
    for ext in CODE_SUFFIXES:
        trials.append(Path(str(candidate) + ext))
    for ext in (".ts", ".vue"):
        trials.append(candidate / f"index{ext}")
    for trial in trials:
        if trial.is_file() and trial.suffix.lower() not in SKIP_SUFFIXES:
            return trial
    return None


def rewrite_file(path: Path, ui_root: Path) -> tuple[int, list[str]]:
    text = path.read_text(encoding="utf-8")
    changes = 0
    problems: list[str] = []

    def spec_key(base_dir: Path, spec: str) -> str:
        nonlocal changes
        target = resolve_specifier(base_dir, spec)
        if target is None:
            problems.append(spec)
            return spec
        try:
            rel = target.relative_to(ui_root).as_posix()
        except ValueError:
            # 不在 ui/src 下（desktop 内部相对引用）：保持原样。
            return spec
        changes += 1
        return f"@/{rel}"

    def sub_from(match: re.Match) -> str:
        prefix, quote, spec = match.group(1), match.group(2), match.group(3)
        return f"{prefix}{quote}{spec_key(path.parent, spec)}{quote}"

    def sub_dynamic(match: re.Match) -> str:
        prefix, quote, spec = match.group(1), match.group(2), match.group(3)
        return f"{prefix}{quote}{spec_key(path.parent, spec)}{quote}"

    def sub_import(match: re.Match) -> str:
        prefix, quote, spec = match.group(1), match.group(2), match.group(3)
        return f"{prefix}{quote}{spec_key(path.parent, spec)}{quote}"

    text = FROM_RE.sub(sub_from, text)
    text = DYNAMIC_RE.sub(sub_dynamic, text)
    text = IMPORT_RE.sub(sub_import, text)
    path.write_text(text, encoding="utf-8", newline="\n" if "\r\n" not in text else "\r\n")
    return changes, problems


def iter_sources(roots: list[Path]) -> Iterator[Path]:
    for root in roots:
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() in {".ts", ".tsx", ".vue"} and path.is_file():
                yield path


def main() -> None:
    total_changes = 0
    all_problems: list[tuple[Path, str]] = []
    files_changed = 0
    for path in iter_sources([UI_SRC, DESKTOP_SRC]):
        changes, problems = rewrite_file(path, UI_SRC)
        if changes:
            files_changed += 1
        total_changes += changes
        all_problems.extend((path, spec) for spec in problems)
    print(f"files changed: {files_changed}, specifiers rewritten: {total_changes}")
    if all_problems:
        print(f"unresolved specifiers ({len(all_problems)}):")
        for path, spec in all_problems[:40]:
            print(f"  {path.relative_to(CORE)}: {spec}")


if __name__ == "__main__":
    main()
