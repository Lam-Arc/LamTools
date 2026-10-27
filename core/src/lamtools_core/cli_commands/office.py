"""Office document service commands, reports and stable exit codes."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any, Mapping


OFFICE_EXIT_SUCCESS = 0


OFFICE_EXIT_MANIFEST_MISMATCH = 2


OFFICE_EXIT_RENDER_FAILURE = 3


OFFICE_EXIT_LAYOUT_CONFLICT = 4


OFFICE_EXIT_DATA_MISMATCH = OFFICE_EXIT_MANIFEST_MISMATCH


OFFICE_EXIT_RENDER_UNAVAILABLE = OFFICE_EXIT_RENDER_FAILURE


def _office_jsonable(value: Any) -> Any:
    """Convert service reports and issue objects into JSON-safe values."""

    if hasattr(value, "as_dict") and callable(value.as_dict):
        return _office_jsonable(value.as_dict())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _office_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_office_jsonable(item) for item in value]
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return _office_jsonable(vars(value))
    # Dataclass values not exposing ``as_dict`` (for example a lightweight
    # mocked report in tests) are handled without importing dataclasses at
    # module import time.
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return _office_jsonable(asdict(value))
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value


def _office_issue_values(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    issues = payload.get("issues")
    if not isinstance(issues, list):
        return []
    return [item for item in issues if isinstance(item, Mapping)]


def _office_payload_exit_code(payload: Mapping[str, Any], *, action: str) -> int:
    """Map a report's stable status/issue fields to the CLI exit classes."""

    exit_class = str(payload.get("exit_class") or "").casefold()
    statuses = payload.get("statuses")
    statuses = statuses if isinstance(statuses, Mapping) else {}
    issue_codes = {
        str(item.get("code") or "").casefold() for item in _office_issue_values(payload)
    }

    # Layout conflicts are a separate automation concern even when the
    # service's report calls them a generic visual issue.
    if (
        "layout" in exit_class
        or "overlap" in exit_class
        or any("overlap" in code or "layout" in code for code in issue_codes)
    ):
        return OFFICE_EXIT_LAYOUT_CONFLICT

    if (
        str(statuses.get("data") or "").casefold() == "failed"
        or str(statuses.get("structure") or "").casefold() == "failed"
        or exit_class in {
            "manifest_mismatch",
            "data_mismatch",
            "structure_invalid",
            "manifest_invalid",
        }
        or any(
            marker in code
            for code in issue_codes
            for marker in ("manifest", "mismatch", "binding", "dataset", "source_hash")
        )
    ):
        return OFFICE_EXIT_MANIFEST_MISMATCH

    if (
        str(statuses.get("visual") or "").casefold() in {"failed", "unavailable"}
        or exit_class in {
            "visual_unavailable",
            "render_unavailable",
            "render_failure",
            "render_failed",
            "visual_issue",
        }
        or any(
            marker in code
            for code in issue_codes
            for marker in ("render", "visual", "backend", "conversion")
        )
    ):
        return OFFICE_EXIT_RENDER_FAILURE

    # Validation reports do not have a renderer status.  A non-OK result from
    # validation is therefore a manifest/data class by definition.
    if payload.get("ok") is False:
        return OFFICE_EXIT_MANIFEST_MISMATCH if action == "validate" else OFFICE_EXIT_RENDER_FAILURE
    return OFFICE_EXIT_SUCCESS


def _office_exception_payload(exc: BaseException, *, action: str) -> tuple[dict[str, Any], int]:
    name = type(exc).__name__.casefold()
    message = str(exc) or name
    lowered_message = message.casefold()
    if any(marker in name or marker in lowered_message for marker in ("layout", "overlap", "conflict")):
        code = OFFICE_EXIT_LAYOUT_CONFLICT
        exit_class = "layout_conflict"
    elif any(
        marker in name or marker in lowered_message
        for marker in ("manifest", "mismatch", "dataset", "binding", "structure")
    ):
        code = OFFICE_EXIT_MANIFEST_MISMATCH
        exit_class = "manifest_mismatch"
    else:
        code = OFFICE_EXIT_RENDER_FAILURE
        exit_class = "render_failure"
    return (
        {
            "ok": False,
            "exit_class": exit_class,
            "error": {"type": type(exc).__name__, "message": message},
        },
        code,
    )


def _office_usage_payload(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "exit_class": "usage_error",
        "error": {"type": "ArgumentError", "message": message},
    }


def _office_write_report(report_path: Path | None, payload: Mapping[str, Any]) -> None:
    if report_path is None:
        return
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _office_service_operation(action: str) -> Any:
    """Load the Office Skills companion runtime only when a command executes."""

    from lamtools_core.skill_runtime import builtin_core_skill_roots

    runtime_root: Path | None = None
    searched: list[str] = []
    for skill_root in builtin_core_skill_roots():
        candidates = (
            Path(skill_root) / "office-renderer" / "scripts",
            # Compatibility with pre-0.2 development bundles. Remove after
            # existing local installations have migrated to the standard
            # Skill layout.
            Path(skill_root) / "_shared" / "office_renderer",
        )
        for candidate in candidates:
            searched.append(str(candidate))
            if (candidate / "lamtools_office_renderer" / "__init__.py").is_file():
                runtime_root = candidate.resolve()
                break
        if runtime_root is not None:
            break
    if runtime_root is None:
        locations = ", ".join(searched) or "<no built-in skill roots>"
        raise RuntimeError(f"Office Skills renderer runtime was not found; searched: {locations}")

    runtime_path = str(runtime_root)
    if runtime_path not in sys.path:
        sys.path.insert(0, runtime_path)
        importlib.invalidate_caches()
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        module = importlib.import_module("lamtools_office_renderer")
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
    names = {
        "check": ("check_office", "check"),
        "validate": ("validate_office", "validate"),
        "render": ("render_office", "render"),
    }[action]
    for name in names:
        operation = getattr(module, name, None)
        if callable(operation):
            return operation
    raise RuntimeError(f"office {action} service is unavailable")


def _office_operation_kwargs(
    operation: Any,
    *,
    action: str,
    source: Path,
    manifest: Path,
    output_dir: Path | None,
    backend: str,
    timeout: float,
    dpi: int,
    report_path: Path | None,
) -> tuple[list[Any], dict[str, Any]]:
    """Adapt the CLI vocabulary to the service's evolving function signature."""

    try:
        signature = inspect.signature(operation)
        parameters = signature.parameters
    except (TypeError, ValueError):
        parameters = {}

    positional = [
        parameter
        for parameter in parameters.values()
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    accepts_var_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )
    args: list[Any] = []
    kwargs: dict[str, Any] = {}

    # The canonical service API takes manifest (and output_dir for render) as
    # leading positional values.  Keep keyword-only and test-double variants
    # working by falling back to aliases when those parameters are named.
    leading = [manifest] if action == "validate" else [manifest, output_dir]
    canonical_aliases = (
        ("manifest", ("manifest", "manifest_path", "manifest_file", "manifest_value")),
        ("output_dir", ("output_dir", "output", "destination", "destination_dir", "target_dir")),
    )
    consumed: set[str] = set()
    for index, value in enumerate(leading):
        if index < len(positional):
            args.append(value)
            consumed.add(positional[index].name)
            continue
        canonical, aliases = canonical_aliases[index]
        match = next((name for name in aliases if name in parameters), None)
        if match is not None:
            kwargs[match] = value
            consumed.add(match)
        elif accepts_var_kwargs:
            kwargs[canonical] = value

    option_values: tuple[tuple[str, tuple[str, ...], Any, bool], ...] = (
        ("source", ("source", "source_path", "input", "input_path"), source, True),
        ("backend", ("backend", "backend_name"), backend, action == "render"),
        ("timeout", ("timeout", "timeout_seconds", "render_timeout"), timeout, action == "render"),
        ("dpi", ("dpi", "resolution"), dpi, action == "render"),
        ("report_path", ("report_path", "report", "report_file"), report_path, report_path is not None),
    )
    for canonical, aliases, value, enabled in option_values:
        if not enabled:
            continue
        match = next((name for name in aliases if name in parameters and name not in consumed), None)
        if match is not None:
            kwargs[match] = value
        elif accepts_var_kwargs:
            kwargs[canonical] = value
    return args, kwargs


async def _invoke_office_service(
    *,
    action: str,
    source: Path,
    manifest: Path,
    output_dir: Path | None = None,
    backend: str = "auto",
    timeout: float = 120.0,
    dpi: int = 144,
    report_path: Path | None = None,
) -> Any:
    operation = _office_service_operation(action)
    args, kwargs = _office_operation_kwargs(
        operation,
        action=action,
        source=source,
        manifest=manifest,
        output_dir=output_dir,
        backend=backend,
        timeout=timeout,
        dpi=dpi,
        report_path=report_path,
    )
    result = operation(*args, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


def _office_paths(args: argparse.Namespace, *, require_output: bool) -> tuple[Path, Path, Path | None]:
    """Resolve positional and option aliases accepted by the Office CLI."""

    source_option = (
        getattr(args, "source_path", None)
        or getattr(args, "input_path", None)
        or getattr(args, "source", None)
        or getattr(args, "input", None)
    )
    manifest_option = getattr(args, "manifest_path", None) or getattr(args, "manifest", None)
    output_option = (
        getattr(args, "output_dir_path", None)
        or getattr(args, "output_dir", None)
        or getattr(args, "output", None)
    )
    positionals = [
        value
        for value in (
            getattr(args, "source_pos", None),
            getattr(args, "manifest_pos", None),
            getattr(args, "output_pos", None),
        )
        if value is not None
    ]
    if source_option and manifest_option:
        source_value = source_option
        manifest_value = manifest_option
        # With both named paths present argparse still assigns any trailing
        # positional values to ``source_pos``/``manifest_pos``.  The final
        # value is therefore the only sensible positional output directory.
        output_value = output_option or (positionals[-1] if positionals else None)
    elif source_option:
        source_value = source_option
        manifest_value = manifest_option or (positionals[0] if positionals else None)
        output_value = output_option or (positionals[1] if len(positionals) > 1 else None)
    elif manifest_option:
        source_value = positionals[0] if positionals else None
        manifest_value = manifest_option
        output_value = output_option or (positionals[1] if len(positionals) > 1 else None)
    else:
        source_value = positionals[0] if positionals else None
        manifest_value = positionals[1] if len(positionals) > 1 else None
        output_value = output_option or (positionals[2] if len(positionals) > 2 else None)
    if not source_value or not manifest_value or (require_output and not output_value):
        expected = "source/input, manifest, and output directory" if require_output else "source/input and manifest"
        raise ValueError(f"office {getattr(args, 'office_command', 'command')} requires {expected}")
    return Path(source_value), Path(manifest_value), Path(output_value) if output_value else None


async def _cmd_office(args: argparse.Namespace, *, action: str) -> int:
    try:
        source, manifest, output_dir = _office_paths(args, require_output=action == "render")
    except (TypeError, ValueError) as exc:
        payload, code = _office_usage_payload(str(exc)), 1
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return code
    report_path_value = getattr(args, "report_path", None)
    report_path = Path(report_path_value) if report_path_value else None
    try:
        result = await _invoke_office_service(
            action=action,
            source=source,
            manifest=manifest,
            output_dir=output_dir,
            backend=str(getattr(args, "backend", "auto") or "auto"),
            timeout=float(getattr(args, "timeout", 120.0)),
            dpi=int(getattr(args, "dpi", 144)),
            report_path=report_path,
        )
        payload = _office_jsonable(result)
        if not isinstance(payload, dict):
            payload = {"ok": True, "result": payload}
        _office_write_report(report_path, payload)
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return _office_payload_exit_code(payload, action=action)
    except Exception as exc:  # service failures become stable JSON classes
        payload, code = _office_exception_payload(exc, action=action)
        try:
            _office_write_report(report_path, payload)
        except OSError:
            # Preserve the renderer's stable exit class when an optional
            # report path itself is not writable.
            pass
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return code


async def cmd_office_validate(args: argparse.Namespace) -> int:
    return await _cmd_office(args, action="validate")


async def cmd_office_render(args: argparse.Namespace) -> int:
    return await _cmd_office(args, action="render")


async def cmd_office_check(args: argparse.Namespace) -> int:
    report_path_value = getattr(args, "report_path", None)
    report_path = Path(report_path_value) if report_path_value else None
    try:
        operation = _office_service_operation("check")
        result = operation(
            backend=str(getattr(args, "backend", "auto") or "auto"),
            timeout=float(getattr(args, "timeout", 15.0)),
        )
        if inspect.isawaitable(result):
            result = await result
        payload = _office_jsonable(result)
        if not isinstance(payload, dict):
            raise TypeError("Office readiness check returned a non-object report")
        code = OFFICE_EXIT_SUCCESS if payload.get("ok") is True else OFFICE_EXIT_RENDER_FAILURE
    except Exception as exc:
        payload, code = _office_exception_payload(exc, action="render")
        payload.update(
            {
                "message": "Office 应用未就绪 · Test Passed 0/3",
                "passed": 0,
                "total": 3,
            }
        )
    try:
        _office_write_report(report_path, payload)
    except OSError:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    print(str(payload.get("message") or "Office 应用未就绪 · Test Passed 0/3"), flush=True)
    if code != OFFICE_EXIT_SUCCESS:
        print(json.dumps(payload, ensure_ascii=False), flush=True)
    return code
