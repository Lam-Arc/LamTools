from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from lamtools_core.tool import ToolArtifact, ToolCall, ToolResult
from lamtools_core.tool.workspace import validate_workspace_path
from lamtools_core.tool.workspace_files import (
    DEFAULT_MAX_LIST_ITEMS,
    DEFAULT_MAX_SEARCH_RESULTS,
    DEFAULT_MAX_TEXT_LENGTH,
    WorkspaceReadOnlyTools,
)

from app.core.writer.file_tool_helpers import _infer_project_stack, _infer_test_commands
from app.core.writer.skills import WriterSkillRegistry

_DEFAULT_MAX_LIST_ITEMS = DEFAULT_MAX_LIST_ITEMS
_DEFAULT_MAX_TEXT_LENGTH = DEFAULT_MAX_TEXT_LENGTH
_DEFAULT_MAX_SEARCH_RESULTS = DEFAULT_MAX_SEARCH_RESULTS


class ReadOnlyToolExecutor(WorkspaceReadOnlyTools):
    """Writer read-only tools.

    Generic workspace file tools live in Core. Writer extends them with
    product-specific project inspection and skill loading.
    """

    def __init__(
        self,
        work_root: str | Path,
        *,
        max_list_items: int = _DEFAULT_MAX_LIST_ITEMS,
        max_text_length: int = _DEFAULT_MAX_TEXT_LENGTH,
        max_search_results: int = _DEFAULT_MAX_SEARCH_RESULTS,
    ) -> None:
        super().__init__(
            work_root,
            max_list_items=max_list_items,
            max_text_length=max_text_length,
            max_search_results=max_search_results,
        )
        self._skills = WriterSkillRegistry()
        self._loaded_skill_roots = self._resource_roots

    def as_dict(self) -> dict[str, Callable[[ToolCall], Awaitable[ToolResult]]]:
        base = super().as_dict()
        base["inspect_project"] = self.inspect_project
        base["load_skill"] = self.load_skill
        return base

    async def inspect_project(self, call: ToolCall) -> ToolResult:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        path_str = args.get("path") or "."
        max_files_raw = args.get("max_files") or 80
        try:
            max_files = max(10, min(int(max_files_raw), 200))
        except (TypeError, ValueError):
            max_files = 80

        try:
            root = validate_workspace_path(str(path_str), self._work_root)
        except ValueError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=str(exc))

        if not root.exists():
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Path not found: {path_str}")
        if root.is_file():
            root = root.parent

        skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", ".cache"}
        manifest_names = {
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "setup.py",
            "Cargo.toml",
            "go.mod",
            "pnpm-lock.yaml",
            "yarn.lock",
            "package-lock.json",
            "README.md",
            "AGENTS.md",
        }
        entries: list[Path] = []
        manifests: list[Path] = []
        try:
            for current, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".pytest")]
                current_path = Path(current)
                depth = len(current_path.relative_to(root).parts)
                if depth > 3:
                    dirs[:] = []
                    continue
                for fname in sorted(files):
                    path = current_path / fname
                    if fname in manifest_names:
                        manifests.append(path)
                    if len(entries) < max_files:
                        entries.append(path)
                if len(entries) >= max_files and manifests:
                    break
        except OSError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Inspect error: {exc}")

        def rel(path: Path) -> str:
            try:
                return path.relative_to(self._work_root).as_posix()
            except ValueError:
                return path.as_posix()

        lines = [f"Project: {rel(root)}"]
        if manifests:
            lines.append("Manifests:")
            for path in sorted(set(manifests), key=lambda p: rel(p))[:12]:
                lines.append(f"- {rel(path)}")
        else:
            lines.append("Manifests: none found")

        package_json = next((p for p in manifests if p.name == "package.json"), None)
        scripts_data: dict[str, str] = {}
        if package_json:
            try:
                data = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
                scripts = data.get("scripts") if isinstance(data, dict) else None
                if isinstance(scripts, dict) and scripts:
                    lines.append("Scripts:")
                    for name, command in list(scripts.items())[:8]:
                        scripts_data[str(name)] = str(command)
                        lines.append(f"- {name}: {command}")
            except (OSError, json.JSONDecodeError):
                pass

        lines.append(f"Files sampled ({len(entries)}):")
        for path in entries[:max_files]:
            lines.append(f"- {rel(path)}")
        if len(entries) >= max_files:
            lines.append(f"[truncated at {max_files} files]")

        file_samples = [rel(path) for path in entries[:max_files]]
        manifest_samples = [rel(path) for path in sorted(set(manifests), key=lambda p: rel(p))[:20]]
        likely_stack = _infer_project_stack(manifest_samples, file_samples)
        test_commands = _infer_test_commands(scripts_data)
        metadata = {
            "path": rel(root),
            "manifest_count": len(set(manifests)),
            "manifests": manifest_samples,
            "scripts": scripts_data,
            "test_commands": test_commands,
            "files_sampled": file_samples,
            "file_sample_count": len(file_samples),
            "truncated": len(entries) >= max_files,
            "likely_stack": likely_stack,
        }

        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="ok",
            content="\n".join(lines),
            metadata=metadata,
            artifacts=[
                ToolArtifact(
                    kind="project_inspection",
                    uri=rel(root),
                    content=metadata,
                    metadata={
                        "path": rel(root),
                        "manifest_count": len(set(manifests)),
                        "file_sample_count": len(file_samples),
                        "truncated": len(entries) >= max_files,
                    },
                )
            ],
        )

    async def load_skill(self, call: ToolCall) -> ToolResult:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        name = args.get("name", "")
        if not isinstance(name, str) or not name.strip():
            return ToolResult(call_id=call.id, name=call.name, status="failed", error="Missing 'name' argument")

        content = self._skills.load_prompt_content(self._work_root, name)
        found = not content.startswith(f'Skill "{name}" not found.')
        if found:
            skill = self._skills.get(self._work_root, name)
            if skill is not None:
                self.add_resource_root(skill.location.parent)
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="ok" if found else "failed",
            content=content,
            error="" if found else content,
            metadata={
                "skill": name.strip(),
                "found": found,
                "resource_roots": [path.as_posix() for path in self.resource_roots()],
            },
        )
