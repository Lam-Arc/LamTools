# LamTools / Sunday full repository audit — 2026-09-25

本文档是**边审边记**的审计日志：每一批审完即落盘一节，先写事实与证据，再写结论。
未完成的批次在「覆盖表」中标 `pending`，不假装已覆盖。

## 0. 范围与方法

**审计对象**：`codex/multiplatform-dev` 分支工作树，HEAD `255bcaa6` + 未提交改动（5 个修改文件 + 新增 `scripts/build-desktop-update.py`）。

**方法**（沿用 2026-09-24 全场审计的「自动信号先行、再定点人工复核」）：

1. 全树盘点：`git ls-files` 分区统计文件数与 LOC，确定审计单元，避免"没审的部分没被看见"。
2. 自动信号：密钥形状扫描、危险调用扫描（`eval`/`exec`/`shell=True`/`pickle`/`yaml.load`/`os.system`/`create_subprocess_shell`）、TODO/HACK 清单、未忽略的未跟踪物。
3. 定点人工读码：安全闸门（Origin/CORS/WS 鉴权、审批门与命令沙箱、路径穿越、附件）、状态机与终端收敛、契约层（前后端字段）、发布链。
4. 每个进入本文档的结论都要求 `file:line` + 证据；能跑的就跑（pytest / vitest / cargo / curl 实探），不能跑的一律标注「读码」而不写成「已复现」。
5. **与既有审计的关系**：2026-08-13 的 24 分区审计（400 条，`docs/code-audit/`）与 2026-09-24 全场审计（`core/docs/audits/`）已修完 P0/P1/P2。本次对每条相关结论标注 `new` / `still-open`（仍在）/ `fixed`（已修）/ `regressed`（回归）。

**排除**（与既往一致，且会在覆盖表里显式列出）：
`archive/members/`（已归档产品，只在"是否被误引用"角度抽查）、`node_modules`、`target`、`dist`、`build`、`data/`、`artifacts/`、`.lam/`、`core/mobile/artifacts/`。

## 1. 覆盖表（随审计推进更新）

| 单元 | 范围（跟踪文件 / LOC） | 状态 |
|---|---|---|
| A · core Python 后端 | `core/src/lamtools_core` 346 文件 / 134,075 行 | 已审（广度子代理 + 安全面主审） |
| B · core/ui 前端 | `core/ui/src` 192 文件 / 70,563 行 + tests 102 文件 | 已审 |
| C · core/desktop（Tauri 壳 + 打包 + 更新通道） | `core/desktop` 14 文件 / 9,869 行 + spec/installer/CI | 已审 |
| D · core/runtime-rs（Rust 运行时） | 26 文件 / 30,480 行 | 已审 |
| E · core/mobile（移动端宿主） | 66 文件 / 21,884 行 | 已审（无真机，打包态结论为读码） |
| F · 插件 / 技能 / 配置播种 | `plugins` 55 .py / 30,656 行 + bundled 232 文件、`core/config`、`.agents` | 已审 |
| G · 测试与 CI | `core/tests` 163 文件、`core/ui/tests` 102、`e2e` 264、`.github/workflows` 2 | 已审 |
| H · 脚本 / 协议 / 远程 | `scripts` 21 文件 / 3,092 行（`core/protocol`、`core/remote` 为空目录） | 已审 |
| I · website | `website` 20 文件 / 4,535 行 | 已审 |
| J · 文档与状态一致性 | `docs` 217 / 100,779 行、`agent_docs` 6、根 README/PRODUCT/MAINTENANCE/AGENTS | 已审 |
| K · 仓库卫生与敏感物 | 全树未跟踪物、`.gitignore` 与跟踪状态 | 已审 |

**测试基线（本机实跑，作为审计证据）**：`core` pytest **2286 passed / 2 skipped**；`core/ui` vitest **99 文件 / 804 用例**；`core/runtime-rs` cargo test **205 passed**；`core/mobile` vitest **242 passed**；子代理另跑 `core/tests/test_plugin*|hook*|config*|bundled_plugins|skill_runtime` **167 passed**。

**验证纪律**：每条结论标 `[已验证]`（主审亲自读码或跑过）或 `[读码未复现]`（子代理读码、主审未逐条复现）。子代理结论被主审推翻的记入「§4 更正」。

统计基线（`git ls-files`，2026-09-25）：跟踪文件约 2,280 个，其中 `core` 1,393、`e2e` 264、`archive` 262、`docs` 215。

## 2. 审计日志

### 批次 0 · 全树自动信号（已审）

- **密钥形状扫描**（`git grep` 扫 `sk-*`/`AIza*`/`ghp_*`/`AKIA*`/`BEGIN … PRIVATE KEY`，仅跟踪文件）：命中 3 处，全部是既有占位符——`archive/members/writer/backend/tests/test_core_http_writer_unit.py:352`、`archive/members/writer/backend/tests/test_shared_config_split.py:211`、以及审计文档自身的引用。**跟踪树无真实密钥**（`fixed`，与 08-13 结论一致）。
- **危险调用扫描**：`core/src` 内 `eval`/`exec`/`shell=True`/`pickle`/`yaml.load`/`os.system` 命中集中在两处（详见批次 F）：`plugins/bundled/workflow/backend/runtime.py:5845`（生成 Python 源码后 `exec(compile(...))`）与 `:6155`（`eval(source, {"__builtins__": _CONDITION_BUILTINS})`）。其余命中是测试与归档。
- **版本一致性**：`core/src/lamtools_core/__init__.py`、`core/desktop/src-tauri/tauri.conf.json`、`core/desktop/package.json` 均为 `0.3.7-beta.1`；`core/pyproject.toml` 待复核（批次 C/G）。`website/src/components/Download.vue` 的默认版本是 `0.3.6`（桌面）与 `0.1.30`（移动）。

## 3. 按批次的审计记录

### 批次 A · core Python 后端（广度 + 安全面）

**覆盖**：`kernel/`（loop.py 3822 行等）、`app/`（core_db、core_session_store、event_store、snapshot_store、sqlite_write、queue_state、live_hub、project_store、command_execution、default_agent 关键区）、`tool/`（default_toolbox、sub_agent_runner、workspace_files、image_tools、web_tools）、`plugins/engine|registry|hook_config|_jsonc`、`checkpoint.py`、`sub_agent_supervisor.py`、`context_compaction/`、`mem/`、`runtime/`（arrange/plan/observer）、`event/`、`run_event/`、`mcp/`、`llm/retry|policy`、`artifact/`。未覆盖：`export/`、`snapshot/__init__.py`、`member/`、`prompt/`、`session/`、`provider/`、`usage/`、部分小模块、`plugins/bundled/*`（除 workflow 循环/权限区）——列入 §6 缺口。

**既有审计差值（只列仍未修的）**：`04S3` 部分状态重建扫描无覆盖索引（`snapshot_store.py:526` + 索引 `(thread_id,seq)` `core_db.py:139`）· `event_store.py:21` 事件 id 取 uuid4 前 16 hex（碰撞面）· `event_store.py:260` payload 未过 `_json_safe` · `core_db.py:1439` `emit_signal` 无校验（`event_id=""`、缺 `occurred_at` 直接 KeyError）· `kernel/loop.py:533-583` 前置段（mark running / run_start / SessionStart / UserPromptSubmit / `runtime.started`）仍裸露在 try 之外 · `loop.py:631-632` `history_compacted` 的 `trimmed` 在 `del history[:cut]` 之前取值 · `loop.py:1071/1112/1328` `kernel_steps` 无界 + `loop.py:2945` `copy.deepcopy(state.metadata)` · `loop.py:588` 走 `self.kit.toolbox` 协议外属性 · `default_agent.py:2421-2456` `_persist_run_items` 无保护（成功轮可能被报成失败）· `web_tools.py:29-51` `web_fetch` 只挡 loopback/file://，`follow_redirects=True`（SSRF 面仍在）· `image_tools.py:255-262` 参考图路径没走 `is_within_path` · `tool/spreadsheet.py` 死模块 · `artifact/registry.py:203` `path.endswith(target_id)` 误配 · `plan.py:174-176` blocked 步骤被标 completed · `observer.py:264` store 错误杀死 stdout 读取 · `runtime_projection.py:305-311` 与 `_canonical_status:1162-1169` 状态口径不一致 · `plugins/lifecycle` 等未见回归。

**新发现（本批）**

- **P2 · checkpoint blob 永不回收** `[已验证]`：`checkpoint.py:900-1000` `_prune_mainline` 删 `CoreCheckpoint`/`V2*`/`ArtifactRef`/restore，但**不删** `CoreCheckpointBlobRef`、不删 `CoreCheckpointBlob`、也不 `unlink` 文件（`:338-360` 写入 `storage_root/blobs/<digest[:2]>/<digest>`）。全库唯一的 `delete(CoreCheckpointBlobRef)` 在整会话删除路径 `core_session_store.py:629`，`delete(CoreCheckpointBlob)` 全库不存在。每次 `write_file`/`edit_file` 的备份（≤200 MB）都会永久留在磁盘与 DB。`test_core_checkpoint_prune.py` 零 blob 断言。
- **P2 · live 事件持久化失败仍杀死整轮** `[读码未复现]`：`default_agent.py:2463-2524` `_persist_core_event_live` 无 try/except，异常经 `event/__init__.py:154` 落入 `kernel/loop.py:1348-1353` → `final_decision="failed"`，尽管模型与工具都成功。两处调用点（`:752`、`:1230`）均无保护。
- **P3 · arrange 吞掉落库失败** `[读码未复现]`：`runtime/arrange.py:1107` `except Exception: pass`（正是注释声称要防的场景）；`:1125-1133` task 异常从不取回（asyncio 只打日志）。
- **P3 · `SubAgentSupervisor` sqlite 连接从不 close + 进程级无界缓存** `[读码未复现]`：`sub_agent_supervisor.py:144` 的 `_connect()` 在 8 处 `with self._connect() as db`（sqlite3 上下文只提交不关闭）；`:656` `_SUPERVISORS[(data_dir, thread_id)]` 无淘汰（`shutdown_parent_sub_agents` 无调用者）；`tool/workspace_files.py:65` `_FILE_LOCKS` 每路径一个锁不回收。
- **P3 · workflow 多输入端口静默填首个绑定值** `[读码未复现]`：`plugins/bundled/workflow/backend/runtime.py:4232-4233`，`len(input_names)>1` 时未匹配的端口会被填上第一个值。

**主审亲审的安全面（P0 批次是否守住）** `[已验证]`
- HTTP：`app/factory.py:103-106` CORS 走白名单变量（不再是 `*`）；`:218-219` SPA 回退加 `is_relative_to(resolved)` 收敛 → 2026-08-13 的 S1「任意文件读取」已修且仍在。
- WS：`app/live_router.py:103-117` 握手校验 Origin（`is_allowed_origin`/`is_same_server_origin`，不通过 close 1008）；`:706` `turn.start` 在浏览器来源下额外受限。
- 命令沙箱：`tool/approval.py:19-46` `DANGEROUS_COMMAND_RE` + `SHELL_STRUCTURE_RE`（`~`、`$(`、`${}`、`$VAR`、反引号、`\rm`、引号包裹危险名、解释器 `-c`）一律 `ask_user`，注释明示"never auto-allowed"；`tool/command.py:453-472` 拒绝 `~`/`$`/反引号并按 work_root + resource_roots 做 `is_within_path` 校验 → 06 S1 两条已修且仍在。
- 配置 id：`config/model_store.py`、`provider_store.py`、`model_group_store.py` 均过 `validate_config_id`（`:110-239`）→ 09 S2 已修。
- 附件：`attachment/store.py:21-35` session_id `fullmatch` + `..` 拒绝，非规范 id 走 sha256 键（越界写已修）。
- 桌面壳：`core/desktop/src-tauri/src/main.rs:1308` 单实例插件、`:1526-1533` dev 后端不带 `--reload` 且注释记录原因、`:1742-1758` 进程组 SIGTERM→SIGKILL 清理 → 20 S2/S3 已修。

### 批次 B · core/ui

**覆盖**：`appServer/{store,selectors,workbenchProjection,sessionState,client,messageParts,protocol}`、`workbench/createWorkbench.ts`、`app/runtime.ts`、`transport/{directTransport,types}`、`composables/*`（24 个）、`helpers/*`、`ChatThread.vue`、`MessageView.vue`、`MarkdownRenderer.vue`、设置类组件、`study/*`、`styles/*.css`。

**既有审计差值**：15 S3「流式跨空行拆代码块」仍开放（`MarkdownRenderer.vue:435-440,487-497`）；15 S3 `imageSrc` 拼接无 `..` 归一（`MessageView.vue:2473`，仅有 Tauri asset scope 兜底）；15 S4 markdownCache FIFO 淘汰；`checkpointTurnIds` 以数组元素进 v-memo（`ChatThread.vue:13`）；16 S4 `normalizeDeliveryRecord`/`isFinalAssistantContentItem` 死函数、协议版本从未发送/校验（`client.ts:66-70`）、`kind='status'` payload 不并入 item、`receivedEventIds` 20 万条全清、附件数组每帧重建导致消息缓存不命中、`item.deltas` 无界与帧回调无 try；19 S4 `base.css:86` 仍对 `input/textarea` 去焦点环；21 S4 测试里 `process.cwd()`；`LamToolsApp.vue:3700-3705` 每 tick `watch(messages,{deep:true})`。已修项（15/16/17/18/19/21 的主要条目）逐条对到代码，**无 `regressed`**。

**新发现**
- **P2 · 仅 revision 变化的 hydrate 换掉整个 state 对象，与自身注释相反** `[已验证读码，性能后果为读码推演]`：`appServer/store.ts:246-254` 注释写「Keep the local projection object stable」，实现却 `sessionStateStore.applySnapshot(incoming)` 后整体替换 `runtime.state` → `core.items[*]` 身份全变，`workbenchProjection.ts:308` 以 item 引用为键的 part 缓存整线程失效。
- **P3 · `flushFrame` 在 `disconnect()` 后仍自续**：`store.ts:327-339` 在 `runtime.state` 为空时不断重排，`disconnect()`（`:191-202`）未清 `eventFrameScheduled`。
- **P3 · `partMemo` 漏 `live` 与 `autoPlotMath`**：`MessageView.vue:1167-1178` 记忆数组缺这两个入参，而其内部 `:streaming`、`reasoningDuration`、`processCardBodyStateClass` 都依赖 `live`。
- **P3 · 更新状态文案把「装不了」说成「已是最新」**：`useCoreUpdateState.ts:73,101-105` + `CoreSettings.vue:729-732` 配合 `checker.py:271-277`，无 `source` 时仍打印「已是最新版本（v{{latest}}）」。
- **P3 · DEV 诊断每帧跑全量**：`selectors.ts:413,430,463-473` 在 `mergedItemOrder` 内做逐条 `console.warn` 与 `Math.min(...ids.map())` 大数组展开。

### 批次 C · core/desktop + 更新通道

- **P1 · 官网清单优先但没有任何发布/校验闸门** `[已验证]`：`update/checker.py:253-260` 先答者胜、`:284` 只按该源判定；`desktop-update.json` 实测 **404**；`release.yml` 无生成/上传步骤；`scripts/build-desktop-update.py:141` 把上传留给人工；`core/desktop/update-manifest.json` 不存在、未忽略、无消费者。移动端有对应闸门（`release-1030/deploy.py:161-182` scp + `sha256sum -c` + `verify_public.py` 公网校验）。
- **P1 · 「先答者胜」被测试锁死** `[已验证]`：`core/tests/test_update_check.py:208-219` 断言 site 9.9.9 击败 GitHub v10.0.0 → 清单一旦落后即静默冻结更新。
- **P2 · 站点为主源后更新说明退化为一行** `[已验证]`：`checker.py:206` 取清单 `release_notes`，脚本默认 `Sunday {version}`（`build-desktop-update.py:119`），GitHub Release 正文不再被读。
- **P2 · 当前版本无法发布，且预发布用户永远看不到正式版** `[已验证]`：树为 `0.3.7-beta.1`（5 处一致），而 `release.yml:34` 要求 `^v\d+\.\d+\.\d+$`、`:61` 逐字比较，`bump-version.ps1:27` 也拒绝预发布；`checker.py:66-91` 的 `compare_versions` 忽略非数字后缀 ⇒ `0.3.7-beta.1` 被判为 ≥ `0.3.7`，`test_update_check.py:172` 把该语义固化。
- **P2 · 清单脚本未跟踪** `[已验证]`：`git ls-files scripts/` 21 个不含它，而 `checker.py:37` 指名它是清单生产者 → 干净检出无法重生成清单。
- **P3**：`lstrip("v").strip()` 顺序（`checker.py:193,214`）· `download_url` 不校验协议（移动端要求 https）· CLI 人类可读输出不含 `source`，`cli.py:4502` 与 `update/__init__.py:1` docstring 仍写 GitHub Releases · `build-desktop-update.py:129` 二次解析安装包 · 旧测试 `_stub_http` 不看 URL（`test_update_check.py:52-57`）。

### 批次 D · core/runtime-rs

**覆盖**：32,938 行全读（含 provider/study/study_exams/study_notes/compaction/fetch_tools/hooks/image_gen/mcp/plan_tools/project_tools/skills/sub_agent/web_search 等）。

**既有审计差值**：F1 钩子强制（deny/ask_user）**已修且用仓库自带 fixture 复现**；F4 `study_exams` 单测已补（6 个）；F6 clippy 干净（exit 0，仍有 23 warning）；F7 panic 面从 67 降到约 63，其中 provider 只剩 2 处（`unreachable!` `provider.rs:966,1243`），残量集中在 workflow_document(35)/study_notes(7)/sub_agent(7)/workflow_store(7)/web_search(6)；0.1.24/0.1.29 两条 parity 修复确认在位。

**新发现**
- **P2 · 文件工具无输出上限，桌面有** `[已验证]`：`project_tools.rs:125-126` `read_file` 整文件返回、`:137-141` `list_dir` 全量返回；`MAX_SEARCH_MATCHES = 200`（`:192`）对比桌面 50/100/50,000 字符（`tool/workspace_files.py:29-31`）。大文件/大目录会把整个内容送进 provider 与 `runtime_history`。
- **P2 · `search_files` glob 语义与桌面不同** `[读码未复现]`：`project_tools.rs:224-240` 从整条相对路径左对齐匹配，`*.rs` 匹配不到 `src/` 下的文件；桌面用 `Path(rel).match()` 或文件名匹配。
- **P2 · `update_checklist` 丢掉桌面的强制 `reason`** `[读码未复现]`：`plan_tools.rs:383` `required:["action"]`，桌面 `tool/default_toolbox.py:628` 要求 `["action","reason"]` 且缺参失败（`:942`）；未知 action 文案也不同。
- **P2 · 阻塞式同步 I/O 在 async 工具里** `[读码未复现]`：`project_tools.rs:250-329,344-435`（std::fs 递归遍历/读文件）、`skills.rs:266,305,322`、`study.rs:2872`（rusqlite + fs）都在 Tokio worker 上跑，大项目搜索会占住工作线程。
- **P3**：`project_tools.rs:45` `resolve` 对 `C:notes.md` 这类盘符相对路径可逃出 root（Windows-only，无 `canonicalize`+`starts_with` 兜底）· `study_exams.rs:1020-1021,1170,405` 死代码（加载克隆整张私题表后只 `let _ =`）· `lib.rs:562-569` `run_turn` 把 `ApprovalRequired` 折成 `Err`，该公开 API 无法续跑 · `lib.rs:885-891` + `sub_agent.rs:751-785` 迟到指导在请求前被标记已投递，失败即丢 · `sub_agent.rs:907-986` `lock().unwrap()`×7 与无界 `mail` · `fetch_tools.rs:182-189`/`image_gen.rs:131-135` 无界响应体（与 0.1.30 parity 决定一致，记为残量风险）。

### 批次 E · core/mobile

**版本一致性**：8 处全部为 `0.1.30` / versionCode 1030，逐条核对一致；线上 `mobile-update.json` 与仓库副本逐字节相同。唯一漂移：`App.vue:534` 同步导入的 `clientInfo.version` 仍是 `0.1.1`。

**新发现**
- **P2 · `artifact.open` 全链路实现但没注册** `[已验证]`：`core/mobile/src-tauri/src/lib.rs:960` 定义 `sunday_artifact_open`，但两个 `generate_handler!` 列表（`:3466`、`:3518`）都没有它；TS 侧 `native/rustAgent.ts:209` 与 `standalone/StandaloneArtifacts.ts:50-54` 会 `invoke` 它 → 非附件类产物"打开"必然报 `Command sunday_artifact_open not found`。
- **P2 · 局域网发现被 ACL 拒绝** `[已验证]`：`native/lanDiscovery.ts:24-27` 直接 `invoke('plugin:lamtools-lan-discovery|discover')`，而 `capabilities/default.json` 与生成的 `acl-manifests.json` 里 `lan-discovery` 计数为 0；同 App 其余插件都经 Rust 命令包一层（`run_mobile_plugin`，如 `lib.rs:398,978,3099`）。Tauri 会在派发前拒绝。
- **P2 · 发布版没有可用的局域网明文通道** `[已验证]`：移动 CSP `connect-src 'self' ipc: http://ipc.localhost https: wss:`（无 `http:`/`ws:`），而桌面 CSP 显式列了 `http://127.0.0.1:* ws://127.0.0.1:*`；Android `network_security_config.xml` 的 `base-config cleartextTrafficPermitted="false"`。直连 `new WebSocket('ws://'+host)`（`connection/ConnectionManager.ts:228`）与配对 `fetch('http://…')`（`pairing/PairingClient.ts:144`）在 release 包内被双重阻断；debug 构建放开，所以只在正式包暴露。
- **P3 · 账号节点平台名错** `[读码未复现]`：`account/AccountClient.ts:282-286` 用 `Capacitor.isNativePlatform()`，Tauri 下为 false → 真机上报 `mobile-web`。
- **P3 · 守卫测试指向未构建的 Capacitor 工程** `[读码未复现]`：`tests/android-network-policy.test.ts` 断言 `android/AndroidManifest.xml` + `capacitor.config.ts`，而真正出货的是 `src-tauri/gen/android`；这正是能拦住上一条的测试。
- **P3 · Tauri 化之后的 Capacitor 残留**：`native/notifications.ts`（无调用者）、`secureStorage.ts` 的 Browser/Capacitor 分支、`capacitor.config.ts`、整个 `core/mobile/android/`、`@capacitor/*` 依赖与 `cap:*` 脚本。

### 批次 F · plugins / skills / config

**新发现**
- **P1 · 插件清单 `name` 未校验 → 目录穿越 + 任意目录删除** `[已验证读码；rmtree 后果为逻辑推演]`：`plugins/operations.py:1176-1178`（同形于 `:1160-1165`、`:1194-1205`）`name = str(raw_manifest.get("name") or …)` 后直接 `final_dir = root / name`，存在则 `shutil.rmtree`；`plugins/registry.py:222` 加载时同样不校验 `name`。`plugins/install.py:113-114` 的守卫 `if not src.is_relative_to(target.parent) and src.is_relative_to(target)` 在逻辑上不可达（src 在 target 内 ⇒ 也必在 target.parent 内 ⇒ 第一项为假）→ 想拦的"源在目标内"永远拦不住。`plugin.install` RPC 与 `plugin_install` 工具都可达此路径。
- **P1 · 仓库内 `websearch.jsonc` 可指定可执行文件，且 `web_search` 是 AUTO_ALLOW** `[已验证读码]`：`tool/search/factory.py:38-56` 候选顺序含 `work_root/.lam/core/config/websearch.jsonc` 与 `./.lam/core/config/websearch.jsonc`；`_default_config` 合并其中的 `command`/`transport`；`tool/search/external.py:61-66` 用 `create_subprocess_exec(command + [json])` 执行。也就是说：检出（或打开）一个带该文件的仓库 → 模型一旦调用 web_search（无需审批）即在宿主机执行该命令。D5 迁移只加了 `{data_dir}/plugins/websearch.jsonc` 优先项，没有去掉仓库候选。
- **P1 · MCP 服务器从工作区配置自动启动** `[已验证读码]`：`mcp/config.py:88-92` 在 `default_paths is None` 时纳入 `{work_root}/.lamtools/mcp.json`、`{work_root}/.mcp.json`、`{work_root}/mcp.json`；`mcp/registry.py:57-73` 的 `load()` 对所有 enabled 项 `client.start()`。没有信任门 → 仓库里放一个 `.mcp.json`（业界通用约定）即可让宿主启动任意进程。2026-08-13 记为 12 S2，**未修**。
- **P2 · 随包 `hooks.json` 是 JSONC，消费者却要求严格 JSON** `[已验证读码]`：`core/config/resources/hooks.json` 以 `/* … */` 开头；`plugins/hook_config.py:92` 用 `json.loads(...)` → 解析失败即整文件跳过（仅 warning 日志）；保存路径同样严格解析。结果：开箱状态下钩子全部失效且静默，文件里写的"取消注释即可启用"不可达。
- **P2 · 插件依赖经 pip 参数注入** `[已验证读码]`：`plugins/deps.py:154` `[sys.executable, "-m", "pip", "install", *dependencies]` 直接吃清单字符串，`parse_requirement` 只用于状态判断 → `--index-url=<恶意源>`、`-r <任意文件>` 等都会生效。
- **P2 · 随包 hooks 之外的解析/写入不一致**：`tool/approval.py:61` 以严格 JSON 读 `access_tools.jsonc`（注释即静默清空全部 tier）；`tool/search/factory.py:29-33` 第三个正则注释剥离器会把字符串里的 `https://` 截断；`plugins/trust.py:15`、`skills.py:271` 非原子写 + 无保护 `json.loads`（截断文件会让技能索引/钩子加载抛错）。
- **P3**：`skills.py:185` 缺 `utf-8-sig`（带 BOM 的 SKILL.md 丢 frontmatter）· `default_toolbox.py:1080-1112` `_plugin_conflicts` 只填不读 · `registry.py:187-216` 只按路径去重、重名插件第二个不可达 · `config_store.py:22` 同名拼接 · `.github/workflows/release.yml:31` 的正则与 `release-lamtools` 技能文档未覆盖预发布。

### 批次 G · 测试与 CI

**覆盖**：`core/tests` 163 文件 / 59,756 行（收集 2288 个用例）、`core/ui/tests` 102 / 22,298、`runtime-rs/tests` 6、`mobile/tests` 43、`e2e/`、`.github/workflows/*`、`pyproject.toml`、各 `package.json`、`scripts/package*|bump-version|verify-*`。纪律检查：0 `assert True`、0 快照、0 `.only`、0 `@ts-ignore`、4 个带原因的 skip，pytest 侧无真实网络。

**新发现**
- **P1 · 当前版本树无法走完发布链** `[已验证读码]`：`release.yml:34` `^v\d+\.\d+\.\d+$` + `:61` 逐字比较，`bump-version.ps1:27` 同样拒绝 `0.3.7-beta.1` → 打 `v0.3.7-beta.1` 过不了正则，打 `v0.3.7` 过不了等值校验。与批次 C 的「预发布用户看不到正式版」是同一根因的两面。
- **P2 · CI 跳过了唯一的真 WebSocket e2e** `[已验证]`：`.github/workflows/ci.yml:27` 只装 `.[dev]`，而 `dev` = pytest/pytest-asyncio/fastapi（`core/pyproject.toml:26`），uvicorn/websockets 在 `server`/`desktop` 组；`core/tests/test_core_live_client_e2e.py:9` 是模块级 `pytest.importorskip("uvicorn")` → 该模块在 CI 恒被跳过（本机装有 uvicorn，所以本地是跑的）。
- **P2 · 41.9 MB 真实 API 运行记录入库** `[已验证]`：`core/tests/fixtures/context_compaction/` 38 个跟踪文件（`du` 52 MB），含 2–3.4 MB 的 `evidence.json`/`stop.json`/`http_attempts.json` 真实模型 transcript，只被不参与收集的 `tests/experiments/context_compaction_real_api.py` 使用。
- **P2 · 符号级覆盖率缺口** `[读码未复现]`：`config/id_validation.py`、`app/approval_resolution.py`（341 行，审批 claim→terminal 顺序）、`tool/spreadsheet.py`、`tool/search/external.py`、`checkpoint_v2.py`、`runtime/plan.py`、`app/sync_store.py`、`app/session_actor.py`、`plugins/bundled/workflow/backend/adapters.py`、`update/operations.py` 等 24 个模块在测试里零符号引用。
- **P2 · 只被 spec 养着的死模块** `[已验证]`：`kernel/hooks.py` 无任何源码导入者；`tool/verification.py` 只被 `tests/test_tool_verification.py` 导入，两者仍打进 exe。
- **P3**：`core/tests/test_workflow_agent_builds_from_nl.py` 收集不到任何用例（无断言的 live 驱动脚本）· 无覆盖率工具与阈值（`pyproject.toml:38-40` 无 `addopts`，dev 无 pytest-cov）· CI 无 `concurrency`/`timeout-minutes`/pip cache，`git diff --check`（`ci.yml:22,48`）在干净检出上是空操作 · 移动端版本不在任何守卫内（`bump-version.ps1` 只覆盖桌面 5 处，`release.yml` 不校验 mobile，Android job 无版本断言）· 仍开放的老条目：13-S2 钩子失败注入零覆盖、`kernel_steps` 无上限、`test_kernel.py:2955` 的 `elapsed < 0.09` 计时断言、`test_model_store.py:82-85` 的 `time.sleep(0.01)`、21-S2 三条（快照竞态/`forceResetActiveTurn`/自动展开）零测试、`MessageView.vue:1264-1265` 的模块级 5s 计时器在 `onBeforeUnmount` 未清、21-S3 26 个测试文件用源码嗅探（`readFileSync` 共 152 处）、`slot-contract.test.ts:38-45` 不还原 `matchMedia`。

### 批次 H/I/J · scripts / website / 文档一致性

**新发现**
- **P2 · `.agents/skills/lamtools-setup-install` 未被跟踪，但被 AGENTS.md 强制引用** `[已验证]`：`git check-ignore -v` 命中 `.gitignore:82 .agents/`，`git ls-files .agents/skills` 只有 `impeccable` 与 `lam-design-spec` → 干净检出里没有这条「Setup 后置验收」技能，而它是项目本地指令点名的必需流程。
- **P3 · `website/.env.example:2` 的 `VITE_SUNDAY_VERSION=0.3.3`** 与 `Download.vue:10` 默认 `0.3.6`、线上 v0.3.6 不一致；照抄示例会生成 404 的 AppImage 链接。`website/src/mock/runtime.ts:244,305` 的预览版本也停在 0.3.3。
- **P3 · `scripts/test-arrange-agent.js:4` 默认端口 6174**（已归档 Writer 的端口），同目录其余脚本用 5173/5172。
- **P3 · tracked 与 ignored 不一致的老账**：`.agents/skills/{impeccable,lam-design-spec}`（98 文件）在 `.agents/` 被忽略的情况下跟踪；`.zcode/`（4）、`.superpowers/sdd/*`（8）同样 tracked-while-ignored；`output/`（v0.2.6 论文 PDF + 补充包 3.4 MB）与 `kbtool-task/`（7 文件，无 runner、无活引用）是跟踪着的旧产物/demo。
- **P3 · `docs/core-ui-streaming-perf.md` 的行号锚点全部过期**（`:18` 说 ChatThread.vue 5237 行，实际 2080；`:19-24` 指到的位置已换成无关代码），而 AGENTS.md 把它指定为该主题唯一权威；尾部 `:370-404` 混入移动端 APK/Rust 笔记。
- **P3 · `core/lamtools-core-backend.spec:77` 注释“133 Core modules”** vs 实际 225 个 `.py`。
- **文档声明与实现不符（`[已验证]`，逐条见下表）**

| 文档:行 | 声明 | 现实 |
|---|---|---|
| `AGENTS.md:92` | 「Core Windows NSIS setup 构建」 | 实为 Inno Setup（`core/desktop/installer/Sunday.iss`、`build-installer.ps1`、`release.yml:179-204`） |
| `AGENTS.md:99` | website「独立构建，不参与 core 开发链路」 | 强制依赖 core/ui（`website/vite.config.ts:13-22` alias `@ui` 与 `core/ui/node_modules/@vue-flow/*`） |
| `AGENTS.md:121-125` | Showcase 直挂 + `translateZ` + `.mock-window .thread` + `utils/inView.ts` + 全站 `TODO(文案)` | 已改为 iframe 预览 `preview.html`；`inView.ts`/`useScrollReveal` 已删；`TODO(文案)` 在 website 中 0 处 |
| `AGENTS.md:157` | 版本号 5 处同步 | 另有 `Cargo.lock`、`website/Download.vue` |
| `README.md:121`/`README.en.md:121`、`agent_docs/project_core_tech.md:36` | Windows 安装包用 NSIS | Inno |
| `README.md:125` | macOS/Linux「规划中」 | Linux AppImage/.deb 已构建并随 v0.3.6 发布 |
| `core/desktop/PACKAGING.md:148` | 发布资产只匹配 `Sunday_*_x64-setup.exe` | `release.yml:362-366` 同时发 AppImage/.deb |
| 多份文档 | `scripts/office.py`、`scripts/verify-preview.mjs`、`scripts/session_index.py` | 分别在 `core/skills/office-renderer/scripts/`、`website/scripts/`、`plugins/lamtools-rag/scripts/` |

### 批次 K · 仓库卫生与敏感物

- **P1 · 未忽略的未跟踪目录含站点上传私钥** `[已验证]`：`git check-ignore` 对 `core/mobile/artifacts/…`、`artifacts/`、`MyProject/`、`core/experiments/` 全部无命中；`core/mobile/artifacts/release-1030/{site-key,transfer-key}/upload_ed25519` 是 `-----BEGIN OPENSSH PRIVATE KEY-----`（同目录还有 `tls-015/debug.keystore`、11 个 APK，合计 2.85 GB）。`artifacts/` 780 MB 中 `artifacts/linux-x64/sidecar/LamCore`（17.5 MB）同样可见。`git add -A` 即入库。
- **P2 · 生成物与实验产物散落在跟踪树旁**：`core/mobile/src-tauri/gen/schemas/`（6 个生成 JSON）、`docs.7z`（779 KB）、`.tmp_glass_rg.txt`（118 KB）、`test-proj/`（空目录）。
- **P3 · 跟踪着的旧产物**：`output/`（见批次 H/I/J）、`kbtool-task/`、`e2e/`（见下）。

### e2e 与根目录遗留目录（批次 G 结论）

## 4. 更正记录（子代理报出、主审复核后修正）

审计纪律要求把错误留在文档里，不做静默删除。

1. **更正（本条本身被二次更正）**：子代理报 `output/`「被跟踪同时又列在 `.gitignore:171`」。主审先据 `git check-ignore -v output/pdf/…pdf` 无命中判其误报；复查 `.gitignore` 后确认 **`.gitignore:171` 确有 `/output/`**——`git check-ignore` 默认不报告已跟踪文件（`--no-index` 才会），所以"无命中"不是证据。结论：**子代理原本正确**，`output/` 是 tracked-while-ignored（P3，与 `.agents/skills/{impeccable,lam-design-spec}`、`.zcode/`、`.superpowers/sdd/*` 同类）。教训记入 §7。
2. **降级**：子代理报 website「`@vue-flow/*` 未声明 → 干净检出构建失败」（P2）。复核 `website/vite.config.ts:13-22` 把这些 alias 明确指向 `../core/ui/node_modules/*`，即"借 core/ui 的安装"，且 AGENTS.md 本来就写明展示区直挂 core/ui。真正的问题是 **AGENTS.md:99 声称"独立构建、不参与 core 开发链路"与实现不符**（P3 文档），不是构建缺陷。
3. **撤回**：早前一轮子代理报 study 词表首次解析耗时 0.362 s，主审实测 **0.064 s**（`lexicon.table()`，5,769 条）。不构成性能问题，已从结论中移除。
4. **上修**：主审原先只把「预发布版本比较」记为 P3。经批次 G 复核，它与 `release.yml`/`bump-version.ps1` 的预发布拒绝组合后，会形成「当前版本发不出去 + beta 用户看不到正式版」的闭环 → 上修为 **P1**。
5. **限定**：批次 C/D 的部分「仍是 P2 ≤200 MB 备份」判断基于 `checkpoint.py` 的写入路径读码；磁盘增长的规模未做实测量化，按 P2 记。

## 5. 汇总：P1 / P2 与建议修复顺序

### P1（6 条，建议按此顺序）

| # | 结论 | 证据 | 验证 |
|---|---|---|---|
| 1 | 插件安装用清单 `name` 拼 `root/name` 并 `rmtree` 既有目录；`install.py` 的守卫逻辑不可达 | `plugins/operations.py:1176-1178,1160-1165,1194-1205`、`plugins/registry.py:222`、`plugins/install.py:113-114` | 读码 + 逻辑证明 |
| 2 | 仓库内 `websearch.jsonc` 可指定可执行文件，而 `web_search` 无需审批即 `create_subprocess_exec` | `tool/search/factory.py:38-56`、`tool/search/external.py:61-66` | 读码 |
| 3 | MCP 从工作区（`{work_root}/.mcp.json` 等）自动启动进程，无信任门 | `mcp/config.py:88-92`、`mcp/registry.py:57-73` | 读码 |
| 4 | 官网清单是更新主源，却没有生成/上传/校验闸门（线上 404），且"先答者胜"被测试固化 → 清单一旦落后即静默冻结更新 | `update/checker.py:253-260,284`、`tests/test_update_check.py:208-219`、`release.yml` 无清单步骤 | 实测 404 + 读码 |
| 5 | 树为 `0.3.7-beta.1`，`release.yml`/`bump-version.ps1` 拒绝预发布；`compare_versions` 又把 beta 判为 ≥ 正式版 → 发不出去 + beta 用户永远看不到正式版 | `release.yml:34,61`、`bump-version.ps1:27`、`update/checker.py:66-91`、`tests/test_update_check.py:172` | 读码 + 逻辑 |
| 6 | 未忽略的未跟踪目录含站点上传私钥 + debug.keystore（2.85 GB），`git add -A` 即入库 | `git check-ignore` 全部无命中；`core/mobile/artifacts/release-1030/{site-key,transfer-key}/upload_ed25519` | 实读文件首行 |

### P2（20 条，按主题）

| 主题 | 条目 | 关键位置 |
|---|---|---|
| 安全纵深 | shipped `hooks.json` 是 JSONC 但解析器严格 JSON（开箱钩子全失效且静默） | `core/config/resources/hooks.json`、`plugins/hook_config.py:92` |
| 安全纵深 | 插件 `dependencies` 直达 pip argv（参数注入） | `plugins/deps.py:154` |
| 安全纵深 | `access_tools.jsonc` 严格 JSON；`search/factory.py` 第三套注释剥离器截断 URL；`trust.py`/`skills.py` 非原子写 + 无保护 parse | `tool/approval.py:61`、`search/factory.py:29-33`、`plugins/trust.py:15`、`skills.py:271` |
| 发布/更新 | 站点为主源后更新说明退化为 `Sunday <version>` | `checker.py:206`、`build-desktop-update.py:119` |
| 发布/更新 | `scripts/build-desktop-update.py` 未入库，而更新通道依赖它 | `git ls-files scripts/`、`checker.py:37` |
| 数据增长 | checkpoint blob 与文件永不回收（prune 不删 ref/不 unlink） | `checkpoint.py:900-1000`、`core_session_store.py:629` |
| 容错 | live 事件持久化失败仍杀整轮 | `default_agent.py:2463-2524`、`kernel/loop.py:1348-1353` |
| Rust 一致性 | `read_file`/`list_dir` 无上限、search 200 vs 桌面 50/100/50,000 | `runtime-rs/src/project_tools.rs:125-141,192` |
| Rust 一致性 | `search_files` glob 左对齐匹配 | `project_tools.rs:224-240` |
| Rust 一致性 | `update_checklist` 缺强制 `reason`、错误文案不同 | `plan_tools.rs:383,226` vs `default_toolbox.py:628,942` |
| Rust 性能 | 工具路径上的阻塞同步 I/O | `project_tools.rs:250-435`、`skills.rs:266-322`、`study.rs:2872` |
| 移动端 | `artifact.open` 未注册（功能 100% 失效） | `mobile/src-tauri/src/lib.rs:960` vs `:3466,3518` |
| 移动端 | 局域网发现未过 ACL（被 Tauri 拒绝） | `native/lanDiscovery.ts:24-27`、`capabilities/default.json` |
| 移动端 | release 包 CSP + cleartext 政策双阻断局域网直连/配对 | `mobile/tauri.conf.json:22`、`network_security_config.xml` |
| UI | revision-only hydrate 换掉整个 state，击穿 part 缓存 | `appServer/store.ts:246-254` |
| 测试/CI | CI 恒跳过唯一的真 WebSocket e2e（`.[dev]` 不含 uvicorn） | `ci.yml:27`、`pyproject.toml:26`、`test_core_live_client_e2e.py:9` |
| 测试/CI | 41.9 MB 真实 API 运行记录入库 | `core/tests/fixtures/context_compaction/` |
| 测试/CI | 24 个生产模块零符号级测试引用（含 `approval_resolution.py`、`id_validation.py`） | 见批次 G |
| 测试/CI | `kernel/hooks.py`、`tool/verification.py` 死模块仍打进 exe | `lamtools-core-backend.spec:190,264` |
| 仓库卫生 | `.agents/skills/lamtools-setup-install` 未入库但被 AGENTS.md 强制引用 | `.gitignore:82`、`git ls-files .agents/skills` |

### 建议修复顺序

**第 0 波（今天，零风险，不碰逻辑）**：`.gitignore` 加 `/core/mobile/artifacts/`、`/artifacts/`、`/core/experiments/`、`/MyProject/`、`core/mobile/src-tauri/gen/schemas/`、`*.7z`、`.tmp_*`（P1-6）；`scripts/build-desktop-update.py` 入库（P2）。

**第 1 波（安全，一周内）**：P1-1 插件 `name` 白名单 + 修 `install_from_directory` 守卫；P1-2 去掉 websearch 的 work_root/cwd 候选；P1-3 MCP 非用户作用域加显式 opt-in；P2 shipped hooks.json 改严格 JSON（或加载器改 JSONC，二选一并写测试）；P2 pip 依赖过 `parse_requirement`。

**第 2 波（发布与更新通道，与第 1 波并行）**：P1-5 先定版本策略（允许预发布发布 + 预发布排序，或先回落 `0.3.7`），修 `release.yml`/`bump-version.ps1` 正则与 `compare_versions` 语义并改掉那条固化的测试；P1-4 二选一：补齐桌面清单的生成+上传+服务端/公网双校验闸门，或把官网降为回退（不要让"官网优先"先于闸门上线）；P2 更新说明来源。

**第 3 波（产品正确性，一个月内）**：移动端三条（注册 `sunday_artifact_open`、LAN discovery 包一层命令、明确 release 是否允许局域网明文并同步 CSP/网络安全策略/测试）；Rust 工具上限与 glob 对齐桌面 + 阻塞 I/O 下沉；checkpoint blob GC；live 事件持久化隔离；UI hydrate 身份；CI 装 `.[dev,server]`、fixtures 瘦身、加覆盖率工具与阈值。

## 6. 覆盖缺口（本轮未审或未复现的部分）

**未审**：`core/src/lamtools_core/` 的 `export/`、`snapshot/__init__.py`、`member/`、`prompt/`、`session/`、`provider/`、`usage/` 等小模块；`plugins/bundled/` 中除 workflow 执行/评估路径与 study 词典外的插件源码（含 workflow 插件 25k 行的大部）；`.agents/skills/*` 的技能正文正确性；`archive/members/`（归档，仅在"是否被误引用"角度抽查）；`docs/` 100,779 行（按声明抽查，未通读）；`e2e/` 与 `kbtool-task/` 的运行行为（已判定无人执行）；`website` 视觉与截图验证；`core/ui/tests` 102 文件的逐条断言质量（只做了纪律统计与关键项抽查）；`core/desktop/src-tauri/src/main.rs` 1,539 行只做定点 grep（未通读）。

**未复现（`读码未复现` 类）**：真机/打包态的一切结论（无 Android 设备、未构建 APK）；`cargo clippy` 之外的 Rust 运行期行为；CI 的实际执行结果（只读 workflow + 本地跑等价命令）；Tauri ACL 的实际拒绝（依据生成清单与 Tauri 源码语义推断）；`checkpoint` blob 增长的实测量化；UI 缓存击穿的实测帧数。

**本轮明确不做的**：依赖 CVE 扫描（离线无公告库）、负载/性能压测、模糊测试、渗透测试、修复实施（本审计只产出本文档）。

---

## 7. 修复记录（边修边记）

格式：`结论 → 改动 → 测试 → 验证方式`。用户已定四项决策（官网优先+两源取高 / 支持预发布 / 工作区可执行配置只认用户作用域 / 移动端放开局域网明文）。

### 波次 1 · 安全（5 项全部完成）

**1. 插件安装路径穿越（P1）**
- 改动：`plugins/operations.py` 新增 `_resolve_plugin_dir()`（走 `config/id_validation.py` 的 `validate_config_id("plugin", …)` + `is_relative_to(root)` 断言），4 处 `final_dir = root / name`（cc/codex、local、zip、url）全部改用它；下载资产名与 staging 目录名按单段白名单清洗；失败路径清理 staging；`plugin_uninstall` 增加"目标必须落在已知插件根内"检查；`install.py` 修好反转且不可达的守卫（改为 `src.is_relative_to(target)`）并新增 `root` 参数；`registry.py::_read_manifest` 校验 `name`/`id`（经 `discover_errors` 暴露，不影响其他插件加载）；`skill_create` 拒绝前导点号（`..` 曾可写到 `lam_home()/skills/..`）。
- 测试：`test_plugin_lifecycle.py` 新增 11 条（6 种非法名 × 目录穿越、zip 穿越、源在目标内、目标越根、卸载越根、registry 报错可见）。
- 验证：**11 条在旧实现上全部失败**（`git stash push` 三个源文件后重跑），新实现全过；`test_plugin_lifecycle|operations|registry|adapters` 73 passed。

**2. web_search 仓库配置注入（P1）**
- 改动：`tool/search/factory.py` 去掉 `{work_root}/.lam/core/config/websearch.jsonc` 与 cwd 相对候选（保留 `{data_dir}/plugins/websearch.jsonc` + 用户配置根 + `WEBSEARCH_CONFIG`），`work_root` 参数保留但不再参与发现；第三套正则注释剥离器换成共享的 `plugins/_jsonc.strip_jsonc_comments`（不再截断字符串里的 `https://`）；`default_toolbox.py` 的 handlers 表补传 `data_dir`（否则用户作用域配置读不到）。
- 测试：`test_web_tools.py` 新增 2 条（工作区文件被忽略 / 用户作用域 JSONC 生效且 URL 不被截断）。
- 验证：**2 条在旧实现上全部失败**；`test_web_tools|bundled_plugins|plugin_operations` 51 passed。

**3. MCP 工作区配置自动启动（P1）**
- 改动：`mcp/config.py::_config_paths` 去掉 `.lamtools/mcp.json`、`.mcp.json`、`mcp.json` 三个工作区候选；保留用户配置、`env_var`、`config_files`、`default_paths`。
- 测试：`test_core_mcp_registry.py` 新增 2 条（工作区三种文件均不产生 client / 显式 env 仍生效）。
- 验证：workspace 一条在旧实现上失败（另一条是"别收过头"的守卫，旧实现本就通过）；`test_core_mcp_registry|mcp_tools` 12 passed。

**4. hooks.json 开箱不可用（P2）**
- 改动：`plugins/hook_config.py::_load_file` 改用 `load_jsonc_text`（注释/尾逗号/BOM 均可）；`hook_config_get` 增 `parsed`（归一化 JSON）与 `parse_error`；`hook_config_update` 接受 JSONC 并写成严格 JSON（`atomic_write_text` 原子落盘）；`CoreHooksEditor.vue` 两处（添加 Hook 表单、原始配置编辑器）在严格解析失败时改用 `parsed`，两者都不可解析才中止（仍不退回 `{}`）。
- 测试：`test_plugin_operations.py` 3 条（随包 JSONC 可解析 / update 接受 JSONC 并写出严格 JSON / 损坏内容仍报错）+ `test_hook_registry.py` 2 条（带注释的 hooks 文件照常加载 / 随包文件可加载）。
- 验证：3 条实现级测试在旧实现上失败；第 4 条（`test_shipped_hooks_file_is_loadable`）是资产级守卫、不随实现变化，已在测试名中区分；`test_hook_registry|plugin_operations|hook_engine|config_defaults` 48 passed。

**5. 插件依赖 pip 参数注入（P2）**
- 改动：`plugins/deps.py` 的 `_REQUIREMENT_RE` 要求包名以字母/数字开头（`-r` 曾能当"包名"通过）；新增 `validated_requirements()`；`dry_run_install` / `install_dependencies` 只把归一化后的 `name[op]version` 交给 pip，非法项直接返回失败（调用方已有回滚分支）；`uninstall_dependencies` 只按包名卸载；`install_command_hint` 同步。
- 测试：`test_plugin_lifecycle.py` 新增 3 条（归一化剥离 pip 参数 / `install_dependencies` 拒注入且不调用 pip / `dry_run_install` 同上）。
- 验证：3 条在旧实现上全部失败（旧码真的调用了 pip 并带上了 `--index-url`）；全套 35 passed。

### 波次 2 · 发布与更新通道（进行中）

- `scripts/bump-version.ps1` 与 `.github/workflows/release.yml` 的版本/tag 校验放行 `X.Y.Z[-pre][+build]`；`release.yml` 在 Inno 构建后新增「生成官网更新清单」步骤并把 `core/desktop/update-manifest.json` 作为构建产物上传（上传站点仍人工）；`core/desktop/update-manifest.json` 进 `.gitignore`（生成物）。
- `scripts/build-desktop-update.py` 入库（已 `git add`），并修掉 `main()` 二次解析安装包（仓库副本与上传副本现在必定描述同一个文件）。
- 移动端 `StandaloneUpdate.compareVersion` 与桌面 `compare_versions` 对齐为同一套语义（补零比较核心、预发布低于正式版、预发布段按 semver）。
- 前端：`useCoreUpdateState.ts` 增 `reason` / `notes_source` / `noInstallerForPlatform`；`CoreSettings.vue` 在"有版本但本平台没有安装包"时改说「已发布 vX，但没有适用于本平台的安装包」，不再显示成"已是最新版本"。
- 待办：`update/checker.py` 的两源取较高版本 + `notes_source`（回归跑完即改）、CLI 来源行与旧 docstring、`PACKAGING.md` 的发布后上传一节。

### 波次 4 · 正确性（core 批已完成；其余见下）

**已完成并在本提交内**

- **checkpoint 备份永不回收（P2）**：`checkpoint.py::_prune_mainline` 现在删除被裁检查点的 `CoreCheckpointBlobRef`，并新增 `_gc_checkpoint_blobs()`：以「活着的清单引用 ∪ BlobRef」为活引用集（回滚是通过清单里的 digest 找内容的，BlobRef 不是唯一来源），收集无引用的 blob 行 + 文件，同时删掉没有任何 checkpoint 引用的 `CoreWorkspaceManifest` 行；整会话删除路径（`core_session_store.delete_session_records`）同样补上 blob 行与文件回收。**第一版实现只按 BlobRef 判定，被 `test_core_checkpoint_graph` 抓出"收过头"（回滚要的 blob 被删）**——这条故障正好说明为什么清单也要算引用。
- **live 事件持久化失败杀死整轮（P2）**：`default_agent._persist_core_event_live` 的落库 + hub 广播段包 try/except，失败只记 warning（模型与工具都已成功，不该判整轮 failed）。
- **历史裁剪计数反了（P3）**：`kernel/loop.py` 的 `trimmed` 在 `del history[:cut]` 之前取值，报出去的是"剩余"而不是"裁掉"。
- **plan 把 blocked/failed 当完成（P3）**：`runtime/plan.py` 只有无 blocked/failed 步骤时才标 completed。
- **arrange 静默吞异常（P3）**：cancel 落库失败改为 warning + 返回 False；spawn 的任务用具名回调取回异常并记日志。
- **observer 读循环被存储异常杀死（P3）**：单行处理异常不再中断读取，改为 warning + `last_error`。
- **附件引用 endswith 误配（P3）**：`artifact/registry.py` 改为与规范 URI 精确比较。
- **generate_image 参考图越界（P3）**：`tool/image_tools.py` 增加 `is_within_path(work_root)` 收敛（与命令工具同一条边界）。
- **access_tools.jsonc 按 JSONC 读（P3）**：`tool/approval.py` 复用共享解析器，注释不再让整份 tier 静默清空。
- **workflow 多输入端口静默串值（P3）**：未连接的多输入端口留 `None`，不再填第一个绑定值。
- **文件锁表无上限（P3）**：`tool/workspace_files.py` 的 `_FILE_LOCKS` 加上限（超限回收未持有的锁）。
- **信任账本/技能状态损坏即炸（P2/P3）**：`plugins/trust.py` 与 `skills.py` 的 `_load` 解析失败降级为空并记 warning，`_save` 改原子写；技能正文按 `utf-8-sig` 读（带 BOM 的 SKILL.md 曾丢掉整个 frontmatter）。
- **arrange signal 入参校验（P3）**：`core_db.emit_signal` 缺少 `event_id`/`occurred_at` 时给出可读错误，不再以空主键入库或抛 KeyError。
- **事件 payload 序列化（P3）**：`app/event_store.py` 的 `payload_json` 过 `_json_safe`（其余列本来就过）。

**记录但本轮未修（附原因，交由下一批决策）**

- `web_fetch` 的 SSRF 面（私网/环回、重定向跟随）——需要与"允许访问本地服务"的既定用法（`_fetch_with_loopback_bypass`）一起设计，属行为决策而非纯缺陷。
- `SubAgentSupervisor` 的 sqlite 连接不关闭与 supervisor 无淘汰——改动面较大（涉及 `shutdown_parent_sub_agents` 的调用时机），单独一批更稳。
- `runtime_projection` 与 `_canonical_status` 的状态口径不一致（skipped/blocked 的展示）——是产品语义选择，需先定口径。
- `snapshot_store` 重建扫描的覆盖索引、事件 id 长度、`kernel_steps` 上限、循环前置段的 try、`artifact` 等其余 P3——纯改进项，未与本次安全/发布批次混提。
- runtime-rs 与 core/ui 两批（详见 §5 的 P2 清单）与 CI 批次未在本轮执行。
- 移动端 0.1.31 出包未执行：等待 runtime-rs 批次一并进包，避免同一批修复出两次包。

### 波次 5 · 卫生与文档（已完成的与剩余）

**已完成**：`.gitignore` 收口（`/core/mobile/artifacts/`、`/core/experiments/`、`/MyProject/`、`/artifacts/`、`gen/schemas/`、`core/desktop/update-manifest.json`、`*.7z`、`.tmp_*`，只忽略不删文件）；`.agents/skills/lamtools-setup-install` 入库；`AGENTS.md`（Inno、website 依赖 core/ui、展示区改为 iframe 预览、移除已删除的 inView 与 `TODO(文案)` 说法）；`README.md`/`README.en.md`（Inno、Linux 已发布）；`agent_docs/project_core_tech.md`（Inno）；`core/desktop/PACKAGING.md`（预发布版本 + 站点清单上传）；`core/lamtools-core-backend.spec` 的模块数注释；`website/.env.example` 与 `src/mock/runtime.ts` 版本；`scripts/test-arrange-agent.js` 端口。

**剩余（未做）**：`docs/core-ui-streaming-perf.md` 的行号锚点；`core/desktop/PACKAGING.md` 的资产清单行；`docs/` 内其余脚本路径漂移（`scripts/office.py` 等）。以及"待你拍板"的删除类清单（见 §6 与审计报告）。


## 8. 本轮教训

1. **`git check-ignore` 默认不报告已跟踪文件**：它在 `output/` 上"无命中"被我误读成"未被忽略"，于是把子代理的正确结论改错了一次。查"是否被忽略"要看 `.gitignore` 本身或用 `--no-index`；tracked-while-ignored 的判定必须看 `git ls-files` 与规则的组合。（§4 第 1 条已二次更正）
2. **测试要对着旧实现验证**：本轮 16 条新测试里 15 条在 `git stash` 掉源改动后失败、恢复后通过，证明它们钉住的是缺陷而不是实现细节；唯一通过的是资产级守卫（随包文件可加载），已在命名上区分。
3. **收紧"来源"要连带检查消费方**：删掉 websearch 的 work_root 候选后，`default_toolbox` 的 handlers 表原本根本没传 `data_dir`——只改一处会让用户作用域配置静默失效。同类：MCP 收紧后要确证 `env` 与 `config_files` 仍生效。



