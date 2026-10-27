"""Permission-gated command and script node execution."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any
from lamtools_core.config.network import subprocess_env
from .models import WorkflowNode
from .runner_context import WorkflowExecutionContext


async def _execute_command(
    runner, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str,
    execution_context: WorkflowExecutionContext | None = None,
) -> dict[str, Any]:
    """command node: run a shell command (invoke CLI tools).

    Uses the same persisted shell resolution as run_command on Windows,
    feeds bound inputs as stdin JSON + INPUT_<PORT> env vars, and splits
    JSON stdout to same-named output ports (else whole stdout to default).
    """
    await runner._check_execution_permission(
        str(node.config.get("command") or ""),
        work_root=work_root,
        node=node,
        execution_context=execution_context,
    )
    raw = await runner._run_command(node.config, bound_inputs, work_root)
    return runner._split_or_fallback(node, raw)


async def _run_command(
    runner, cfg: dict[str, Any], bound_inputs: dict[str, Any], work_root: str
) -> str:
    from .runner_process import _create_workflow_process, _python3_shim_dir, _substitute_env_vars, _terminate_workflow_process
    from .runner_values import _as_float
    command = str(cfg.get("command") or "")
    if not command:
        raise ValueError("command node requires config.command")
    cwd = str(cfg.get("cwd") or work_root or ".")
    env = subprocess_env()
    extra_env = cfg.get("env") or {}
    # Preserve declaration order when generating WSLENV: explicit node
    # environment entries first, followed by bound workflow inputs.
    forward_env_names: list[str] = []
    if isinstance(extra_env, dict):
        custom_env = {str(k): str(v) for k, v in extra_env.items()}
        env.update(custom_env)
        forward_env_names.extend(custom_env)
    # Bind inputs as INPUT_<PORTNAME> env vars AND substitute ${VAR}/$VAR
    # tokens in the command ourselves — Windows cmd.exe does not expand
    # $VAR, so relying on the shell would break portability.
    substitutions: dict[str, str] = {}
    for name, value in bound_inputs.items():
        if value is None:
            continue
        env_name = f"INPUT_{name.upper()}"
        env[env_name] = str(value)
        forward_env_names.append(env_name)
        substitutions[env_name] = str(value)
    command = _substitute_env_vars(command, substitutions)
    timeout = _as_float(cfg.get("timeout"), default=60.0)
    # Feed bound inputs as a JSON object on stdin ({port:val}) so a command
    # that wants structured input can read it; INPUT_<PORT> env vars + ${VAR}
    # substitution are a convenience for shells that prefer them.
    stdin_payload = json.dumps({"inputs": bound_inputs}, ensure_ascii=False, default=str).encode("utf-8")
    # Run through the same shell preference as run_command on Windows
    # (auto: WSL, Git Bash, then Windows PowerShell), so command nodes behave
    # identically to the rest of the product. create_subprocess_shell would
    # otherwise fall back to COMSPEC (cmd.exe) on Windows, breaking bash
    # syntax (single quotes, pipes) the model may write.
    argv: list[str]
    if sys.platform == "win32":
        from lamtools_core.tool.command_runner import resolve_command_shell

        shell = resolve_command_shell()
        argv = shell.argv_for(command, cwd=cwd)
        env = shell.prepare_environment(env, forward_names=forward_env_names) or env
        # On a python.org install of Windows, `python3` resolves to the
        # Microsoft Store redirect stub (exits non-zero / opens Store).
        # Prepend a shim directory mapping python3 → the real interpreter
        # so model-written `python3 ...` commands actually run. This is a
        # platform-defect workaround, not behaviour fabrication.
        shim_dir = None if shell.kind == "wsl" else _python3_shim_dir()
        if shim_dir is not None:
            env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")
    else:
        argv = ["sh", "-lc", command]
    proc = await _create_workflow_process(
        argv,
        cwd=cwd,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(stdin_payload), timeout=timeout)
    except asyncio.TimeoutError:
        await _terminate_workflow_process(proc)
        raise RuntimeError(f"shell command timed out after {timeout}s")
    except asyncio.CancelledError:
        await _terminate_workflow_process(proc)
        raise
    text_out = stdout.decode("utf-8", errors="replace") if stdout else ""
    text_err = stderr.decode("utf-8", errors="replace") if stderr else ""
    if proc.returncode != 0:
        raise RuntimeError(
            f"shell command exited with code {proc.returncode}\nstderr:\n{text_err}"
        )
    return text_out.strip()


async def _execute_script(
    runner, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str,
    execution_context: WorkflowExecutionContext | None = None,
) -> dict[str, Any]:
    """script node: Python binder. Runs the script via a generated runner
    that binds input-port names as locals and reads output-port names back;
    stdout JSON flows through _split_or_fallback to the output ports.
    """
    await runner._check_execution_permission(
        str(node.config.get("script") or ""),
        work_root=work_root,
        node=node,
        execution_context=execution_context,
    )
    raw = await runner._run_script(node, node.config, bound_inputs, work_root)
    return runner._split_or_fallback(node, raw)


async def _run_script(
    runner, node: WorkflowNode, cfg: dict[str, Any], bound_inputs: dict[str, Any], work_root: str
) -> str:
    """Python binder: input/output PORT NAMES are program variables.

    The user's ``config.script`` is plain Python. Input-port names are
    available as variables (node ``IN x`` → ``x`` in code); assigning to an
    output-port name produces that output (``OUT y`` → ``y = ...``). No
    stdin parsing, no print, no JSON, no shell, no quoting — the model just
    writes ``y = x * 2``.

    Implementation: persist the user source to a real file under
    ``work_root/.lam/workflow_scripts/<nodeId>.py`` (config.script is the
    source of truth; rewritten only when its content hash changes), then
    run a generated ``<nodeId>.runner.py`` via ``sys.executable`` as an
    isolated subprocess. The runner binds inputs as locals, execs the user
    file (redirecting stray prints so they don't corrupt the output JSON),
    then prints a JSON object mapping each output-port name to its bound
    value. That stdout flows through ``_split_or_fallback`` unchanged.
    """
    from .runner_process import _create_workflow_process, _read_hash, _terminate_workflow_process, _write_runner
    from .runner_values import _as_float
    import hashlib

    script = str(cfg.get("script") or "")
    if not script:
        raise ValueError("script node requires config.script")

    scripts_dir = Path(work_root or ".") / ".lam" / "workflow_scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(c if c.isalnum() or c in {"-", "_"} else "_" for c in (node.id or "node")).strip("_") or "node"
    src_path = scripts_dir / f"{safe_id}.py"
    runner_path = scripts_dir / f"{safe_id}.runner.py"

    # Persist user source (rewrite only on content change).
    content_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()[:16]
    hash_path = scripts_dir / f"{safe_id}.hash"
    if not (src_path.exists() and hash_path.exists() and _read_hash(hash_path) == content_hash):
        src_path.write_text(script, encoding="utf-8")
        try:
            hash_path.write_text(content_hash, encoding="utf-8")
        except OSError:
            pass

    # Output port names drive the emitted JSON keys.
    out_port_names = [p.name for p in node.output_ports()]
    _write_runner(runner_path, src_path, out_port_names)

    cwd = str(cfg.get("cwd") or work_root or ".")
    timeout = _as_float(cfg.get("timeout"), default=60.0)
    # Inputs reach the user code as locals (via the runner reading stdin);
    # INPUT_<PORT> env vars are also set as a convenience.
    env = subprocess_env()
    for name, value in bound_inputs.items():
        if value is None:
            continue
        env[f"INPUT_{name.upper()}"] = str(value)
    stdin_payload = json.dumps(bound_inputs, ensure_ascii=False, default=str).encode("utf-8")

    proc = await _create_workflow_process(
        [sys.executable, str(runner_path)],
        cwd=cwd,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(stdin_payload), timeout=timeout)
    except asyncio.TimeoutError:
        await _terminate_workflow_process(proc)
        raise RuntimeError(f"script timed out after {timeout}s")
    except asyncio.CancelledError:
        await _terminate_workflow_process(proc)
        raise
    text_out = stdout.decode("utf-8", errors="replace") if stdout else ""
    text_err = stderr.decode("utf-8", errors="replace") if stderr else ""
    if proc.returncode != 0:
        raise RuntimeError(f"script exited with code {proc.returncode}\nstderr:\n{text_err}")
    return text_out.strip()
