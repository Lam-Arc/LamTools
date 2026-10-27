"""Process lifecycle, shell environment and script value conversion."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from .models import WorkflowNode


_VAR_TOKEN_RE = re.compile(r"\$(?:\{(?P<braced>\w+)\}|(?P<plain>\w+))")


def _substitute_env_vars(command: str, substitutions: dict[str, str]) -> str:
    """Replace ${VAR} and $VAR tokens in ``command`` with the given values.

    Shell-agnostic: Windows cmd.exe does not expand ``$VAR``, so we substitute
    the known INPUT_<PORT> variables ourselves before handing the command to the
    shell. Unknown ``$tokens`` are left untouched.
    """
    if not substitutions or not command:
        return command

    def _replace(match: re.Match[str]) -> str:
        name = match.group("braced") or match.group("plain")
        value = substitutions.get(name)
        if value is None:
            return match.group(0)
        return value

    return _VAR_TOKEN_RE.sub(_replace, command)


_PYTHON3_SHIM_DIR: str | None = None


def _python3_shim_dir() -> str | None:
    """Return a PATH dir mapping ``python3`` → the real interpreter on Windows.

    On a python.org install, ``python3`` is the Microsoft Store redirect stub
    (exits non-zero / pops the Store). We drop two tiny wrappers (``python3``
    and ``python3.exe``) into a temp dir and let callers prepend it to PATH so
    model-written ``python3 ...`` commands run. The wrappers exec
    ``sys.executable`` (the host's own interpreter), preserving argv. No-op on
    POSIX, where ``python3`` is the correct native name. Cached per process.
    """
    global _PYTHON3_SHIM_DIR
    if sys.platform != "win32":
        return None
    if _PYTHON3_SHIM_DIR is not None:
        return _PYTHON3_SHIM_DIR
    interpreter = sys.executable
    if not interpreter:
        return None
    # Bare wrapper (no extension) for sh/git-bash; .exe wrapper for cmd-style
    # resolution. Both exec the real interpreter, passing argv through.
    wrapper = (
        "#!/bin/sh\n"
        f'exec "{interpreter}" "$@"\n'
    )
    try:
        d = tempfile.mkdtemp(prefix="lamtools_py3shim_")
        Path(d, "python3").write_text(wrapper, encoding="utf-8")
        # Git Bash needs the bare script executable; mark it on POSIX.
        try:
            os.chmod(Path(d, "python3").as_posix(), 0o755)
        except OSError:
            pass
        # .exe not strictly required under bash (it finds the bare script),
        # but write a Windows-batch echo-through so direct .exe lookups resolve.
        Path(d, "python3.bat").write_text(
            f'@"{interpreter}" %*\r\n', encoding="utf-8"
        )
        _PYTHON3_SHIM_DIR = d
        return d
    except OSError:
        return None


async def _create_workflow_process(
    argv: list[str],
    *,
    cwd: str,
    env: dict[str, str],
) -> asyncio.subprocess.Process:
    """Start a node process in its own group so cancellation reaches children."""
    kwargs: dict[str, Any] = {
        "cwd": cwd,
        "env": env,
        "stdin": asyncio.subprocess.PIPE,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    return await asyncio.create_subprocess_exec(*argv, **kwargs)


async def _terminate_workflow_process(proc: asyncio.subprocess.Process) -> None:
    """Terminate a command/script process tree and drain its pipes."""
    from .runner_signals import signal
    if proc.returncode is None:
        if sys.platform == "win32" and getattr(proc, "pid", None):
            try:
                killer = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/PID",
                    str(proc.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await killer.communicate()
            except (OSError, ValueError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        else:
            try:
                # ``start_new_session=True`` gives the command its own process
                # group.  Killing only the shell would leave descendants such
                # as ``sleep``/``python`` alive after a cancelled workflow.
                if getattr(proc, "pid", None):
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except ProcessLookupError:
                pass
            except OSError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
    try:
        await asyncio.wait_for(proc.communicate(), timeout=2.0)
    except (asyncio.TimeoutError, ProcessLookupError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


def _read_hash(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _write_runner(runner_path: Path, user_file: Path, out_port_names: list[str]) -> None:
    """Write the binder runner that turns port-names-as-variables into JSON.

    Binds stdin inputs as locals, execs the user file (stray stdout captured so
    it can't corrupt the emitted JSON), then prints a JSON object mapping each
    output-port name to the value bound to that name in the user's namespace.
    Overwritten each run so out_port_names stay current with the node config.
    """
    import json as _json

    src_repr = repr(str(user_file))
    names_repr = repr(out_port_names)
    runner = (
        "import json, sys, io\n"
        "_IN = json.load(sys.stdin) if not sys.stdin.isatty() else {}\n"
        "_NS = dict(_IN); _NS.setdefault('__name__', '__main__')\n"
        "_buf = io.StringIO(); _real = sys.stdout; sys.stdout = _buf\n"
        "try:\n"
        f"    with open({src_repr}, 'r', encoding='utf-8') as _f:\n"
        f"        exec(compile(_f.read(), {src_repr}, 'exec'), _NS)\n"
        "finally:\n"
        "    sys.stdout = _real\n"
        f"_OUT = {{p: _NS.get(p) for p in {names_repr}}}\n"
        "print(json.dumps(_OUT, default=str))\n"
    )
    runner_path.write_text(runner, encoding="utf-8")


def _ports_to_io(node: WorkflowNode) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a node's ports into ``inputs[]``/``outputs[]`` dicts for storage."""
    inputs: list[dict[str, Any]] = []
    for p in node.input_ports():
        entry: dict[str, Any] = {"name": p.name, "type": p.type, "description": p.description}
        if p.lazy:
            entry["lazy"] = True
        inputs.append(entry)
    outputs: list[dict[str, Any]] = []
    for p in node.output_ports():
        entry: dict[str, Any] = {"name": p.name, "type": p.type, "description": p.description}
        if p.value is not None:
            entry["value"] = p.value
        outputs.append(entry)
    return inputs, outputs


def _normalise_type(type_name: str) -> str:
    from .runner_validation import _WORKFLOW_TYPES
    t = (type_name or "any").strip().lower()
    aliases = {"text": "string", "str": "string", "int": "number", "integer": "number", "float": "number", "bool": "boolean", "dict": "object", "list": "array"}
    return aliases.get(t, t) if t in aliases or t in _WORKFLOW_TYPES else "any"


def _types_compatible(src: str, dst: str) -> bool:
    """True when a value of type ``src`` may flow into a port of type ``dst``.

    Same type, either side ``any``, or number/boolean -> string are accepted.
    """
    s = _normalise_type(src)
    d = _normalise_type(dst)
    if s == "any" or d == "any" or s == d:
        return True
    if s in {"number", "boolean"} and d == "string":
        return True
    return False


def _coerce_value(value: Any, target_type: str) -> Any:
    """Best-effort coercion of a value to ``target_type``; failures keep the
    original value (runtime never aborts on coercion). Sentinels pass through."""
    from .runner_graph import SKIP_SENTINEL
    if value is None or value == SKIP_SENTINEL:
        return value
    t = _normalise_type(target_type)
    if t == "any":
        return value
    try:
        if t == "string":
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        if t == "number":
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return value
            return float(value)
        if t == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                low = value.strip().lower()
                if low in {"true", "1", "yes", "y"}:
                    return True
                if low in {"false", "0", "no", "n", ""}:
                    return False
            return bool(value)
        if t in {"object", "array"}:
            if isinstance(value, (dict, list)):
                return value
            return json.loads(value)
    except (TypeError, ValueError):
        return value
    return value


def _json_object(content: str) -> dict[str, Any] | None:
    """Parse a JSON object from model/shell output, tolerating ```json fences."""
    candidate = (content or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    try:
        value = json.loads(candidate)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _response_content(response: Any) -> str:
    """Extract provider-neutral text from modern and legacy model responses."""
    from .runner_values import _summarize
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        value = response.get("content", response.get("text", ""))
        return value if isinstance(value, str) else _summarize(value)
    value = getattr(response, "content", None)
    if value is None:
        value = getattr(response, "text", "")
    return value if isinstance(value, str) else _summarize(value)
