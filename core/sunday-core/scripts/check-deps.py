#!/usr/bin/env python3
"""Enforce the dependency rules of the new core.

Two checks:

1. Internal edges. Each crate may only depend on crates below it:
       protocol  (nothing)
       store     -> protocol
       platform  -> protocol
       tools     -> protocol, platform
       agent     -> protocol, store
       cli       -> anything internal
   A new edge must be added here first, which makes the decision visible.

2. Forbidden tokens. No core crate may mention a platform host or a foreign
   runtime. The cli is exempt from the process rule because it is a host.

Exit code is non-zero when anything is violated, so CI fails rather than warns.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CRATES = ROOT / "crates"

ALLOWED = {
    "sunday-protocol": set(),
    "sunday-store": {"sunday-protocol"},
    "sunday-platform": {"sunday-protocol"},
    "sunday-tools": {"sunday-protocol", "sunday-platform"},
    "sunday-extensions": {"sunday-protocol", "sunday-store", "sunday-agent"},
    "sunday-llm": {"sunday-protocol"},
    "sunday-context": {"sunday-protocol"},
    "sunday-agent": {"sunday-protocol", "sunday-store", "sunday-context"},
    "sunday-cli": {
        "sunday-protocol",
        "sunday-store",
        "sunday-platform",
        "sunday-agent",
        "sunday-tools",
        "sunday-llm",
        "sunday-context",
        "sunday-extensions",
    },
}

# Tokens that must never appear in a core crate.
FORBIDDEN = {
    "tauri": "the core must not know about the desktop shell",
    "jni": "the core must not know about Android",
    "lamtools_core": "the core must not read the Python tree",
    "pyo3": "the core must not host Python",
    "rusqlite::Connection::open_in_memory": "tests must use a real file, not a mock",
}

# Only these crates are hosts and may spawn processes.
HOST_CRATES = {"sunday-cli"}

# Crash tests must be able to kill a child process, so the process ban applies to
# production code only. Anything under `tests/` is exempt and reviewed by hand.
TEST_DIRS = {"tests"}


def crate_dirs() -> list[Path]:
    return sorted(p for p in CRATES.iterdir() if p.is_dir() and (p / "Cargo.toml").exists())


def internal_deps(name: str, cargo_toml: Path) -> set[str]:
    text = cargo_toml.read_text(encoding="utf-8")
    found = set()
    for dep in ALLOWED:
        if dep == name:
            continue
        # Matches `sunday-x.workspace = true` and `sunday-x = { path = ... }`
        if re.search(rf"^\s*{re.escape(dep)}\s*[.=]", text, re.MULTILINE):
            found.add(dep)
    return found


def check_edges() -> list[str]:
    problems = []
    for crate in crate_dirs():
        name = crate.name
        if name not in ALLOWED:
            problems.append(f"{name}: unknown crate, add it to the rule table")
            continue
        deps = internal_deps(name, crate / "Cargo.toml")
        unexpected = deps - ALLOWED[name]
        if unexpected:
            problems.append(
                f"{name}: depends on {sorted(unexpected)} but only {sorted(ALLOWED[name])} is allowed"
            )
    return problems


def check_tokens() -> list[str]:
    problems = []
    for crate in crate_dirs():
        name = crate.name
        for path in sorted(crate.rglob("*.rs")):
            if "target" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            rel = path.relative_to(ROOT).as_posix()
            for token, why in FORBIDDEN.items():
                if token in text:
                    problems.append(f"{rel}: contains `{token}` ({why})")
            in_tests = any(part in TEST_DIRS for part in path.parts)
            if (
                name not in HOST_CRATES
                and not in_tests
                and "std::process::Command" in text
            ):
                problems.append(f"{rel}: a core crate may not spawn processes")
    return problems


def main() -> int:
    edge_problems = check_edges()
    token_problems = check_tokens()

    for problem in edge_problems + token_problems:
        print(f"FAIL {problem}")

    if not edge_problems and not token_problems:
        print(f"ok {len(crate_dirs())} crates, edges and tokens clean")
        return 0

    print(f"\n{len(edge_problems) + len(token_problems)} problem(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
