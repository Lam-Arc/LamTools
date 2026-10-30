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
        "skillMethods": [],
        "modelMethods": [],
        "storageMethods": [],
        "credentialMethods": [],
        "configMethods": [],
        "filesystemMethods": [],
        "compactionMethods": [],
        "permissionMethods": [],
        "processMethods": [],
        "backgroundMethods": [],
        "questionMethods": [],
        "phase2Methods": [],
        "subagentMethods": [],
        "durableMethods": [],
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
                # user:“给我把 2 阶段做完，前端除外”+(固定机器映射只建议已验收接口，不执行跨语言盲替换)。
                if kind == "phase2Methods":
                    port = catalog.get("phase2MethodPorts", {}).get(name)
                    item.update(conversion="agent-required", difference="此方法尚无已验收映射；按服务清单核对原协议，不猜测接口。")
                    if port is not None:
                        item.update(port)
                # user:“剩下问题交给 agent 来移植”+(为已具备宿主契约的方法提供人工映射，不执行参数或事件格式的盲替换)。
                if kind == "services" and name == "subprocess":
                    item.update(candidateContract="context.processes", conversion="agent-required",
                                difference="Windows 原生 Job 受管 argv 进程、有限输出和回收；不是完整 DSH 标准流/控制管道/PTY 或跨平台提供方。")
                if kind == "durableMethods":
                    item.update(conversion="agent-required")
                    if name in {"goals.create", "goals.list", "schedule.create", "schedule.list", "schedule.update"}:
                        item.update(suggestedContract="context." + name,
                                    difference="Python 持久目标/Arrange 近似接口，固定插件/项目命名空间；create 要求 thread_id/request_id，重复返回原记录。目标状态、轮数/CAS/续跑和提醒投递协议不同；需人工重设计，非 DSH 原日志域。")
                    else:
                        item.update(difference="完整 DSH 目标续跑/比较交换/投影或提醒历史、cron/删除协议未提供；须人工按 Sunday 目标更新/计划控制协议移植。")
                if kind == "backgroundMethods":
                    # user:“继续，把 2 阶段都做完”+(只提示实际存在的方法，未知作业协议保留人工待办)。
                    item.update(conversion="agent-required")
                    if name == "spillStore.saveText":
                        item.update(candidateContract="context.spill_store.save_text",
                                    difference="异步本地UTF-8文本保存，显式 content/session_id/suggested_name/source，最多8MiB；返回 locator/bytes/retrieval_hint。插件/会话标签目录不授予读取权限，持久文件不自动过期；取消等待磁盘写入结束后传播，可能已保存。无远程后端或自动工具结果截断。")
                    elif name in {"jobs.start", "jobs.get", "jobs.list", "jobs.read", "jobs.wait", "jobs.kill", "jobs.remove"}:
                        item.update(candidateContract="context." + name,
                                    difference="Python异步回调作业；所有权为插件启动代/项目视图，session_id仅标签而非DSH会话ACL。8运行/128保留、每流64KiB字节尾、结果64KiB JSON；read为非消费显式偏移。无控制器注册、推送通知、日志环、持久化或跨插件接管；停用取消并等待配合取消的回调，外部子进程仍须受管进程接口。")
                    else:
                        item.update(difference="未提供该DSH后台作业或spill方法的等价协议；不得把非消费read映射为消费游标、事件通知或控制器。")
                if kind == "questionMethods":
                    # user:“继续，把 2 阶段都做完”+(问答候选不代理审批、计时继续或活Agent身份)。
                    item.update(conversion="agent-required")
                    if name == "ask":
                        item.update(candidateContract="context.questions.ask",
                                    difference="仅程序化普通表单问答，questions+显式timeout≤300秒，单终端受管回答者。校验每题一答、选项、自定义及跳过；无提供方明确报错，取消/撤回/超时不编造答案。没有Agent身份、审批intent、持久投影、Web接线、waterfall或计时继续协议；不得将返回答案当工具授权。")
                    else:
                        item.update(difference="未实现该DSH问答方法、Client接手、持久继续或Remote协议；不可用阻塞ask冒充askTimed。")
                if kind == "subagentMethods":
                    # user:“继续”+(持久成员门面不冒充DSH Agent/activation提供方，保留人工移植边界)。
                    item.update(conversion="agent-required")
                    candidates = {"subagents.startActivation": "context.subagents", "subagents.sendMessage": "context.subagents.message", "subagents.listChildren": "context.subagents.list", "subagents.interrupt": "context.subagents.interrupt"}
                    if name in candidates:
                        item.update(candidateContract=candidates[name],
                                    difference="仅Sunday具名持久成员：固定原项目/可见父会话/插件命名空间，原监督器与邮箱；create后message启动，request_id用于原邮箱去重。interrupt改为父会话+友好name并等待本成员清理，缺失成员报错，不等同DSH同步信号回执/精确在线authority。resume仅支持已中断且有非活动提交状态和真实继续执行器的成员，不是根Agent恢复；无DSH AgentHandle/activation结果、fork/provider registry、明确Queue/Steer或子父互发；插件停用只撤回门面，成员仍归原监督器。")
                    else:
                        item.update(difference="该DSH根Agent或子代理方法没有等价公开协议；不得用具名成员create/list/close代替AgentHandle、activation dispose/结果、恢复或全树控制。")
                if kind == "processMethods":
                    # user:“继续，把 2 阶段都做完”+(Shell 与环境只提示有差异的真实候选，后续原进程映射仍保持独立)。
                    shell_methods = {"shell.resolve": "shell.resolve", "shell.execute": "shell.execute",
                                     "shellEnv.register": "shell_env.register", "shellEnv.collect": "shell_env.collect", "shellEnv.list": "shell_env.list"}
                    item.update(conversion="agent-required")
                    mapped = {"subprocess.resolveExecutable": "resolve_executable", "scrubbedParentEnv": "environment"}
                    if name == "subprocess.spawn":
                        item.update(suggestedContract="context.processes.spawn",
                                    difference="改为 await spawn(argv,timeout=...)；仅 Windows 原生程序、stdin关闭、有限字节尾输出；wait/terminate/read_output。成功依赖 Job 所有权；根退出会回收余下成员。有启动到 Job 分配之间的竞争窗口，不是完整 DSH stdio/PTY 或远程协议。")
                    elif name in mapped:
                        item.update(suggestedContract="context.processes." + mapped[name],
                                    difference="同步 Python 本地子集；PATH 只查绝对目录、不搜索当前目录，Windows 用 PATHEXT；环境为不可变映射，过滤凭据名称及 DSH_/SUNDAY_/LAMTOOLS_，显式覆盖后应用上限。无 DSH proxy overlay、远程世界或控制管道。解析不执行，不授予权限。")
                    elif name in shell_methods:
                        item.update(candidateContract="context." + shell_methods[name],
                                    difference="桌面 PowerShell 近似；显式 timeout≤3600，环境每次启动收集，SUNDAY_* 代替 DSH_*，session_id 只是调用方标签而非身份授权。后台仍有期限，输出为有限字节尾/显式游标，无 spill、stdin、PTY、沙箱或远程协议。准备超时抛错，result 取消只停止观察；进程随原插件停用回收。需人工调整对象、参数与生命周期。")
                    else:
                        item.update(difference="此方法的完整 DSH 标准流、终端、远程或控制协议尚未提供；不能用近似进程/PowerShell 代替未知方法。")
                if kind == "services" and name == "permissionPresets":
                    item.update(candidateContract="context.permissions", conversion="agent-required",
                                difference="仅 Sunday 固定 ask/auto/full_access 目录和会话持久偏好读侧；不是 DSH sandbox/approval 组合预设。")
                if kind == "permissionMethods":
                    item.update(conversion="agent-required")
                    if name == "approval.request":
                        item.update(suggestedContract="context.approvals.request",
                                    difference="改为 session_id/tool_name/call_id，活动回合内调用；需受管终端回答者，缺失为 unavailable。返回含审计序号的 ApprovalResult；非 DSH 审计编码、waterfall 或数字审批绕过令牌，无前端卡片和持久 setPolicy。")
                    elif name in {"permissionPresets.catalog", "permissionPresets.current"}:
                        item.update(suggestedContract="context.permissions." + ("catalog" if name.endswith(".catalog") else "read"),
                                    difference="只读近似；current 的 session 改为 session_id，从返回视图读取 preset。Sunday auto 是免问等级 2，不是 DSH Auto review；目录固定，不含 sandbox/defaultOptions/custom/展示文案。结果不是授权凭证，也不含动态工具实际权限。")
                    else:
                        item.update(difference="未提供此DSH审批扩展方法、持久setPolicy、预设切换或registerAuto；已有后端request/answer近似不覆盖这些协议，不得用权限读取模拟批准或持久策略修改。")
                if kind == "services" and name == "compaction":
                    item.update(candidateContract="context.compaction", conversion="agent-required",
                                difference="仅桌面已知空闲会话的手动压缩；共用原命令和持久控制记录，不是 DSH CompactionEngine。")
                if kind == "compactionMethods":
                    item.update(conversion="agent-required")
                    if name == "compactNow":
                        item.update(suggestedContract="context.compaction.compact_now",
                                    difference="手工把 agent 改为 session_id，先读 SESSIONS.state.last_event_seq 并传 expected_revision；结果区分 compacted/not_needed/cancelled。无自动重试、持久压缩锁、DSH seq 区间或命令 ID 去重。失败/取消不保证回滚，停用等待已接收调用结束。")
                    else:
                        item.update(difference="未开放 DSH 自动触发、指定区间、压力计量、检查点标记或 summary-error waterfall；保留 agent 待办，不能映射为手动压缩。")
                if kind == "services" and name == "fs":
                    item.update(candidateContract="context.filesystem", conversion="agent-required",
                                difference="固定工作目录的有限读写、本地路径与轮询监听近似；不是 DSH FsTarget 后端，也不是会话目录持久化服务。")
                if kind == "services" and name == "workingDirectory":
                    item.update(candidateContract="context.working_directory", conversion="agent-required",
                                difference="原会话持久执行目录/CAS近似；显式for_session取得插件视图。主代理文件工具/Git/run_command在模型请求边界固定目标并追加目录通知；MCP等其余工具及DSH目录事件仍有差异。")
                if kind == "filesystemMethods":
                    item.update(conversion="agent-required")
                    mapped = {"fs.stat": "stat", "fs.readBytes": "read_bytes", "fs.readText": "read_text", "fs.listDir": "list_dir"}
                    # user:“继续，把 2 阶段都做完”+(路径与轮询监听只给人工适配候选，不冒充稳定目标标识或原生事件流)。
                    targets = {"fs.resolve": "resolve", "fs.processPath": "process_path", "fs.fileUrl": "file_url",
                               "fs.contains": "contains", "fs.processPathFromHostPath": "process_path_from_host_path"}
                    if name in targets:
                        item.update(candidateContract="context.filesystem." + targets[name],
                                    difference="仅根内本地原生路径；resolve 返回 Path，process_path 返回绝对路径，file_url 为本地 URI，contains 返回布尔值。host_path 映射为路径或 None；相对宿主路径拒绝。无远程挂载、opaque FsTarget、授权或跨后端身份。需逐项调整参数与返回类型。")
                    elif name == "fs.watch":
                        item.update(candidateContract="context.filesystem.watch",
                                    difference="异步有限元数据轮询近似，可能合并或遗漏两次轮询间的变化；只观察文件或目录直接条目。interval 0.01–60 秒，目录最多1000条，每视图64监听。回调失败停止，停用关闭；不是原生事件、递归监听或 DSH AbortSignal 协议，须显式 aclose。")
                    elif name in {"fs.writeText", "fs.editText"}:
                        item.update(suggestedContract="context.filesystem." + ("write_text" if name == "fs.writeText" else "edit_text"),
                                    difference="先 observe 取得内容修订号，显式 expected_revision；None 仅允许创建缺失文件。1MiB UTF-8 文本，edit 为字面匹配；合作调用按路径锁串行、原子替换。不能抵御绕过锁的外部写入；失败 may_have_changed 时先核对，不盲重试。")
                    elif name == "fs.streamText":
                        item.update(suggestedContract="context.filesystem.stream_text",
                                    difference="手工将 FsTarget 改为目录内路径；同步 Iterator[str]，显式 max_bytes≤64MiB、chunk_bytes≤64KiB。必须耗尽才验证完整文本，后部非 UTF-8/NUL 或普通文件变化可在已返回前缀后报错；yield 不保留文件句柄，仍无原子快照、异步取消或远程流。")
                    elif name == "fs.readByteRange":
                        item.update(suggestedContract="context.filesystem.read_byte_range",
                                    difference="手工把 FsTarget 改为目录内路径、range 改为关键字 offset/length；同步 bytes，length≤1MiB、区间端点在有符号64位范围，允许零长度与 EOF 短读；不穿过链接，无取消或快照。")
                    elif name == "fs.lstat":
                        item.update(suggestedContract="context.filesystem.lstat",
                                    difference="同步 FileInfo，只允许观察最终链接本身，不允许穿过根/上级链接；缺失抛 fs/not-found，不返回 undefined；没有 cwd/signal 参数。")
                    elif name in mapped:
                        item.update(suggestedContract="context.filesystem." + mapped[name],
                                    difference="手工将 FsTarget 改为目录内路径；同步调用、启动代撤回；读取必传 max_bytes≤1MiB；缺失 stat 抛错；列表有上限且无稳定排序，检查 truncated；拒绝链接。无取消或快照。")
                    elif name in {"workingDirectory.get", "workingDirectory.set", "workingDirectory.ensure"}:
                        # user:“继续，把 2 阶段都做完”+(持久执行目录保持原项目配置身份，调用方显式取固定执行视图)。
                        item.update(candidateContract="context.working_directory." + name.rsplit(".", 1)[1],
                                    difference="按session_id持久目录/CAS，set/ensure要求expected_revision，原项目不变且仅允许其内现有目录。插件用await context.for_session(session_id)取固定视图；主代理文件工具/Git/run_command在每次模型请求后、审批前固定路径/cwd，变化追加尾部通知。旧审批/进程不重定向。MCP等其余工具、子代理、即时通知及DSH事件重放仍有差异。")
                    else:
                        item.update(difference="未实现该 DSH 完整目标域方法或会话目录 set/ensure；需 agent 单独补齐，不可盲替换。")
                if kind == "services" and name in {"configEditor", "settings"}:
                    item.update(candidateContract="context.config", conversion="agent-required",
                                difference="仅当前插件文件快照、基础校验和条件整对象保存；不含 profile overlay、volatile 引用、secret 字段投影或热重载回滚。保存不代表应用。")
                if kind == "configMethods":
                    item.update(conversion="agent-required")
                    if name == "configEditor.edit":
                        item.update(candidateContract="context.config.replace",
                                    difference="人工改为先 read revision 再整对象保存，同步且 applied=false；不保留注释，不提供 DSH profile 应用/失败回滚事务。")
                    else:
                        item.update(difference="未实现 DSH 表单/volatile/分层重置/生成策略接口；保留待办，不能把文件读写当作相同 Settings 协议。")
                if kind == "services" and name == "credentials":
                    item.update(suggestedContract="context.credentials", conversion="agent-required",
                                difference="仅当前插件的同步字符串凭据引用；resolve/describe/set/unset 可人工适配。无全局环境回退、CredentialRecord/modifyRecord、跨插件读取或变更事件。")
                if kind == "credentialMethods":
                    item.update(conversion="agent-required")
                    if name in {"resolve", "describe", "set", "unset"}:
                        item.update(suggestedContract="context.credentials." + name,
                                    difference="POSIX 风格字符串名，当前 owner 命名空间，同步读取现有 DPAPI 存储；不解析 branded 引用或环境回退，set 空值拒绝。")
                    else:
                        item.update(difference="当前未实现授权/凭据记录、异步原子 modifyRecord 与元数据枚举契约，不能把对象序列化成字符串就视为兼容。")
                if kind == "services" and name in {"storage", "storageDomain"}:
                    item.update(candidateContract="context.storage", conversion="agent-required",
                                difference="当前仅插件所有的 SQLite JSON KV；DSH hub 后端/形式和带 schema、表、全局槽及变更事件的领域需重新设计，不能盲替换。")
                if kind == "storageMethods":
                    item.update(conversion="agent-required")
                    if name == "storageDomain.open":
                        item.update(candidateContract="context.storage.open",
                                    difference="仅可考虑人工重构为单元+不透明键。同步接口、正整数精确版本、无 schema/tables/global/后端路由/变更事件；持久写不随启动失败回滚。")
                    else:
                        item.update(difference="当前未实现 DSH backend/form 注册与挂载协议，保留 agent 待办，不生成空后端。")
                if kind == "services" and name in {"llm", "agentDefaultModel", "subagentModelSelection"}:
                    item.update(suggestedContract="context.models (read-only catalog subset)", conversion="agent-required",
                                difference="仅目录、精确引用和显式场景选择；模型记录 ID 与上游 ID 分离。无 stream/prepareCall/适配器注册、全局默认写入或子代理路由授权策略。")
                    if name == "llm":
                        item.update(suggestedContract="context.llm / context.models",
                                    difference="已有原生实际 complete、结构化异步 stream、估算和目录；固定项目/模型记录和有限输出/截止时间。仍需调整 DSH 消息、prepareCall、adapter 注册与路由协议。")
                if kind == "modelMethods":
                    item.update(conversion="agent-required")
                    mappings = {"llm.listModels": "context.models.list", "llm.resolveModelInfo": "context.models.resolve",
                                "agentDefaultModel.currentSelection": "context.models.select"}
                    if name == "llm.stream":
                        item.update(suggestedContract="context.llm.stream",
                                    difference="使用 Sunday LLMRequest 与 async with 管理的异步流；固定项目和模型记录，300 秒内截止、8MiB 输出、耗尽需终态。非 DSH 消息/适配器/prepareCall 协议，部分结果后仍可能失败，停用清理打开流。")
                    elif name in mappings:
                        item.update(suggestedContract=mappings[name],
                                    difference="只读 Python 元数据；按模型记录 ID 或唯一精确别名查询。select 必须明确 chat/study/background，不等价于进程级默认或会话最终模型。")
                    else:
                        item.update(difference="当前没有相同调用/写入/路由策略契约，保留 agent 待办；目录成员不代表子代理获准使用该路由。")
                if kind == "services" and name == "skills":
                    item.update(suggestedContract="context.skills.register / skill.list / load_skill", conversion="agent-required",
                                difference="仅同步登记内存文字技能，Python 参数与 model_invocable/user_invocable 策略需适配。现有磁盘技能优先；无 registerProvider、scope 层级、snapshot/invalidate 或 skills/change。")
                if kind == "skillMethods":
                    item.update(conversion="agent-required")
                    if name == "register":
                        item.update(suggestedContract="context.skills.register",
                                    difference="把定义对象拆为 name/description/content 和两个布尔策略；全局内存文字，不提供路径、作用域覆盖或远程加载器。")
                    elif name == "list":
                        item.update(suggestedContract="skill.list",
                                    difference="宿主管理目录 operation，列全部策略组合；模型和用户目录另按对应策略过滤，不是 DSH scope/cwd 异步发现协议。")
                    else:
                        item.update(difference="当前没有对应的提供方/快照/失效/读取协议；保留 agent 待办，不能伪造文件位置或声明支持远程来源。")
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
                if kind == "events" and name == "approval/request":
                    item.update(candidateContract="context.approvals.answer", conversion="agent-required",
                                difference="受管单终端回答者，不是 Cordis waterfall/agent-scoped next 链。必须按请求 plugin/session/turn 明确匹配；默认缺失或错误不放行。")
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
            for match in re.finditer(receiver + r"\s*\.\s*skills\s*\.\s*([\w$]+)\s*\(", text):
                add("skillMethods", match[1], match.start())
            for match in re.finditer(receiver + r"\s*\.\s*(llm|agentDefaultModel|subagentModelSelection)\s*\.\s*([\w$]+)\s*\(", text):
                add("modelMethods", match[1] + "." + match[2], match.start())
            for match in re.finditer(receiver + r"\s*\.\s*(storage|storageDomain)\s*\.\s*([\w$]+)\s*\(", text):
                add("storageMethods", match[1] + "." + match[2], match.start())
            for match in re.finditer(receiver + r"\s*\.\s*credentials\s*\.\s*([\w$]+)\s*\(", text):
                add("credentialMethods", match[1], match.start())
            for match in re.finditer(receiver + r"\s*\.\s*(configEditor|settings)\s*\.\s*([\w$]+)\s*\(", text):
                add("configMethods", match[1] + "." + match[2], match.start())
            for match in re.finditer(receiver + r"\s*\.\s*(fs|workingDirectory)\s*\.\s*([\w$]+)\s*\(", text):
                add("filesystemMethods", match[1] + "." + match[2], match.start())
            for match in re.finditer(receiver + r"\s*\.\s*compaction\s*\.\s*([\w$]+)\s*\(", text):
                add("compactionMethods", match[1], match.start())
            for match in re.finditer(receiver + r"\s*\.\s*(permissionPresets|approval)\s*\.\s*([\w$]+)\s*\(", text):
                add("permissionMethods", match[1] + "." + match[2], match.start())
            for match in re.finditer(receiver + r"\s*\.\s*(subprocess|shell|shellEnv)\s*\.\s*([\w$]+)\s*\(", text):
                add("processMethods", match[1] + "." + match[2], match.start())
            for match in re.finditer(receiver + r"\s*\.\s*(goals|schedule)\s*\.\s*([\w$]+)\s*\(", text):
                add("durableMethods", match[1] + "." + match[2], match.start())
            for match in re.finditer(receiver + r"\s*\.\s*(jobs|spillStore)\s*\.\s*([\w$]+)\s*\(", text):
                add("backgroundMethods", match[1] + "." + match[2], match.start())
            for match in re.finditer(receiver + r"\s*\.\s*userQuestions\s*\.\s*([\w$]+)\s*\(", text):
                add("questionMethods", match[1], match.start())
            for match in re.finditer(receiver + r"\s*\.\s*(agents|subagents)\s*\.\s*([\w$]+)\s*\(", text):
                add("subagentMethods", match[1] + "." + match[2], match.start())
            phase2_names = [row["dsh"] for row in catalog["services"] if row["phase"] == 2]
            for match in re.finditer(receiver + r"\s*\.\s*(" + "|".join(re.escape(name) for name in phase2_names) + r")\s*\.\s*([\w$]+)\s*\(", text):
                add("phase2Methods", match[1] + "." + match[2], match.start())
            for match in re.finditer(r"\bscrubbedParentEnv\s*\(", text):
                add("processMethods", "scrubbedParentEnv", match.start())
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
             "- 已验收的内存技能子集：agent_docs/plugin_skill_extensions.md；context.skills.register 复用原技能注册表，模型与用户调用策略分别生效，没有文件位置和文件授权。",
             "- 已验收的模型只读子集：agent_docs/plugin_model_access.md；context.models.list/resolve/select 保持项目、记录 ID 和场景边界，不调用模型、不写入选择。",
             "- 已验收的插件 JSON KV：agent_docs/plugin_storage_access.md；context.storage 使用原稳定插件数据目录；不等价于 DSH storageDomain，必须人工调整领域结构与同步写入。",
             "- 已验收的凭据引用子集：agent_docs/plugin_credentials.md；context.credentials.resolve/describe/set/unset，当前插件命名空间、同步调用、无环境回退或授权记录协议。",
             "- 已验收的配置文件子集：agent_docs/plugin_config_access.md；context.config.read/validate/replace，带修订号和基础校验，保存不代表运行时应用。",
             "- 逐项缺口：agent_docs/dsh_compatibility_matrix.md。",
             "- 分阶段验收与未完成项：agent_docs/dsh_compatibility_checklist.md；仅已通过行为验收的子集可以打勾。",
             "- 上游依据：deepseek-ai/deepseek-harness @ " + report["upstreamCommit"], "",
             "## 待移植", ""]
    for item in report["findings"]:
        lines.append(f'- [ ] `{item["file"]}:{item["line"]}` [{item["code"]}] {item["message"]}')
    lines.append("- 文件读取基础：agent_docs/plugin_filesystem_access.md；含 read_byte_range、最终链接 lstat 和有限同步 stream_text。条件修改、本地路径与轮询监听的最新范围见 plugin_phase2_runtime.md；无完整 FsTarget 或会话目录变更。")
    lines.append("- 已验收的手动压缩子集：agent_docs/plugin_compaction_access.md；context.compaction.compact_now 要求会话修订号，区分未压缩/已压缩/取消；失败先核对持久状态，禁止盲目重试。")
    lines.append("- 已验收的权限读侧：agent_docs/plugin_permission_access.md；context.permissions.catalog/read 只读目录和会话偏好，不返回授权或改变策略；Sunday auto 不等于 DSH Auto review。")
    lines.append("- 程序解析与环境基础：agent_docs/plugin_process_access.md；实际受管 spawn/run、PowerShell 与环境贡献的最新范围见 plugin_phase2_runtime.md，终端/远程/隔离等仍须单独移植。")
    lines.append("- 第二阶段持续补齐：agent_docs/plugin_phase2_runtime.md；条件文件修改、轮询监听、Windows Job进程、PowerShell/环境贡献、后台作业、长文本保存、实际LLM/流、目标/Arrange、会话查询、后端审批与管理。完整状态见 agent_docs/dsh_phase2_completion.md，不能因子集存在就勾选整个阶段。")
    lines.append("- 会话目录与恢复：agent_docs/plugin_session_recovery.md；目录/CAS与for_session保留原项目；主代理文件/Git/run_command按请求固定目标并追加目录通知。checkpoints复用原对话恢复/分叉；其余工具、子代理与DSH持久化/事件协议仍须适配。")
    lines.append("- 子代理持久成员：agent_docs/plugin_subagent_access.md；context.subagents.create/list/get/message/close共用原监督器，命名空间与request_id需显式移植。不是DSH根Agent或activation句柄，不把停用门面当作成员结束。")
    for kind in ("services", "events", "remotes", "slots", "promptMethods", "commandMethods", "skillMethods", "modelMethods", "storageMethods", "credentialMethods", "configMethods", "filesystemMethods", "compactionMethods", "permissionMethods", "processMethods", "durableMethods", "backgroundMethods", "subagentMethods", "questionMethods", "phase2Methods"):
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
              "- [ ] 嵌入式技能用 context.skills.register，转换 modelInvocable/userInvocable 并验证四种组合。磁盘技能优先，内存技能没有资源目录；registerProvider、scope、snapshot/invalidate 和 skills/change 另行移植。停用只阻止新加载，不清除已发送给模型的正文。",
              "- [ ] 模型查询用 context.models，区分记录 id 与 model_id，明确选择场景并处理同场景替换通知。不要把 list 当作路由授权，把 select 当作会话最终模型或全局写入；stream、prepareCall、适配器和子代理路由策略另行移植。",
              "- [ ] 持久状态可人工改为 context.storage 的 JSON KV，保留 expected_revision 和 unknown-state 处理；不要直接替换 storageDomain.open(spec)。schema、tables/global、compatibleVersions、后端路由和 domain/changed 仍需实现；配置与凭据不得混为一般状态。",
              "- [ ] 凭据引用用 context.credentials，describe 元数据不得替代 resolve；保留当前插件 owner，显式调整无环境回退与同步语义。readRecord/modifyRecord、事件与跨插件引用继续留缺口，不将凭据值写进配置、迁移报告或日志。",
              "- [ ] 配置候选保存可人工改为 context.config：先 read revision，保留完整对象，明确基础校验并处理 applied=false。DSH overlays/volatile/reset/secret 表单投影、重载失败回滚、注释保留仍需实现；旧界面尚未提交修订号，不据此声称所有客户端已防过期。",
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
