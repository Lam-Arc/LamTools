# 06 tool 工具系统 审计报告

审计日期：2026-08-13 ｜ 审计员：全区审计第 06 区 ｜ 仓库：E:\LamTools

## 1. 概况

本区覆盖 `core/src/lamtools_core/tool/` 全部 29 个文件（约 7869 行），包括：命令执行链（command.py / command_runner.py / command_tools.py）、审批系统（approval.py / approval_continuation.py / permission.py）、文件工具（workspace.py / workspace_files.py / document_normalize.py / spreadsheet.py）、子 agent（sub_agent_runner.py）、工作流工具（workflow_build_tools.py / workflow_tools.py）、搜索（search/ 包）、网络与图片（web_tools.py / image_tools.py）、MCP（mcp_tools.py）、注册与工具箱（__init__.py / default_toolbox.py / loadtools.py / git_tools.py / verification.py / durable_tools.py）。

总体评价：架构分层清晰（审批门 → prepare_call → execute 统一入口，`base_agent.py:403` 保证所有模型输出必经 `prepare_call`），防御意识较强（敏感模式、路径边界、文档炸弹防护、输出截断、进程树清理均有实现）。**但命令执行的路径沙箱与危险命令分类均为"字符串启发式"，可被 shell 语法轻易绕过，且 Windows 默认以完整 shell（Git Bash `bash -lc`）执行，这两点是本区最严重的缺陷**；此外 web_fetch 的 SSRF 面、工作流命令节点的审批真空、仓库配置投毒等构成第二梯队问题。

## 2. 问题清单

### S1（严重）

- **[S1] validate_command_paths 路径沙箱可被 shell 展开绕过 → 工作区外读写无审批**
  - 位置：`core/src/lamtools_core/tool/command.py:406-430`；调用点 `core/src/lamtools_core/tool/command_tools.py:194-204`
  - 问题：该校验把命令按 `shlex.split(posix=False)` 切分后，对含 `/`、`\`、`~` 或盘符的 token 做 `(work_root / value).resolve()` 词法归一判断。它假设"命令里的字面路径就是最终路径"，但 Windows 上命令实际经 Git Bash `bash -lc` 或 PowerShell `-Command` 在**完整 shell** 中执行，任何 shell 展开都绕过校验。实测（只读脚本验证）：
    - `cat ~/.ssh/id_rsa` → `~/.ssh/id_rsa` 解析为 work_root 内的字面目录，**校验通过**，shell 展开 `~` 后读取用户家目录私钥；
    - `cat $HOME/.ssh/id_rsa` → 同样通过（`$HOME` 被当字面目录名）；
    - `echo x > ~/.bashrc` → **校验通过**，shell 写入用户家目录 `.bashrc`；
    - 对照组 `cat /etc/passwd` 会被正确拦截——说明边界只在"字面绝对路径"层面有效。
    - 解释器参数同样全线穿透：`python -c "open(r'C:/x','w').write(...)"`、`bash -c '...'` 等，token 内不出现独立路径即不触发检查。
  - 影响：run_command 的"路径不越出工作区"承诺形同虚设；`regular` 组命令默认 `auto_allow`（approval.py:29-32），读家目录私钥、向工作区外写文件均可在**零人工确认**下完成。这是本区最直接的沙箱逃逸。
  - 修复建议：a) 对含 `~`、`$`、反引号、`$(...)`、`${...}` 或引号内路径的命令一律提升为 ask_user，不做启发式放行；b) 更彻底的做法是 Windows 不再用 `bash -lc`/`-Command` 整串执行，改为解析出的 argv 直接 exec（与 POSIX 分支一致），把 shell 特性（管道/重定向/展开）视为需要人工确认的高级操作；c) 若保留 shell，应显式拒绝任何含命令替换/变量/转义序列的命令，仅允许纯字面 token。

- **[S1] DANGEROUS_COMMAND_RE 危险命令分类可被 shell 语法绕过 → 审批门失效**
  - 位置：`core/src/lamtools_core/tool/approval.py:15-27`（正则）、`approval.py:99-105`（classify_command）、策略 `approval.py:29-32`
  - 问题：正则用 `(^|[;&|]\s*|\s)` 前缀 + `\b` 后缀匹配 `rm|del|...`，只认"前面是行首/空白/分隔符"的字面命令名。实测（只读脚本验证）以下形态**全部被分为 regular（默认 auto_allow）**：
    - `\rm -rf /`（反斜杠转义，bash 中等价于 rm）
    - `$(rm -rf /)`（命令替换）
    - `` `rm -rf /` ``（反引号）
    - `"rm" -rf /`（引号包裹）
    - `python -c "import os;os.system('rm -rf /')"`（解释器内嵌）
  - 影响：`rm`/`del`/`format` 等破坏性命令可零确认执行；叠加 S1-1 的 `~` 绕过后可静默删除工作区外文件（如 `\rm -rf ~/Documents`）。审批门对模型（可能被提示注入）的约束名存实亡。
  - 修复建议：分类前先剥离/拒绝 shell 元字符（`\`、`$`、反引号、`$(...)`、引号包裹的命令名）；凡命令串中出现转义或命令替换即强制 ask_user；根本方案是把"允许自动执行"收敛到可执行程序白名单（git/python/node/npm 等），其余一律人工确认。

### S2（中等）

- **[S2] web_fetch 无内网/云元数据地址过滤（SSRF），重定向跟随放大风险**
  - 位置：`core/src/lamtools_core/tool/web_tools.py:32-51`（`_is_loopback_url` / `_fetch_with_loopback_bypass`）、`web_tools.py:74-89`
  - 问题：只拦截 `file://` 和判定 loopback，`169.254.169.254`（云元数据）、RFC1918 内网段、IPv6 链路本地地址全部可直连；`follow_redirects=True` 使外部 URL 可 302 跳转到内网资源。loopback 分支 `trust_env=False` 反而是为了"放行本机服务"。
  - 影响：模型可借 web_fetch 探测/读取用户内网服务与云元数据（工具为 ASK_USER，但单次人工确认即可放行，且重定向目标不在确认范围内）。
  - 修复建议：增加私网段/链路本地/元数据地址黑名单（含重定向后的目标校验）；或将非公网目标强制要求显式用户确认并在结果中标注。

- **[S2] generate_image 参考图本地路径无工作区边界 → 任意本地文件上传第三方 API**
  - 位置：`core/src/lamtools_core/tool/image_tools.py:255-262`（`_reference_image_bytes`）
  - 问题：`reference_urls` 中的本地路径直接 `Path(ref)`/`work_root / ref` 后 `resolve()`，**未做 `is_within_path` 边界检查**；绝对路径（如 `C:\Users\...\.ssh\id_rsa`）或 `..\..\` 相对路径均可解析并读取，随后作为 multipart 上传到配置的生图 API（第三方服务）。
  - 影响：一次 generate_image 审批即可把工作区外任意文件内容外发；且参考图内容不经用户可见（除路径外）。
  - 修复建议：与 read_file 一致，先 `resolve_read_resource_path`/`validate_workspace_path` 边界校验；拒绝工作区外路径（或在 schema 描述中强制声明并在 UI 展示完整路径）。

- **[S2] 工作流 command/script 节点任意命令/Python 执行，审批真空且无路径校验**
  - 位置：`core/src/lamtools_core/tool/workflow_tools.py:73`（暴露工作流工具 `permission=AUTO_ALLOW`）、`core/src/lamtools_core/tool/workflow_build_tools.py:84-93`（config.command/script 自由写入）、执行端 `core/src/lamtools_core/runtime/workflow.py:989-1038`（`_run_command`：`cwd = cfg.get("cwd") or work_root` **无边界**、`env` 任意、无 DANGEROUS_COMMAND_RE、无 validate_command_paths）
  - 问题：模型建图（workflow_add_node/update_node，ASK_USER 一次性审批）后可写入任意 `config.command`（shell 串，与 run_command 同一 shell）或 `config.script`（任意 Python）；图一旦建好，调用暴露的工作流工具（AUTO_ALLOW）即执行这些命令，**每条命令不再经过任何命令审批/危险分类/路径校验**，`cwd` 还可指定任意目录。
  - 影响：审批只覆盖"改图"动作而非"执行"动作；注入提示词的模型可用"建图 + 运行"两步实现未审批的任意命令/代码执行。
  - 修复建议：a) workflow.run 执行 command 节点时复用 ApprovalGate 的 run_command 决策（危险命令 ask_user）；b) `cwd` 限定在 work_root 内；c) 工作流工具至少对含 command/script 节点的图执行要求人工确认。

- **[S2] websearch.jsonc 可被仓库内容投毒 → web_search（AUTO_ALLOW）执行仓库声明命令**
  - 位置：`core/src/lamtools_core/tool/search/factory.py:33-53`（配置加载：优先 `work_root/.lam/core/config/websearch.jsonc`，其次 `WEBSEARCH_CONFIG` 环境变量）、`factory.py:96-113`（`provider=subprocess` 直接用配置 command 构造内核）、`search/external.py:61-79`（`create_subprocess_exec(*command, json)`）
  - 问题：配置声明 `{"provider": "subprocess", "command": ["powershell","-c",...]}` 即可让 web_search 执行任意程序；该配置来源之一是**工作区仓库内的 `.lam/core/config/websearch.jsonc`**，而 web_search 是 AUTO_ALLOW 工具，模型一旦调用即触发。
  - 影响：打开恶意仓库 → 仓库自带配置文件 → 零审批执行任意命令（供应链式投毒，模型无需被诱导）。
  - 修复建议：subprocess/http 内核的配置只从用户级目录（非仓库内）读取；对 `work_root` 内的 websearch.jsonc 忽略 command/url 字段或要求人工确认。

- **[S2] 敏感文件硬阻断大小写绕过（Windows）+ read_file 对 .env/id_rsa 零拦截**
  - 位置：`core/src/lamtools_core/tool/approval.py:202-208`（`_check_hard_blocks` 子串匹配、**大小写敏感**）、`approval.py:189-190`（read_file AUTO_ALLOW 直接放行）
  - 问题：a) `.env` 阻断是 `pattern in path` 大小写敏感；Windows NTFS 大小写不敏感，实测 `.ENV`、`.Env` 绕过阻断（`_check_hard_blocks('write_file', {'path':'.../.ENV'})` 返回空 = 放行），而磁盘上 `.ENV` 就是 `.env`；b) 敏感模式只对 write/edit 生效，`read_file` 读 `.env`/`id_rsa`/`.git/config` 直接 AUTO_ALLOW（路径边界之外无任何检查）。
  - 影响：可写穿敏感文件保护（Windows 主平台）；工作区内 `.env` 等密钥文件可被模型直接读取并出现在对话/日志中。
  - 修复建议：`pattern in path.casefold()`；把敏感模式检查扩展到 read_file（或至少 `.env*`、`id_rsa*` 等密钥类）；在 schema 描述中明确 read_file 对密钥文件的策略。

- **[S2] active_tier 白名单短路危险命令分类**
  - 位置：`core/src/lamtools_core/tool/approval.py:162-174`（tier 分支直接返回 auto-approve）vs `approval.py:176-187`（run_command 命令策略分支）
  - 问题：设置了 `active_tier` 且 run_command 在该 tier 的 access 列表内时，`check()` 在 tier 分支**直接返回放行**，`DANGEROUS_COMMAND_RE` 的 ask_user 逻辑永远不会执行——`rm -rf /` 也自动批准。空 access 列表时（fall through）才走命令分类，行为不一致且与 S1-2 叠加后毫无兜底。
  - 影响：tiered 模式下危险命令分类完全失效（若管理员把 run_command 放进 full_edit 列表属常见配置）。
  - 修复建议：tier 放行前仍先执行命令分类；或文档明确"tier 列表即放弃命令级审批"，并在 UI 中提示。

### S3（轻微）

- **[S3] resume_approved 不重过审批门，仅信任持久化 state 中的 pending_call**
  - 位置：`core/src/lamtools_core/tool/sub_agent_runner.py:394-463`（用 state.metadata 的 pending_call 重建 ToolCall 并**伪造** `approval: {approved: True, auto_approved: True}` 元数据，经 auto_approve 工具箱直接 `execute`）；`default_toolbox.py:945-968`（execute 只查 blocked 标志与 disabled_tools，不查 permission tier）
  - 问题：审批后恢复路径不再校验工具权限（HARD_BLOCK 工具不在此列）；若 RuntimeCheckpointStore 持久化的 state 被篡改（或跨会话残留），任意工具/参数可被当作"已批准"执行。硬阻断工具（disabled_tools 之外，如 access_tools.jsonc 中 hard_block 的工具）在正常 prepare 路径会被 gate 拦截，但 resume 路径不会。
  - 影响：低概率但无防护的审批状态信任链；state 即权限。
  - 修复建议：resume 前用 ApprovalGate 重跑 `check(call.name, args)`（把 gate 决策并入自动批准元数据）；对 HARD_BLOCK 工具直接拒绝。

- **[S3] 工作流工具输出无大小截断**
  - 位置：`core/src/lamtools_core/tool/workflow_tools.py:192-206`（`json.dumps(output, ensure_ascii=False, default=str)` 全量入 content）
  - 问题：workflow.run 的 output 可能是数 MB/任意大小，直接拼接进 ToolResult.content，无截断（对比 run_command 的 50k、web_fetch 的 30k 截断）。
  - 影响：一次工作流运行即可撑爆上下文窗口/消息体。
  - 修复建议：按 `max_text_length` 截断并标注 `[... truncated]`。

- **[S3] read_file 图片 base64 无体积上限**
  - 位置：`core/src/lamtools_core/tool/workspace_files.py:171-184`
  - 问题：图片文件整读并 base64 进 metadata（注释明确"不设体积上限"），文本内容截断对 data URL 不生效；超大类图片（数百 MB）直接进内存与消息。
  - 影响：内存/带宽/上下文消耗不受控。
  - 修复建议：给图片读取设字节上限（如 20MB），超出返回提示而非 base64。

- **[S3] run_command timeout 无上限**
  - 位置：`core/src/lamtools_core/tool/command_tools.py:150-164`
  - 问题：`timeout` 仅校验 `<= 0`，模型可传任意大值（如 86400×365），命令挂起不受约束。
  - 影响：单次调用可长时间占用执行线程；配合后台模式可无限运行。
  - 修复建议：设上限（如 600s）并拒绝超限值。

- **[S3] POSIX 平台进程树未整体终止，孙进程残留**
  - 位置：`core/src/lamtools_core/tool/command.py:60-72`（`terminate_process_tree` 非 Windows 分支只 `process.kill()` 直接子进程）、`command.py:243-244`（reader 线程 join(timeout=1) 超时即泄漏）
  - 问题：Windows 用 `taskkill /T` 杀整树是正确的；POSIX 只杀 bash 壳，`bash -lc 'cmd &'` 或 spawn 的后代进程继续运行并可能持有 stdout 管道，导致 reader 线程永久阻塞泄漏。
  - 影响：超时/取消后残留进程（资源泄漏、测试/服务环境脏化）。
  - 修复建议：POSIX 用 `os.setpgrp` + `os.killpg` 杀进程组；reader 线程改 daemon + 非阻塞或加管道关闭兜底。

### S4（建议）

- **[S4] spreadsheet.py 的 write_spreadsheet_tool 为死代码**
  - 位置：`core/src/lamtools_core/tool/spreadsheet.py:111`（`write_spreadsheet_tool`）
  - 问题：全仓 grep 除本文件外无任何引用，未注册进 default_toolbox（handlers/durable/workflow 均无）；SPREADSHEET_WRITE_INPUT_SCHEMA 亦未被 DEFAULT_TOOL_DEFINITIONS 使用。实现本身（temp+os.replace 原子写、路径/单元格校验）质量良好。
  - 影响：功能未上线；审计/维护成本；schema 与代码漂移风险。
  - 修复建议：要么接入 default_toolbox（ASK_USER + 路径边界 + 敏感模式），要么删除。

- **[S4] command_tools.py 重复导入 _run_subprocess**
  - 位置：`core/src/lamtools_core/tool/command_tools.py:17` 与 `:33`
  - 问题：同一符号从 command 与 command_runner 各导一次，后者覆盖前者（两者实为同一对象），属死导入。
  - 影响：无功能影响；可读性。
  - 修复建议：删除 `:33` 的重复导入。

- **[S4] approve_for_session 被归一化为 approve，会话级审批未在本模块持久化**
  - 位置：`core/src/lamtools_core/tool/approval_continuation.py:26-36`、`core/src/lamtools_core/app/live_approval.py:12`
  - 问题：`approve_for_session` 与 `approve_once` 都归一化为 `approve`，本模块不存在"会话内后续审批自动通过"的状态记录（若依赖内核侧另行实现，则此处命名与行为容易误导）。
  - 影响：偏保守（更安全），但与 UI 语义可能不一致；若内核未实现会话级豁免，用户预期落空。
  - 修复建议：确认内核是否消费 `approve_for_session`；若不支持，UI 移除该选项或本模块显式记录会话豁免集合。

- **[S4] prepare_call 中 arrange 只读操作覆盖决策，绕过 tier"未在列表即审批"逻辑**
  - 位置：`core/src/lamtools_core/tool/default_toolbox.py:920-926`
  - 问题：`arrange` 的 list/get 在 gate 已返回 requires_approval（tier 模式下未列入 access 列表）时被无条件覆盖为放行；只读动作影响有限，但与 tier 语义不一致。
  - 影响：tiered 模式下 arrange list/get 恒免审批。
  - 修复建议：仅在 `decision.blocked` 为 False 且 tier 未设或 access 列表为空时覆盖。

- **[S4] run_subprocess_blocking 取消分支 communicate(timeout=2) 超时无兜底**
  - 位置：`core/src/lamtools_core/tool/command.py:100-110`、`:125-134`
  - 问题：取消分支 `process.communicate(timeout=2)` 若再超时直接抛出（被调用方 suppress），进程可能未真正终止且无 `kill()` 兜底（对比 TimeoutExpired 分支有 kill 兜底）。
  - 影响：极端情况下取消后进程残留。
  - 修复建议：取消分支同样加 kill 兜底。

- **[S4] search/external.py 超时后 kill 未回收进程**
  - 位置：`core/src/lamtools_core/tool/search/external.py:71-74`
  - 问题：`asyncio.TimeoutError` 分支 `proc.kill()` 后未 `await proc.communicate()`/`wait()` 即 raise，子进程可能残留（POSIX 僵尸），且 `_search_subprocess` 无 cwd/env 约束（外部工具配置域内）。
  - 影响：极端情况下进程残留；Task 销毁告警。
  - 修复建议：kill 后 `await proc.communicate()` 再抛。

## 3. 该区 Top 3 问题

1. **run_command 路径沙箱可绕过（S1）**：`validate_command_paths` 对 `~`/`$VAR`/`$(...)`/解释器参数全线穿透，Windows 完整 shell 执行下可零审批读写工作区外文件（已实测复现）。它是本区唯一声称的"路径边界"，失效即沙箱失效。
2. **危险命令分类可绕过（S1）**：`DANGEROUS_COMMAND_RE` 被 `\rm`、`$(...)`、反引号、引号、`python -c` 轻易绕过（已实测复现），`rm -rf` 无需人工确认；与 S1 叠加可静默破坏工作区外数据。
3. **审批真空链：工作流命令节点 + 仓库配置投毒 + SSRF（S2 组）**：workflow 暴露工具 AUTO_ALLOW 执行任意命令节点、`websearch.jsonc` 仓库投毒执行任意程序、web_fetch 可触达内网/云元数据——三者均为"设计上需要权限、实现上无第二道闸门"的审批缺口。

## 4. 亮点

- **审批门分层设计**：HARD_BLOCK 敏感模式 → 路径边界 → tier/命令策略三级检查集中在一个 `ApprovalGate.check`，且 `prepare_call` 为唯一入口（`base_agent.py:403`），执行端 `execute` 校验 blocked 标志，校验与执行分离但一致；`question` 工具绕过 gate 强制人工输入的设计正确。
- **命令执行工程细节扎实**：全部走 argv 列表（实际无 `shell=True` 路径）；Windows `taskkill /T /F` 杀进程树；超时/取消双路径处理；输出 50k 截断；后台 readiness probe 用随机 token 文件防"服务器服务了错误目录"、端口占用预检、`readiness_url` 限制 localhost。
- **文件工具边界与原子性**：`validate_workspace_path`/`is_within_path` 的 resolve + 边界判定正确（能挡 `..` 与符号链接）；spreadsheet 用 temp + `os.replace` 原子写；DOCX/XLSX 有 zip 炸弹防护（条目数/展开体积上限）、XLSX 关系目标穿越防护、PDF 页数上限。
- **文档内容可信标注**：DOCX/PDF/XLSX 归一化统一加 `[UNTRUSTED DOCUMENT CONTENT]` 声明与限制说明，防止文档内容劫持指令优先级。
- **子 agent 防失控**：禁用 `sub_agent` 递归、同任务失败去重（`_failed_sub_agent_calls`）、死亡场景转发、capability-aware 附件拆分。
- **web_fetch 基础防护**：拦截 `file://`、loopback 专用无代理通道、`expect` 文本校验、30k 截断。

## 5. 审计范围与方法

- **范围**：`core/src/lamtools_core/tool/` 下全部 29 个文件（`__init__.py`、approval*.py、command*.py、default_toolbox.py、document_normalize.py、durable_tools.py、git_tools.py、image_tools.py、loadtools.py、mcp_tools.py、permission.py、spreadsheet.py、sub_agent_runner.py、verification.py、web_tools.py、workflow_build_tools.py、workflow_tools.py、workspace.py、workspace_files.py、search/ 7 文件）。
- **方法**：全文件逐行通读；对关键断言用只读 Python 片段实测复现（路径校验绕过、危险命令分类绕过、敏感模式大小写绕过，均为 `python -c` 只读验证，未执行任何工具/命令）；交叉验证调用链（`prepare_call` 唯一入口、`resume_approved` 执行路径、`websearch.jsonc` 加载来源、工作流命令节点执行端）；grep 确认死代码（spreadsheet、重复导入、`format_mcp_result`/`clean_mcp_arguments` 实际使用方）。
- **约束**：全程只读，未修改/创建/删除任何代码文件，未运行 pytest 与服务；执行端 `runtime/workflow.py` 仅作为工作流工具的影响链路被引用，不在本区正式范围。
