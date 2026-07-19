from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PORTS_FILE = ROOT / "scripts" / "ports.json"
POWERSHELL = "powershell"


@dataclass
class Check:
    id: str
    status: str
    message: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "warn"}


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _load_ports() -> dict[str, dict[str, int]]:
    return json.loads(PORTS_FILE.read_text(encoding="utf-8-sig"))


def _run(command: list[str], *, cwd: Path = ROOT) -> int:
    return subprocess.run(command, cwd=str(cwd), env=_env()).returncode


def _run_ps(script: str, args: list[str]) -> int:
    command = [
        POWERSHELL,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts" / script),
        *args,
    ]
    return _run(command)


def _probe_url(url: str, timeout: float = 0.75) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 500, f"HTTP {response.status}"
    except urllib.error.URLError as exc:
        return False, str(exc.reason if hasattr(exc, "reason") else exc)
    except TimeoutError:
        return False, "timeout"


def _frontend_url(target: str) -> str | None:
    ports = _load_ports()
    if target == "core":
        return f"http://127.0.0.1:{ports['core']['frontend_dev']}"
    if target == "writer":
        return f"http://127.0.0.1:{ports[target]['frontend_dev']}"
    if target == "sage":
        return f"http://127.0.0.1:{ports[target]['frontend_dev']}"
    return None


def _backend_health_url(target: str) -> str | None:
    ports = _load_ports()
    if target in {"writer", "sage"}:
        return f"http://127.0.0.1:{ports[target]['backend']}/api/health"
    return None


def _targets(value: str) -> list[str]:
    if value == "all":
        return ["core", "writer", "sage"]
    return [value]


def cmd_dev(args: argparse.Namespace) -> int:
    code = _run_ps("dev.ps1", [args.component, args.layer])
    if code == 0 and args.open and args.layer in {"all", "frontend"}:
        for target in _targets(args.component):
            _open_target(target)
    return code


def cmd_build(args: argparse.Namespace) -> int:
    return _run_ps("build.ps1", [args.component])


def cmd_test(args: argparse.Namespace) -> int:
    return _run_ps("test.ps1", [args.component])


def _open_target(target: str) -> int:
    url = _frontend_url(target)
    if not url:
        print(f"unknown target: {target}", file=sys.stderr)
        return 2
    ok, detail = _probe_url(url)
    if ok:
        print(f"[open] {target}: {url}")
    else:
        print(f"[open] {target}: {url} is not responding ({detail})")
        print(f"[open] start it with: lamtools dev {target} frontend")
    webbrowser.open(url)
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    code = 0
    for target in _targets(args.target):
        code = max(code, _open_target(target))
    return code


def _command_version(command: list[str]) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            env=_env(),
            text=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    output = (completed.stdout or completed.stderr or "").strip().splitlines()
    return completed.returncode == 0, output[0] if output else f"exit {completed.returncode}"


def _path_writable(path: Path) -> bool:
    target = path if path.exists() and path.is_dir() else path.parent
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".lamtools-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _doctor_static_checks(targets: list[str]) -> list[Check]:
    checks: list[Check] = []
    checks.append(Check("root", "ok" if ROOT.exists() else "error", str(ROOT)))
    checks.append(Check("ports", "ok" if PORTS_FILE.exists() else "error", str(PORTS_FILE)))

    npm_command = "npm.cmd" if os.name == "nt" else "npm"
    for label, command in {
        "python": ["py", "-3.14", "--version"],
        "node": ["node", "--version"],
        "npm": [npm_command, "--version"],
    }.items():
        ok, detail = _command_version(command)
        checks.append(Check(label, "ok" if ok else "error", detail))

    for target in targets:
        if target == "core":
            checks.append(Check("core.ui", "ok" if (ROOT / "core" / "ui").exists() else "error", "core/ui"))
            continue
        member_dir = ROOT / "members" / target
        checks.append(Check(f"{target}.dir", "ok" if member_dir.exists() else "error", str(member_dir)))
        checks.append(Check(f"{target}.cmd", "ok" if (ROOT / f"{target}.cmd").exists() else "warn", f"{target}.cmd"))

    if "writer" in targets:
        data_dir = Path(os.environ.get("LAMWRITER_DATA_DIR", ROOT / "members" / "writer" / "data"))
        db_path = data_dir / "lamwriter.db"
        if db_path.exists():
            checks.append(Check("writer.db", "ok", str(db_path)))
        elif _path_writable(db_path):
            checks.append(Check("writer.db", "warn", "database not created yet", str(db_path)))
        else:
            checks.append(Check("writer.db", "error", "database directory is not writable", str(db_path)))

    return checks


def _doctor_server_checks(targets: list[str]) -> list[Check]:
    checks: list[Check] = []
    for target in targets:
        frontend = _frontend_url(target)
        if frontend:
            ok, detail = _probe_url(frontend)
            status = "ok" if ok else "warn"
            checks.append(Check(f"{target}.frontend", status, frontend, detail))
        backend = _backend_health_url(target)
        if backend:
            ok, detail = _probe_url(backend)
            status = "ok" if ok else "warn"
            checks.append(Check(f"{target}.backend", status, backend, detail))
    return checks


def cmd_doctor(args: argparse.Namespace) -> int:
    targets = _targets(args.target)
    checks = _doctor_static_checks(targets) + _doctor_server_checks(targets)
    ok = all(check.ok for check in checks)
    if args.json:
        print(json.dumps({"ok": ok, "checks": [check.__dict__ for check in checks]}, ensure_ascii=False, indent=2))
    else:
        for check in checks:
            suffix = f" ({check.detail})" if check.detail else ""
            print(f"[{check.status}] {check.id}: {check.message}{suffix}")
    return 0 if ok else 1


def _member_rows() -> list[dict[str, Any]]:
    ports = _load_ports()
    rows: list[dict[str, Any]] = []
    members_dir = ROOT / "members"
    for member_dir in sorted(path for path in members_dir.iterdir() if path.is_dir()):
        member_id = member_dir.name
        rows.append(
            {
                "id": member_id,
                "path": str(member_dir.relative_to(ROOT)),
                "ports": ports.get(member_id, {}),
                "cli": str((ROOT / f"{member_id}.cmd").relative_to(ROOT))
                if (ROOT / f"{member_id}.cmd").exists()
                else None,
            }
        )
    return rows


def cmd_members_list(args: argparse.Namespace) -> int:
    rows = _member_rows()
    if args.json:
        print(json.dumps({"ok": True, "members": rows}, ensure_ascii=False, indent=2))
        return 0
    for row in rows:
        ports = row["ports"]
        backend = ports.get("backend", "-")
        frontend = ports.get("frontend_dev", "-")
        print(f"{row['id']}\tbackend={backend}\tfrontend={frontend}\tcli={row['cli'] or '-'}")
    return 0


def cmd_scaffold_member(args: argparse.Namespace) -> int:
    ps_args = ["-Id", args.id, "-Name", args.name]
    if args.display_name:
        ps_args += ["-DisplayName", args.display_name]
    if args.capability:
        ps_args += ["-Capabilities", ",".join(args.capability)]
    if args.dry_run:
        ps_args.append("-DryRun")
    return _run_ps("scaffold-member.ps1", ps_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lamtools", description="LamTools repository maintenance CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    dev = sub.add_parser("dev", help="Start development services")
    dev.add_argument("component", nargs="?", default="all", choices=["core", "writer", "sage", "all"])
    dev.add_argument("layer", nargs="?", default="all", choices=["backend", "frontend", "all"])
    dev.add_argument("--open", action="store_true", help="Open frontend URL after starting")
    dev.set_defaults(func=cmd_dev)

    build = sub.add_parser("build", help="Build frontend packages")
    build.add_argument("component", nargs="?", default="all", choices=["core", "writer", "sage", "all"])
    build.set_defaults(func=cmd_build)

    test = sub.add_parser("test", help="Run test suites")
    test.add_argument("component", nargs="?", default="all", choices=["core", "writer", "sage", "all"])
    test.set_defaults(func=cmd_test)

    open_cmd = sub.add_parser("open", help="Open a running frontend")
    open_cmd.add_argument("target", choices=["core", "writer", "sage", "all"])
    open_cmd.set_defaults(func=cmd_open)

    doctor = sub.add_parser("doctor", help="Check local runtime health")
    doctor.add_argument("target", nargs="?", default="all", choices=["core", "writer", "sage", "all"])
    doctor.add_argument("--json", action="store_true", help="Print machine-readable output")
    doctor.set_defaults(func=cmd_doctor)

    members = sub.add_parser("members", help="Inspect members")
    members_sub = members.add_subparsers(dest="members_command", required=True)
    members_list = members_sub.add_parser("list", help="List registered member directories")
    members_list.add_argument("--json", action="store_true")
    members_list.set_defaults(func=cmd_members_list)

    scaffold = sub.add_parser("scaffold", help="Scaffold repository artifacts")
    scaffold_sub = scaffold.add_subparsers(dest="scaffold_command", required=True)
    scaffold_member = scaffold_sub.add_parser("member", help="Scaffold a new member")
    scaffold_member.add_argument("id")
    scaffold_member.add_argument("--name", required=True)
    scaffold_member.add_argument("--display-name")
    scaffold_member.add_argument("--capability", action="append", default=[])
    scaffold_member.add_argument("--dry-run", action="store_true")
    scaffold_member.set_defaults(func=cmd_scaffold_member)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
