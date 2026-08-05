from __future__ import annotations

from pathlib import Path


def _infer_project_stack(manifests: list[str], files: list[str]) -> list[str]:
    names = {Path(path).name.lower() for path in [*manifests, *files]}
    stack: list[str] = []
    if "package.json" in names:
        stack.append("node")
    if "vite.config.ts" in names or "vite.config.js" in names:
        stack.append("vite")
    if "tsconfig.json" in names:
        stack.append("typescript")
    if "pyproject.toml" in names or "requirements.txt" in names or "setup.py" in names:
        stack.append("python")
    if "cargo.toml" in names:
        stack.append("rust")
    if "go.mod" in names:
        stack.append("go")
    if "readme.md" in names:
        stack.append("docs")
    return stack or ["unknown"]


def _infer_test_commands(scripts: dict[str, str]) -> list[str]:
    commands: list[str] = []
    for name, command in scripts.items():
        lowered_name = name.lower()
        lowered_command = command.lower()
        if any(marker in lowered_name for marker in ("test", "check", "lint", "typecheck")):
            commands.append(f"npm run {name}")
        elif any(marker in lowered_command for marker in ("pytest", "vitest", "jest", "playwright", "vue-tsc")):
            commands.append(command)
    return commands[:8]
