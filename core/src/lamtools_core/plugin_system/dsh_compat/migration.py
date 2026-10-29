"""Conservative, bounded, offline DSH port preparation; never evaluates code.

user:“自动化兼容脚本”+(自动转换可验证的静态资源，动态注册和框架差异交给 agent，不生成假后端)。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .catalog import load_surface

IGNORED = {".git", "node_modules", ".venv", "__pycache__", ".env", ".DS_Store"}
CODE = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}
MAX_FILES = 4000
MAX_BYTES = 32 * 1024 * 1024


def _files(root: Path, max_files: int, max_bytes: int) -> list[Path]:
    files: list[Path] = []
    size = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in dirs + names:
            path = base / name
            if name in IGNORED or name.startswith(".env."):
                continue
            if path.is_symlink() or path.is_junction():
                raise ValueError(f"linked source requires manual review: {path.relative_to(root)}")
        dirs[:] = sorted(d for d in dirs if d not in IGNORED)
        for name in sorted(names):
            if name in IGNORED or name.startswith(".env."):
                continue
            path = base / name
            size += path.stat().st_size
            files.append(path)
            if len(files) > max_files or size > max_bytes:
                raise ValueError("source scan limit exceeded; choose one plugin package")
    return sorted(files)


def _object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must be an object")
    return value


def analyze(source: Path | str, *, max_files: int = MAX_FILES, max_bytes: int = MAX_BYTES) -> dict[str, Any]:
    root = Path(source).resolve()
    if not root.is_dir():
        raise ValueError("source must be a local plugin directory")
    files = _files(root, max_files, max_bytes)
    package = _object(root / "package.json")
    catalog = load_surface()
    known = {row["dsh"]: row for row in catalog["services"]}
    report: dict[str, Any] = {
        "schemaVersion": 1, "upstreamCommit": catalog["upstreamCommit"],
        "sundayHostContracts": catalog.get("hostContracts", {}),
        "package": {key: package.get(key, "") for key in ("name", "version", "description")},
        "runtimeVerified": False, "status": "declarative-only",
        "services": [], "events": [], "remotes": [], "slots": [],
        "promptMethods": [],
        "commandMethods": [],
        "findings": [], "converted": {"skills": [], "mcp": []},
        "files": [p.relative_to(root).as_posix() for p in files],
        "excluded": sorted(IGNORED) + [".env.*"],
        "analysisLimits": "静态保守扫描；注释/字符串可能产生候选，计算属性、重命名和跨函数传递不能完整推断。无运行验证。",
    }

    def finding(code: str, file: str, line: int, message: str) -> None:
        report["findings"].append({"code": code, "file": file, "line": line, "message": message})

    # Accept likely Context names, including apply(context) and simple aliases.
    for path in files:
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() in CODE:
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeError:
                finding("unreadable-code", relative, 1, "源码不是 UTF-8，需 agent 检查。")
                continue
            finding("javascript-runtime", relative, 1, "JS/TS/Cordis 源码需移植为 Sunday 后端或受管进程；未生成运行适配。")
            names = {"ctx", "context"}
            names.update(re.findall(r"\bapply\s*\(\s*([A-Za-z_$][\w$]*)", text))
            for _ in range(4):
                for alias, parent in re.findall(r"\b(?:const|let)\s+([\w$]+)\s*=\s*([\w$]+)\s*[;\n]", text):
                    if parent in names:
                        names.add(alias)
            receiver = r"\b(?:" + "|".join(re.escape(n) for n in sorted(names)) + r")"
            def add(kind: str, name: str, pos: int) -> None:
                item = {"name": name, "file": relative, "line": text.count("\n", 0, pos) + 1}
                # user:“剩下问题交给 agent 来移植”+(为已具备宿主契约的方法提供人工映射，不执行参数或事件格式的盲替换)。
                if kind == "services" and name == "commands":
                    item.update(suggestedContract="context.commands / command.catalog / command.execute", conversion="agent-required",
                                difference="受管 Python 文本动作命令；显式 session_id 范围与 CommandResult，原路径裁剪输入空白。附件、Agent 原对象、stable definitionId、change 和 DSH 日志格式未覆盖。")
                if kind == "commandMethods":
                    item.update(conversion="agent-required")
                    contracts = {"register": "context.commands.register", "list": "command.catalog", "execute": "command.execute"}
                    if name in contracts:
                        item.update(suggestedContract=contracts[name],
                                    difference="Python 注册或 Sunday operation；参数对象、回调、会话标识及结果需适配，execute 接收分开的 command/arguments，非 DSH 完整行解析。")
                    else:
                        item.update(difference="当前没有同名公开方法；需基于目录查询或另行实现，不能生成空函数。")
                if kind == "services" and name == "systemPrompt":
                    item.update(suggestedContract="context.prompts", conversion="agent-required",
                                difference="同步 Python section/variable/on_assemble；插件命名空间和会话/agent_id 范围需适配。无 complete、动态上下文/抑制/刷新、集中顺序表或工具 schema 注册。")
                if kind == "events" and name == "system-prompt/assemble":
                    item.update(suggestedContract="context.prompts.on_assemble", conversion="agent-required",
                                difference="同步 callback(PromptContext, PromptAssembly)，支持返回组装结果或 None；不提供 DSH 原始参数、动态上下文或工具字段；失败按 Sunday 规则回退内置提示词。")
                if kind == "promptMethods":
                    item.update(conversion="agent-required")
                    if name in {"section", "variable"}:
                        item.update(suggestedContract="context.prompts." + name,
                                    difference="将 JS 对象参数/回调改为 Python 契约；同步求值，作用域显式声明，完整替换及上下文方法未支持。")
                    else:
                        item.update(difference="当前提示词契约尚无此方法；保留待办，不能改为无效空调用。")
                if kind == "services" and name == "tools":
                    item.update(suggestedContract="context.tools", conversion="agent-required",
                                difference="Python 动态工具契约；register/restrict/guard/on 需逐项适配。仅扁平原始类型参数 schema，沿用数值等级审批，不支持 execute 包装、参数重写或动态 ask。")
                if kind == "events" and name in {"tools/pre-execute", "tools/post-execute", "tools/result"}:
                    item.update(suggestedContract=f'context.tools.on("{name}", callback)', conversion="agent-required",
                                difference="Python 只读调用/结果快照；pre 仅 allow/deny，post 仅内容补丁，result 仅观察；同步/异步回调均须适配，非 Cordis waterfall。")
                if kind == "remotes" and name.startswith("session."):
                    method = name.partition(".")[2]
                    if method in {"create", "state", "prompt", "cancel", "events", "follow", "wait", "updateQueue"}:
                        item.update(suggestedContract="sessions." + ("update_queue" if method == "updateQueue" else method),
                                    conversion="agent-required",
                                    difference="Python SESSIONS 契约，参数、回执和持久事件格式需适配；仅文本，未支持 workspace/preset/附件与实时 token。")
                if kind == "services":
                    row = known.get(name)
                    item.update({"status": row["status"] if row else "gap", "sunday": row["sunday"] if row else "补充未收录接口的公开契约", "phase": row["phase"] if row else 2})
                    if row is None:
                        finding("unknown-service", relative, item["line"], f"未收录服务 {name}，需核对插件依赖及上游版本。")
                if item not in report[kind]:
                    report[kind].append(item)
            for match in re.finditer(receiver + r"\s*\.\s*([\w$]+)", text):
                name = match[1]
                if name not in {"on", "once", "effect", "inject", "plugin", "emit", "remote", "slots"}:
                    add("services", name, match.start())
            for match in re.finditer(r"\binject\s*=\s*\[([^\]]*)\]", text):
                for value in re.finditer(r"['\"]([^'\"]+)['\"]", match[1]):
                    name = value[1]
                    if name not in {"remote", "slots"} and not name.startswith("remote."):
                        add("services", name, match.start(1) + value.start())
            for match in re.finditer(receiver + r"\s*\.\s*(?:on|once)\s*\(\s*['\"]([^'\"]+)['\"]", text):
                add("events", match[1], match.start())
            # user:“自动化兼容脚本”+(按提示词方法逐项提示，未知方法仍保留给 agent，不把整个服务误标为可直接替换)。
            for match in re.finditer(receiver + r"\s*\.\s*systemPrompt\s*\.\s*([\w$]+)\s*\(", text):
                add("promptMethods", match[1], match.start())
            for match in re.finditer(receiver + r"\s*\.\s*commands\s*\.\s*([\w$]+)\s*\(", text):
                add("commandMethods", match[1], match.start())
            for match in re.finditer(receiver + r"\s*\.\s*remote\s*\.\s*([\w$]+)\s*\.\s*([\w$]+)", text):
                add("remotes", match[1] + "." + match[2], match.start())
            for match in re.finditer(receiver + r"\s*\.\s*slots\s*\.\s*inject\s*\(\s*['\"]([^'\"]+)['\"]", text):
                add("slots", match[1], match.start())
            for match in re.finditer(receiver + r"\s*\[", text):
                finding("dynamic-access", relative, text.count("\n", 0, match.start()) + 1, "动态 Context 属性需 agent 解析，不能按名称自动替换。")
        if path.name == "SKILL.md":
            # Sunday scans child skill directories, rather than SKILL.md on
            # the declared root itself. Keep upstream resources beside it.
            if path.parent == root:
                finding("root-skill", relative, 1, "根目录技能需移入一个独立技能子目录后再登记。")
            else:
                parent = path.parent.parent.relative_to(root).as_posix()
                report["converted"]["skills"].append("./upstream" + ("/" + parent if parent != "." else ""))
        if path.name == "package.json" and path.parent != root:
            finding("nested-package", relative, 1, "嵌套包需分别核对依赖与入口。")
        if path.name in {"hooks.json", "hooks.jsonc", "tools.json", "tools.jsonc", "cordis.json", "cordis.jsonc"}:
            finding("declarative-review", relative, 1, "未自动转换的工具/钩子/组合声明，需 agent 核对后登记到 Sunday 清单。")
        if path.suffix.lower() in {".yml", ".yaml"}:
            finding("composition", relative, 1, "组合配置、挂载顺序和作用域需 agent 显式移植；不执行 YAML。")
        if path.parent == root and path.name in {"mcp.json", ".mcp.json"}:
            try:
                data = _object(path)
                servers = data.get("mcpServers")
                if not isinstance(servers, dict) or not servers or any(
                    not isinstance(spec, dict) or not (isinstance(spec.get("command"), str) and spec["command"].strip() or isinstance(spec.get("url"), str) and spec["url"].strip())
                    for spec in servers.values()
                ):
                    raise ValueError("mcpServers requires named command/url entries")
                report["converted"]["mcp"].append("./upstream/" + path.name)
                finding("mcp-launch-review", relative, 1, "已保留 MCP 配置；首次启用前核对相对路径、环境变量和外部服务。")
            except (ValueError, OSError) as error:
                finding("mcp-format", relative, 1, str(error))
    dsh = package.get("dsh")
    if dsh is not None:
        finding("dsh-manifest", "package.json", 1, "dsh 字段的 bundle/profile/client 声明需按 Sunday 清单与 UI 契约移植。")
    blockers = [item for item in report["findings"] if item["code"] != "mcp-launch-review"]
    if blockers:
        report["status"] = "needs-port"
    report["converted"]["skills"] = sorted(set(report["converted"]["skills"]))
    return report


def _handoff(report: dict) -> str:
    lines = ["# DSH 插件 → Sunday：agent 移植交接", "",
             "原源码保留在 upstream/；migration-report.json 是静态分析结果。没有执行上游代码，没有运行兼容认证。", "",
             "## 必须先读", "",
             "- Sunday 宿主契约：agent_docs/dsh_compatibility.md、agent_docs/plugin_host_rebuild.md。",
             "- 已验收的服务注册与清理：agent_docs/plugin_owned_services.md；服务和资源在 start/on_load 中注册，工厂只构造运行对象。",
             "- 已验收的桌面会话契约：agent_docs/plugin_session_control.md；用 SESSIONS 经过 live 接收路径，区分 queue/steer 和回执/完成。",
             "- 已验收的动态工具子集：agent_docs/plugin_tool_extensions.md；用 context.tools 在受管 start/on_load 中注册，主/子代理复用原审批。",
             "- 已验收的提示词子集：agent_docs/plugin_prompt_extensions.md；context.prompts.section/variable/on_assemble 随启动代撤回；同步求值，失败回退与 DSH 不同。",
             "- 已验收的动态命令子集：agent_docs/plugin_command_extensions.md；context.commands.register 接入原 command.catalog/execute，输入与结果格式需适配。",
             "- 逐项缺口：agent_docs/dsh_compatibility_matrix.md。",
             "- 上游依据：deepseek-ai/deepseek-harness @ " + report["upstreamCommit"], "",
             "## 待移植", ""]
    for item in report["findings"]:
        lines.append(f'- [ ] `{item["file"]}:{item["line"]}` [{item["code"]}] {item["message"]}')
    for kind in ("services", "events", "remotes", "slots", "promptMethods", "commandMethods"):
        for item in report[kind]:
            lines.append(f'- [ ] {kind}: `{item["name"]}` @ `{item["file"]}:{item["line"]}`，核对参数、返回值、作用域、取消、错误与卸载语义。')
    lines += ["", "## 验收", "",
              "- [ ] 先写需求行为测试；仅运行本次新增的相关测试，不使用 Computer Use。",
              "- [ ] 对照原插件的用户可见能力逐项验证，包括失败、权限拒绝、停用和资源清理。",
              "- [ ] JS/TS 后端通过 Sunday 受管进程协议或 Python 服务实现；不靠全局改包名冒充兼容。",
              "- [ ] Python 服务使用 register_service/bind_service，跨插件调用优先 ServiceRef.call；用 effect/on_dispose 登记清理，验证停用、重启和启动失败。",
              "- [ ] 会话移植使用 SESSIONS，保留 request_id 的去重语义；按 Sunday 持久事件格式适配，不直接把 DSH 原始历史或实时 token 当成同一协议。",
              "- [ ] 动态工具移植到 context.tools.register/restrict/guard/on；明确 level 与参数 schema。pre 仅 allow/deny，post 仅内容补丁，result 只读观察；tools/execute、参数重写、动态 ask 和复杂 schema 另列缺口，不能机械替换。",
              "- [ ] 提示词移植到 context.prompts；适配插件段名、会话/agent_id 范围与同步回调，测试变量缺失、停用与失败回退。complete、上下文快照/刷新/抑制、集中顺序表、change 事件、工具 schema 注册及异步 provider 仍需单列移植。",
              "- [ ] 斜杠命令使用 context.commands.register，回调返回 CommandResult，目录/执行走 command.catalog/execute；会话范围、裁剪空白、无附件、非稳定注册令牌和缺少 commands/change、DSH command/run/done 必须逐项适配。现有界面只查询全局目录，专属目录需显式带 thread_id。",
              "- [ ] React/Cordis 界面按 Sunday 桌面 UI 契约移植；未实现位置保留明确待办。",
              "- [ ] MCP 的相对命令路径、依赖安装和变量模板在目标环境实测；保留默认停用直至完成。",
              "- [ ] 更新插件文档、差异表及本报告的验收记录；原报告 runtimeVerified=false 只代表脚本未验收。", ""]
    return "\n".join(lines)


def export_port(source: Path | str, output: Path | str, *, max_files: int = MAX_FILES, max_bytes: int = MAX_BYTES) -> dict:
    root, target = Path(source).resolve(), Path(output).resolve()
    if target == root or target.is_relative_to(root) or root.is_relative_to(target):
        raise ValueError("source and output must be separate non-nested directories")
    if target.exists():
        raise FileExistsError(target)
    report = analyze(root, max_files=max_files, max_bytes=max_bytes)
    raw_name = str(report["package"]["name"] or root.name).lower()
    name = re.sub(r"[^a-z0-9_-]+", "-", raw_name).strip("-")
    if not name:
        raise ValueError("package name cannot be converted to a Sunday name")
    manifest = {
        "name": name, "version": str(report["package"]["version"] or "0.0.0"),
        "description": str(report["package"]["description"] or ""), "defaultEnabled": False,
        "skills": report["converted"]["skills"], "mcp": report["converted"]["mcp"],
        "dshMigration": {"status": report["status"], "upstreamCommit": report["upstreamCommit"], "report": "./migration-report.json"},
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dsh-port-", dir=target.parent) as temporary:
        staging = Path(temporary) / "result"
        staging.mkdir()
        for relative in report["files"]:
            src = root / relative
            if src.is_symlink() or src.is_junction() or not src.resolve().is_relative_to(root):
                raise ValueError("source changed into a link during export")
            dst = staging / "upstream" / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        for filename, value in (("plugin.json", manifest), ("migration-report.json", report)):
            (staging / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staging / "PORTING.md").write_text(_handoff(report), encoding="utf-8")
        # Validate against the same manifest/capability parser used by the host.
        from ..manifest import load_manifest
        from ..capabilities import read_capabilities
        capabilities = read_capabilities(load_manifest(staging / "plugin.json"))
        recognized = {item.location.resolve() for item in capabilities.skills}
        for relative in report["files"]:
            original = root / relative
            if original.name == "SKILL.md" and original.parent != root:
                if (staging / "upstream" / relative).resolve() not in recognized:
                    raise ValueError(f"Sunday skill parser rejected {relative}; check duplicate names, visibility and file readability")
        if target.exists():
            raise FileExistsError(target)
        staging.rename(target)
    return report
