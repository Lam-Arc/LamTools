from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from lamtools_office_renderer import check_office, render_office, validate_office


EXIT_SUCCESS = 0
EXIT_DATA_OR_MANIFEST = 2
EXIT_RENDER_FAILURE = 3
EXIT_LAYOUT_CONFLICT = 4


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and render Office artifacts")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("--backend", choices=("auto", "microsoft", "libreoffice"), default="auto")
    check.add_argument("--timeout", type=float, default=15.0)
    check.add_argument("--report", dest="report")
    for action in ("validate", "render"):
        command = commands.add_parser(action)
        command.add_argument("source_pos", nargs="?")
        command.add_argument("manifest_pos", nargs="?")
        if action == "render":
            command.add_argument("output_pos", nargs="?")
        command.add_argument("--source", "--input", dest="source")
        command.add_argument("--manifest", dest="manifest")
        command.add_argument("--output-dir", "--output", dest="output_dir")
        command.add_argument("--backend", choices=("auto", "microsoft", "libreoffice"), default="auto")
        command.add_argument("--timeout", type=float, default=120.0)
        command.add_argument("--dpi", type=int, default=144)
        command.add_argument("--report", dest="report")
    return parser


def _payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "as_dict") and callable(value.as_dict):
        value = value.as_dict()
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    raise TypeError("Office renderer returned a non-object report")


def _exit_code(payload: Mapping[str, Any], *, action: str) -> int:
    issues = payload.get("issues")
    codes = {
        str(issue.get("code") or "").casefold()
        for issue in issues if isinstance(issue, Mapping)
    } if isinstance(issues, list) else set()
    exit_class = str(payload.get("exit_class") or "").casefold()
    statuses = payload.get("statuses") if isinstance(payload.get("statuses"), Mapping) else {}
    if "layout" in exit_class or "overlap" in exit_class or any("overlap" in code or "layout" in code for code in codes):
        return EXIT_LAYOUT_CONFLICT
    if (
        str(statuses.get("data") or "").casefold() == "failed"
        or str(statuses.get("structure") or "").casefold() == "failed"
        or any(marker in code for code in codes for marker in ("manifest", "mismatch", "binding", "dataset", "source_hash"))
    ):
        return EXIT_DATA_OR_MANIFEST
    if payload.get("ok") is False:
        return EXIT_DATA_OR_MANIFEST if action == "validate" else EXIT_RENDER_FAILURE
    return EXIT_SUCCESS


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        try:
            payload = _payload(check_office(backend=args.backend, timeout=args.timeout))
        except Exception as exc:
            payload = {
                "ok": False,
                "exit_class": "render_failure",
                "message": "Office 应用未就绪 · Test Passed 0/3",
                "passed": 0,
                "total": 3,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if args.report:
            report_path = Path(args.report).expanduser().resolve()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(encoded, encoding="utf-8")
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
        print(str(payload.get("message") or "Office 应用未就绪 · Test Passed 0/3"))
        if payload.get("ok") is not True:
            print(encoded, end="")
        return EXIT_SUCCESS if payload.get("ok") is True else EXIT_RENDER_FAILURE
    source = Path(args.source or args.source_pos).expanduser().resolve() if (args.source or args.source_pos) else None
    manifest = Path(args.manifest or args.manifest_pos).expanduser().resolve() if (args.manifest or args.manifest_pos) else None
    if source is None or manifest is None:
        parser.error("--source and --manifest are required")
    try:
        if args.command == "validate":
            report = validate_office(manifest, source=source)
        else:
            raw_output = args.output_dir or args.output_pos
            if not raw_output:
                parser.error("--output-dir is required for render")
            report = render_office(
                manifest,
                Path(raw_output).expanduser().resolve(),
                source=source,
                backend=args.backend,
                timeout=args.timeout,
                dpi=args.dpi,
            )
        payload = _payload(report)
    except Exception as exc:
        payload = {
            "ok": False,
            "exit_class": "manifest_mismatch" if args.command == "validate" else "render_failure",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        report_path = Path(args.report).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return _exit_code(payload, action=args.command)


if __name__ == "__main__":
    raise SystemExit(main())
