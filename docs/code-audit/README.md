# LamTools 全面代码审计 · 汇总索引

- 审计日期：2026-08-13
- 范围：Core（Python 后端 52.3k 行 + UI 34.2k 行 + Tauri 桌面壳 + 全部测试 43.2k 行）+ website/（1.9k 行）+ 依赖 CVE（联网）+ CI/仓库卫生
- 方法：24 个只读审计 agent 分 4 波并行（Wave1 后端核心 8 / Wave2 配置·集成·测试·发布 6 / Wave3 前端+桌面 6 / Wave4 交叉·外围·website 4），统一严重度口径（S1=严重缺陷/安全隐患，S2=中等，S3=轻微，S4=建议），统一输出格式（概况 / 问题清单 file:line / Top3 / 亮点 / 方法），关键结论均经只读复现或交叉核对。
- 排除：`archive/members/`（已归档）、`core/data`、`core/.lam`、`cp2-8`、`checkpoint-data*`、`dist`/`build`/`node_modules`、`e2e/real-task-runs`、PyInstaller 生成物。
- **审计不改代码**：本目录 24 份分区报告为唯一产出，修复按本文档第 4 节批次另行开工单。

## 1. 统计总览

| # | 分区报告 | S1 | S2 | S3 | S4 | 合计 |
|---|---|---|---|---|---|---|
| 01 | [live 协议体系](01-live-system.md) | 1 | 3 | 7 | 6 | 17 |
| 02 | [Agent 生命周期](02-agent-lifecycle.md) | 0 | 2 | 6 | 6 | 14 |
| 03 | [HTTP 服务层](03-http-server.md) | 3 | 4 | 4 | 4 | 15 |
| 04 | [数据库持久化层](04-db-layer.md) | 0 | 2 | 7 | 6 | 15 |
| 05 | [kernel 主循环](05-kernel.md) | 0 | 2 | 8 | 10 | 20 |
| 06 | [tool 工具系统](06-tool-system.md) | 2 | 6 | 5 | 6 | 19 |
| 07 | [runtime 编排与事件](07-runtime-event.md) | 0 | 5 | 12 | 6 | 23 |
| 08 | [CLI 与入口模块](08-cli-entry.md) | 0 | 3 | 6 | 11 | 20 |
| 09 | [配置体系](09-config-system.md) | 0 | 3 | 7 | 5 | 15 |
| 10 | [LLM 适配层](10-llm-layer.md) | 0 | 1 | 8 | 8 | 17 |
| 11 | [后端小包合集](11-small-packages.md) | 0 | 4 | 13 | 9 | 26 |
| 12 | [安全专项](12-security.md) | 0 | 4 | 3 | 2 | 9 |
| 13 | [core 测试质量](13-core-tests.md) | 1 | 3 | 7 | 5 | 16 |
| 14 | [构建/发布链](14-build-release.md) | 0 | 1 | 5 | 10 | 16 |
| 15 | [MessageView 渲染核心](15-messageview.md) | 1 | 1 | 5 | 8 | 15 |
| 16 | [ChatThread 与状态层](16-chatthread-store.md) | 0 | 1 | 3 | 11 | 15 |
| 17 | [设置与编辑组件](17-settings-editors.md) | 0 | 2 | 12 | 7 | 21 |
| 18 | [工作流与运行面板](18-workflow-panels.md) | 0 | 6 | 8 | 9 | 23 |
| 19 | [外壳/会话/composables](19-shell-composables.md) | 0 | 3 | 15 | 6 | 24 |
| 20 | [Tauri 桌面壳](20-tauri-desktop.md) | 0 | 2 | 4 | 7 | 13 |
| 21 | [前端契约测试](21-ui-tests.md) | 0 | 3 | 5 | 3 | 11 |
| 22 | [website 官网](22-website.md) | 0 | 1 | 5 | 9 | 15 |
| 23 | [依赖安全与健康](23-dependencies.md) | 1 | 4 | 2 | 1 | 8 |
| 24 | [CI 与仓库卫生](24-ci-repo-hygiene.md) | 0 | 3 | 3 | 7 | 13 |
| | **合计** | **9** | **69** | **160** | **162** | **400** |

## 2. 总体结论

架构与工程质量在同类产品中属上乘：写路径统一走 `SQLiteWriteCoordinator`（BEGIN IMMEDIATE + 乐观锁）、审批门三级分层（HARD_BLOCK → 路径边界 → tier/命令）、UI 投影两级缓存 + part 级 v-memo 隔离、测试纪律（无快照、无真实网络、隔离干净）、全历史无真实密钥入库、版本 5 处一致。**没有结构性烂账，问题集中在四类主题**：

1. **安全主题（最重）**：本地服务零鉴权 + CORS 全开 + WS 无 Origin 校验（03），叠加审批门可绕过（03）、命令沙箱可绕过（06）、SPA 任意文件读取（03）、hook 信任门一键绕过（12）——恶意网页可完全控制本机 agent，是当前最大的系统性风险，且 20 区确认"随机端口"不构成防护。
2. **容错主题**：多处"旁路/事后"失败被放大为整轮失败或状态卡死——事件实时持久化失败杀死整轮（02）、hook 脏 JSON 杀死 run（05）、循环两端异常无收敛（05/02）、重试 100×360s 最坏 10 小时（05/10）、`tool_progress` 强制 continue 可无限循环（05）。
3. **契约断裂主题**：前后端契约失配导致功能 100% 失效或静默无效——主线消息无 `metadata.live` 使流式渲染优化整体失效（15）、once 触发器 100% 失败（18）、NodeEditCard 超时绑错字段（18）、AI agent 工具集勾选无效（18）、`turn.start` 忽略 `include_snapshot:false`（01）、attachment upload 必崩（08）。
4. **漂移与死代码主题**：文档/脚本/清单与实现漂移（14/20/24：patch-nsis、installer 旧模板、僵尸 CI、e2e 指向已归档 Writer）、大量死代码（02/10/11/16/18/21/22）、测试与已知缺陷脱节（13/21：`tool_progress`、快照前事件丢弃、hook 失败注入全部零覆盖）。

## 3. Top 10 高优先级问题（跨区）

1. **[S1·03] 零鉴权 + CORS `*` + WS 无 Origin → 任意网页可驱动本机 agent（RCE 面根因）**
   `app/factory.py:97-103`（`allow_origins=["*"]`+credentials）、`app/live_router.py:92-103`（WS 无来源校验）、全路由无鉴权（默认绑定 127.0.0.1:5172）。20 区确认随机端口只是发现门槛。DNS rebinding 可扩至局域网。
2. **[S1·03+06] 审批门可绕过：`auto_approve` 直通 + 危险命令/路径沙箱可被 shell 语法绕过（已实测）**
   `live_operations.py:705-722` 客户端可声明 `auto_approve` 且 `approval.respond` 可自答；`tool/approval.py:15-27` 的 `DANGEROUS_COMMAND_RE` 被 `\rm`/`$(...)`/反引号/`python -c` 绕过；`tool/command.py:406-430` 路径沙箱被 `~`/`$HOME`/解释器参数穿透。组合成"无监督任意命令执行"。
3. **[S1·03] SPA 回退路由任意文件读取**
   `app/factory.py:166-172`：`resolved / filename` 无 containment 校验，`/%2e%2e/%2e%2e/...` 可读任意本地文件（含配置 api_key）。
4. **[S1·01] 等待审批的 turn 被 `_ensure_turn_terminal` 误标 completed → 队列未批准自放行 + 双 turn 并发 + 审批被消费无法重试**
   `app/live_operations.py:1835-1878`：守卫只排除 `{completed, idle}`，waiting 状态被当作已完成；排队项在批准前自动派发，新旧两个 kernel 并发，旧审批请求被新 turn 顶掉。
5. **[S1·15] 主线消息从不打 `metadata.live` → live 流式渲染路径在主流程整体不生效**
   `appServer/selectors.ts:113-120` 只写 processMetrics、`workbenchProjection.ts:208` 仅透传；全库唯一打标是两处无 parts 的占位（selectors.ts:261、useCoreWorkbenchController.ts:122）。主消息实际走 history 分支的"每 tick 全量 markdown 重解析"，阶段 3/4 流式优化形同虚设，工具过程流不可见。
6. **[S1·13+05] `tool_progress` 强制 continue 无轮次上限（可无限循环）且测试 0 覆盖**
   `kernel/loop.py:1066-1069` 无条件覆盖 Kit 的 wait/failed 终局决策；`tool_progress_blocked_rounds` 不统计该路径；tests/ 全目录 0 引用（已复核）。
7. **[S2·03+11] 附件无大小上限 + session_id 目录越界写 + `/open` 触发本机执行**
   `http_agent_app.py:620-628` 无大小限制；`attachment/store.py:17-18` session_id 直拼路径（`..` 可越界）；`http_agent_app.py:713-718` 无鉴权端点可"默认程序打开"上传的可执行文件。
8. **[S2·05+02] hook 失败未隔离 + 循环两端无异常保护 + 取消路径无统一收敛**
   `plugins/engine.py:202-215` 的 `json.loads` 无捕获，脏 JSON 杀死整个 run；`kernel/loop.py:421-466/1172-1219` 循环外关键路径裸露（state 卡 running / 结果丢失）；`task.cancel` 路径跳过 on_run_end/Stop hook/终端事件（loop.py:288-296）。
9. **[S2·10+05] 4xx 被当瞬时错误重试 10 次；重试最坏 100×360s ≈ 10 小时且无总时长/步数硬上限**
   `llm/retry.py:39-71` 只按类型名/消息文本分类，`cli.py:187-188` 把 >=400 全压成 RuntimeError → 401/403 重试 10 次（~34s 无效等待）；`policy.py:17-22` `model_retries=100`；kernel 无 run 级截止，非流式路径合作式取消不生效。
10. **[S2·09+12] 配置面三连：id 路径穿越 + base_url 可改致密钥外带 + settings 可改权限**
    `config/model_store.py:258/provider_store.py:235` 的 id 直拼文件名（可写任意 .jsonc）；`config/operations.py:346-356` 保留 api_key 可任意改 base_url（下次请求密钥定向外发，不依赖零鉴权）；`settings.update` 可把 permission_mode 改为 full_edit。

**紧随其后**（按修复优先级）：`arrange` 任务重复执行组（07：租约重领/同步 executor/取消不落库/recover_running 无属主校验）、快照前事件丢弃且不自愈（16）、hook.trust_all 一键信任 + plugin hook 命令注入（12）、core attachment upload 必崩（08，一行修复）、迁移 DROP COLUMN 缺索引清理旧库无法启动（04，一行修复）、MEMORY.md 重写丢人工编辑（11）、once 触发器 100% 失败（18）、LoadTools 编辑无法保存（17）、移动端抽屉 CSS 合并丢失（19）、pypdf 约束过低 19 条 DoS 公告（23，一行修复）。

## 4. 修复批次建议

### P0 · 立即（安全与数据完整性，建议一周内）

| 项 | 说明 | 出处 |
|---|---|---|
| 1 | 服务端 Origin/Host 校验 + CORS 白名单（`tauri://localhost`、`http://127.0.0.1:*`）+ WS 来源校验；启动随机 token 方案可后置 | 03 S1 / 20 S2 |
| 2 | SPA 回退路由 containment 校验（`resolve()` + `relative_to`） | 03 S1 |
| 3 | `auto_approve` 仅限已鉴权调用方；`approval.respond` 绑定发起连接；`settings.update` 对 runtimeControls 加门控 | 03 S1/S3 |
| 4 | 命令审批重做：危险命令分类与路径沙箱对非字面命令（`~`/`$`/反引号/`$(...)`/引号包裹）一律 ask_user；收敛为可执行程序白名单 | 06 S1×2 |
| 5 | model/provider id 白名单净化（拒绝 `./\` 与路径分隔符） | 09 S2 |
| 6 | `_ensure_turn_terminal` 排除 waiting 状态（守卫改为校验该 turn 自身已终端） | 01 S1 |
| 7 | `pypdf>=6.15.0`（一行） | 23 S1 |
| 8 | `cli.py` 补 `from urllib.parse import quote`（一行）+ 冒烟测试 | 08 S2 |
| 9 | `_migrate_core_app_schema` 补 `DROP INDEX IF EXISTS ix_core_arrange_jobs_project_id`（一行）+ 迁移整体 try/except | 04 S2 |
| 10 | `hook.trust_all` 移除或改为逐个确认；plugin hook 命令模板改 argv 执行（消除 `create_subprocess_shell`） | 12 S2 |
| 11 | 附件：session_id 白名单正则 + 上传大小上限（50MB）+ `/open` 端点鉴权/移除 | 03 S2 / 11 S2 |

### P1 · 近期（功能正确性与数据丢失，建议一个月内）

- **15 区**：投影层为运行中 turn 的最后一条 assistant 消息打 `metadata.live`（含回归测试）
- **18 区**：once 触发器对齐后端 `date/time/timezone`；NodeEditCard 超时绑定改 `timeout`；AI agent 工具集后端透传或移除 UI
- **16 区**：`!runtime.state` 时挂起事件而非丢弃；`shouldHydrateSnapshot` 增 core.items 内容指纹；合并批去重改为按 id 过滤
- **05/13 区**：hook 失败隔离（`_decision_from_text` 捕获）+ 循环两端异常收敛（`_finalize_run` 统一正常/取消路径）+ `tool_progress` 轮次上限 + 补全部回归测试
- **07 区**：arrange 重复执行组——同步 executor 改 `asyncio.to_thread`、租约 fencing（occurrence 代次校验）、`cancel` 原子落库、`recover_running` 仅回收过期租约
- **02 区**：并行同名 sub_agent 串行化（per-session 锁）；`_finalize_run` 覆盖 task.cancel 路径
- **11 区**：MEMORY.md 重写保留未识别原文；WorkflowStore.delete 限定作用域
- **17 区**：LoadTools dirty 追踪；HooksEditor 禁止解析失败兜底 `{}` 写回；imagegen api_key 掩码 + 留空保留
- **19 区**：layout.css 移动端抽屉规则从 worktree 合并回主干；stopGraceTimer 加 onScopeDispose
- **10/08 区**：4xx 结构化分类（401/403/400→fatal）；Retry-After 兑现；tokens fast 模式 CJK 加权
- **05 区**：`kernel_steps` 上限 + 浅拷贝（O(n²)）；run 级总步数/时长硬上限
- **08 区**：checkpoint 外部路径备份改独立命名空间（回滚不再整体失败）；blob GC
- **14 区**：release.yml 加 tag↔版本一致性校验；spec hiddenimports 与模块树同步（CI 检查）；`update.check` 异步化
- **24 区**：删除僵尸 `core/.github/workflows/ci.yml`；`dist-core-app/` 移出跟踪；e2e/ 重写或归档
- **22 区**：website package.json 补 marked/dompurify/katex/mermaid；`complete` 改 `onComplete`
- **20 区**：卸载器"删除应用数据"指向 `$INSTDIR\.lam`；单实例保护；后端崩溃检测与提示
- **21 区**：补"快照前事件丢弃"回归用例；tsconfig.test + @types/node 纳入类型检查

### P2 · 计划（清理与加固）✅ 已完成（详见第 7 节进度跟踪）

- **死代码清理**：`sub_session.py`（02）、`llm/adapter.py` 与 helpers 非 profile 归一化（10）、`spreadsheet.write_spreadsheet_tool`（06）、`FloatingApprovalCard.vue`（21）、`mock/session-script.ts`（22）、`normalizeDeliveryRecord`/`isFinalAssistantContentItem`（16）、`patch-nsis.ps1`/`start.bat`/`kill-*.ps1`/`installer/installer.nsi` 旧模板（14/20/24）、`_safe_relative_path` 等（08）、`emit_debug_events`/`_emit_stream_part.raw`（05）
- **配置容错统一**：jsonc 读取统一 `utf-8-sig`（BOM）；三套注释剥离器统一为 profiles 版；配置写入统一 tmp+rename 原子写；hooks.json 结构错误降级为跳过；settings 损坏保留 .bak（09/11/17）
- **测试补齐**：`durable_tools.py`/`workflow_build_tools.py` 契约测试、forceReset 三态、`history_compacted` payload、mermaid 多实例、once 触发器、checkpoint 外部路径回滚（13/21）
- **依赖**：npm lock 刷新（mermaid 11.16.1、dompurify 3.4.13、nanoid 3.3.17+、postcss 8.5.23+）；katex/marked 等 patch 跟进；PyInstaller 版本固定（23/14）
- **CI/仓库卫生**：`git diff --check` 修正、concurrency/timeout-minutes/pip cache、README 徽章版本、.worktrees/ 入 .gitignore、obs-profile.json 移出跟踪、lamtools_cli.py 过期注释（24）
- **安全加固（纵深）**：安全响应头、WS 消息大小/深度上限、请求体上限、health/配置接口路径脱敏、provider `extra` 脱敏、`settings.get` imagegen 掩码、密钥文件 chmod 0o600（03/12）
- **05/07 S4 系列**：`backup_file` 产品分支下沉、turn_count 口径、pending_approval 清理、eval 条件表达式沙箱声明、`$VAR` 前缀碰撞、hub 修剪后 seq 单调
- **20/22 S4**：CSP + asset scope 收敛、capabilities 最小化、双根 env 契约统一、website 源码入库决策

## 5. 亮点（值得保持的设计）

- **安全基线干净**：全 git 历史无真实密钥；无 pickle/yaml；无 shell=True 主路径（唯一例外是 plugin hook 模板，见 P0-10）；工具证据回传前脱敏（`base_agent.py:61-66`）。
- **写路径工程**：`SQLiteWriteCoordinator`（进程内锁 + BEGIN IMMEDIATE + 退避）从根上解决 `database is locked`；revision 乐观锁贯穿 runtime/goal/arrange；事件 `(thread_id, seq)` 唯一约束；崩溃恢复（`recover_stale_active_turns` + `force_reset` 逃生舱）成体系。
- **审批门分层**：HARD_BLOCK 敏感模式 → 路径边界 → tier/命令策略，`prepare_call` 唯一入口、校验与执行分离一致；`ApprovalResolutionLifecycle` 的 claim→durable→terminal 顺序约束。
- **UI 性能工程**：投影两级缓存 + 消息级指纹 + part 级 v-memo + 增量分段渲染 O(tail)/tick + 快照 hydrate 跳过判定，配合 56MB 线程实测数据，是目前 repo 内最完整的性能文档化实践（`docs/core-ui-streaming-perf.md`）。
- **测试纪律**：core 103 文件全假 LLM/无网络、conftest 单一 autouse 隔离；ui 321 用例零快照、`scheduleFrame` 确定性驱动、回归注释文档化；CI 链路（typecheck→contract→build→pytest）完整。
- **发布链**：版本 5 处一致（bump-version.ps1 单点）、单一 PyInstaller spec、CI 真冒烟（`/api/health` 轮询）、`.lam` 不打包用户配置不覆盖、更新走"检测+引导下载"不静默安装。

## 7. 修复进度跟踪（2026-08-13 起）

**P0 批次（11 项）已完成**：Origin 白名单 + WS 来源校验 + SPA containment（03）、auto_approve 门控 + approval.respond 线程绑定 + settings 值域校验（03/12）、命令审批 shell 结构强制 ask_user + 路径沙箱拒绝展开（06）、config id 白名单（09）、_ensure_turn_terminal 排除 waiting（01）、pypdf>=6.15.0 / cli quote / 迁移 DROP INDEX（23/08/04）、hook.trust_all 移除 + hook 命令 argv 化（12）、附件 session_id 白名单 + 50MB 上限 + open 危险类型拒绝（03/11）。新增回归测试约 25 个；全量 pytest 1350 通过。

**P1 批次（13 项）已完成**：P1-1 metadata.live 接线（15）、P1-2 契约修复 once/timeout/AI 工具集（18）、P1-3 状态层快照前事件挂起 + hydrate 指纹 + 合并去重（16）、P1-4 hook 失败隔离 + tool_progress 上限（05/13）、P1-5 arrange 重复执行组（07）、P1-6 统一终端收敛 + 取消路径 usage（02/05）、P1-7 小包（MEMORY.md 保留人工内容/WorkflowStore 作用域+slug 唯一化/MCP 泄漏+消息上限/plugins 容错/JSONC 字符串感知/dreaming 死分支修复/hub TTL+gap，11）、P1-8 设置编辑（LoadTools dirty 追踪+HooksEditor 解析失败中止+imagegen 密钥打码+分区 KeepAlive 保活+关闭确认，17）、P1-9 外壳（移动端抽屉 CSS 恢复+快捷键焦点豁免+文件树竞态+对话框焦点管理+IME 守卫，19）、P1-10 LLM/CLI（4xx 结构化分类+Retry-After 兑现+流式 finish_reason 折叠+checkpoint 外部路径跳过+回滚真备份补偿，10/08）、P1-11 发布链（release.yml tag↔5 处版本校验+bump 失败中断+spec hiddenimports 同步+僵尸 CI 删除+dist 移出跟踪+PYTHONPATH，14/24）、P1-12 Tauri（去 reload 孤儿+单实例+崩溃检测横幅+卸载器删除目标+CSP+asset scope 收敛，20）、P1-13 测试链与 website（tests 首次纳入 vue-tsc 全量修复 100+ 类型错误+forceReset/todo_update 回归测试+website 依赖声明+anime v4 onComplete+active-turn id 约定，21/22）。

**已知遗留（已全部清零）**：`tests/test_core_live_client_e2e.py::test_core_app_server_client_runs_live_operation_matrix_against_real_websocket_server` 曾因取消路径无统一终端收敛导致 `KeyError: 'usage'`（cancel/steer 后 turn 缺 usage 事件），已随 P1-6 修复（`_finalize_run` 共享正常/取消收敛 + `runtime.cancelled` 事件替代 `runtime.failed`，cancel/failed 的 usage 随 terminal 事件投影落库）。当前无已知遗留失败；全量 pytest 1373 通过（新增回归测试 23 个），UI vitest 322 通过，typecheck 三链（src/demo/tests）全绿。

**P2 批次（进行中）**：
- **P2-1 死代码清理（已完成）**：cli.py 死函数 3 个（`_safe_relative_path`/`_non_empty_line_count`/`_fallback_document`）+ 自导入 4 处、`FloatingApprovalCard.vue`（21）、`mock/session-script.ts`（22）、`patch-nsis.ps1`/`start.bat`/`installer/installer.nsi` 旧模板（14/20/24）、spec 幽灵模块检查脚本改为 modules∪packages 判定
- **P2-2 配置容错统一（已完成）**：`load_jsonc` utf-8-sig（BOM 容错）+ 字符串感知 `strip_trailing_commas` 单实现复用（10）、`atomic_write_text` 统一 tmp+os.replace 原子写 + settings 损坏 rename .bak（09/17）、imagegen 密钥掩码 + 留空保留 + `_is_project_source` 作用域推断（17）
- **P2-3 测试补齐（已完成）**：`test_durable_tools.py`（12）+ `test_workflow_build_tools.py`（12）+ `test_workflow_watcher.py`（4）+ `test_project_workflow_store.py` + `test_security.py` 安全回归
- **P2-4 依赖刷新（已完成）**：desktop lock nanoid 3.3.16→3.3.18（≥3.3.17 公告版本）
- **P2-5 CI/仓库卫生 + 安全加固（已完成）**：僵尸 `core/.github/workflows/ci.yml` 删除、`dist-core-app/`（300+ 构建产物）与 `obs-profile.json` 移出跟踪、安全响应头中间件（nosniff/SAMEORIGIN/no-referrer/CORP same-origin）、health 接口 work_root/core_db 路径脱敏、WS 消息大小上限 4MB（超限 close 1009，`receive_text`+`json.loads` 替换原 `receive_json`）
- **P2-6 杂项 S4 系列（已完成）**：① kernel——`turn_count` 统一口径（4 处分支 +1 收敛为模型响应后单点 +1，错误路径也计数）、`pending_approval`/`pending_waiting_request` run 开始清理、`_backup_file_for_writer_tool` 硬编码工具名改 `backup_tool_names` 可配置字段、`invalid_tool_argument_errors` 改按 `call.id` 匹配（索引仅作兜底）；② runtime——`_substitute_env_vars` 正则整体匹配消除 `$VAR` 前缀碰撞、`_eval_condition` 拦截 `__` 开头属性访问（阻断 `x.__class__` 沙箱逃逸链）+ 信任边界文档化、死代码 `RuntimeProjectionBuffer`（含无界 `_pending_parts`）删除并清理导出与 2 个专测、hub 慢消费者丢包记日志（每队列告警一次）+ `_max_sequence` 高水位保证修剪后 seq 严格单调；③ Tauri——capabilities 删 3 个未用 `core:window` 权限（仅留 `allow-start-dragging`）、双根 env 收敛（`desktop_backend.py` 不再预设 `LAMTOOLS_CORE_WORK_ROOT`，默认 work_root 统一为 `projects_root/default`，dev/prod/CLI 三态一致）；④ website——Download.vue `site-btn-disabled` 类名匹配修复；源码入库决策：官网未进入发布流程（文案全为占位），保持 `.gitignore` 排除，待发布时移除条目并提交（22 S4）。新增回归测试 5 个（`$VAR` 前缀碰撞 ×2、eval dunder 拦截、hub seq 单调、丢包日志）。
- 全量回归：pytest **1408 passed**（P2 批次净增 35 个测试），live/security/e2e 57 passed；UI vitest 322 passed 保持。

## 8. 交叉主题速查

| 主题 | 涉及区 |
|---|---|
| 本地零鉴权 + 任意网页控制 | 03 S1、12（trust_all/base_url）、20 S2 |
| 审批/命令执行门失效 | 03 S1、06 S1×2、06 S2（workflow 节点/投毒/SSRF） |
| 状态卡死/无终端收敛 | 01 S1、02 S2/S3、05 S2 |
| 失败放大为整轮失败 | 02 S3×3（重放/实时持久化/批量持久化）、05 S2（hook） |
| 前后端契约断裂 | 01 S2（include_snapshot）、15 S1（live）、18 S2×3（once/timeout/tools） |
| 无界增长/内存泄漏 | 01（seen ids）、02（kernel_steps/written_files）、05、07（signals）、11、16（deltas/typing ids）、18 |
| 测试与已知缺陷脱节 | 13 S1（tool_progress）、21 S2（快照前事件/auto-expand/forceReset） |
| 文档/脚本/产物漂移 | 14、20、22 S4、24 |
