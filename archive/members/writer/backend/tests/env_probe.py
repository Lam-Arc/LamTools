"""Environment capability probe — detects runtimes and writes ENV_CAPABILITY.md.

Usage:
    py -3.14 env_probe.py          # probe and write report
    py -3.14 env_probe.py --json   # output JSON to stdout (for programmatic use)

This script is designed to be called:
- Manually when the environment changes
- Before each architecture planning phase by Writer
- Periodically to keep the capability doc fresh
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent  # LamWriter/
OUTPUT_MD = ROOT / "ENV_CAPABILITY.md"

COMMON_INSTALL_DIRS = [
    Path("C:/Program Files"),
    Path("C:/Program Files (x86)"),
    Path(os.environ.get("LOCALAPPDATA", ""), "Programs"),
    Path(os.environ.get("APPDATA", "")),
]

RUNTIME_CHECKS: list[dict[str, Any]] = [
    {
        "name": "Python",
        "commands": [["python", "--version"], ["py", "-3.14", "-c", "import sys; print(sys.version)"]],
        "key_packages": ["fastapi", "uvicorn", "pytest", "sqlalchemy", "httpx", "aiohttp"],
    },
    {
        "name": "Node.js",
        "commands": [["node", "--version"]],
        "npm_command": ["npm", "--version"],
    },
    {
        "name": "Java (JRE)",
        "search_executable": "java.exe",
    },
    {
        "name": "Java (JDK)",
        "commands": [["javac", "-version"]],
        "search_executable": "javac.exe",
        "build_tools": [["mvn", "--version"]],
    },
    {
        "name": "Docker",
        "commands": [["docker", "--version"]],
    },
    {
        "name": "Rust",
        "commands": [["rustc", "--version"]],
        "cargo_path": Path(os.environ.get("USERPROFILE", ""), ".cargo/bin"),
    },
    {
        "name": "Go",
        "commands": [["go", "version"]],
    },
    {
        "name": "Git",
        "commands": [["git", "--version"]],
    },
]


def _run(args: list[str], timeout: int = 5) -> tuple[bool, str]:
    """Try to run a command. Returns (success, output). Tries shell=True first for PATH commands, shell=False fallback."""
    cmd_str = " ".join(args)
    for use_shell in (True, False):
        try:
            result = subprocess.run(
                cmd_str if use_shell else args,
                capture_output=True, text=True, timeout=timeout,
                shell=use_shell,
            )
            output = (result.stdout + result.stderr).strip()
            return result.returncode == 0, output[:500]
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    return False, ""


def _check_python_packages() -> list[str]:
    """Check if key Python packages are importable (try py launcher first, then python)."""
    available: list[str] = []
    python_cmd = "python"
    ok, _ = _run(["py", "-3.14", "-c", "pass"])
    if ok:
        python_cmd = "py"
        python_args = ["-3.14", "-c"]
    else:
        python_args = ["-c"]
    
    for pkg in ["fastapi", "uvicorn", "pytest", "sqlalchemy", "httpx", "aiohttp"]:
        ok, _ = _run([python_cmd] + python_args + [f"import {pkg}"])
        if ok:
            available.append(pkg)
    return available


def _find_in_install_dirs(executable_name: str) -> list[Path]:
    """Search common install directories for an executable (depth 4 for thoroughness)."""
    found: list[Path] = []
    for base in COMMON_INSTALL_DIRS:
        if not base.exists():
            continue
        try:
            # Search up to depth 4: base/*/*/*/*/<executable>
            for depth, pattern in enumerate([
                executable_name,
                f"*/{executable_name}",
                f"*/*/{executable_name}",
                f"*/*/*/{executable_name}",
            ]):
                for p in base.glob(pattern):
                    if p.is_file():
                        found.append(p)
                if found:
                    break
        except PermissionError:
            continue
    return found


def probe() -> dict[str, Any]:
    """Run full environment probe and return structured results."""
    results: dict[str, Any] = {
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "runtimes": [],
    }

    for rt in RUNTIME_CHECKS:
        # Skip entries without commands or search_executable (like Java JRE stub)
        if not rt.get("commands") and not rt.get("search_executable"):
            continue

        entry: dict[str, Any] = {"name": rt["name"], "path_available": False, "absolute_available": False, "details": ""}

        # Try PATH commands first
        for cmd in rt.get("commands", []):
            ok, out = _run(cmd)
            if ok:
                entry["path_available"] = True
                entry["details"] = out.split("\n")[0][:100] if out else "available"
                break

        # Search install directories as fallback
        executable = rt.get("search_executable", "")
        if not entry["path_available"] and executable:
            found = _find_in_install_dirs(executable)
            if found:
                found_path = found[0]
                entry["absolute_available"] = True
                entry["absolute_path"] = str(found_path)
                ok, out = _run([str(found_path), "--version"])
                if ok:
                    entry["details"] = out.split("\n")[0][:100] if out else "found via directory scan"
                else:
                    entry["details"] = "found via directory scan"

        # Check build tools
        if "build_tools" in rt:
            for tool_cmd in rt["build_tools"]:
                ok, _ = _run(tool_cmd)
                entry[f"build_tool_{tool_cmd[0]}"] = "available" if ok else "not found"

        # Check npm version
        if "npm_command" in rt:
            ok, out = _run(rt["npm_command"])
            if ok:
                entry["npm_version"] = out.strip()[:50]

        results["runtimes"].append(entry)

    # Python packages
    results["python_packages"] = _check_python_packages()

    return results


def generate_markdown(data: dict[str, Any]) -> str:
    """Generate ENV_CAPABILITY.md from probe data."""
    lines = [
        "# Environment Capability Reference",
        "",
        "> Auto-probed. Used by the weighted decision system to estimate real COST.",
        f"> Last probed: {data['probed_at'][:19]}",
        "",
        "## Runtime Inventory",
        "",
    ]

    for rt in data["runtimes"]:
        name = rt["name"]
        if rt.get("path_available"):
            status = "READY (PATH)"
        elif rt.get("absolute_available"):
            ap = rt.get("absolute_path", "unknown path")
            status = f"LIMITED (found at `{ap}`)"
        else:
            status = "NOT INSTALLED"

        lines.append(f"### {name}")
        lines.append(f"- **Status**: {status}")
        if rt.get("details"):
            lines.append(f"- **Details**: {rt['details']}")
        if rt.get("npm_version"):
            lines.append(f"- **npm**: {rt['npm_version']}")
        for key in rt:
            if key.startswith("build_tool_"):
                lines.append(f"- **{key.replace('build_tool_', '')}**: {rt[key]}")
        lines.append("")

    # Python packages
    pkgs = data.get("python_packages", [])
    lines.append("## Python Key Packages")
    lines.append(f"- Available: {', '.join(pkgs) if pkgs else 'unknown'}")
    lines.append("")

    # Verification table
    lines.extend([
        "## Setup Cost Guide",
        "",
        "| Missing Item | Estimated Setup Cost |",
        "|-------------|---------------------|",
        "| Python packages (pip install) | LOW |",
        "| Node packages (npm install) | LOW |",
        "| Java JDK + Maven | HIGH |",
        "| Go toolchain | MEDIUM |",
        "| Docker | HIGH |",
        "| Rust toolchain | MEDIUM |",
        "| Database server (PostgreSQL/MySQL) | HIGH |",
        "| SQLite | NONE |",
        "",
        "## Recovery Playbook",
        "",
        "If PATH doesn't show a runtime:",
        "1. Check common install dirs: `C:\\Program Files\\`, `%LOCALAPPDATA%\\Programs\\`",
        "2. Try absolute path invocation",
        "3. If found: use absolute path. Do NOT modify user's PATH.",
        "4. If missing: add install step to candidate's Setup Cost.",
        "",
    ])

    return "\n".join(lines)


def main():
    data = probe()

    if "--json" in sys.argv:
        print(json.dumps(data, indent=2))
    else:
        md = generate_markdown(data)
        OUTPUT_MD.write_text(md, encoding="utf-8")
        print(f"Written: {OUTPUT_MD}")
        print(f"Runtimes found: {sum(1 for r in data['runtimes'] if r.get('path_available') or r.get('absolute_available'))}/{len(data['runtimes'])}")


if __name__ == "__main__":
    main()
