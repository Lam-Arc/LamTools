"""Pipeline checker tool: compare a host module with its replacement file.

user:“管道完整性的校验，对于那些插件开发者来说，甚至都可以开发一个插件来做”
+这里就是那颗插件：静态比对导出，不导入任何东西，报缺失和多出来的名字。
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

from lamtools_core.tool import ToolCall, ToolResult


def _declared_all(tree: ast.Module) -> set[str]:
    """Use an explicit ``__all__`` when the module has one."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            continue
        if isinstance(node.value, (ast.List, ast.Tuple)):
            return {
                element.value
                for element in node.value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
    return set()


def _defined_names(path: Path, *, include_private: bool) -> set[str]:
    """Top-level names a module exposes, read without executing it."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    declared = _declared_all(tree)
    if declared:
        return declared
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id != "__all__":
                    names.add(target.id)
    if not include_private:
        names = {name for name in names if not name.startswith("_")}
    return names


def _module_path(target: str) -> Path | None:
    try:
        spec = importlib.util.find_spec(target)
    except (ImportError, AttributeError, ValueError):
        return None
    origin = getattr(spec, "origin", None) if spec is not None else None
    return Path(origin) if origin and origin.endswith(".py") else None


async def check_exports(call: ToolCall) -> ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    target = str(args.get("target") or "").strip()
    replacement_raw = str(args.get("replacement") or "").strip()
    if not target or not replacement_raw:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="failed",
            error="target and replacement are required",
        )
    replacement = Path(replacement_raw).expanduser()
    if not replacement.is_file():
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="failed",
            error=f"replacement file is missing: {replacement}",
        )
    target_path = _module_path(target)
    if target_path is None or not target_path.is_file():
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="failed",
            error=f"cannot resolve host module source: {target}",
        )
    try:
        expected = _defined_names(target_path, include_private=False)
        actual = _defined_names(replacement, include_private=False)
    except SyntaxError as exc:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="failed",
            error=f"syntax error: {exc.msg} ({exc.filename}:{exc.lineno})",
        )
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    payload = {
        "target": target,
        "target_file": str(target_path),
        "replacement": str(replacement),
        "missing": missing,
        "extra": extra,
        "ok": not missing,
    }
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="ok" if not missing else "failed",
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        error="" if not missing else "replacement is missing exported names",
    )
