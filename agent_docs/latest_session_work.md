# Latest Session Work

## 待一起处理的业务现象清单（2026-09-29；用户：「先记着，等到时候一起搞」）

用户要求把本轮诊断出的现象记在这里，等拿到另一台机器的日志/文件后一起处理；需要时由 agent 向用户索取材料（用户已表示会主动提供）。

### 已修、未出包（改动已提交，未发布）

1. **项目外文件让整轮失败** — 已修 `1f6c15a7`（含守卫测试）。现象：批准访问工作区外后，文件读写是成功的，但事后"成果登记"拒绝它并把整轮判失败（`Artifact path escapes project`）。现在项目外文件不再登记为项目成果（保留工具卡片、记一条跳过日志），且成果登记的任何失败只降级为警告。
2. **Study 运行中禁用输入框** — 已修 `8292ecf1`。现象：学习模式运行期间无法输入、排队或引导（该模式自行声明"运行中禁用"，与全产品一致行为相反）。现在只有会话未就绪时才禁用。
3. **手机端停止后上下文丢失** — 已修 `7a95ea1c`。现象：手机上中途停止再发一条，模型像失忆（之前的工具步骤与结果全丢）；修法同时保证"半截工具调用"（有调用无结果）不会被发出。

→ 这三条都要出包才到用户手上：**桌面 0.3.10 / 手机 0.1.47**（用户尚未确认发布）。

### 已诊断、按用户要求暂不动手

4. **供应商密钥含非 ASCII** → 请求本地就构造失败，且被当成临时故障重试 10 次。现象：`Model call failed after 10 attempts: 'ascii' codec can't encode characters in position 7-14`。实测只有"请求头的值含非 ASCII"会报这一句，`Bearer ` 恰好 7 字符，而模型请求头里唯一来自配置的值就是密钥。本机 12 份供应商配置中仅 `E:\setuptest\0.3.6\.lam\core\config\providers\command-code.jsonc` 是坏的（61 字符、43 个汉字的句子，形如对话内容）。待修：保存时校验并给人话提示；编码类错误归为"配置错误、永不重试"；报错点名"供应商密钥"。
5. **供应商配置在磁盘上被外部改写会在运行中途生效**。现象：用户报"另一台电脑、同一模型同一供应商，运行着运行着突然编码异常"。机制：供应商配置按 `(path, mtime_ns, size)` 缓存失效（`config/provider_store.py:167-175, 257-267`），文件一变下次调用就重读。可能的改写通道：环境变量引导（`LAMTOOLS_LLM_API_KEY` 会写入供应商）、云盘/备份同步、编辑器旧缓冲、同机第二个实例、恢复备份。产品自身除设置/CLI 外不写供应商配置，且打码/空值不会覆盖真密钥；同步/中继层不携带配置。待修：配置在磁盘上变化时给出可见提示。

   **用户 2026-09-29 补充的复现（用户称已验证可靠）**：选 Command Code 的 DeepSeek-V4.1 flash + 推理档"轻"；在一轮执行中再发一条消息（进入排队/引导队列）→ 该轮结束后这条被派发执行 → 该轮报编码错误；到供应商设置里重新输入 API key 后恢复正常。

   **本轮排查结论（2026-09-29）**：产品**没有**"把排队消息文本写进密钥"的代码路径——写 `api_key` 的地方只有三处：设置页 `config.provider.create/update`（用户保存）、`import_environment_operation`（设置页"从当前环境导入"按钮，手动触发）、老式 `POST /providers`（UI/手机均未引用）；排队派发调用的成员钩子 `materialize_turn` 为空实现（只读）。因此更可能是「**密钥先被应用之外的东西改写，下一次模型调用（恰好是那条被派发的消息）才暴露**」——配置按文件签名失效，运行中途就会换用新值。仍未排除：手机连着主机时在手机上保存供应商设置（写的是主机那份文件）、同机第二个实例共用同一配置目录。

   **一次定案所需证据**（下次复现，先别重输密钥）：①该供应商配置文件的副本，或至少其修改时间 + 密钥字段形状（长度/是否含中文，勿贴内容）；②`.lam/backend.log`；③该机器是否存在 `LAMTOOLS_LLM_API_KEY` 及其值形状；④**那条排队消息的原文**——若密钥字段里的中文恰好就是它，即为产品内部写入（继续深挖）；若不是，则定案为外部改写 + 缓存失效时机。

   **2026-09-29 日志取证（用户提供另一台机器 E:\Sunday 的 backend.log，47545 行）**：
   - 编码错误共 47 处，全部落在 **免费池** 供应商的模型上：`command-code-free-inclusionai-ling-3.0-flash-sante-free`、`command-code-free-poolside-laguna-s-2.1-free`、以及 `poolside/laguna-s-2.1-free`（另一个供应商记录）。同一日志里**正式版** Command Code（`model=command-code-deepseek-deepseek-v4.1-flash`）HTTP 200 正常——用户以为在用的正是这个，实际失败的是模型分组 "Free" 的成员。
   - 时序：`queue/create`(8072) → `queue/guide`(8093，用户对排队项点了引导) → `config.provider.create`(8614) → **首次失败**(8693) → `config.provider.update`(9005，用户重输密钥) → 恢复；之后 21369/28280/34838/41106/43672 又出现失败，并伴随 33601/41164 的再次 `config.provider.update` 修复。
   - 结论：报错的直接原因是**该供应商文件里存的密钥是非 ASCII**（日志里 key 值不可见，但错误形态与本地实验一致：只有请求头值非 ASCII 会报 `'ascii' codec can't encode characters in position 7-14`，`Bearer ` 恰好 7 字符）。写密钥的只有"新增/更新供应商"，且字段映射逐行核对正确、当前预设**没有**预填密钥（历史上仅有一个 ASCII 的 `defaultApiKey: 'public'`）；预设文件与日志里都搜不到 0.3.6 那份密钥里的中文（"王者万象棋开…"）。因此中文来自**创建供应商时密钥框里的输入内容**（8 个非 ASCII 前缀紧接 ASCII 密钥，符合"复制密钥时把中文标签一起带走"）。
   - "引导后崩"是**暴露时机**而非原因：失败的那一轮只是密钥变坏之后的下一次模型调用。产品侧仍缺三件事：保存时不校验非 ASCII、编码错误被当作可重试（重试 10 次）、报错不点名供应商/模型（这次用户因此误判供应商）。
6. **403 `Authentication failed` 缺定位信息**。现象：报错不带供应商/地址/模型，用户只能猜。待修：错误里带上这三项；并排查"密钥被放进对方不检查的请求头"（协议/auth 变体不一致）这一可能。
7. **命令预检误伤合法命令**。现象：`Path argument '…' (position 13) uses mixed or unmatched quoting that cannot be validated safely`（被拒的是一条 Linux 环境探查命令，未执行）。根因：引号无法静态验证即整条拒绝，而工作区边界已于 2026-09-27 取消强制（`_outside_access_allowed()` 恒真），该检查只剩误伤；同一判断在审批侧的实现是跳过（`outside_workdir_path_arguments`）。实测本机（git-bash 分词）原样通过，说明与所用 shell 有关——很可能是新增的 WSL 通道。待修：与兄弟实现对齐（不强制边界时跳过）、提示改可操作文案、补三种外壳的回归。
8. **审批/提问出现时，用户不知道要点卡片，会跑到输入框里"回答"**（用户 2026-09-29 提出，来自其朋友的实际使用）。用户建议采用标准 Agent 做法：**有审批时把输入框替换为审批样式**；样式不必照搬现有审批卡，由实现者设计。实现要点（建议，待与用户确认细节）：①审批/提问待解时，输入框区域被审批面板占据（说明"要做什么/影响什么/有哪些选项"），用户不可能误把输入框当回答入口；②选项即按钮（允许一次 / 允许本次会话 / 拒绝 / 用一句话引导），引导输入只作为该面板的一部分；③面板解决后自动恢复为正常输入框；④与排队/引导、以及手机端窄屏下的呈现一并对齐。

### 进行中：缓存命中率偏低（2026-09-29 用户新提）

- 现象：用户观察到**缓存命中率约 70%**，预期约 98%。
- 指标定义：`cache_hit_rate = cached_tokens / input_tokens`（`event/runtime_projection.py:1122-1137`），**分母是该次调用的全部输入**；`cached_tokens` 由供应商上报（`cachedContentTokenCount` 等，`llm/profiles.py:1689`）。
- 判断：每次调用都 98% 只在"新增内容极少、前缀极稳定"时成立；工具结果成段进入上下文时命中率必然下降。产品代码里**没有任何缓存断点标记**（无 `cache_control`/ephemeral），能命中多少取决于供应商的自动前缀缓存。
- 待查方向：①该指标口径与用户"98%"预期的来源是否一致（是否来自别的工具/别的机器/旧版本）；②是否每轮在换模型或供应商（模型分组 "Free" 含两个模型，缓存各自独立）；③是否有每轮变化的内容破坏前缀（工具集变化、上下文压缩、每轮注入的上下文）；④指标本身是否存在口径问题（把缓存写入计为未命中、分母含新增内容等）。
- 需要的材料：该机器的 `.lam` 日志、**每轮用量指标**（`cached_tokens`/`input_tokens`/`cache_creation_tokens`/`cache_hit_rate` + 当轮模型与供应商 id）、70% 的观察位置、98% 预期的来源、所用供应商与协议（Anthropic 协议尤其需要显式缓存断点）。

### 用户决定（待实现）：取消"全局默认模型"，改为"跟随上一个会话"

用户 2026-09-29 明确要求：**不再设立默认模型**；**新建会话跟随上一个会话的模型**；**在其他非会话区域调用模型时，也跟随上一个会话所使用的模型**。动机：新增供应商会静默改默认模型 → 会话在用户不知情的情况下换模型（本次编码错误事件的成因）。

现状与影响面（供实现时定位）：
- 现状：预设新增供应商会给其"预设默认模型"打 `is_default`，后端写为**全局唯一默认**并把原默认降级（`config/operations.py:162,236,255,805-806`）；"当前模型"由 `selectCoreExecutionModel(models, selectedModelId, defaultModel)` 解析，**所选 id 缺失即回落默认**（`ui/src/composer/execution.ts:122-132`）。每会话其实已有运行时偏好记忆（`RuntimePreferences`），非会话调用（自动标题等）当前是"回合模型 > 会话元数据 > 宿主默认"（见提交 `7597a271`）。
- 待实现（要点）：①新增/更新供应商时不再静默改全局默认；②新会话继承"上一个会话"的模型；③非会话调用（自动标题、上下文压缩、dreaming 等）跟随最近会话所用模型；④空配置/首次运行的确定性规则（见下）。
- **需要用户拍板的开放点**（建议已给出，待确认）：
  1. **首次/空配置**：没有任何"上一个会话"时用什么？建议：用"最近一次新增供应商时选定的模型"，仍为空则明确提示"请先添加供应商/模型"，不再静默回落。
  2. **"上一个会话"的作用域**：桌宠会话刻意用便宜模型、Study 需要能看图的模型、子代理/观察者会话是自动创建的。建议**按作用域各自记忆**（主对话 / Study / 桌宠 / 后台任务），而不是全局一个"最近会话"，否则新建主对话可能继承桌宠的便宜模型。
  3. **继承对象被删除或不可用时**：建议明确报错或回落"同作用域内最近可用的模型"，不静默换到别的供应商。
  4. **模型分组**：会话继承的是"组"还是"组内具体模型"？建议继承组（保持轮换语义）。


### 进行中：新增供应商会静默改变"当前模型"（2026-09-29 日志取证）

- 现象（用户提问）："我全程用的都是 DeepSeek，为什么一引导就被切到免费模型组？"
- 证据（E:\Sunday 那份 backend.log）：同一个会话 `003e34e3df8b483d9f34620e237420e0` 内，前两轮 `model=command-code-deepseek-deepseek-v4.1-flash`（正常），第三轮（用户插队/引导之后的下一轮）变成 `command-code-free-inclusionai-ling-3.0-flash-sante-free`；该轮之前日志里正好有一次 `config.provider.create`（+ `config.model_group.create/members.set`，即预设新增供应商并建组）和一次 `settings.update`。
- 机制（代码）：预设新增供应商时，UI 会给"预设的默认模型"打 `is_default`（`CoreSettings.vue` 的 payload 构造），后端把新默认写为全局默认并**把原默认降级**（`config/operations.py:162,236,255,805-806`）；而"当前模型"的解析是 `selectCoreExecutionModel(models, selectedModelId, defaultModel)`——**所选 id 缺失时回落到默认模型**（`ui/src/composer/execution.ts:122-132`）。用户从未显式指定模型（一直用默认），因此默认一换，**下一轮就换模型，且界面没有任何提示**。
- 待修（产品决策）：①预设新增供应商不应静默改"当前模型"（要么不动全局默认，要么明确提示"当前模型已切换为 XXX"）；②这正是"时好时坏"的来源——每次新增免费池预设都把默认模型换到它自己的默认模型，而那条记录的密钥是坏的。与第 4、5 条同属一类：缺校验 + 缺可见性 + 报错不点名。

## Mobile parity batches and the eight behaviour defects (mobile_parity_and_behaviour_fixes_20260924; 2026-09-24)

- State: **complete**, both goals. The parity batches 1–8 (0.1.14–0.1.23) closed the surface gaps recorded in `core/docs/audits/mobile-desktop-parity-2026-09-24.md`; the eight defects real-device testing then reported (0.1.24–0.1.28) were behaviour defects inside code that already existed, and each is recorded with its evidence and residual in the behaviour-audit section of that same document.
- Baseline and tip: work started at HEAD `5d11f3fe`; the series ends at `a17c7073` on `codex/multiplatform-dev` with the working tree clean apart from the untracked release-artifact folders and pre-existing stray paths. Every version was committed by itself; no tag and no push.
- Releases: 0.1.14 … 0.1.28, each built by `scripts/package-mobile.ps1`, independently re-verified with apksigner/aapt, uploaded through the audited Cloud Assistant flow, published with the previous stable archived, and confirmed by a full public GET against the local SHA-256. Audit per version in `core/mobile/artifacts/release-10NN/RELEASE.md`. The website carries each version under `site-releases/0.3.6-mobile-<version>-20260924`.
- 0.1.24 tool rounds (`runtime-rs`): the `MAX_TOOL_ROUNDS = 8` cap and `RuntimeError::ToolLimit` are gone, replaced by the desktop's two evidence-based guards — tool-only round counting with the desktop's verbatim `[TOOL_PROGRESS_REQUIRED]` note, and the repeated-identical-result stop (10 within 12). Where the desktop pauses for the user, mobile winds the turn down recoverably: no error, nothing discarded, reason on `runtime_warnings`, one final tool-free request. Thresholds are `TurnOptions` fields.
- 0.1.25 context after cancel/failure: `conversationMessages` accepts the durable `rust_runtime_history` whenever the turn that wrote it is still a completed turn of the session, then appends the messages of the later turns in order; failure reports are no longer replayed as assistant answers (only to the model — the transcript keeps them).
- 0.1.26 update manifest: published for the first time as part of the release steps (generated from the built APK's metadata, compared against the repository copy, hash-verified server-side), asserted in `verify_public.py`, and every client failure now names the address it could not read. The shipped function was run against the live endpoint once (`up_to_date` for 0.1.26, `update_available` for 0.1.0) with a temporary test that was removed afterwards.
- 0.1.27 attachments: `sunday_attachment_save`/`read` carry `dataBase64` (no `Vec<u8>` remains on the command surface), the client keeps its `Uint8Array` signature, and attachment bodies are cached by id under a 32 MiB budget so replaying a conversation no longer re-reads every image.
- 0.1.28 P3: the Workflow entry's stale comment is replaced with the truth (mode still hidden by decision), idle `queue/create` enqueues and dispatches immediately with its own envelope, and `openStudySession` deduplicates in flight per scope.
- Verification at the tip: runtime-rs 146, mobile crate 46, mobile vitest 241. New tests that pin a defect were checked against the previous implementation by stashing the source change; the only exception is the `turn/steer`-with-no-active-turn case, which passes either way because that guard already existed.
- Not verified on device: the >8-round tool chain of 0.1.24 and the large-attachment timing of 0.1.27. Both need a real phone run of the kind of task that produced them.
- Operational lessons from this series are in `agent_docs/project_diary.md` (behaviour-audit coverage, `*>` redirect killing the packager wrapper, CRLF hashing, stale per-release constants, leaving a foreign SSH key alone).

## Mobile/Desktop audit and Study skill assembly closure (mobile_study_skill_assembly_20260923; 2026-09-23)

- State: **complete for the audit plus specified Study main-agent assembly fixes only**. This does not mean all findings are fixed or the Rust migration is complete. The canonical finding list and repair sequence are in [the full audit](../core/docs/mobile-desktop-code-audit-2026-09-23.md); detailed evidence is under `core/docs/audits/mobile-desktop-2026-09-23/`.
- Read-only baseline: HEAD `9cc013066f6229ce48a0cf4784cdb9e9f6503019`; audit covered the current working tree. The source changes are uncommitted and unreleased. Published APK remains 0.1.7 / versionCode 1007; next package is 0.1.8 / 1008.
- Study source repairs: accept `study` and `study:study`; pass mode and disabled-skill filtering on initial and approval-resumed assembly; embed five canonical skills and fourteen references with bounded `load_skill` / `read_skill_reference`; improve capability and save-claim prompt rules; correct two mobile text color tokens. These fixes are not in 0.1.7. Ordinary skill loading and Study subagent tools/context are still missing.
- Verification: mobile tests 175, runtime Rust tests 130, native Rust tests 18, and mobile typecheck passed (323 tests total). Independent local PreToolUse fixture reproduced the unresolved issue: both `deny` and `ask_user` returned completed and each invoked the tool once. This is a confirmed failure, not a pass.
- Next entry point: repair permission enforcement, attachment byte persistence/model input, Study mark concurrency, and encrypted backup recovery first; continue in the priority order and acceptance conditions in the report. Preserve ability parity by implementing usable paths, not by hiding features. Keep current version/build/publish state unchanged until the fixes are scoped, verified, and a later release is requested.
- Git handoff: no commit, push, version bump, package build, publication, or cleanup in this closure. HEAD is unchanged and the working tree remains broadly dirty, including work from other tasks; preserve all of it.

## Goal

Finish and verify the LamTools single-UI + multi-Transport mobile refactor,
with no remaining demo/mobile business-UI entry point.

## Implemented

- Promoted `core/ui/src/app/LamToolsApp.vue` to the shared product root and
  removed `core/ui/src/demo/` and `tsconfig.demo.json`.
- Added the connection-neutral Workbench runtime and Transport contract. All
  shared UI REST/RPC access goes through the injected transport.
- Switched Tauri desktop to DirectTransport and mobile to one stable
  RemoteTransport. Mobile `App.vue` retains only pairing, native lifecycle,
  trusted-device, and connection orchestration before mounting the shared app.
- Added Noise-secured LAN/Relay tunnel handling, pairing/device identity,
  split secret storage, reconnect/route selection, sequence replay checks,
  protocol negotiation, and multi-client Core event/response routing.
- Added transport, Workbench, tunnel, pairing, gateway, and multi-client
  synchronization coverage. Corrected the context-compaction planner guard
  and no-LLM short-history behavior.
- Applied LamTools design tokens and verified the design audit is clean.

## Verification

- `cd E:\LamTools\core; py -3.14 -m pytest -q`: `1677 passed, 2 skipped`.
- `cd E:\LamTools\core\ui; npm run typecheck`: pass.
- `cd E:\LamTools\core\ui; npm run test:contract`: 67 files / 471 tests pass.
- UI build, mobile typecheck/tests/build/Capacitor sync, desktop Rust tests,
  check/format, Relay tests/format, Android Debug APK build, and website build:
  pass.
- Docker Compose static configuration passes with a supplied domain; the real
  image build is pending Docker Hub network access.
- `node .agents/skills/lam-design-spec/scripts/audit.mjs`: 69 files, 0
  deviations.
- `git diff --check`: pass (Git only reports normal LF-to-CRLF warnings).

## Working-tree Notes

The repository remains uncommitted so existing user changes are preserved.
The generated context-compaction fixture directories and `playwright-test/`
were left untouched; they are not part of the refactor implementation.

## Continuation

Use Tauri as the UI observation surface. Any future business capability should
be added once in shared UI/Workbench. Any future connection path should be
implemented behind RemoteTransport/ConnectionManager without adding a second
mobile UI.

## Provider cancellation and retry visibility

- Codex666 AI connectivity is valid at the models endpoint, but real completion
  is slow and streaming is unstable (including upstream 502 responses).
- Model retry projection now retains the error/backoff details, and all process
  rendering paths show them while retrying.
- Live Stop now cancels provider I/O before SQLite persistence and keeps the run
  claim until terminal state is durable. A real provider run measured 102 ms for
  the server-side cancel RPC and about 240 ms until the cancelled terminal event.
- Verification: 238 targeted Python tests, 78 targeted UI tests, UI typecheck,
  design-token audit, and `git diff --check` pass.
- Follow-up raw capture showed standard `data: ` framing. A minimal request
  completed in about 9 seconds on one run and 40 seconds on another; an actual
  CLI-assembled 33,147-byte/24-tool request completed in about 12.7 seconds.
  This narrows the incident to high provider latency variance and intermittent
  upstream errors rather than a stable request incompatibility. The client now
  also accepts valid `data:value` SSE framing; its focused profile suite passes
  40/40 tests.

## Office retest process-audit handoff

- Task/deployment: `office_retest_process_audit`; state: `complete`.
- Outcome: process review of the Microsoft FY25 Q4 and customer-handover retests is complete. Scores are 5.8/10 directness and planning, 6.4/10 failure/problem control, 5.5/10 speed/efficiency, 8.9/10 instruction adherence, overall 6.7/10.
- Material documentation: `core/docs/office-skills-internal-evaluation-2026-09-10.md` now records event-derived elapsed times (finance 641.384 s; handover 241.735 s, baseline 140.720 s), timing breakdowns, failure evidence, Skill-routing gaps, cache-prefix evidence, and visual limitations.
- Verification: read-only review of `summary.json` and `events-redacted.json`; event start/done timestamps confirm the recorded wall times. No implementation tests were rerun for this documentation-only closure.
- Pending work/blockers: newcomer-onboarding retest was not run; finance footer/source-note and page-number overlap remains a visual acceptance risk despite a zero-overlap geometry report; handover still lacks the `office-email` route.
- Evidence: `.tmp/office-skills-evaluation/2026-09-10-retest/02-microsoft-fy25q4/run/` and `/07-customer-handover/run/` (`summary.json`, `events-redacted.json`). Exact next entry point: resolve the finance footer reserve-area/geometry check and complete the missing Skill routes before another Office retest.

## Card overlay close pointer guard handoff

- Task/deployment: `card_close_pointer_guard`; closure state: `complete`.
- Outcome: overlay card dismissal now requires the same pointer's
  `pointerdown` and `pointerup` to both occur outside the card. The shared
  implementation is `core/ui/src/composables/useOutsidePointerDismiss.ts`.
- Material changes: all existing `@click.self` / `@mousedown.self` card
  overlay close points use the pointerdown/pointerup guard. Nested and
  Teleport-rendered overlays are isolated through their overlay subtrees.
  Coverage includes CoreSettings, CorePluginsEditor, CoreProjectSettings,
  PluginsShell, SearchShell, CoreArrangeManager, ThemeEditor, MessageView,
  CoreProjectCreate, CoreProjectPicker, and FolderBrowserDialog.
- Verification: `npm run test:contract` passed with 71 files / 494 tests;
  `npm run typecheck` passed; `npm run build` passed; LamTools design-spec
  audit passed with 71 files / 0 deviations; `git diff --check` passed.
- Verification limitation/blocker: Tauri/CUA manual observation was attempted
  and the prescribed retry/reset flow was exhausted, but it was blocked by
  `nodeRepl.fetch request failed`. No manual-observation pass is claimed.
- Working-tree disposition: existing uncommitted user changes remain present;
  the closure did not commit, revert, or clean them. The pointer-guard source
  and test files are also uncommitted in the current working tree.
- Pending work: no pointer-guard deployment work remains. Real-device
  LAN/Relay pairing and reconnect validation, plus the Docker image build when
  Docker Hub access is available, remain project-level follow-up items.
- Evidence: `core/ui/src/composables/useOutsidePointerDismiss.ts`, the covered
  component sources listed above, `core/ui/tests/outside-pointer-dismiss.test.ts`,
  and the command/audit results recorded here. Exact next entry point: inspect
  the current uncommitted working tree, then continue with real-device
  LAN/Relay pairing and reconnect validation when credentials and devices are
  available.

## Office Skills GUI 财报复测（2026-09-11）

- 会话：`#4124c504`；项目：
  `.tmp/office-skills-evaluation/2026-09-11-gui-retest/02-microsoft-fy25q4`。
- 详细报告：`core/docs/office-skills-gui-retest-2026-09-11.md`。
- 事件证据：`data/core.db` 的 `core_app_events`，thread id
  `4124c50498f5441d83b377dc16fa0e48`；`turn/accepted` 到完成状态为
  1241.224 秒，1261 条事件。
- 结果：XLSX/PPTX/PDF/摘要均生成；证据 350/350 命中，工作簿重算 28
  项通过、5 项记录、0 个错误单元格，PPTX/PDF 结构和数字交叉核对通过。
- 过程评分：直接性/规划 6/10，失败控制 5/10，速度/效率 3/10，指令
  遵循 7/10，综合 5.5/10。
- 运行量：118 个 LLM 步骤、140 个逻辑工具调用、8 个工具失败、123
  个 usage 回合；输入 15,543,306、缓存 15,260,800、输出 140,028，
  加权缓存命中率 98.18%，最大单次输入 243,853/256,000 Token。
- 视觉结论：程序化报告称 0 越界/0 重叠，但人工查看预览发现 p02、p03、
  p04、p06、p07、p09 仍有标题、表格或文字区域冲突；不得把几何/文本
  校验当作视觉通过。
- GUI 刷新结论：事件在停止前按顺序落库，未重现旧订阅队列阻塞的后端证据；
  仍需以人工首条正文、重试和 Stop 响应时间记录完成 GUI 验收。
- 下一步：先修生成前的标题/表格/页脚安全区和视觉通道前置判断，再收敛
  批量生成步骤与重复状态事件；不要先扩大 Office Skill 范围。

## Auto-follow and process-card compacting handoff

- Task/deployment: `auto_follow_process_cards_20260911`; closure state:
  `complete`.
- Outcome: auto-follow uses `scrollHeight - clientHeight`, clears stale
  programmatic intent after upward input, and only frame-corrects after actual
  growth. Older history auto-loads within 160px of the top with an in-flight
  guard and height-delta viewport anchoring; the manual load control is gone.
- Material changes: the thread scrollbar reaches the main chat edge with 5%
  resting / 12% hover thumb opacity. Live thinking/tool process remains visible
  while each message-level card defaults collapsed to a responsive three-line
  semantic-tail caption. Captions snapshot every 2s with fade transition;
  operation/state uses Lucide icons; running uses shimmer plus restrained
  breathing and completed is static. Pointer leave schedules 5s card/group
  collapse and re-entry cancels it. Adjacent reasoning and ordinary tool parts
  fold into one group while pending approvals remain auto-exposed.
- Final copy/interaction correction: reasoning titles preserve the last semantic
  sentence. Tool titles use action + target: `load_skill` renders “加载技能 ·
  技能名”, writes/edits render the filename, and commands render the concrete
  command; title indentation is unified. Clicking a title reveals 3 lines of
  body content, clicking the body expands a 7-line body viewport, and mouseleave
  collapses it after 5s. The 3/7-line limit applies only to card body content,
  not tool outer frames or file/terminal bars; `.thread
  .reasoning-body.process-card-body--*` raises specificity for reasoning bodies.
- Older-history pagination hides its skeleton, prefetches at two viewports or at
  least 640px ahead, fetches 50 items per batch, and anchors correction to the
  first visible message DOM node.
- Verification: focused 4-file coverage passed 104/104 tests; final
  `npm run test:contract` passed 71 files / 500 tests; `npm run typecheck` and
  `npm run build` passed; Lam design audit passed 71 files / 0 deviations;
  `git diff --check` passed with only LF/CRLF warnings.
- Final correction verification: the focused suite passed 96/96; contract suite
  passed 71 files / 502 tests; typecheck, build, and the 71-file/0-deviation
  design audit passed; `git diff --check` reported only newline warnings.
- Limitation: no Tauri/manual UI run was performed, per the user request to
  verify code correctness only; no visual/manual pass is claimed.
- Working-tree disposition: pre-existing and concurrent uncommitted changes
  remain; this closure changed only the assigned documentation and did not
  commit, revert, or clean production/test work.
- Evidence: `docs/core-ui-streaming-perf.md`,
  `core/ui/src/composables/useCoreAutoFollowScroll.ts`,
  `core/ui/src/app/LamToolsApp.vue`, `core/ui/src/components/ChatThread.vue`,
  `core/ui/src/components/MessageView.vue`, `core/ui/src/styles/layout.css`,
  and the focused/contract test results above.
- Pending work/blockers: no deployment-specific blocker is known. Project-level
  follow-up remains the Office visual-quality work, real-device LAN/Relay
  pairing/reconnect validation, and the Docker image build when Docker Hub
  access is available. Exact next entry point: inspect the current uncommitted
  tree, then continue with those project-level milestones.

## User-message history paging handoff

- Task/deployment: `user_message_history_paging_20260912`; closure state:
  `complete`.
- Root cause: `_character_page_snapshot` paged only `core.item_order`, then
  filtered top-level items by Core-selected IDs, making persisted `userMessage`
  rows unreachable in large turns.
- Fix: unify sequence-ordered top/Core paging, include causally preceding
  user-message anchors for selected assistant turns, and widen the frontend
  tail window when a boundary lands on an assistant.
- Evidence: real thread `4124c50498f5441d83b377dc16fa0e48` now yields an initial
  200KB page containing its user ID, 27 latest Core items, `has_more=true`, and
  `character_count=186390`.
- Regression coverage: `core/tests/test_core_sync.py` and
  `core/ui/tests/core-workbench-projection-window.test.ts`.
- Verification: `pytest tests/test_core_sync.py -q` passed 7 tests; focused UI
  coverage passed 2 files / 32 tests; full UI Vitest passed 71 files / 503
  tests; `npm run typecheck` and `npm run build` passed; touched-file
  `git diff --check` passed with LF/CRLF warnings only.
- Limitation: a broader pre-existing backend subset had 89 passed / 1 unrelated
  failure in `test_core_live_resume_response_exposes_page_cursor` because it
  expects events although resume defaults to include a snapshot. This is not
  attributed to the paging patch. No Tauri/manual UI run was performed per the
  user request.
- Working-tree disposition: existing uncommitted changes remain; this closure
  changed only the assigned documentation and did not commit, revert, or clean
  production/test work. No deployment-specific blocker is known.
- Exact next entry point: inspect the current uncommitted tree, then continue
  with the existing project-level Office visual-quality, real-device LAN/Relay,
  and Docker Hub follow-up milestones.

## Unified message attachment deck handoff

- Task ID: `artifact_deck_closure`; deployment:
  `core_artifact_attachment_deck`; closure state: `complete`.
- Outcome: `core/ui/src/components/MessageAttachmentDeck.vue` is the shared,
  panel-free deck for message-local files. Assistant output is limited to
  `image` and `file_change` and omits `file_read`; uploaded attachments appear
  below user messages. Output expands left-to-right and uploads right-to-left.
- Material behavior: compact overlapping cards expand on hover, focus, or
  click; click pins one preview. Deck width is measured with `ResizeObserver`
  to derive page size, with side arrows for paging. Text/code/config/document
  excerpts, image thumbnails, typed file icons, GSAP Flip motion, restrained
  back easing, selected scale/z-layer elevation, and reduced-motion fallback
  are implemented. `MessageView.vue` owns placement and output filtering;
  shared app/workbench projection sources carry uploaded attachment data.
- Verification: focused 3 files / 16 tests passed; full
  `npm run test:contract` passed 72 files / 512 tests; `npm run typecheck` and
  `npm run build` passed; LamTools design audit passed 72 files / 0 deviations.
  `git diff --check` on tracked touched files reported only LF-to-CRLF
  warnings, with no whitespace-error text.
- Limitation: Tauri/CUA manual observation was attempted twice, including once
  after CUA reset. Desktop Vite was correctly on `127.0.0.1:5173`, but both
  attempts failed with `nodeRepl.fetch request failed`; no manual UI pass is
  claimed.
- Read-only Git handoff: deployment files are the new
  `core/ui/src/components/MessageAttachmentDeck.vue`, its
  `core/ui/src/components/MessageView.vue` integration, shared app/workbench
  projection updates, and the focused attachment-deck/artifact-panel tests.
  The working tree was already heavily dirty and remains uncommitted; this
  closure preserved unrelated/concurrent changes and performed no commit,
  revert, or cleanup.
- Pending work/blockers: no deployment-specific blocker is known. Exact next
  entry point is to inspect the current uncommitted tree, then continue the
  project-level Office visual-quality work, real-device LAN/Relay
  pairing/reconnect validation, and Docker image build when Docker Hub access
  is available.

## Web search plugin repair handoff

- Task ID/deployment: `web_search_plugin_repair_closure` /
  `web_search_plugin_repair_20260912`; closure state: `complete`.
- Outcome/root causes: bundled/current `consider` loadtools omitted
  `web_search`; real default Baidu was blocked by wappass captcha; Bing's
  parser returned no result structure; and the schema used `duckduckgo` while
  runtime accepted `ddg`.
- Material changes: bundled `consider` includes `web_search`; the search
  factory falls back across configured providers in `ddg` then `bing` order,
  keeps strict explicit-provider behavior, records attempted-provider/error
  metadata, and makes `duckduckgo` a compatibility alias with `ddg` canonical
  in schema. Local runtime configs now expose `web_search` and default to DDG.
- Verification: 99 targeted tests passed (`test_web_tools.py`,
  `test_bundled_plugins.py`, `test_config_defaults.py`, `test_default_toolbox.py`,
  `test_core_default_agent.py`); current `consider` config reports
  `web_search_visible=True`; real default search for `LamTools GitHub` returned
  `status=ok` via `ddg` with 3 results; scoped `git diff --check` passed with
  newline warnings only.
- Git disposition: read-only inspection identified tracked deployment files
  in the loadtools/default-agent/websearch-schema/default-toolbox/search-factory/
  sub-agent-runner paths and their related config, toolbox, agent, HTTP-agent,
  and web-tool tests. `core/.lam/core/config/loadtools.jsonc` and
  `data/core-agent/plugins/websearch.jsonc` are local runtime config changes
  likely ignored by Git. The tree remains heavily dirty and uncommitted; no
  commit, revert, or cleanup was performed.
- Material gaps/risks: no deployment-specific blocker is known. Provider
  availability remains network-dependent; the next entry point is to inspect
  the current uncommitted tree, then continue the project-level Office
  visual-quality, real-device LAN/Relay, and Docker Hub milestones.

## Baidu official API decision handoff

- Task ID/deployment: `baidu_search_official_api_decision` /
  `baidu_search_plugin_repair_20260912`; closure state: `paused` pending user
  choice. This is separate from the completed
  `web_search_plugin_repair_20260912` deployment.
- Outcome: no production code changed in this deployment; the main agent added
  one durable diary lesson. Direct probes of `https://www.baidu.com/s`
  (standard HTML and `tn=json`), `https://m.baidu.com/s` (`word` and `wd`),
  HTTP/HTTPS, cookie warmup, and `trust_env` true/false all returned 302
  redirects to `wappass.baidu.com/static/captcha`; no proxy environment
  variables were active.
- Official source: Baidu docs at
  `https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5` specify
  `POST https://qianfan.baidubce.com/v2/ai_search/web_search`, API-key auth,
  references output, and 1,500 free monthly calls with daily allocation.
- Verification limitation: the official authenticated API was not integrated
  or exercised because the user decision and key are not yet available.
- Exact next entry point: ask whether to replace the anonymous Baidu provider
  with this official authenticated API; if approved, obtain and configure a
  key. The working tree remains heavily dirty and uncommitted; unrelated and
  concurrent changes were preserved.

## Web search proxy configuration handoff

- Task ID/deployment: `web_search_proxy_config_closure` /
  `web_search_proxy_config_20260912`; closure state: `complete`.
- Outcome: websearch schema, UI, and backend accept optional port-only
  `proxy_port`; the UI persists it through the existing websearch config RPC.
  DuckDuckGo derives `http://127.0.0.1:<port>` when configured and connects
  directly otherwise. Local runtime config is `7890`. Generic `plugin config
  get/set` already provides the matching CLI capability.
- Verification: 119 backend-related tests passed; focused UI coverage passed
  1/1; full UI coverage passed 74 files / 518 tests; UI typecheck and build
  passed; LamTools design audit passed 72 files / 0 deviations; a real DDG
  request through configured port 7890 returned `status=ok` with 3 results.
  Touched-source `git diff --check` had newline warnings only.
- Limitation: no Tauri visual/manual observation was performed, so no manual UI
  pass is claimed.
- Read-only Git handoff: touched deployment source/tests are
  `core/src/lamtools_core/plugins/bundled/websearch/config/schema.jsonc`,
  `core/src/lamtools_core/tool/search/duckduckgo.py`,
  `core/src/lamtools_core/tool/search/factory.py`,
  `core/ui/src/components/CoreWebSearchEditor.vue`,
  `core/tests/test_web_tools.py`, and
  `core/ui/tests/core-web-search-editor.test.ts`. The working tree remains
  dirty and uncommitted; unrelated and concurrent changes were preserved. Exact
  next entry point: use the existing UI or generic plugin config CLI to adjust
  `proxy_port` if the local proxy port changes.

## Artifact system redesign handoff

- Task ID/deployment: `artifact_system_redesign_closure` /
  `artifact_system_redesign_20260912`; closure state: `paused`.
- Outcome: diagnosis and a proposed redesign direction are recorded, but the
  deployment stopped before implementation because project rules require user
  consensus. No production code or tests changed. The main agent added one
  lasting diary lesson; this deployment changed only the assigned documentation
  in addition to that diary bullet.
- Verified diagnosis: the project registry uses per-artifact JSON UUID
  manifests at `.lam/artifact`; runtime projection derives `artifact-{sha1}`
  IDs for tool artifacts without IDs; only image-generation and upload paths
  register durable manifests, while ordinary `file_change` events do not.
  `data/core.db` contains 3,842 events with top-level artifacts and 3,842
  refs: 2,210 `command_output`, 1,072 `file_change`, 495 `file_read`, 47
  `web_fetch_content`, 17 `web_search_result`, and 1 `test_result`. The
  `.lam/artifact` directory contains only two manifests, both deleted
  user-upload images.
- UI evidence: `ArtifactPanel.vue` is mounted beneath runtime status in the
  292px right drawer, fetches only on mount/project change/manual refresh, and
  owns a separate preview. The uncommitted `MessageAttachmentDeck.vue` is
  message-local and filters output presentation; it does not solve durable
  artifact identity.
- Proposed direction, explicitly pending user approval: one durable Artifact
  fact model; distinct output/input/evidence roles; contextual message deck
  plus project-wide 成果库; StagePane as preview/open surface; live RPC/event
  updates; CLI parity; and migration/compatibility for existing manifests and
  events.
- Verification and limitation: Tauri dev was running on `127.0.0.1:5173`, but
  two CUA attempts, including a reset/retry, failed with
  `nodeRepl.fetch request failed`. No visual/manual pass is claimed. Only
  read-only evidence review and documentation consistency checks were done;
  no production test suite was run for this paused deployment.
- Git disposition: the working tree was already heavily dirty and remains
  uncommitted. This deployment preserved unrelated/concurrent changes and made
  no production or test-file edits.
- Blocker and exact next entry point: user approval or revision of the proposed
  direction is required. After approval, inspect the existing artifact
  schemas/RPC and event projection, define the durable contract and migration
  compatibility first, then implement live updates, CLI parity, and the
  message-deck/project-library/StagePane surfaces. Evidence references:
  `data/core.db`, `.lam/artifact`, `core/ui/src/components/ArtifactPanel.vue`,
  and `core/ui/src/components/MessageAttachmentDeck.vue`.

## Sunday branding and visual implementation handoff

- Task ID/deployment: `sunday_brand_plan_closure` /
  `sunday_ai_brand_20260912`; state: `complete`. The canonical product name
  is `Sunday`; `AI software` is only a subdued secondary label/tagline. No
  translated product name is displayed.
- Completed theme and metadata: shared `SUNDAY_DARK_THEME`/
  `SUNDAY_LIGHT_THEME` defaults plus the `sunday` preset; validated project
  `icon_key`/`color_key` metadata with backend persistence and shared picker /
  icon rendering.
- Completed owned brand assets: `core/ui/src/assets/sunday-mark.svg`,
  `sunday-app-icon.svg`, `core/ui/src/components/SundayLogo.vue`, and the
  desktop/UI/Tauri ICO assets. The app icon uses the requested gradient mark
  on a warm-white rounded-square background with a soft shadow.
- `TitleBar.vue` places the mark at the far left, then strong `Sunday` and the
  weak `AI software` label. Document, native main-window, and plugin-host
  titles are Sunday-facing. The desktop left sidebar is 232px; the mobile
  drawer keeps the separate `min(86vw, 320px)` rule.
- Project settings save name and icon/color metadata immediately on
  change/blur/enter or selection; the picker and settings use the same
  validated project-visual contract.
- Packaging uses the repository-owned Inno chain:
  `core/desktop/installer/Sunday.iss` and `build-installer.ps1`, orchestrated
  by the package script. Tauri uses `--no-bundle`; the stable upgrade/runtime
  boundary remains `lamcore.exe`, `lamcore-backend/LamCore.exe`, and
  `com.lamtools.lamcore`, with legacy installation migration retained.
- Startup first-paint bootstrap resolves the saved/system Sunday theme before
  stylesheet paint, preventing the dark-preference ~80ms light flash. Tauri
  verification covered dark preference at 80/480/740ms, explicit light with a
  dark system, and reduced-motion. The motion handoff is translucent veil →
  centered bare logo → theme background expanding from the logo center → shell
  components fading in; reduced-motion removes clip-path motion while keeping
  the accessible hand-off. Empty sessions render an animated Sunday
  logo/greeting.
- Final gates passed: UI 75 files / 540 tests, typecheck, UI build, desktop
  build, design audit 76 files / 0 deviations, and `git diff --check`.
  Final Inno package:
  `E:\LamTools\core\desktop\src-tauri\target\release\bundle\inno\Sunday_0.3.2_x64-setup.exe`
  (56,460,297 bytes; SHA-256
  `238EB54CDBD4A55C76735F767A28864F8316CA70F9248F8952B3CE87083E096A`).
  Installation to `E:\setuptest\0.3.2` verified the main process at PID
  `34412` and backend at PID `39536`, with both executable paths correct.
- Evidence: the files listed above, `core/ui/src/motion/startupSplash.ts`,
  `core/desktop/index.html`, `core/ui/tests/startup-splash.test.ts`,
  `core/ui/src/styles/variables.css`, `core/ui/tests/workspace-shell.test.ts`,
  `core/desktop/installer/Sunday.iss`, the final package, and the installed
  `E:\setuptest\0.3.2` process check.
- Pending work/blockers: no Sunday deployment blocker is known. The project
  next entry point is the existing Artifact redesign consensus, followed by
  Office visual-quality, real-device LAN/Relay pairing/reconnect, and Docker
  image validation when Docker Hub access is available.

## Modular right-sidebar closure

- Task ID/deployment: `sidebar_closure_handoff` /
  `modular_sidebar_20260913`; closure state: `complete`.
- Outcome: Core/Sunday now has a modular, pluggable right rail. A roughly
  320px single-column separator stack is hosted on one high-transparency,
  subtly blurred, theme-token-driven liquid-glass surface. The host owns
  ordering, visibility, collapse, and per-project persistence. Built-ins are
  Runtime, Resources, Web Search engine/health, RAG status/search, and
  Artifacts; Three.js/runtime visualization is deferred.
- Material backend changes: plugin widget manifests and validation, scoped
  `plugin.widget.list/get/invoke` operations, ownership/schema checks,
  dangerous-action confirmation, mutation idempotency, and CLI
  `plugin widget list/show/action` access. Web Search exposes snapshot and
  real-health operations. Relevant implementation areas are
  `core/src/lamtools_core/plugins/{models.py,registry.py,operations.py,cli.py}`,
  the bundled Web Search backend/manifest, and the app-server HTTP exposure.
- Material frontend changes: `core/ui/src/right-sidebar/types.ts`,
  `useRightSidebarLayout.ts`, the `RightSidebarHost`, module/editor/renderer,
  Runtime/Web Search/RAG components, trusted plugin loader registry and
  `PluginModeHost`, plus `LamToolsApp`/`WorkspaceShell` integration and
  Artifact embedding. Declarative widgets render bounded snapshots; trusted
  Vue components are registered in-process, and raw plugin markup is not
  evaluated. With no RAG plugin installed, the UI says unavailable and only
  attempts legacy search after a user action; no fabricated counts or event
  push are used.
- Verification: frontend focused coverage passed 25/25; full UI coverage
  passed 77 files / 553 tests; UI typecheck and `build:app` passed with only
  existing chunk/dynamic-import warnings. Backend plugin/lifecycle/workflow
  coverage passed 64, CLI/assembly 76, widget 7/7, Web Search 10/10, and the
  combined target passed 42 with 1 skip; HTTP exposure passed. Full pytest
  separately passed 1740 with 2 skips. The two unrelated live-resume failures
  reproduce alone: `test_core_app_server_client_runs_live_operation_matrix_against_real_websocket_server`
  and `test_core_live_resume_response_exposes_page_cursor` (expected 500, got
  0); neither uses the sidebar call path. `git diff --check` passed.
- Limitation: the user explicitly stopped visual/Tauri interaction; no
  visual/manual UI pass is claimed. The working tree remains heavily dirty
  and uncommitted; this closure preserved unrelated/concurrent changes and
  made no commit, revert, or cleanup. Archivist changed only the assigned
  durable documentation.
- Evidence: `core/ui/src/components/RightSidebarHost.vue`,
  `RightSidebarLayoutEditor.vue`, `RightSidebarModule.vue`,
  `RightSidebarWidgetRenderer.vue`, `RightSidebarRuntimeStatus.vue`,
  `RightSidebarWebSearch.vue`, `RightSidebarRag.vue`,
  `core/ui/src/right-sidebar/types.ts`,
  `core/ui/src/composables/useRightSidebarLayout.ts`,
  `core/tests/test_plugin_widgets.py`,
  `core/ui/tests/right-sidebar.test.ts`, and the related plugin/UI tests.
- Pending work/blockers: no deployment-specific blocker is known. Exact next
  entry point: inspect the current uncommitted tree, then continue the
  existing Artifact redesign consensus/contract work, Office visual quality,
  real-device LAN/Relay pairing/reconnect, and Docker Hub image validation.

## ComfyUI 工作流与 Agent 对齐规划

- Task ID/deployment: `workflow_alignment_planning_closure` /
  `comfyui_workflow_agent_alignment_20260913`; closure state: `paused`。
  本轮是 Heavy 规划/研究部署，未修改生产代码或测试；项目规则要求在实现
  前先取得用户对完整方案的共识。
- ComfyUI 研究结论：对齐范围应覆盖能力、架构和交互范式，不是像素级视觉
  克隆。ComfyUI 前后端为 GPL-3.0，LamTools 为 MIT，因此后续依据公开规范
  独立实现并沿用 Sunday/LamTools 设计语言，不复制其代码。
- 当前 Workflow 证据：`core/src/lamtools_core/plugins/bundled/workflow/`
  已有后端 store/runtime/operations/watcher/CLI/build-tools 与 Vue Flow UI。
  现有 UI 支持五类节点、条件边、自动保存、全图/单节点/从节点运行和 Agent
  自然语言改图；但步进每次从第一个节点重新执行，运行结果/节点输出/错误/尝试
  次数未形成稳定投影，后端 `completed/failed` 与前端 `done/error` 不一致，右
  栏 Teleport 目标缺失，并缺少运行输入表单、历史、缓存、Undo/Redo、多选、
  分组、reroute、模板、导入导出及 Schema 驱动节点注册。自动保存没有 revision/
  CAS，端口重命名也不会同步修复连线。
- 建议的稳定关系：Workflow 独立拥有文档、存储、校验、队列、运行时、缓存、
  历史和事件；Agent 只经显式适配器与 `ExecutionContext` 参与——辅助编辑图、
  作为 Agent 节点执行器，或将 Workflow 作为工具调用。两者不共享隐式会话状态
  或彼此注入内部运行对象，以同时保证独立性与配合性。
- UI 方向：将工作流 UI 拆为 `model/commands/document/canvas/catalog/inspector/
  runtime/resources/services/tests`，复用 `RightSidebarHost`、`ArtifactPanel`、
  `StagePane`、共享菜单、`AutoTextarea`、`CoreConfirmDialog`；移除 `WfSelect`，
  统一 `UiSelect`。运行态、历史/缓存、撤销重做、输入和导入导出应成为一等
  工作流体验，而非 Agent 会话的附属面板。
- 待用户决策的四项边界：
  1. 采用行为/交互对齐，还是要求像素级复制；
  2. 是否保留现有 Workflow 文件格式并提供迁移；
  3. 是否允许插件注册任意节点类型；
  4. 缓存是否限制为声明的纯函数/确定性节点（建议命令、脚本、Agent 默认不缓存）。
- Verification/limitations：本轮完成代码、架构、ComfyUI 公开规范和 UI 的只读
  审计；没有生产测试、构建或 Tauri 手工验收，也没有宣称通过。工作树仍重度
  dirty 且未提交，未执行 stage、commit、revert 或 cleanup；所有既有及并发用户
  改动均保留。
- Exact next entry point：用户确认四项边界后，先定义 Workflow/Agent 适配器、
  `ExecutionContext`、节点 Schema、运行事件/缓存契约和旧格式迁移，再按后端
  核心、CLI parity、画布/目录/检查器、运行历史与 UI 收尾分阶段实现。证据入口：
  `core/src/lamtools_core/plugins/bundled/workflow/`、
  `core/tests/test_workflow_*.py`、
  `core/src/lamtools_core/plugins/bundled/workflow/ui/`，以及本次 Heavy 审计记录。

## ComfyUI 工作流与 Agent 对齐实现闭环

- Task ID/deployment: `workflow_rebuild_closure` /
  `comfyui_workflow_rebuild_20260913`; state: `complete`。本节取代上方
  `comfyui_workflow_agent_alignment_20260913` 的 paused 规划状态。
- Outcome: 独立实现已覆盖节点注册表与 Schema 节点、DAG/部分执行、持久续跑、
  声明纯节点缓存、队列/历史/取消、CLI/RPC parity、旧格式兼容，以及
  revision/CAS、并发原子锁和保存冲突处理。Workflow 通过
  `WorkflowExecutionContext` 与 Model/Agent/插件适配器协作，权限、取消和
  事件链路保持显式边界。
- Agent-tool verification: 真实
  `KernelSubAgentRunner→CoreBaseAgentKit→workflow-tool` 链路保留附件、runtime
  snapshot、环境、能力、权限、lineage 和 workflow stack；外部 stack 含当前
  workflow 时立即拒绝，内部 child context 合法。
- UI outcome: 节点目录、输入表单、运行结果、队列/历史/缓存、导入导出、模板、
  右栏、Undo/Redo、多选、分组、reroute、注释、系统剪贴板、重连、对齐/分布、
  标签页和移动端布局已实现；统一 Sunday/LamTools 设计体系，删除重复
  `WfSelect` 并使用共享 `UiSelect`。
- Verification: backend workflow subset `py -3.14 -m pytest -q tests -k workflow`
  = 74 passed / 1689 deselected；UI typecheck PASS；`npm run test:contract` =
  80 files / 573 tests PASS；`npm run build:app` PASS（仅既有
  chunk/dynamic-import warnings）；`git diff --check` PASS（仅 CRLF warnings）。
  Full backend `py -3.14 -m pytest -q tests` = 1759 passed / 2 skipped / 2 failed。
  两项失败为部署前已存在且与 Workflow 无关的 live-resume 空 events：
  `test_core_live_client_e2e::test_core_app_server_client_runs_live_operation_matrix_against_real_websocket_server`
  和 `test_core_live_router::test_core_live_resume_response_exposes_page_cursor`。
- Limitation/disposition: 用户负责视觉验收；未启动 Tauri、浏览器或人工视觉检查，
  不宣称视觉通过。工作树重度 dirty 且未提交；未 commit、cleanup、revert、stage
  或归因，并保留所有既有/并发用户改动。Archivist 本次仅更新本文件和
  `agent_docs/project_progress.md`。
- Exact next entry point: 用户先做视觉验收；发现问题时仅修复 Workflow UI；若无
  问题，另起独立范围部署处理上述无关 live-resume 失败。证据入口为
  `core/src/lamtools_core/plugins/bundled/workflow/`、
  `core/tests/test_workflow_*.py`、Workflow UI 目录及本次验证命令输出。
## Workflow 数据模型研究闭环

- Task ID/deployment: `workflow_data_model_research_closure` /
  `workflow_data_model_alignment_20260913`; state: `paused`，等待用户确认
  Sunday-native V2 或 ComfyUI JSON canonical。该部署只有规划/研究和文档交接，
  未修改生产代码或测试；前一节 `workflow_rebuild_closure` 的实现闭环保持原样。
- 研究快照（官方 ComfyUI backend `0.35.0`、frontend `1.55.7`）：持久化工作流
  是 LiteGraph editor document，而非直接执行 payload。v0.4 为数组 links；v1
  同时包含 state counters、object links、groups、reroutes、config、extra、
  subgraph definitions，以及节点 geometry/flags/mode/order/slots/properties/
  widgets_values。执行 prompt 单独以 node-id keyed objects 表示，节点含
  `class_type` 与 `inputs`，引用为上游 node/output slot pair；muted/virtual
  editor nodes 被省略。后端从输出递归校验 required inputs、types、combos 和
  cycles。
- 运行时边界为 `/prompt`、`/queue`、`/history`、`/object_info` 与 WebSocket；
  queue tuple 实际字段可能不同于 OpenAPI，集成层应做版本探测而不是硬编码。
  官方研究入口：
  `https://github.com/Comfy-Org/ComfyUI_frontend/blob/main/src/platform/workflow/validation/schemas/workflowSchema.ts`、
  `https://github.com/Comfy-Org/ComfyUI_frontend/blob/main/src/utils/executionUtil.ts`、
  `https://github.com/Comfy-Org/ComfyUI/blob/master/server.py`、
  `https://github.com/Comfy-Org/ComfyUI/blob/master/execution.py`、
  `https://github.com/Comfy-Org/ComfyUI/blob/master/openapi.yaml`。两仓库均为
  GPL-3.0-only；Sunday 只采用概念/规范行为，不复制实现。
- 本地审计确认的 Sunday 弱点：`WorkflowDef` 混合执行和画布位置；config/types
  为自由形态；edges 与派生/持久 map 的含义重复；平铺完整 JSON 不利于 Agent
  语义理解。建议 canonical 采用 Sunday-native V2，编译到独立 execution prompt，
  再生成紧凑 model semantic view，并提供 ComfyUI import/export adapters；原始
  LiteGraph JSON 不作为内部 canonical。
- Verification/limitations：只读完成官方规范、本地代码/测试目录和 Git 状态核对；
  未运行生产测试、构建、浏览器或 Tauri 手工检查，不宣称实现或视觉通过。工作树
  重度 dirty、未提交；未执行 stage、commit、revert、cleanup 或归因，保留所有
  既有及并发用户改动。Evidence: `core/src/lamtools_core/plugins/bundled/workflow/`
  及 `core/tests/test_workflow_*.py`。
- Exact next entry point：向用户确认 canonical 选择；若采纳 Sunday-native V2，
  先定义 V2 文档、执行 prompt 编译器、semantic view、ComfyUI 迁移适配器和
  compatibility tests，再进入生产实现。

## Hide project header hash handoff

- Task ID/deployment：`hide_project_hash_setting_closure` /
  `hide_project_hash_setting`；closure state：`paused`，pending user
  clarification/consensus。
- Verified request context：截图中的 `#4124c504` 是当前 session/thread ID
  的前 8 位，不是 project ID。常规标题栏路径是 `LamToolsApp` 挂载的
  `CoreSessionTitleEditor`；Workflow 同样复用该组件。
- Verified settings boundary：`CoreProjectSettings` 已收到 `project.id`，
  但没有 `activeSessionId`。因此仍有两个待选解释：（1）把当前 session ID
  移到项目设置；（2）在项目设置显示 project ID。
- Outcome/limitation：这是只读规划交接；没有修改任何 production/test 文件，
  也没有运行测试或构建。证据仅核对
  `core/ui/src/components/CoreSessionTitleEditor.vue`、
  `core/ui/src/app/LamToolsApp.vue`、
  `core/ui/src/components/CoreProjectSettings.vue`、
  `core/ui/tests/core-session-title-editor.test.ts`、
  `core/ui/tests/core-project-components.test.ts`。
- Git disposition：工作树原已重度 dirty、未提交；本部署未执行 commit、
  stage、revert 或 cleanup，既有及并发改动均保留。
- Exact next entry point：用户确认两种解释之一后，从上述组件的标识传递边界
  开始实施选定方案，更新对应测试，再运行聚焦验证；在确认前不改代码。

## Right-sidebar motion closure

- Task ID/deployment: `sidebar_motion_closure` /
  `right_sidebar_motion_20260913`; closure state: `complete`.
- Outcome: the modular right-sidebar motion pass is complete and independently
  verified; runtime visualization is unchanged. `RightSidebarHost.vue` now
  scopes lifecycle-safe GSAP editor motion and uses `TransitionGroup` for
  module enter/leave/reorder. `RightSidebarModule.vue` retains body content
  with `v-show`, animates collapse through 200ms grid/opacity, applies
  `aria-hidden`/`inert` safety, shows drag lift/drop feedback, and cleans up
  animation/listener state. `workspace-shell.css` defines 240ms enter / 180ms
  exit, an instant reduced-motion fallback, the exact 2px main gap, rounded
  left corners only, and square right corners.
- Verification: focused right-sidebar coverage passed 25/25; full UI coverage
  passed 553/553; `npm run typecheck` and `npm run build:app` passed; design
  audit passed 83 files / 0 violations; `git diff --check` passed. Earlier
  full-backend evidence remains 1740 passed / 2 skipped, with unrelated
  failures in `test_core_app_server_client_runs_live_operation_matrix_against_real_websocket_server`
  and `test_core_live_resume_response_exposes_page_cursor`.
- Limitation: no Tauri runtime interaction or visual/manual UI pass was
  performed. The working tree remains heavily dirty and uncommitted; this
  closure preserved unrelated/concurrent changes and performed no commit,
  stage, revert, cleanup, or attribution. Archivist changed only the assigned
  durable documentation.
- Evidence: `core/ui/src/components/RightSidebarHost.vue`,
  `core/ui/src/components/RightSidebarModule.vue`,
  `core/ui/src/styles/workspace-shell.css`,
  `core/ui/tests/right-sidebar.test.ts`, and the existing sidebar host/layout
  contract files.
- Pending work/blockers: no deployment-specific blocker is known. Exact next
  entry point: when available, perform Tauri visual/manual validation of
  collapse, reorder, drag feedback, geometry, and reduced-motion states;
  otherwise inspect the current uncommitted tree and continue the existing
  Artifact consensus, Office visual-quality, real-device LAN/Relay, and Docker
  image milestones.

## ComfyUI 工作流最终核验补充

- Task ID: `workflow_rebuild_closure`；这是最终核验补充，取代同日 Workflow
  数据模型研究的 paused 规划状态。用户此前记录的 UI 收尾一并完成：全幅画布、
  中键平移、右键菜单、紧凑 workflow composer、保存 icon-only、exposure 移入
  设置，以及 ComfyUI 节点稳定端口。
- Contract/UI boundary: V2 UI 使用 canonical RPC，并保留兼容回退；模型边界
  对齐 ComfyUI v1 state/object links、0.4 reroutes、max id、strict one-hop
  引用。扩展字段隔离在 `canvas.comfyui`，不进入 Sunday-native canonical
  文档。
- Final verification: UI typecheck PASS；UI contract tests 583/583 PASS；
  `build:app` PASS；design audit 83/0；Workflow focused tests 92/92。后端
  full suite 为 1777 passed / 2 skipped / 2 failed，两个失败是已知且与
  Workflow 无关的 live-resume 空 events 问题。
- Runtime handoff: Tauri 观察环境已 ready，Vite `5173`、backend `58273`。
  这不是视觉通过声明；用户负责视觉验收。本次只更新本文件与
  `agent_docs/project_progress.md`，未修改代码，未 stage/commit/cleanup/
  revert 或归因；工作树仍重度 dirty。
- Exact next entry point: 用户在 Tauri 中完成 Workflow 视觉验收；发现问题时
  仅修复 Workflow UI，并保持 canonical RPC 与兼容回退边界。

## Workflow UI 工具栏收尾

- Task ID: `workflow_rebuild_closure`。最终 UI 收尾已验证：工具栏固定画布左侧
  纵向排列，按钮为 icon-only 并带 `title`，工具栏可纵向滚动；Vue Flow
  Controls 已移除，运行控制条上移以避开紧凑 workflow composer。
- 变更文件：`WorkflowCanvas.vue`、`WorkflowControlBar.vue`、
  `workflow-canvas-parity.test.ts`。
- Verification: 定向 Vitest 18/18、UI typecheck、`npm run build:app`、设计
  审计 0 偏离、`git diff --check` 均通过；Tauri Vite `5173` 与 backend
  `58273` 均 HTTP 200。
- Limitation: 视觉验收归用户负责；本次不宣称视觉通过。未修改业务代码之外
  的内容，未覆盖或回退他人改动。

## Session ID 项目设置与标题栏收尾

- Task ID/deployment：`move_session_id_to_project_settings_closure` /
  `move_session_id_to_project_settings`；closure state：`complete`。本节明确
  supersedes the earlier paused `hide_project_hash_setting` planning note。
- Outcome：普通 `LamToolsApp` header 已移除 session ID 前 8 位；
  `CoreProjectSettings` 仅在当前活动 session 属于所选项目时显示 `#` 加前 8
  位，并支持复制完整 ID 与复制成功反馈。Workflow 和
  `CoreSessionTitleEditor` 行为保持不变。
- Desktop layout：ordinary title row uses `data-session-header`、token-derived
  75px band，以及 token-derived `-44px` inset reclaim，位于原生标题栏下沿与
  divider 之间居中；mobile 与 Workflow 不受影响。
- Evidence：`core/ui/src/app/LamToolsApp.vue`、
  `core/ui/src/components/CoreProjectSettings.vue`、
  `core/ui/src/styles/layout.css`、
  `core/ui/tests/core-project-components.test.ts`、
  `core/ui/tests/package-boundary-contract.test.ts`。
- Verification：focused 2 files / 27 tests passed；full UI contract 80 files /
  588 passed；typecheck passed；`build:app` passed with existing
  chunk/dynamic-import warnings；Lam audit 83 files / 0 violations；scoped
  `git diff --check` passed。Independent tester inspected built CSS and accepted
  after one rejected cascade defect was repaired。
- Limitation/decision：用户明确停止 Tauri automation；没有 runtime/manual visual
  pass 声明。工作树仍 heavily dirty/uncommitted；未执行 commit、stage、revert、
  cleanup 或归因，保留既有及并发改动。
- Exact next entry point：若需要视觉确认，用户在 Tauri 中检查普通标题栏与项目
  设置的间距/复制反馈；否则从上述证据文件和当前未提交树继续，不重复此前 paused
  标识符方案讨论。

## Workflow 节点目录与 Agent 边界重构

- Task ID/deployment：`workflow_node_catalog_refactor_closure` /
  `workflow_node_catalog_refactor_20260913`；state：`complete`。
- Verified outcome：右键添加器与节点目录现在从 `object_info` 动态注册并按分类、
  搜索和 schema 添加；canonical 类型为 Model、Agent、Command、Python、Constant、
  Input、Output、Template、Condition、Merge、Join、Subgraph。旧 `AI`、`Script`、
  `Content`、`Transform`、`Branch` 隐藏但仍可执行；类型 ID 开放，端口 ID 稳定且
  不可变，V2/ComfyUI 往返兼容边界保留。Tool/MCP、HTTP 节点因安全宿主边界未定
  暂缓。
- Verified architecture：Workflow 独立拥有文档、校验、队列、运行时、缓存、历史
  和事件；Agent 仅经显式 `WorkflowExecutionContext`/适配器参与。SemanticGraph
  编辑视图保留 params、position 与 link modifiers；WorkflowView 的 Agent 说明
  已明确使用语义 JSON 并优先引用稳定 port ID。
- Evidence/checks：Workflow backend `103 passed`；Agent/default-toolbox regression
  `97 passed`；UI contracts `81 files / 596 tests passed`；`npm run typecheck`、
  `npm run build:app`、Lam design audit `83 files / 0 violations` 通过；Tauri
  Vite `5173` 与 backend `58273` `/api/health` 均 HTTP 200。
- Limitation/disposition：用户负责 Tauri 视觉验收与真实工作流运行实测，本记录不
  宣称视觉通过。工作树重度 dirty、未提交；仅完成只读 Git handoff，未 stage、
  commit、revert、cleanup 或归因；未发现本部署特有 blocker。
- Exact next entry point：用户在 Tauri 中视觉检查并实际运行工作流；问题出现时从
  Workflow UI/目录继续，保持 canonical RPC 与兼容回退边界。

## n8n 工作流系统对齐研究交接（2026-09-13）

- Task ID/deployment：`n8n_workflow_alignment_research_closure` /
  `n8n_workflow_alignment_20260913`；state：`paused`。目标是把 n8n 的成熟
  工作流运行契约转化为 LamTools 自有实现；本部署停在用户共识前，未修改生产
  代码或测试。
- 研究结论：n8n workflow JSON 将版本化 node type、parameters、credential
  references、connections 和 execution settings 作为持久契约；运行时围绕
  item/binary-data、表达式和 lineage；触发器/webhook、retry/error routing、
  wait/resume、subflow、credential isolation、execution persistence、
  pin/manual data 是生产级配套能力。n8n 使用 Sustainable Use License，故
  仅作概念/行为参考，任何代码或 UI 复用须先法律审查：
  <https://docs.n8n.io/n8n-community-license/sustainable-use-license.md>。
- LamTools 现状（代码核对）：`backend/registry.py` 的 `object_info`/Schema
  registry 已可动态描述节点；`document.py` 已有 V2 文档、canvas-free
  execution prompt 编译和分页 semantic graph；`runtime.py` 有 Model/Agent
  分离、`WorkflowExecutionContext`、subgraph、queue/cache/history/snapshot/
  resume；`core/src/lamtools_core/app/cli.py` 的 Arrange 已支持 once、
  daily/monthly calendar 和 event trigger。
- Gap map：工作流尚无一等 item/binary envelope 与 lineage packet；表达式仍是
  Condition/edge 的受信作者 Python `eval`，缺统一安全表达式引擎；无 workflow
  `CredentialRef`/vault 与凭据隔离；Arrange 尚未连接 activation/webhook；缺
  node version migration chain 和明确 upgrade policy。HTTP、Tool、MCP 节点的
  credential/permission host boundary 尚未成立。现有 queue/cache/history/
  snapshots/resume 不等同于 n8n 的 per-node error outputs、wait/resume、
  pin/debug 交互契约，后者仍需补齐。
- 推荐实施顺序（待确认）：
  1. 契约基础：版本迁移、`DataPacket` legacy adapter、安全表达式、
     `CredentialRef`；
  2. 触发器：复用 Arrange，并加入受认证 webhook；
  3. 每节点 error outputs、wait/resume、pin/debug 投影；
  4. 最后再引入 HTTP/Tool/MCP 节点。
  Workflow/Agent 继续以显式 `WorkflowExecutionContext`/adapter 协作，不共享
  隐式运行状态。
- 用户决定清单：确认 n8n 仅作概念参考及四阶段顺序；确认 `DataPacket` 的
  item/binary/lineage 语义与旧 Workflow 格式迁移；确定表达式语法/沙箱能力和
  credential vault/ref 隔离；确定 Arrange + webhook 的激活、认证、幂等、重放
  策略；确认 HTTP/Tool/MCP 是否继续暂停至宿主权限契约落地。
- Verification/limitations：完成官方 n8n 规范和本地 workflow/Arrange/Agent
  源码的只读核对；未运行测试、构建、Tauri 或真实 workflow runtime 验收，不
  宣称实现通过。工作树原已重度 dirty 且未提交；本部署未 stage、commit、
  revert、cleanup 或归因。Evidence：`core/src/lamtools_core/plugins/bundled/
  workflow/backend/registry.py`、`document.py`、`runtime.py`、`queue.py`、
  `cache.py`、`history.py`、`snapshots.py`、`operations.py` 及
  `core/src/lamtools_core/app/cli.py` 的 Arrange CLI。
- Exact next entry point：等待用户确认上述边界；确认后先写契约、迁移、兼容测试，
  再按四阶段推进实现。

## Workflow 画布容器交互与 parent_id 部署闭环

- Task ID/deployment：`workflow_canvas_parenting_closure` /
  `workflow_canvas_parenting_20260913`；closure state：`complete`。
- Outcome：Workflow 画布现为左键无修饰框选（Vue Flow
  `selectionKeyCode=true`）、中键平移；元素必须先选中才可拖动。框架/分组双击
  全选内部节点和画布元素。容器右键菜单包含“全选”“删除”“全部删除”：前者
  选择递归内部元素；“删除”仅删除容器并将子项解除父级；“全部删除”递归删除
  容器、后代内容及相关节点 edges，并在确认框中倒计时 3 秒后解禁确认删除键。
- Data contract：`WorkflowNode.parent_id` 从 legacy/V2 导入、store、UI
  document/resources 和 clipboard 复制/粘贴端到端保留；legacy `parentId` 作为
  读取兼容别名，canonical V2 归一为 `canvas.node_views[*].parent_id`。该字段是
  画布关系元数据，不进入执行 prompt 或 node execution config。ComfyUI
  `bounding`、`pos`、`size` 的几何字段仍可归一化，旧数据无 parent 时用几何包含
  回退。
- Evidence：Workflow UI 4 files / 39 tests；UI typecheck、`npm run build:app`、
  LamTools design audit（83 files / 0 deviations）与 `git diff --check` 通过。
  Python 验证包含主代理复核 37 tests、执行者更广 Workflow 102 tests 和独立
  tester 39 tests。视觉验收由用户负责；未宣称 Tauri/CUA 实机视觉或真实工作流
  运行已通过。
- Git handoff：工作树仍重度 dirty、未提交；未执行 stage、commit、revert、
  cleanup 或归因，既有及并发改动均保留。主线程因续接压缩上下文未在本部署首条
  commentary 写入 deployment marker，token report 需原样返回该限制。
- Pending/next entry point：用户在 Tauri 完成视觉验收，并运行含容器父子关系、
  框选/拖动、双击全选和两种删除路径的真实 Workflow；若出现缺陷，从
  `core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowCanvas.vue`、
  `WorkflowCanvasElement.vue`、`canvas.ts`、`document.ts` 与
  `resources.ts` 继续，保持 `parent_id` 只存在于画布视图且不进入执行语义。

## Durable Workflow Platform deployment closure

- Task ID/deployment：`durable_workflow_platform_closure` /
  `durable_workflow_platform_20260913`；state：`complete`。
- Outcome：Sunday Workflow 已升级为本地优先的 durable runtime。Canonical V2
  document 为每次 Run 固定不可变 revision；运行内核持久化
  Workflow/Version/Run/NodeRun/Attempt、append-only JSONL event journal 与
  派生 snapshot。Queue 记录 workflow ID、revision 和完整 definition snapshot；
  恢复会跳过已完成节点，具有副作用历史但缺 snapshot 时 fail-closed，相同终态
  run 重试不重复副作用。Retry/backoff/timeout、取消、幂等、缓存、activation、
  wait/signal 均属于 Engine contract，activation 复用 Core Arrange。
- Contract/security：WorkflowDataPacket 用 item envelope 传递 JSON 与
  Attachment/Artifact 引用；CredentialRef 只在单次 Node Attempt 临时解析，
  secret 不得进入 execution metadata、events、snapshots、日志或结果。Capability
  与 resource class 必须得到宿主显式授权，否则 fail-closed。内置节点保持 legacy
  raw-value 兼容，可信插件 executor 走 packet boundary；Condition、edge
  modifiers、Template 使用版本化安全表达式 AST 并保留 legacy 兼容。Agent 与
  Workflow 通过显式 WorkflowExecutionContext/adapter 协作，不共享隐式状态。
- Verification：`py -3.14 -m pytest -q tests -k workflow` 为 166 passed / 1691
  deselected；相邻 Agent/runner 回归主代理侧 99 passed、独立侧 117 passed，含
  4 个既有 deprecation warnings；UI typecheck passed；UI contract 为 81 files /
  607 tests passed；`npm run build:app` passed（仅既有 chunk/dynamic-import
  warnings）；workflow manifests parsed；LamTools design audit 为 Core UI
  83 files / 0 deviations（脚本不扫描 workflow plugin directory）；workflow
  plugin 手工 banned-token scan 无 findings；`git diff --check` exit 0，仅有
  line-ending warnings。
- Concurrency correction：独立验证曾发现不同 WorkflowRunner 并发 signal 会产生
  duplicate side effect；现已使用按 store path 区分的 process-level single-flight
  及有界 lock 生命周期修复，同一进程内覆盖，不能宣称跨进程一致性。
- Residual limits：无跨进程 locking；timeout settle 仍在 signal 时惰性完成；没有
  完整 HumanTask center；Fast/Express 延后；HTTP/MCP 及其他 external connectors
  等待完整 credential/permission host boundary。Effectively-once 仍要求外部
  executor 遵守 idempotency key。
- Visual/Git disposition：未启动 Tauri、浏览器或人工视觉验收，不宣称视觉通过；
  视觉验收和真实 Workflow 运行由用户负责。工作树仍 heavily dirty、uncommitted；
  未 stage、commit、revert、cleanup 或归因，既有和并发改动均保留。
- Evidence/next entry：实现证据在
  `core/src/lamtools_core/plugins/bundled/workflow/backend/{durable.py,runtime.py,queue.py,snapshots.py,data_packet.py,credentials.py,capabilities.py,expressions.py,activations.py}`
  及相邻 document/registry/adapters；UI 契约在 workflow tests。下一步由用户在
  Tauri 运行真实 Workflow，覆盖 durable wait/signal 与 Agent boundary；出现缺陷
  时从上述 backend 合同和 canonical V2/legacy 兼容边界继续。

## Manual `/compact` auto-alignment closure (2026-09-13)

- Task ID/deployment: `compact_auto_alignment_closure` /
  `compact_auto_alignment_20260913`; closure state: `complete`。
- Goal/outcome: make manual `/compact` an immediate entry to the automatic
  compaction path. It now uses the shared `ContextCompactionController`; its
  `force` flag only skips the automatic trigger threshold. It does not turn off
  thinking, change the compaction target, or use a separate request path.
  `resolve_compaction_budget`, snapshot model/reasoning/thinking settings,
  trigger/limit/safety margin, 4096 default summary output, retry count and
  retry strategy are shared. Effective history is loaded by `summary_seq` with
  the legacy summary-blob fallback. Raw history is retained and persistence of
  the summary/recovery boundary occurs only after a completed successful stream.
- Verification: backend compaction/runtime checks `317 passed`; UI command/action
  checks `22 passed`; UI typecheck and Python `compileall` passed; `git diff
  --check` passed. No real `/compact` invocation was run, so runtime behavior
  remains for the user's test.
- Runtime handoff: Tauri restart completed successfully; frontend Vite is on
  `5173`, backend on `61646`. The target session is idle with 100 history rows
  (`seq` 1..100), `summary_seq=0`, and a 6561-character existing summary.
- Git/working-tree disposition: heavily dirty and uncommitted; no stage,
  commit, revert, cleanup, or attribution was performed, and unrelated or
  concurrent user changes were preserved.
- Exact next entry point: run `/compact` in the restarted Tauri session and
  verify the manual request matches automatic compaction, including failure
  atomicity.

## Durable Workflow phase 2 closure

- Task ID/deployment: `durable_workflow_phase2_closure` /
  `durable_workflow_phase2_20260913`; state: `complete`。
- Outcome: the durable engine now uses cross-process SQLite claims with
  lease/heartbeat/fencing and protects claims against definition fingerprint
  mismatches. JSONL event appends are serialized across processes. HumanTask
  state has a durable projection, and Arrange-backed once timeouts resume without
  exposing a resume token. Runtime admission covers concurrency, rate, throttle
  and debounce; queue priority is persisted and the UI exposes a strategy panel.
- Verification: Workflow backend 195 passed; adjacent Agent/Runner 100 passed;
  claims + HumanTask focused checks 23 passed; UI typecheck passed; UI contracts
  82 files / 610 tests passed; `npm run build:app` passed; LamTools design audit
  Core UI 83/0; `git diff --check` exit 0 with line-ending warnings. Tauri Vite
  `5173`, backend `61646`, and `lamcore.exe` were alive; health returned 200.
- Limitations and Git disposition: user owns visual and real Workflow
  acceptance. The JSON queue does not itself provide a cross-process queue-item
  claim, and external side effects require executor idempotency. The worktree
  remains heavily dirty/uncommitted; no stage, commit, revert or cleanup was
  performed.
- Exact next entry point — Tauri user acceptance checklist: inspect canvas,
  strategy panel and HumanTask projection; run a normal Agent-bound Workflow;
  exercise concurrent claims, lease/heartbeat recovery and fingerprint mismatch;
  exercise concurrency/rate/throttle/debounce plus queue priority; complete a
  HumanTask via signal/approval and verify Arrange once-timeout resume; restart
  during execution and confirm the pinned revision resumes without duplicate
  external side effects. No visual or real-run pass is claimed here.

## Transparent startup window handoff

- Task/deployment: `transparent_startup_closure` /
  `transparent_startup_window_20260914`; closure state: `complete`.
- Outcome: the main Tauri window now has `transparent: true`, an alpha-zero
  background, and `shadow: false`. Pre-shell `html`/`body`/`#app` and the splash
  are transparent, and only the centered Sunday mark is painted.
- Material changes: the full-screen veil/reveal/backdrop-filter path was removed;
  the normal workspace shell takes over after Vue is ready. Click-through is not
  enabled. Normal and reduced-motion paths clear `aria-hidden` and clean their
  animation state.
- Evidence: `core/desktop/src-tauri/tauri.conf.json`,
  `core/desktop/index.html`, `core/ui/src/motion/startupSplash.ts`, and
  `core/ui/tests/startup-splash.test.ts`.
- Verification: focused startup tests passed 12/12; full UI contracts passed
  610/610; full UI typecheck and desktop Vite build passed; `npm run build:app`
  generated `lamcore.exe`; config JSON/bootstrap syntax checks passed; Lam
  design audit passed 83/0; scoped `git diff --check` passed with line-ending
  warnings only.
- Limitation: no Tauri GUI/OS visual check was run, per the code-only request;
  manual smoke remains user-owned. No deployment-specific blocker is known.
- Git handoff: the worktree remains heavily dirty and uncommitted; no stage,
  commit, revert, cleanup, or attribution was performed, and unrelated/concurrent
  changes were preserved. Exact next entry point: user performs manual Tauri
  startup smoke/visual acceptance; if it fails, inspect the four evidence files
  above and keep the transparent shell contract intact.

## Workflow UI tabs, responsive catalog, and localized affordances handoff (2026-09-14)

- Task ID/deployment: `workflow_ui_acceptance_closure_20260914`; closure state:
  `complete`.
- Implemented: Workflow View supports multiple open workflow tabs with active
  state, dirty markers, close actions, and an unsaved-switch guard. The
  schema-driven node catalog supports sidebar/popover responsive bounds,
  bounded scrolling, search across canonical and localized values, category
  filters, recent/favorite filters, keyboard activation, and mobile-sized
  controls. Chinese labels, descriptions, categories, and accessible copy are
  presentation-only; canonical English type IDs, schema keys, stored
  preferences, and execution behavior are preserved. Workflow node/catalog,
  inspector, queue, trigger, and canvas affordances use semantic Lucide icons.
- Verification: full `npm run typecheck` passed. The Workflow UI suite covered
  5 files / 49 tests passed: `workflow-canvas-parity.test.ts` (19),
  `workflow-node-contract.test.ts` (3), `workflow-policies-panel.test.ts` (2),
  `workflow-runtime-services.test.ts` (9), and `workflow-ui.test.ts` (16).
  Backend `core/tests/test_workflow_node_contract.py` passed 7 tests. LamTools
  design audit: 83 files / 0 deviations. Independent Tester final code review:
  pass. These are code/design checks only; no visual Tauri pass is claimed.
- Runtime evidence: read-only process/log-chain verification found Tauri dev
  frontend Vite on `127.0.0.1:5173` and backend on `127.0.0.1:49733`. The
  process chain is ready for user observation, but it does not verify layout or
  visual behavior.
- Git disposition: Workflow UI product changes remain uncommitted alongside
  the existing dirty tree. This closure writes only
  `agent_docs/project_progress.md` and this file; `agent_docs/project_diary.md`
  was not touched. Keep unrelated/concurrent startup and desktop changes
  un-attributed: `core/desktop/index.html`,
  `core/desktop/src-tauri/tauri.conf.json`,
  `core/ui/src/motion/startupSplash.ts`, and
  `core/ui/tests/startup-splash.test.ts`. Keep untracked temporary material
  (`artifacts/`, `core/core.db-wal`, `core/core.db-shm`) untouched. No stage,
  commit, revert, cleanup, or attribution was performed.
- Exact next entry point: user performs Tauri visual acceptance of Workflow
  tabs, catalog responsiveness, Chinese presentation, and semantic icons, then
  runs a representative Workflow. If a problem appears, continue from the
  Workflow UI source and the five test files above; preserve the canonical
  registry/RPC and presentation-only localization boundary.

## Optical liquid-glass closure

- Task ID/deployment: `optical_liquid_glass` /
  `optical_liquid_glass`; closure state: `complete`.
- Outcome: `core/ui/src/styles/optical-glass.css` centralizes the optical
  liquid-glass treatment. Its tokenized surface keeps background transmission
  clear while applying 8px blur, saturation 1.14, brightness 1.02, contrast
  1.03, and 2% tint. Localized radial, linear, and conic layers provide
  restrained reflection, dispersion, highlight, and environment/color
  response. `layout.css` imports the stylesheet, and `.optical-glass` is used
  by the WorkspaceShell right drawer and ContextMenuPanel. The outer surfaces
  have border 0; legacy four-edge masks and per-surface filters were removed,
  so there is no uniform white border or edge opacity fade.
- Evidence: `core/ui/src/styles/optical-glass.css`,
  `core/ui/src/styles/variables.css`, `core/ui/src/styles/layout.css`,
  `core/ui/src/components/WorkspaceShell.vue`,
  `core/ui/src/components/context-menu/ContextMenuPanel.vue`, and
  `core/ui/tests/context-menu.test.ts`.
- Verification: focused main coverage passed 36/36; independent coverage
  passed 56/56; full UI coverage passed 82 files / 614 tests; UI typecheck and
  `build:app` passed; LamTools design audit passed 84 files / 0 violations;
  independent Tester review passed; scoped `git diff --check` passed.
- Limitation: no Tauri runtime visual check was authorized or performed. The
  worktree remains heavily dirty and uncommitted; this closure preserved
  unrelated/concurrent changes and made no stage, commit, revert, cleanup, or
  attribution. Archivist changed only the assigned documentation.
- Pending work/blockers: no deployment-specific blocker is known. Exact next
  entry point: if visual validation is later authorized, inspect the Tauri
  right drawer and shared root/submenu context menus against the optical-glass
  contract; otherwise inspect the current uncommitted tree and continue the
  existing Workflow acceptance, Artifact consensus, Office visual-quality,
  real-device LAN/Relay, and Docker image milestones.

## Context-menu liquid-glass closure

- Task ID/deployment: `context_menu_liquid_glass` /
  `context_menu_liquid_glass`; closure state: `complete`.
- Outcome: every right-click caller now uses the shared
  `openContextMenu`/`ContextMenuHost` path, and root menus plus submenus share
  `core/ui/src/components/context-menu/ContextMenuPanel.vue`. The stable outer
  transparent blur uses `blur(var(--space-4)) saturate(1.08)`, a 4% current-area
  text tint, and a four-edge mask; animation is confined to inner content.
- Evidence: `core/ui/src/components/context-menu/ContextMenuPanel.vue`,
  `core/ui/src/components/context-menu/ContextMenuHost.vue`,
  `core/ui/src/components/context-menu/context-menu.ts`, and
  `core/ui/tests/context-menu.test.ts`. The seven caller surfaces route through
  the shared host/open function.
- Verification: focused context-menu coverage passed 58/58; full UI coverage
  passed 82 files / 614 tests; UI typecheck and `build:app` passed; LamTools
  design audit passed 83 files / 0 violations; independent Tester review
  passed; scoped `git diff --check` passed.
- Limitation: no Tauri runtime/visual check was performed, per the code-only
  scope. The working tree remains heavily dirty and uncommitted; this closure
  preserved unrelated/concurrent changes and made no stage, commit, revert,
  cleanup, or attribution. Archivist changed only the assigned documentation.
- Pending work/blockers: no deployment-specific blocker is known. Exact next
  entry point: when visual validation is requested, inspect root and submenu
  context menus in Tauri; otherwise inspect the current uncommitted tree and
  continue the existing Workflow acceptance, Artifact consensus, Office
  visual-quality, real-device LAN/Relay, and Docker image milestones.

## Workflow observability, HumanTask approval, and Schema UX closure

- Task ID/deployment: `workflow_observability_20260914`; closure state:
  `complete`.
- Outcome: Workflow runs now have a persistent, collapsible run panel with
  live node/edge state, timing, attempts, retry/cache/error information,
  safe input/output summaries, tool-audit summaries, logs, and final results.
  The canvas and run panel share the public run projection. HumanTask approval
  is an explicit, resumable action; completing approval returns the continued
  terminal run snapshot rather than only an acknowledgement. Schema UX now
  exposes usable node/default parameters and JSON/text editing instead of an
  inert one-word Schema label; existing ports are not redundantly synthesized.
- Security boundary: Queue and Run public projections redact credentials,
  tokens, resume secrets, and hidden reasoning. Durable execution storage
  retains the execution input required for recovery/audit. The Agent adapter
  currently reports tool names and aggregate counts only; it does not expose
  per-call tool status, so no finer-grained tool timeline is claimed.
- Real-run evidence: workflow `工作流测试1`, ID
  `77638d5256364cc99f6887fa00e17d08`, revision 148, had 9 current nodes and
  9 links. Run `workflow_run_4f43e4a76fe0` paused for HumanTask approval and
  completed after approval. The Agent returned 23 sources and the model output
  was 17,970 characters.
- Verification: Workflow backend coverage passed 214 tests / 1693 deselected;
  focused Workflow UI coverage passed 56 tests; UI typecheck and
  `npm run build:app` passed; LamTools design audit passed 84 files / 0
  deviations; `git diff --check` passed. Independent Tester final review
  passed (backend 45 / UI 45). These checks do not constitute visual Tauri
  acceptance.
- Runtime handoff: Tauri dev was fully restarted and is currently reported at
  frontend Vite `127.0.0.1:5173`, backend `127.0.0.1:61293`, session
  `20858`. This is a readiness/runtime state, not a visual layout claim.
- Git disposition: the repository remains heavily dirty and uncommitted. This
  closure changed only `agent_docs/project_progress.md` and
  `agent_docs/latest_session_work.md`; it did not stage, commit, revert,
  clean, or attribute unrelated/concurrent work, and did not touch
  `project_diary.md`.
- Exact next entry point: the user performs visual acceptance in the Tauri
  window: open the run panel, observe node/edge progress, expand input/output
  and audit details, approve a HumanTask, and inspect the final result. If a
  defect appears, continue from
  `core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowRunPanel.vue`,
  `SchemaNodeEditor.vue`, and the Workflow runtime projection/RPC files while
  preserving the public redaction boundary.

## Graph-native Workflow runtime sidecar closure

- Task ID/deployment: `workflow_canvas_runtime_sidecar_docs_20260914` /
  `workflow_canvas_runtime_sidecar_20260914`; closure state: `complete`.
- Outcome: the global `WorkflowRunPanel` was removed from the default/UI
  source. Workflow nodes remain opaque; running nodes use a rainbow ring and
  the active graph node is layered at z-index 34, below toolbar 35, composer
  40, and popovers 60. A translucent right-side dock now presents accumulated
  public delta, output, logs, tool summaries, image/PDF/file artifacts,
  errors, and HumanTask actions. Completed runs collapse the dock. Hidden
  reasoning is filtered defensively before presentation.
- Canvas contract: VueFlow presentation-only updates no longer emit workflow
  definition changes or autosaves; only actual coordinate changes do. This
  keeps live graph positioning independent from execution semantics and
  persistence.
- Verification: full UI coverage passed 83 files / 620 tests; UI typecheck and
  `npm run build:app` passed with only existing chunk/dynamic-import warnings;
  LamTools design audit passed 84 files / 0 deviations; `git diff --check`
  exited 0 with line-ending warnings. Independent Tester passed the focused
  4-file / 45-test surface plus typecheck and diff check.
- Limitations: no Tauri visual acceptance and no real Workflow run were
  performed. The known `工作流测试1` data is damaged at revision 155 with 8
  nodes and 0 links; it was deliberately not rerun or restored during this
  deployment. Do not treat the code checks as runtime or visual confirmation.
- Git disposition: the repository remains heavily dirty and uncommitted. This
  closure changes only `agent_docs/project_progress.md` and
  `agent_docs/latest_session_work.md`; it does not stage, commit, revert,
  clean, or attribute unrelated/user changes, and leaves `project_diary.md`
  untouched.
- Exact next entry point: the user performs Tauri visual acceptance of the
  graph-native sidecar, active-node ring/layering, dock expansion/collapse,
  artifact/error/HumanTask rendering, and live canvas interaction. A valid
  Workflow fixture must be repaired or recreated before real-run acceptance;
  do not restore the damaged fixture implicitly.

## Workflow dynamic-module loading repair (2026-09-14)

- Root cause: HMR left a stale `index.ts` URL in the failed dynamic-module
  cache, while the deprecated `WorkflowRunPanel` export and dead
  `WorkflowView` state remained in the module graph. Entering Workflow could
  therefore fail before the view mounted.
- Repair: removed the deprecated component/export and dead view state, then
  fully restarted Tauri to rebuild the Vite module graph and clear the stale
  failure state.
- Verification: the three Workflow Vite modules each returned HTTP 200;
  backend Workflow V2 document reading succeeded; focused coverage passed 34
  tests; UI typecheck, `npm run build:app`, and the LamTools design audit
  passed. No visual Tauri acceptance or real Workflow execution is claimed.
- Exact next entry point: user opens Workflow in the restarted Tauri window,
  confirms the view loads, then performs the existing graph-native sidecar
  visual checks. Keep the damaged `工作流测试1` fixture unrepaired unless a
  separate restoration decision is made.

## Artifact V2 deployment handoff

- Task ID/deployment: `artifact_v2_closure` /
  `artifact_system_v2_20260914`; closure state: `complete`.
- Outcome: SQLite Artifact V2 is implemented and reviewed with stable
  per-project-path identity and immutable SHA-256-deduplicated revisions. It
  preserves legacy `.lam/artifact` manifests and historical projection-ID
  aliases, ingests at event boundaries, treats uploads as inputs, records
  generated and `file_change` outputs, supports soft remove/restore and
  revision preview/restore, and exposes RPC/HTTP/CLI parity. Checkpoints carry
  Revision pointers; workspace rollback restores referenced revisions and
  soft-removes artifacts created after the target checkpoint. Main review also
  hardened project-scoped mutation/read boundaries.
- UI outcome: the project 成果库 provides role/kind/status/search filtering,
  history/restore, StagePane preview, and event-driven refresh. Conversation
  preview stacking is preserved; card and preview surfaces remain opaque.
- Verification evidence: final backend-focused coverage passed 34 tests / 1
  skipped. The broader related suite before the final narrow hardening passed
  60 / 2 skipped. Focused UI coverage passed 3 files / 24 tests; full UI
  coverage passed 83 files / 624 tests; UI typecheck passed; `npm run
  build:app` passed; website build passed; Python `compileall` passed; the
  LamTools design audit passed 84 files / 0 deviations; scoped
  `git diff --check` passed with line-ending warnings only. Existing Vite
  chunk/dynamic-import warnings and aiosqlite datetime deprecation warnings
  are non-blocking.
- Limitation: no Tauri visual/runtime acceptance was run because this was a
  code-only scope. No visual pass is claimed. The repository remains heavily
  dirty and uncommitted; no stage, commit, revert, cleanup, or attribution was
  performed, and unrelated/user changes remain untouched.
- Exact next entry point: user performs Tauri acceptance of the project
  成果库, StagePane preview, conversation card opacity/stacking, event-driven
  refresh, and revision restore/rollback, then exercises the matching
  RPC/HTTP/CLI paths. If a defect appears, continue from the Artifact V2
  backend/RPC/CLI contract and project-library/StagePane UI; preserve legacy
  manifest/projection aliases and project-scoped boundaries.

## Reasoning levels, sub-agent overrides, and Shallow visibility handoff (2026-09-15)

- Task ID/deployment: `reasoning_levels_archive` /
  `reasoning_levels_xhigh_medium`; closure state: `complete`.
- Outcome: the canonical reasoning levels are now `off`, `light`, `medium`,
  `high`, `xhigh`, and `max`, with `xh` accepted as an alias for `xhigh`.
  Providers use multi-to-fewer mapping when they expose fewer native levels;
  DeepSeek is verified as `off → disabled`, `light → low`,
  `medium/high/xhigh → high`, and `max → max`. Adapter preset definitions
  cover the expanded six-level contract.
- Delegation outcome: a sub-agent call can override its model and
  `reasoning_level`; when omitted, both inherit the parent agent settings.
  Optional-argument filtering preserves compatibility with older narrow
  `sub_agent` runners. CLI `medium`/`xhigh` choices and approval-resume
  `reasoning_level` continuation are included. The Shallow control is hidden
  from user menus, but its compatibility field, CLI, and legacy-session path
  remain intact.
- Verification: independent Tester — 108 Python tests; 3 UI files / 22 tests;
  typecheck; 26 adapter preset checks; DeepSeek payload; inheritance/override;
  old-runner compatibility; Shallow hidden; and diff check all passed. Main
  agent — 185 Python tests passed with 28 warnings, 22 UI tests, typecheck,
  8 supplementary focused tests, CLI choices, and approval-resume continuation
  checks passed. No Tauri visual acceptance was run or claimed.
- Git disposition: only this handoff and the matching progress entry are
  documentation scope; the repository remains heavily dirty and uncommitted,
  with unrelated/concurrent changes preserved. No stage, commit, revert,
  cleanup, or attribution was performed. The next entry point is the focused
  reasoning/profile/sub-agent/UI test surface when extending adapters or
  delegation controls; do not infer visual Tauri acceptance from these checks.

## Startup optical-glass handoff

- Task/deployment: `startup_optical_glass_20260915`; closure state: `complete`.
- Outcome: `core/desktop/index.html` now renders the startup glass with a
  low-gray tint, 8px blur, static localized dispersion/environment-color
  penetration, and a masked edge highlight. `core/desktop/src-tauri/src/main.rs`
  lowers the native Acrylic alpha from 32 to 18.
- Material scope: the transparent first paint is preserved; no full-screen
  opaque treatment was introduced. Evidence files are
  `core/desktop/index.html`, `core/desktop/src-tauri/src/main.rs`, and the
  existing startup splash contract in `core/ui/src/motion/startupSplash.ts`.
- Verification: startup-focused tests passed 12/12; UI typecheck and desktop
  build passed; `cargo check --no-default-features` passed with only existing
  dead_code warnings; LamTools design audit passed 84 files / 0 deviations.
- Limitation: no Tauri GUI/OS visual check was run under the code-only scope;
  manual smoke remains user-owned. No deployment-specific blocker is known.
- Git handoff: worktree remains heavily dirty and uncommitted; no stage,
  commit, revert, cleanup, or attribution was performed, and unrelated/concurrent
  changes were preserved. Exact next entry point: user performs startup visual
  smoke in Tauri; if a defect appears, continue from the three evidence files
  above while preserving transparent first paint and low-cost static effects.

## Asynchronous sub-agent lifecycle and messaging handoff

- Task/deployment: `subagent_async_lifecycle_ui`; closure state: `complete`.
- Outcome: sub-agents have explicit create/close lifecycle operations and a
  stable `(parent_thread_id, name)` reuse identity. The main-agent
  `sub_agent_message(type, name, prompt)` path validates both type and name;
  the sub-agent-only `message(message)` path reports to the parent. Dispatch
  runs in the background and returns without blocking the parent. A prompt
  sent while a sub-agent is busy is queued for injection before sampling at
  the next `step`.
- Contract/UI outcome: `consider` and `execute` have isolated tool sets and
  cannot recursively delegate. Late context places the sub-agent name, model,
  and summary after history as a final user message for provider cache-prefix
  stability. The UI renders `type name · model reasoning · elapsed`; the right
  rail lists every current and historical sub-agent for the session, supports
  click-to-locate/expand, and shows model/reasoning on hover.
- Verification: backend focused tests passed 160; default-agent plus HTTP
  tests passed 61 with 1 skipped; UI tests passed 28; UI typecheck, Python
  `compileall`, LamTools design audit (84 files / 0 violations), and scoped
  `git diff --check` passed. Independent model-notes verification had already
  passed 216 related tests. The extended live-router suite has one existing
  pagination-resume failure unrelated to this deployment; it remains a
  known limitation and is not attributed here.
- No Tauri visual/runtime acceptance was run under this code-only closure.
  The repository remains heavily dirty and uncommitted; no stage, commit,
  revert, cleanup, or unrelated attribution was performed.
- Exact next entry point: preserve the stable name/type validation, provider
  tail ordering, next-step busy-message injection, and right-rail session
  projection when extending the supervisor or delegation UI; begin with the
  focused supervisor/runner/toolbox/HTTP and sub-agent UI tests.

## Asynchronous sub-agent UI motion follow-up

- Task/deployment: `subagent_async_lifecycle_ui`; closure state remains
  `complete`. This follow-up fills the interaction motion on the existing
  sub-agent lifecycle surface.
- Changed UI behavior: `CoreSubAgentPanel` animates list add/remove/reorder,
  expands rows including those without a source timeline, and keeps status
  icon/label transitions aligned. `CoreSubAgentDialog` adds status, backdrop,
  and close micro-motion. `RightSidebarHost` transitions files/modules and
  uses a GSAP mount-preserving runtime/artifacts transition so module instances
  remain mounted. `LamToolsApp` completes sub-agent location with a temporary
  source-heading highlight.
- Reduced-motion behavior disables the animations and switches scrolling to
  `auto`.
- Evidence: `core/ui/src/components/CoreSubAgentPanel.vue`,
  `CoreSubAgentDialog.vue`, `RightSidebarHost.vue`, `core/ui/src/app/LamToolsApp.vue`,
  `core/ui/tests/core-sub-agent.test.ts`, and
  `core/ui/tests/right-sidebar.test.ts`.
- Verification: the two focused Vitest files passed 33 tests; `npm run
  typecheck` passed; LamTools design audit passed 84 files / 0 deviations;
  scoped `git diff --check` passed with CRLF warnings only. No Tauri visual or
  runtime acceptance was run.
- Git disposition: the repository remains heavily dirty and uncommitted;
  existing and concurrent changes were preserved, with no stage, commit,
  revert, cleanup, or attribution. Exact next entry point: user visually
  checks the sub-agent panel/dialog and right-rail transitions in Tauri,
  including preserved runtime/artifacts instances, source-heading highlight,
  and reduced-motion scrolling.

## Startup theme reveal follow-up

- Continuation of deployment `startup_optical_glass_20260915`: the transparent
  startup glass is unchanged. When application preparation completes, the saved
  theme background performs one circular reveal from the actual Sunday mark
  center, expanding to a `farthest-corner` radius over 0.5s before the staged
  main-shell fade-in.
- Reduced motion skips the reveal and uses a direct cross-fade. The change keeps
  the static low-cost optical treatment and existing accessibility cleanup.
- Verification: startup-focused tests 12/12; UI typecheck; desktop build;
  LamTools design audit 84/0; and scoped `git diff --check` all passed. No
  Tauri visual verification was run; manual acceptance remains user-owned.
- Git disposition: existing heavily dirty, uncommitted work remains untouched;
  no stage, commit, revert, cleanup, or attribution was performed. Exact next
  entry point: user performs startup visual smoke in Tauri, checking reveal
  origin, radius timing, staged shell fade-in, and reduced-motion cross-fade.

## Sunday ivory/graphite brand closure

- Task ID: `sunday_ivory_graphite_close`; deployment:
  `sunday_ivory_graphite_20260915`; state: `complete`.
- Material changes: Sunday light and dark themes are flat ivory/graphite. Main
  and composer surfaces share the fill color and solid border. The exact old
  default theme can be migrated without replacing a user-customized theme.
  The 1024-viewBox logo geometry is shared by `SundayLogo.vue`, the startup
  inline logo, `sunday-mark.svg`, `sunday-app-icon.svg`, and light/dark SVG
  variants. ICO, ICNS, and legacy ICO copies were regenerated for the app icon
  and title-bar branding.
- Evidence: `core/ui/src/helpers/theme.ts`,
  `core/ui/src/data/theme-presets.ts`, `core/ui/src/components/SundayLogo.vue`,
  `core/desktop/index.html`, the Sunday SVG assets, desktop icon outputs,
  `core/ui/tests/sunday-brand.test.ts`,
  `core/ui/tests/theme-helpers.test.ts`, and
  `core/ui/tests/startup-splash.test.ts`.
- Verification: focused 6-file coverage passed 48 tests; UI typecheck/build,
  desktop Vite build, Tauri Rust build, LamTools audit (84 files / 0
  deviations), and targeted `git diff --check` passed. ICO copies hash-match;
  ICNS validation passed.
- Limitations: the full UI suite was 634/637; the three failing
  `MessageView`/`chat-thread-process` tests are pre-existing and outside this
  deployment. No Tauri visual/runtime check was performed, so title-bar,
  startup, and theme appearance remain user-owned acceptance items.
- Git disposition: repository remains heavily dirty and uncommitted. This
  closure changed only `agent_docs/project_progress.md` and
  `agent_docs/latest_session_work.md`; no stage, commit, revert, cleanup, or
  unrelated attribution was performed, and `project_diary.md` was untouched.
- Exact next entry point: on visual-validation request, open the Tauri app and
  inspect the Sunday mark at the title bar and startup surface, then check
  ivory/graphite main/composer contrast in both themes; preserve the migration
  guard and synchronized SVG/ICO/ICNS asset set when iterating.

## Sunday reference-image trace correction

- Task ID: `sunday_reference_icon_trace_archive`; deployment
  `sunday_reference_icon_trace_20260915`; state: `complete`.
- This correction replaces the approximate prior redraw with the two supplied
  reference images as the source of truth. The retained files are lossless
  1254×1254 RGBA PNGs:
  `core/ui/src/assets/sunday-app-icon-dark.png` has SHA-256
  `43baa9ec01d1f571852e3dc86463b27e39a077ff43c49523d6bfb27f12768291`, and
  `core/ui/src/assets/sunday-app-icon-light.png` has SHA-256
  `dba8a5508c294093fb3723bfe9417a04564bf797a2bf61121247464db0bd0087`.
- The application icon, title-bar icon, and startup splash now select the
  complete framed reference artwork using the resolved effective theme. The
  standalone Sunday mark is an independently measured tight 1024-viewBox
  vector, while the app-icon SVG wrappers preserve the full reference frame.
  The ivory/graphite theme tokens remain flat and sampled from the reference;
  no gradients are introduced. ICO, ICNS, and both legacy ICO copies were
  regenerated. Startup fallback colors now match the backdrop, and the Tauri
  dev stack was fully restarted after asset and startup changes.
- Evidence: `core/ui/src/assets/sunday-app-icon-{dark,light}.png`, the
  matching SVG wrappers and mark variants, `core/ui/src/components/SundayLogo.vue`,
  `core/ui/src/components/TitleBar.vue`, `core/desktop/index.html`, desktop
  icon outputs, theme token files, and `core/ui/tests/sunday-brand.test.ts`.
- Verification: focused Sunday coverage passed 47 tests; UI typecheck/build,
  desktop build, `cargo check`, the LamTools audit (84 files / 0 deviations),
  and native icon/hash checks passed. Full UI coverage was 637/640; the three
  failures are unrelated `chat-thread-process` label assertions. No Computer
  Use or visual GUI verification was performed, so visual acceptance remains
  a residual user-owned risk.
- Runtime handoff: Tauri dev is running in session `66861`, frontend port
  `5173`, backend port `64257`. The working tree is heavily dirty and
  uncommitted; existing, unrelated, and concurrent changes were preserved.
  No stage, commit, revert, cleanup, or broad attribution was performed by
  this closure. `project_diary.md` was left untouched per ownership.
- Exact next entry point: the user performs Tauri visual smoke in both
  effective themes, checking that startup and title-bar show the complete
  framed icon, the standalone mark matches the measured geometry, startup
  fallback matches the backdrop, and flat ivory/graphite surfaces retain
  contrast. If iteration is needed, begin with the corrected PNG/SVG asset
  set and the focused Sunday brand contract.

## Sunday workbench frame and icon coverage handoff

- Task ID/deployment: `archivist_sunday_workbench_frame_color_20260915` /
  `sunday_workbench_frame_color_20260915`; closure state: `complete`.
- The user clarified that “背景” refers to the `backdrop` workbench,
  background-board, and sidebar area. Chat main and composer are separate
  surfaces. The final flat light contract is workbench `#D2D8E6`, chat
  main/composer `#FDFBF7`, and controls `#2E3138` with `#FBF7F0` text. The
  dark contract is workbench `#818289`, chat main/composer `#1B1D22`, and
  controls `#FBF7F0` with `#2E3138` text. Gradients are excluded.
- Migration logic recognizes the older colorful, prior gray-control, and
  immediately previous inverted-control Sunday defaults, while preserving
  custom themes. The canonical implementation is in the Sunday theme token,
  migration, and workspace/layout surface styles.
- The raw 1254×1254 source PNGs remain byte-identical. Centered 1120px crops
  resized with LANCZOS produce 1254px display masters at approximately 90%
  meaningful alpha coverage; SundayLogo, startup splash, SVG icon wrappers,
  ICO, and ICNS use the normalized display masters. All three ICO copies are
  byte-identical with 16/24/32/48/64/256 sizes, and the ICNS is valid.
- Verification evidence: independent scoped checks passed 54/54 focused UI
  tests, UI typecheck, desktop Vite build, `cargo check` (four existing
  dead-code warnings), and scoped `git diff --check`. The full UI suite was
  645/648; three unrelated chat-thread-process assertions still expect
  obsolete `001 · name` labels instead of current `execute name` labels.
- Runtime handoff: fresh Tauri dev is active in exec session `28924`, frontend
  Vite `5173`, backend `63144`; backend ready in 2108 ms and desktop plugin
  host ready. No Computer Use or GUI visual check was run, so visual
  acceptance remains a residual user-owned item.
- Git disposition: the worktree remains heavily dirty and uncommitted. No
  stage, commit, revert, cleanup, or broad attribution was performed; all
  unrelated and concurrent edits were preserved. Exact next entry point: the
  user checks both effective themes in Tauri, especially the corrected
  workbench frame color, enlarged startup/title-bar icon, chat surfaces,
  controls, and boundaries. On defect, continue from the Sunday theme
  migration helpers, workspace/layout styles, and normalized display-master
  asset set.

## Compaction keep-recent-step setting pause

- Task ID/deployment: `compaction_keep_steps_settings_closure` /
  `compression_keep_steps_settings_20260915`; state: `paused`.
- User request: make the number of recent steps retained by compaction
  adjustable in settings. Read-only diagnosis found that current structural
  compaction is driven by token budgets and the planner retains complete
  semantic message groups split at user turns (plus compaction summary
  boundaries); there is no count-based retention setting.
- Semantic boundaries to preserve: `LoopPolicy.max_history_messages` trims a
  bounded number of history messages before context construction and is not
  the compaction retention policy. The Goal evaluator copies only
  `metadata.kernel_steps[-12:]` into its `recent_steps` projection and is not
  the compaction planner. `kernel_steps` also counts kernel loop iterations,
  which may differ from semantic user-turn groups.
- Blocker: implementation needs the user to define what “Step” means for this
  setting. No production files, tests, or runtime configuration were changed
  in this paused planning turn, and no tests/builds were run.
- Evidence pointers: `core/src/lamtools_core/context_compaction/planner.py`
  (semantic grouping and token-target layout),
  `core/src/lamtools_core/kernel/policy.py` and `kernel/loop.py`
  (`max_history_messages` trim), and
  `core/src/lamtools_core/runtime/goal.py` (`kernel_steps[-12:]` projection).
- Git disposition: the worktree remains heavily dirty and uncommitted;
  unrelated and concurrent changes were preserved. No stage, commit, revert,
  cleanup, or attribution was performed. `agent_docs/project_diary.md` was
  left unchanged.
- Exact next entry point: once “Step” is defined, update the corresponding
  settings/schema and compaction planner contract, add focused coverage for
  the chosen unit, and verify that message-count trimming and Goal’s fixed
  twelve-step projection remain independent.

## Compaction retained-step setting implementation

- Task ID/deployment: `compaction_step_tail_backend` /
  `compaction_step_tail_20260915`; state: `complete`.
- Outcome in the current worktree: structural compaction now reads
  `core.contextCompaction.retained_steps` (default `6`, accepted range `1–100`)
  with safe fallback. The settings UI (`CoreSettings`) and CLI
  (`context-compaction show/config --retained-steps`) expose the value.
  `CompactionPlanner` defines a model Step as one assistant response and its
  immediately following contiguous tool results; it protects the latest N
  Steps together with the latest 20 user messages. The exact token fitter can
  remove the oldest selected units when the target budget requires it while
  retaining the newest user boundary. Automatic and manual `/compact` share
  this policy, with per-call and `LoopPolicy.compact_retained_steps` overrides.
- The planner’s oversized-union path was corrected to enter compaction and
  use the exact token budget instead of returning an early no-op. The prior
  kernel compatibility failures were then repaired by the main agent.
- Verification evidence: main-agent backend expansion across context,
  step-tail, live/kernel, CLI, default-agent, and budget suites passed 341
  tests with 28 existing aiosqlite deprecation warnings; `compileall` passed.
  UI focused coverage passed 54 tests; UI typecheck and the LamTools design
  audit passed (84 files / 0 deviations); scoped `git diff --check` passed
  with LF/CRLF warnings only. `ruff` was unavailable (`No module named ruff`).
  The independent Tester’s corrected regression command passed 247 tests in
  35.85 seconds. Its audit confirmed union retention, budget reservation and
  shrinkage, atomic assistant+tool dropping, the newest-user minimum boundary,
  and shared automatic/manual behavior. The earlier nine kernel failures were
  fixed; the planner/fitter stage docstring mismatch was also corrected.
- Evidence pointers: `core/src/lamtools_core/context_compaction_budget.py`,
  `context_compaction/planner.py`, `context_compaction/controller.py`,
  `kernel/policy.py`, `kernel/loop.py`, `config/operations.py`, `cli.py`,
  `app/default_agent.py`, `app/command_execution.py`,
  `core/ui/src/components/CoreSettings.vue`, and the focused
  `core/tests/test_context_compaction_step_tail.py` contract.
- Git disposition: the worktree remains heavily dirty and uncommitted;
  unrelated and concurrent changes were preserved. No stage, commit, revert,
  cleanup, or attribution was performed. `project_diary.md` was not edited by
  this closure and remains under main-agent ownership.
- Exact next entry point: begin any follow-up with the focused compaction,
  step-tail, and kernel tests. Preserve the setting namespace, Step grouping,
  20-user union, newest-user boundary, and exact-budget behavior. This closure
  did not include Tauri visual acceptance.

## Input composer token alignment handoff (2026-09-15)

- Task ID/deployment: `input_token_alignment_archive` /
  `input_token_alignment_20260915`; state: `complete`.
- Outcome: every active Core UI text-like input box and textarea sources
  background, border, text, caret, and placeholder colors from composer tokens.
  Transparent title inputs are the explicit exception and remain area-local.
  Select, button, badge, and native non-text input surfaces remain on
  control-area tokens. The LamTools design guidance at
  `.agents/skills/lam-design-spec/SKILL.md` was synchronized.
- Contract evidence: `core/ui/tests/input-composer-tokens.test.ts` scans the
  app, components, workflow, and styles surfaces. Executor affected tests were
  60/60; focused contract coverage was 4/4; UI typecheck passed; the LamTools
  design audit covered 84 files with 0 violations; and the scoped diff check
  passed. Independent Tester PASS after scanner hardening confirmed focused
  4/4 and found no applicable residue in the static scan.
- Validation limits: the full UI suite had 651 passes and 3 unrelated failures
  in `tests/chat-thread-process.test.ts` for obsolete sub-agent labels. No
  Computer Use/Tauri visual verification was run. Existing
  `CoreGoalStrip.vue` cancel-button composer coloring is outside this scope.
- Git disposition: read-only handoff; the repository remains heavily dirty and
  uncommitted, with unrelated and concurrent edits preserved. No stage, commit,
  revert, cleanup, or attribution was performed. Exact next entry point: use
  the composer-token contract and `input-composer-tokens.test.ts` scanner when
  adding or auditing text-entry surfaces; retain the title-input exception and
  control-area mapping.

## Composer action-button color handoff (2026-09-15)

- Task ID/deployment: `composer_action_button_archive` /
  `composer_action_button_colors_20260915`; state: `complete`.
- `CoreSendStopButton` send and stop outer surfaces use
  `--theme-composer-text`; paper-plane, stop glyph, and motion trail use
  `--theme-composer-background`. GSAP runtime color resolution no longer uses
  control tokens or red, while existing motion, accessibility, and hit-area
  behavior remains unchanged. The lam-design-spec canonical guidance includes
  this explicit composer action-button exception.
- Evidence: executor focused 3 files / 8 tests, UI typecheck, LamTools design
  audit 84 files / 0 violations, and scoped diff check passed. Independent
  Tester PASS covered 3 files / 22 tests, typecheck, design audit 84/0, scoped
  diff check, and a temporary non-reduced GSAP send→stop→send runtime test
  that passed; the temporary test was removed.
- Limitation: jsdom cannot compute pseudo-element `currentColor`; source
  inheritance was verified. No Tauri or pixel visual run was performed.
- Git disposition: read-only handoff; the repository remains heavily dirty and
  uncommitted, with unrelated and concurrent edits preserved. No stage, commit,
  revert, cleanup, or attribution was performed. Exact next entry point: begin
  with `CoreSendStopButton`, the composer action-button exception, and focused
  contract coverage when extending send/stop coloring.

## Title input transparency handoff (2026-09-15)

- Task ID/deployment: `title_input_transparency_archive` /
  `title_input_transparency_20260915`; state: `complete`.
- Root cause was selector specificity from accumulated `:not(...)` clauses on
  the shared text-input recipe. Wrapping that recipe in zero-specificity
  `:where(...)` lets seven inline/pure-text title exceptions reliably set
  border 0, transparent background, and local text/caret while preserving
  composer colors, native exclusions, and the select-control recipe. Form
  values named `title` or `name` remain composer input boxes.
- Evidence: executor 5 files / 62 focused tests, UI typecheck, LamTools design
  audit 84 files / 0 violations, and scoped diff checks passed. Independent
  Tester PASS covered 8 files / 109 tests, typecheck, scoped diff check, and
  selector-specificity/source review.
- Limitation: static CSS contract only; no rendered Tauri CSSOM or visual run.
  A discarded invalid explicit Vitest-config attempt had no product impact.
- Git disposition: read-only handoff; the repository remains heavily dirty and
  uncommitted, with unrelated and concurrent edits preserved. No stage, commit,
  revert, cleanup, or attribution was performed. Exact next entry point: use
  the zero-specificity recipe and seven title exceptions when auditing title
  controls, retaining composer tokens for ordinary `title`/`name` fields.

## Context compaction full-summary and recent-user handoff (2026-09-15)

- Task ID/deployment: `compaction_full_summary_recent_users_20260915`; state:
  `complete`.
- Material behavior: `core.contextCompaction.retained_steps` defaults to `0`
  with a valid range of `0–100`. The zero setting summarizes all non-prefix
  history, then programmatically appends a generated `## Recent user messages`
  section containing the newest 20 user instructions verbatim as `1.`, `2.`,
  and subsequent numbered entries. Positive values retain recent Step units
  (assistant response plus contiguous tool results) alongside that user suffix.
- Budget and repeat rules: the exact fitter drops the oldest retained Steps,
  then the oldest numbered user entries, and preserves the newest user
  instruction unless it cannot fit by itself. Repeated compaction removes the
  previous generated section before summarizing and appending again. For
  multimodal instructions, text/content blocks remain and media-only blocks
  are omitted. Automatic and manual `/compact` use the same policy; CLI,
  settings RPC, and CoreSettings UI accept `0`.
- Exact implementation and contract files:
  `core/src/lamtools_core/app/command_execution.py`,
  `core/src/lamtools_core/app/default_agent.py`, `core/src/lamtools_core/cli.py`,
  `core/src/lamtools_core/config/operations.py`,
  `core/src/lamtools_core/context_compaction/__init__.py`,
  `core/src/lamtools_core/context_compaction/controller.py`,
  `core/src/lamtools_core/context_compaction/fitter.py`,
  `core/src/lamtools_core/context_compaction/formatting.py`,
  `core/src/lamtools_core/context_compaction/models.py`,
  `core/src/lamtools_core/context_compaction/planner.py`,
  `core/src/lamtools_core/context_compaction_budget.py`,
  `core/src/lamtools_core/kernel/loop.py`,
  `core/src/lamtools_core/kernel/policy.py`,
  `core/tests/test_context_compaction.py`,
  `core/tests/test_context_compaction_step_tail.py`, and
  `core/ui/src/components/CoreSettings.vue`.
- Verification: main backend regression `348 passed`; independent Tester
  `209 passed`; CoreSettings Vitest `15 passed`; UI typecheck, `compileall`,
  LamTools design audit (84 files / 0 deviations), and scoped
  `git diff --check` passed. No Tauri visual/runtime check was run, matching
  this code-focused acceptance scope.
- Git disposition: implementation and documentation remain uncommitted in a
  heavily dirty worktree; concurrent and unrelated changes were preserved. No
  stage, commit, revert, cleanup, or attribution was performed. No blockers
  remain for this deployment. Exact next entry point: start with the focused
  compaction/step-tail tests before changing the zero default, recent-user
  suffix, newest-user minimum, or exact-budget drop ordering.

## Sub-agent lifecycle event copy and mailbox projection handoff (2026-09-15)

- Follow-up to deployment `subagent_async_lifecycle_ui`; this handoff records
  the event-copy and projection closure. `MessageView` renders five explicit
  lifecycle/mailbox states with Lucide icons: `UserRoundPlus` — `创建了
  {name} · {model} {reasoning}`; `Power` — `启用了 {name} · {model}
  {reasoning}`; `PowerOff` — `关闭了 {name}`; `Send` — `向 {name} 发送了消息`;
  and `Inbox` — `收到了 {name} 的消息`.
- Backend `sub_agent` operation results carry the transient actions
  `created`, `enabled`, `closed`, and `message_sent`. Child-to-parent guidance
  is projected as a completed `sub_agent_receive` tool row with `name`/`type`
  arguments and `message_received` metadata. Asynchronous lifecycle calls stay
  ordinary dynamic tool rows rather than `agent_summary` rows.
- The projection metadata is presentation-only: provider/model history keeps
  the original message text and does not receive lifecycle UI metadata. This
  preserves the late-context/cache-prefix contract and keeps the mailbox body
  visible without leaking event bookkeeping into prompts.
- Evidence and verification: the UI closure suite passed 116 tests, the
  backend closure suite passed 249 tests, and `npm run typecheck` passed. No
  Tauri visual/runtime check was run or claimed.
- Git disposition: only this documentation handoff is owned here. The working
  tree remains heavily dirty and uncommitted; unrelated and concurrent edits
  were preserved, with no stage, commit, revert, cleanup, or `project_diary.md`
  change. Exact next entry point: use `MessageView`,
  `event/runtime_projection.py`, `sub_agent_supervisor.py`, and the lifecycle
  tests when extending copy or mailbox behavior; retain the five mappings,
  action metadata, ordinary asynchronous tool rows, and body-only model
  history.

## Context compaction full-summary bugfix continuation (2026-09-16)

- Task ID/deployment: `compaction_full_summary_recent_users_20260915`; state:
  `complete`.
- Same-run later Steps now retain the generated summary in memory while
  filtering it from durable rows. Manual zero-tail compaction uses valid
  high-water/compacted sequence values and no longer falls back to full
  history. Repeated compaction combines the previous structured
  `recent_user_messages` section with new raw users and rolls it forward to
  the newest 20. Internal request-local user messages are excluded; typed
  media fields are excluded and media-only users receive a placeholder.
- The visible numbered original-user suffix remains unchanged. Ambiguous
  heading/number/newline, CRLF, and special `splitlines()` inputs carry an
  invisible length footer so decoding round-trips exactly. Automatic and
  manual policy overrides have matching behavior.
- Evidence: compaction planner/controller/formatter and budget contracts in
  `core/src/lamtools_core/context_compaction/` and
  `core/src/lamtools_core/context_compaction_budget.py`, with focused coverage
  in `core/tests/test_context_compaction.py` and
  `core/tests/test_context_compaction_step_tail.py`.
- Verification: main focused tests `289 passed`; independent focused tests
  `215 passed` plus the compaction trio `95 passed`; 61 targeted tests and
  20,000 randomized round-trip cases passed; `compileall` and scoped
  `git diff --check` passed. Full Core: `1965 passed, 2 skipped`, with six
  unrelated failures in tool-count, artifact-DB, and live-resume tests. No
  Tauri run was performed.
- Git disposition: only these two documentation files are owned by this
  handoff. The worktree remains heavily dirty and uncommitted; concurrent and
  unrelated changes were preserved, with no stage, commit, revert, cleanup,
  attribution, or diary edit. Exact next entry point: begin with the focused
  compaction and round-trip contracts before changing sequence handling,
  newest-20 roll-forward, exclusion rules, or invisible footer encoding.

## Sub-agent runtime integration repair closure (2026-09-16)

- Task ID/deployment: `fix_subagent_runtime_integration`; closure state:
  `complete`.
- Outcome: create/close validate the complete
  `action/type/name/model/reasoning_level` contract; `sub_agent_message`
  validates `type/name/prompt`; the child-only `message(message)` channel is
  auto-allowed. `consider` and `execute` receive isolated tool sets without
  recursive delegation. Child runs execute asynchronously and use `name` as
  the stable reuse key.
- Runtime behavior: parent/child run, Step, call, and source anchors refresh
  on lifecycle operations; persistent mailbox and live guidance deliver child
  messages at the next Step. Cross-run and cross-invocation deduplication is
  enforced, and child item IDs include sub-session, run, and invocation
  identity. Approval resume restores child identity, toolbox, and request-local
  context. Child events remain attached to the active `sub_agent_message`
  item and do not terminate or leak into the parent main line. States expose
  running, idle, paused, closed, interrupted, and error.
- Prompt/config behavior: `xh`/`XH` and `Medium` normalize through schema,
  CLI, and runtime; DeepSeek level reduction is mapped and tested. Model notes
  enter model request prompts. Name, model, and summary are appended after
  history as request-local context to preserve cache prefixes.
- UI behavior: the right rail combines live and historical sub-agents with
  click-to-locate/expand/highlight, hover model/reasoning details, status
  ordering, and reduced-motion-safe transitions. Rows show
  `类型 名 · 模型 思考强度 · 耗时`; lifecycle rows use the create/enable/close/
  send/receive copy and icons. Shallow is hidden from entry points while
  active indicators remain available.
- Verification: main-agent backend expansion `205 passed`; UI `86 files /
  665 passed`; typecheck, `build:app`, Python `compileall`, LamTools design
  audit `84 files / 0 deviations`, and scoped diff check passed. The build
  reported only existing chunk/dynamic-import warnings and diff check only
  line-ending warnings. Independent Tester: PASS with backend `152 passed`,
  UI `665 passed`, typecheck, compileall, and diff check. No Tauri visual
  acceptance was performed, matching the user-requested code-only scope.
- Git handoff: read-only; the heavily dirty worktree remains uncommitted and
  all unrelated/concurrent changes were preserved. No stage, commit, revert,
  cleanup, or attribution was performed. Exact next entry point: use the
  supervisor/runner contracts, runtime projection, and sub-agent UI tests for
  follow-up changes, retaining asynchronous mailbox delivery, approval-resume
  child identity, late-context placement, and the five lifecycle mappings.

## Context compaction final fix delta (2026-09-16)

- Task ID/deployment: `compaction_full_summary_recent_users_20260915`; state:
  `complete`.
- Consecutive manual compactions now union prior `compacted_history_seqs`
  while preserving positive retained Steps. Steps removed by the exact-budget
  fitter are marked and cannot reappear in same-run memory, durable history, or
  the next run for either manual or automatic compaction.
- Final evidence: main focused coverage `291 passed`; independent targeted
  coverage PASS. The full Core baseline remains `1965 passed, 2 skipped`, with
  six unrelated failures in tool-count, artifact-DB, and live-resume tests.
  No Tauri run was performed.
- Git handoff: only this documentation delta is owned here; the heavily dirty
  uncommitted worktree and concurrent changes remain untouched. No stage,
  commit, revert, cleanup, attribution, or diary edit was performed. Exact
  next entry point: use the focused sequence-union and fitter-removal
  contracts before changing zero-tail behavior, newest-20 suffix handling, or
  positive-Step retention.

## Sub-agent role assignments handoff (2026-09-16)

- The role-assignment model uses a global `role_assignments` baseline. Project
  assignments merge by trimmed, case-folded `task_type`: a same-name project
  assignment overrides the global assignment and a new project assignment is
  appended. The stored fields are `task_type`, `type`, `model`,
  `reasoning_min`, and `reasoning_max`; `type` is `consider` or `execute`.
  Supported reasoning is `off/light/medium/high/xhigh/max`; `xh` normalizes to
  `xhigh`, and `shallow` is not supported.
- Shared UI edits both global and project scopes and saves canonical
  `model_id`. RPC responses distinguish `local`, `effective`, and `inherited`.
  CLI commands are `subagent roles show/set/delete`. The role section in the
  system prompt is emitted immediately after the guide section.
- Verification: backend `77 passed`; frontend `37 passed`; typecheck,
  `compileall`, LamTools design audit (`84/0`), and `git diff --check` passed.
  No Tauri visual acceptance was run.
- Git handoff: this entry is documentation-only; preserve the existing dirty,
  uncommitted worktree and unrelated changes. For follow-up, begin with the
  role-assignment merge/RPC/CLI contracts and the shared UI tests, retaining
  canonical model IDs, inherited/effective state, and the no-Shallow boundary.

## Office renderer contract planning handoff (2026-09-16)

- Task ID/deployment: `office_renderer_contract_20260916`; closure state:
  `paused`.
- Scope completed: read-only inspection and planning for a unified renderer
  needed by the built-in Office Skills. Core currently has no durable Office
  renderer/service that owns rendering and layout validation.
- Proposed contract for the next implementation entry: expose one `office
  render` CLI/service; require the Agent to write a canonical, machine-readable
  data manifest first; validate each table cell and each chart
  series/category/value binding against that manifest before rendering; fail
  closed on any mismatch and return a structured error with code, page/element
  identity, expected and actual values, and source location.
- Layout QA belongs in the renderer. The planned PDF/PNG preview pass should
  detect text overlaps and return page number, element IDs, visible text,
  bounding boxes, overlap rectangle, and the conflicting element so the Agent
  can correct the source layout. Planned conversion is LibreOffice Office to
  PDF with an isolated profile and no automatic installation; packaging must
  declare PyMuPDF, python-pptx, and openpyxl.
- Verification performed: read-only document/code/Git inspection only. No
  tests, builds, Tauri/Computer Use, production or Skill edits, staging,
  commit, revert, cleanup, or attribution were performed. The worktree remains
  heavily dirty with unrelated and concurrent changes preserved.
- Blocker/decision: implementation must wait for user confirmation of the
  proposed renderer location, CLI/service boundary, manifest schema, supported
  Office formats, and LibreOffice availability behavior. Exact next entry point
  is to confirm that contract, then inspect existing Office Skill/tooling
  surfaces and add the renderer plus CLI and contract tests.

## Sub-agent delegation strategy handoff (2026-09-16)

- Task ID/deployment: `delegation_strategy_closure` /
  `subagent_delegation_strategy`; closure state: `complete`.
- Delegation strategy is `forbidden`, `low`, `medium`, or `high`, defaulting to
  `medium`. The global baseline is inherited by projects; an explicit project
  value overrides it, while `null` or `unset` deletes the local key and
  restores inheritance. RPC returns `local`, `effective`, `global`, and
  `inherited`; CLI commands are `subagent strategy show/set/unset`.
- Projects with blank `work_root` are rejected, including the unified
  guide/roles validation. The shared editor supports all four levels and a
  project “inherit global” option with independent saves. Prompt order is
  `guide → strategy (priority declaration) → roles`, and high-strategy
  responsibility copy is complete.
- `CoreBaseAgentKit` and `_build_core_runtime_toolbox` hide/disable
  `sub_agent` and `sub_agent_message` under `forbidden`. Direct calls and
  approval resumes after switching to `forbidden` are blocked; already-running
  historical agents are not closed. Explicit user/operator lifecycle RPCs do
  not belong to the main-agent strategy boundary.
- Verification: backend prompt/CLI `83 passed`; config defaults `5 passed`;
  approval-focused `2 passed` plus approval group `5 passed`; blank-root CLI
  `9 passed`; blank-root RPC `4 passed`; frontend `3 files / 40 passed`;
  typecheck, `compileall`, design audit `84/0`, and diff check passed. Tester
  verdict: ACCEPT, with no P0/P1/P2 findings. No Tauri or Computer Use run was
  performed.
- Git handoff: documentation-only scope; the shared dirty, uncommitted tree
  and unrelated changes remain untouched. Next entry point is the strategy
  merge/RPC/CLI/editor contract and forbidden-boundary approval tests.

## Title-bar sidebar toggle and narrow-screen closure (2026-09-16)

- Task ID/deployment: `titlebar_sidebar_controls_archive` /
  `titlebar_sidebar_controls_20260916`; closure state: `complete`.
- WorkspaceShell now owns left/right pin state. Both pin changes, including
  responsive auto-unpin, are emitted and synchronized into LamToolsApp; TitleBar
  only requests the toggles. At max-width 640px, only the two sidebar controls
  are hidden; device/account and native window controls remain available.
- Evidence surfaces: `core/ui/src/components/WorkspaceShell.vue`,
  `core/ui/src/app/LamToolsApp.vue`, `core/ui/src/components/TitleBar.vue`,
  and the responsive/sidebar contract tests.
- Verification: focused coverage 24/24; full UI contract 87 files / 674 tests;
  UI typecheck passed; LamTools design audit covered 84 files with 0 violations;
  affected-file `git diff --check` was clean.
- Limitation: code-only verification; no Tauri visual/runtime check was run.
- Git handoff: read-only; the heavily dirty, uncommitted tree was preserved.
  No stage, commit, revert, cleanup, or unrelated attribution was performed.
  Exact next entry point: start with the WorkspaceShell/LamToolsApp/TitleBar
  synchronization contracts and responsive sidebar-control tests when extending
  this behavior.

## Unified Office renderer implementation handoff (2026-09-16)

- Task/deployment: `office_renderer_implementation_20260916`; this deployment
  originally delivered the renderer below `_shared`. The later standard
  packaging repair in this handoff supersedes that location. The former
  `lamtools_core.office` package remains removed.
- Contract: canonical datasets are written first in a manifest. Table and
  chart targets bind to that manifest using `pptx_table`, `pptx_chart`,
  `docx_table`, `xlsx_range`, or `xlsx_chart`. Each cell, category, series,
  and value is compared before rendering. A data or structure mismatch stops
  before backend discovery and leaves no PDF/PNG/Office output.
- Rendering and diagnostics: Windows `auto` uses Microsoft Office COM first
  and LibreOffice second through `soffice.com`. Successful rendering provides
  PDF/PNG previews and text-overlap reports with page, conflicting elements,
  visible text, and geometry.
- CLI entry points are `office validate` and `office render`. Runtime location
  checks passed for source, simulated `_MEIPASS`, and wheel installation. The
  wheel contains the companion runtime and no `__pycache__`. The PyInstaller
  spec static-path check passed; a complete PyInstaller build was not run.
- Evidence: final main regression coverage passed 157 tests; independent
  acceptance passed 133 tests; a real Microsoft Office COM CLI smoke run
  passed. Deliberate mismatch and text-overlap cases retain exit codes 2 and 4
  with structured diagnostics.
- Limitations and pending work: this evidence covers structural/data gates,
  backend conversion, and programmatic overlap diagnostics; it is not a claim
  of pixel-level human visual acceptance. The repository remains a shared
  dirty tree pending the user's normal commit/review decision. This handoff
  changed only the two assigned documents; no diary, staging, commit, revert,
  cleanup, or unrelated attribution was performed. Exact next entry point is
  the companion-runtime CLI path and the unrun complete PyInstaller build.

## Office Skill standard packaging repair handoff (2026-09-16)

- Deployment `office_skill_standard_packaging_20260916`; closure state:
  `complete`.
- The GUI retest exposed a discoverability failure: from an isolated project
  directory the Agent ran `which office`, concluded the renderer was absent,
  and bypassed the required manifest gate. The stable invocation is now
  embedded directly in each relevant authoring Skill as
  `py -3.14 -m lamtools_core.cli office ...`; PATH probing is forbidden.
- Renderer ownership is now standard and self-describing at
  `core/skills/office-renderer/`, with `SKILL.md`, explicit-only
  `agents/openai.yaml`, executable `scripts/office.py`, and the implementation
  package below `scripts/lamtools_office_renderer/`. Core CLI lazy-loads this
  path and keeps the former `_shared` lookup only as a temporary compatibility
  fallback.
- The ten authoring Skills gained standard `agents/openai.yaml` metadata and
  moved to version 0.2.0 beta. Spreadsheet guidance requires recalculation to
  be saved into the exact file bound and delivered; chart guidance forbids
  truncated positive-value bar baselines.
- Runtime support now honors standard
  `policy.allow_implicit_invocation: false`: the renderer can be loaded
  explicitly but is omitted from automatic Skill indexes, with cache
  invalidation when `openai.yaml` changes.
- Evidence: all 11 Office Skills passed the Skill Creator validator; 117
  Office/Skill/runtime tests and 59 Core CLI tests passed; direct script help
  and structured JSON failure behavior passed from unrelated working
  directories; scoped diff check had no errors. Wheel build remains unexecuted
  because neither available Python environment has `hatchling`; existing
  recursive force-include/spec packaging covers the new standard tree.
- Git disposition: the repository remains heavily dirty with concurrent work.
  No staging, commit, revert, cleanup, or attribution of unrelated edits was
  performed. The next behavioral acceptance step is a fresh GUI task in a new
  project directory and confirmation that `office-data.json`, validate report,
  render report, and preview directory are all produced before delivery.

## Turn artifact discovery and presentation repair (2026-09-16)

- Completed top-level Agent answers now discover explicitly listed local file
  paths, reject missing/out-of-project paths, register the files in Artifact V2,
  and attach them to the same message item so both “本轮产出” and the project
 成果库 receive the deliverables without a UI-side filesystem scan.
- The stable system prompt now requires every newly created or updated
  deliverable path to be listed explicitly in the final answer.
- Message artifact cards use theme-aware neutral surfaces and Lucide type icons;
  the hard black card and saturated blue code tile were removed. Artifact-panel
  selection and primary actions were also neutralized, with spreadsheet,
  presentation, and code icons inferred from the filename.
- Text/code artifacts open in an internal plain-text preview instead of the OS
  default app. CLI parity is available through `artifact preview`.
- Follow-up interaction repair: card expansion is hover-only; click/focus no
  longer pins its size. Text preview opens on double-click (or Enter/Space) and
  is teleported to `body`, so its fixed overlay is window-relative rather than
  anchored to the transformed/scrolling chat content. The overlay now reuses
  the neutral Core confirmation backdrop recipe instead of the themed solid
  color that appeared blue.
- The “本轮产出” hover stage now expands horizontally only. Card, icon area,
  and deck height stay at 72px, so inspecting a file no longer pushes later
  chat content downward.
- Verification: Artifact V2 tests 8/8; focused UI tests 93/93; UI typecheck
  passed; design audit scanned 84 files with zero violations; scoped diff check
  passed aside from existing line-ending warnings. No Tauri visual run or commit
  was performed.

## Office Skill direct-execution prompt repair (2026-09-16)

- Task/deployment: `office_skill_runtime_directness_20260916`; state: complete.
- Root cause: the generic instruction to confirm tools and environments allowed
  ordinary Office production to drift into renderer source inspection, backend
  probing, scratch experiments, and capability re-certification. The renderer's
  automated `visual=passed` status was also being conflated with a full preview
  review, so only representative pages were viewed while an overall visual pass
  was claimed.
- Repair: `office-renderer/SKILL.md`, `office-renderer-contract.md`, and
  `tooling-contract.md` now make the public CLI/JSON report the trusted boundary
  and prescribe the single path `office-data.json -> final source -> validate ->
  render -> structured-error repair -> validate`. Ordinary tasks may not inspect
  renderer/Core CLI source, make scratch Office/negative-manifest/formula-cache
  experiments, or probe PATH/installations/private backends. A formal environment
  error stops rendering and is reported rather than reverse-engineered.
- Visual claim boundary: full visual review requires every generated page/sheet
  preview image to be viewed once; sampled review must list the viewed pages.
  Programmatic `visual=passed` remains an automated-rule result, not evidence of
  human or vision-model page review.
- Evidence: new static prompt-contract coverage plus renderer regression suites
  passed 31 tests. All 11 Office Skills passed `quick_validate.py` with UTF-8
  enabled. Scoped `git diff --check` passed with line-ending warnings only. No
  GUI or complex Office scenario rerun was performed.
- Git disposition: the shared worktree remains heavily dirty and uncommitted;
  unrelated and concurrent changes were preserved. Exact next entry point is a
  fresh GUI Office task verifying the Agent uses the direct path and performs a
  truthful full-versus-sampled preview review.

## Direct transport repair and `16-2-test` process-only review (2026-09-17)

- Root cause of the observed `direct transport disconnected` behavior was split
  between presentation and queue pressure: the client discarded WebSocket close
  diagnostics and surfaced every disconnect immediately, while the backend live
  reader performed a pointless sync-journal SQLite lookup for every transient
  `seq=0` delta. Under bursty streaming this could fill the 256-event subscriber
  queue and close with code 1013.
- Repair files: `core/ui/src/transport/{types,directTransport}.ts`,
  `core/ui/src/composables/useCoreToast.ts`, `core/ui/src/app/LamToolsApp.vue`,
  `core/ui/src/appServer/store.ts`, and `core/src/lamtools_core/app/live_router.py`,
  with focused tests in the corresponding UI/backend suites. Reconnects within
  two seconds are silent; persistent disconnects retain actionable close details.
- Verification: focused UI 42/42; full UI 683/683 across 87 files; UI typecheck
  and build passed; LamTools design audit reported 0 deviations across 84 files;
  the new backend regression passed. The wider router/hub run retained one
  unrelated failure in `test_core_live_resume_response_exposes_page_cursor`.
- Process audit evidence for session `95593909ad434e5e99aa45ca597ede80`:
  607 seconds, 48 model calls, 82 unique tool calls (80 completed, 2 failed),
  4,077,666 input tokens, 3,916,672 cached tokens, 73,654 output tokens, and a
  weighted 96.05% cache-hit rate. The Agent loaded the 0.2.1 renderer contract
  but still probed Python packages, LibreOffice paths, and matplotlib and ran a
  forbidden scratch formula-cache experiment. A later UTF-8 validation command
  failed because inline JSON reads used the Windows GBK default. After changing
  and rerendering the workbook, the Agent did not reopen the regenerated XLSX
  previews before claiming full visual review. This is a process finding only;
  no deliverable-quality judgment was made.
- Git disposition: the shared worktree remains heavily dirty. This closure did
  not stage, commit, revert, clean, or attribute unrelated changes.

## Optional Office readiness command and positive prompt (2026-09-17)

- Superseding prompt decision: Office Skills no longer enumerate renderer
  source inspection, PATH probes, scratch files, or other unwanted behaviors.
  They state the direct production path and one optional readiness command.
- `py -3.14 -m lamtools_core.cli office check` creates temporary minimal DOCX,
  XLSX, and PPTX files and performs real PDF conversions. Success prints exactly
  `Office 应用已就绪 · Test Passed 3/3`; JSON detail is written only when a
  report path is requested, while failures retain a concise status plus
  structured diagnostics.
- The companion `office-renderer/scripts/office.py check` entry point has the
  same behavior for standalone Skill packages. Both real commands passed 3/3
  locally. Focused tests passed 33/33, and all 11 Office Skills passed
  `quick_validate.py` with UTF-8 enabled.
- The shared worktree remains dirty; no staging, commit, cleanup, or unrelated
  attribution was performed.

## Model/provider and tool-mode settings entry cleanup (2026-09-17)

- Task ID/deployment: `model_provider_page_entry_refresh_archive` /
  `model_provider_page_entry_refresh_20260917`; closure state: `complete`.
- Production scope: `core/ui/src/components/CoreSettings.vue` removes the
  `.models-overview-bar` statistics and duplicate create buttons while keeping
  the page title/subtitle, provider-rail footer and provider empty-state CTA,
  and model-section header and model empty-state CTA. `CoreLoadToolsEditor.vue`
  removes `.loadtools-overview-bar` metrics and the duplicate top add action
  while keeping title/subtitle, dirty/refresh/save controls, mode-rail footer,
  and the empty-state CTA.
- Tests: `core/ui/tests/core-settings.test.ts` was updated and
  `core/ui/tests/core-loadtools-editor.test.ts` was added.
- Verification evidence: executor focused CoreSettings passed 16 tests;
  combined focused coverage passed 19 tests; typecheck, build, LamTools audit
  (84 files / 0 deviations), and scoped diff check passed. Independent Tester
  PASS included focused 19/19, full UI 88 files / 687 tests, typecheck,
  `npm run build`, and Git diff checks. Build output contained only existing
  dynamic-import warnings.
- Limitations: no Tauri/Computer Use visual validation was performed. The
  Tester observed older pre-existing dead CSS in CoreSettings unrelated to the
  removed active overview selectors; no blocker was found.
- Git handoff and exact next entry point: the shared worktree remains dirty and
  uncommitted, with unrelated files preserved. No stage, commit, revert,
  cleanup, or attribution was performed. If visual acceptance is requested,
  open the model/provider settings page and tool-mode editor in Tauri and check
  the retained local add/empty-state entry points.

## Website self-hosted distribution implementation closure (2026-09-17)

- Task ID/deployment: `website_self_hosted_distribution_closure` /
  `website_self_hosted_distribution_20260917`; implementation is complete;
  hosting/distribution follow-up is pending user confirmation.
- Completed scope: `website/` is now tracked. `website/src/App.vue` contains
  SiteNav/Hero/Showcase/Features/Download/SiteFooter. Showcase mounts the full
  real `LamToolsApp` with a typed in-memory `MockTransport`; it makes zero
  real API, XHR, or WebSocket calls. The UI provides synchronized ivory-white
  and graphite-black themes, with a very small rainbow spectrum reserved for
  fine-line emphasis. The default download is same-origin
  `/downloads/Sunday-latest-x64-setup.exe`.
- Preview containment repair: inline mounting had caused Core's
  `position:fixed`/`100vw`/`100vh`, settings cards, and composer to resolve
  against the host page. The preview now runs in a same-origin
  `preview.html` iframe with an independent viewport, still directly
  importing the complete `LamToolsApp` and `MockTransport`; the parent page
  does not load Core global CSS. Vite multi-page output now includes both
  `index.html` and `preview.html`.
- Theme synchronization is implemented with a fixed iframe URL and
  same-origin `postMessage`; the iframe remounts the real `LamToolsApp`, so
  switching themes is independent of parent-page scrolling and inline Core
  state.
- Independent Tester evidence: `npm run build` and
  `scripts/verify-preview.mjs` passed at 1440px and 390px; `pageScrollY=0`,
  no horizontal page overflow, and no console errors were reported.
- Extended verification passed at 2277x1362, 1440x1000, and 390x844, including
  shell/main/composer/settings containment, no Core overlay leakage into the
  parent page, and no API/XHR/WebSocket calls, console errors, or horizontal
  overflow.
- Final independent Tester verification passed in the production preview on
  port 5200 (`verify-preview` exit 0). Graphite and ivory both reported
  `pageScrollY=0`; settings rect `107.7/74.6/1330.3/798.5` was fully within
  the `1438x819` viewport; no API/XHR/WebSocket calls, console errors, or page
  errors occurred.
- Not yet executed: owned-server hosting, DNS configuration, update-source
  migration, and deployment. Until the user confirms the canonical HTTPS
  domain and upload/deployment method, the existing GitHub update/release
  path remains the active backend path. The installer artifact convention is
  `Sunday_<version>_x64-setup.exe`.
- Exact next entry point: after confirmation, deploy the tracked website and
  installer/manifest assets, configure DNS and same-origin update/download
  endpoints, then verify the live website and desktop update check. The local
  preview/test evidence must not be reported as live-server verification.
- Documentation/Git handoff: this correction changes only
  `agent_docs/project_progress.md` and `agent_docs/latest_session_work.md`.
  Preserve unrelated dirty/untracked files; no stage, commit, revert, cleanup,
  attribution, or `project_diary.md` edit was performed here.

## Study plugin UI repair closure (2026-09-17)

- Task ID: `study_plugin_style_archive`. Deployment ID/state:
  `study_plugin_style_20260917` / `complete`.
- Outcome/material changes: Study title now teleports into
  `.workspace-plugin-header` and follows the standard header band. Overview
  rows/progress use main-area tokens. The VueFlow graph remains backend-owned
  through `net.relations`, with theme-derived dot grid, relationship styles
  and legend, plus node/relationship counts. Study chat retains
  `useCoreAutoFollowScroll`, the IntersectionObserver bottom sentinel,
  jump-to-latest, and remount reset/forced-bottom behavior. Selection-assistant
  readability fills now use main theme tokens rather than hardcoded dark/light
  fills.
- Verification/evidence: focused Study 7/7; related scroll/plugin 31/31; full
  UI 92 files / 698 tests; backend Study 10/10; typecheck and build passed;
  LamTools audit 84 files / 0 deviations; manual Study token scan found no
  off-scale literals; scoped diff check passed. Tauri dev launched and the
  app/backend connected. Build output retained the existing `::highlight`
  lightningcss warning.
- Limitations/pending: no Computer Use or pixel visual acceptance was run.
  Exact next entry point is user visual acceptance in the now-open Tauri Study
  mode. No deployment-specific blocker is known.
- Git disposition: Study UI/test files are untracked inside the existing
  broader dirty tree; `project_diary.md` and these two documents are modified.
  No staging, commit, revert, cleanup, or unrelated attribution was performed.

## Study graph layout closure (2026-09-18)

- Task ID/deployment: `study_obsidian_graph_archive` /
  `study_obsidian_graph_20260918`; state: `complete`.
- Outcome/material changes: Study graph rendering now uses a deterministic
  one-shot relation-aware force layout with label-aware spacing. Compact
  Obsidian-like dot/label nodes, theme-derived edges, hover/focus/selection
  direct-edge emphasis, saved/manual position preservation, and existing graph
  navigation, inspection, and pagination are retained.
- Viewport contract: persistence uses supported VueFlow `@init`
  `store/setViewport` plus `moveEnd.flowTransform`; unsupported
  `v-model:viewport` was removed. The viewport repair was independently
  Tester-verified PASS.
- Verification/evidence: focused Study 7/7; full UI 92 files / 698 tests;
  UI typecheck; production build; LamTools audit 84 files / 0 deviations;
  independent Tester PASS after viewport repair; scoped diff/whitespace
  checks passed. The existing `::highlight` build warning remains.
- Limitations/pending: no Tauri/Computer Use or pixel-level visual acceptance
  was performed per project instruction. No deployment-specific blocker is
  known. Exact next entry point: user visual acceptance in Tauri Study mode
  for layout, viewport/position persistence, and direct-edge interaction.
- Git disposition: read-only handoff; the shared tree remains heavily dirty
  with concurrent and untracked Study/session/context changes. Preserve them
  without attribution. No stage, commit, revert, cleanup, or diary edit was
  performed.

## Selection assistant target grounding closure (2026-09-18)

- Task ID: `selection_target_grounding_archive`. Deployment ID/state:
  `selection_target_grounding_20260917` / `complete`.
- Outcome/material changes: the exact selected quote is the primary target for
  lightweight selection-assistant calls. Prefix and suffix text provide
  disambiguation only. Every Ask follow-up re-anchors to the selected quote,
  so a short mark such as “英语周” does not silently broaden into the whole
  surrounding passage.
- Cache/history behavior: the prompt version invalidates old explain/translate
  cache entries, while per-mark Q&A history is preserved. The local dictionary
  path remains model-free.
- Verification/evidence: backend Study coverage passed 11 tests; focused
  frontend coverage passed 13 tests; full UI contract passed 92 files / 698
  tests; typecheck passed; and the independent Tester returned PASS with no
  P0/P1/P2 findings.
- Limitations: no real-model semantic exercise or Tauri visual exercise was
  performed, so semantic answer quality and visual presentation remain for
  later acceptance.
- Git disposition and next entry point: the shared tree remains dirty and
  uncommitted; unrelated and concurrent changes were preserved. No staging,
  commit, revert, cleanup, or unrelated attribution was performed. If this
  behavior is extended or accepted manually, begin with a real Tauri selection
  of a short term, then Ask and verify the response remains quote-grounded.

## Study Markdown translation and response rendering closure (2026-09-18)

- Task ID: `study_markdown_translation_archive`. Deployment ID/state:
  `study_markdown_translation_20260917` / `complete`.
- Outcome/material changes: SelectionAssistant explain answers, model
  translation fallbacks, and Ask-assistant replies reuse `MarkdownRenderer`
  with `mermaid=false`. User questions and dictionary entries remain plain
  text. Card body line-height is `1.35`, with compressed Markdown spacing.
- Backend contract: quote, prefix, and suffix are explicit sections;
  translate/explain/ask limits are 256/600/1200. Old `prompt_version`
  invalidation clears only explain/translate/dictionary entries and preserves
  thread history. The dictionary fast path does not call the model.
- Verification/evidence: `study.test.ts` 7/7; `test_study.py` 11/11; full UI
  92 files / 698 tests; typecheck and build passed. The only build note is the
  existing `::highlight` lightningcss warning. Tauri session 13230 remains
  running and application RPC activity was confirmed.
- Limitations/pending: no Computer Use or pixel-level visual acceptance was
  performed. Exact next entry point is user visual acceptance in the open
  Tauri Study mode. No deployment-specific blocker is known.
- Git disposition: shared tree remains dirty and uncommitted; Study files may
  remain untracked. `project_diary.md` and the two assigned documents are
  modified. No stage, commit, revert, cleanup, or unrelated attribution was
  performed.

## Study shared chat primitives and node-session closure (2026-09-18)

- Deployment ID/state: `study_shared_primitives_20260918` / `complete`.
- Study no longer owns a parallel chat implementation. Its chat page uses the
  Core thread, history paging, message actions, composer, single sentinel
  observer, and complete attachment flow (picker, tray, drag/drop, paste,
  attachment-only send, and historical rendering).
- Core attachment storage now accepts plugin-owned colon session IDs and maps
  them to stable filesystem-safe directories while preserving the exact
  logical session ID in records and runtime input.
- Conversation architecture now consists of the compatible builder session
  `study:main` plus one session per knowledge node. The builder is titled
  `知识图谱`; node sessions keep teaching/exam context isolated. Unicode and
  punctuation-heavy node IDs map to stable hashed session IDs with the exact
  source ID retained in metadata.
- Agent/Workflow/Study switching no longer leaves the Workflow session visible
  in Agent. Node clicks select the corresponding node thread and prefill the
  learning prompt without sending it.
- Verification: backend Study/attachment HTTP 22/22; focused Study/mode/scroll 9/9;
  attachment/composer tests 35/35; full UI 92 files / 698 tests; typecheck,
  production build, design audit (84 files / 0 deviations), and diff check
  passed. The existing `::highlight` build warning remains. Computer Use was
  intentionally not used.
- Git disposition: the shared worktree remains dirty and uncommitted, including
  pre-existing unrelated changes and untracked Study files. Nothing was staged,
  committed, reverted, or cleaned.

## Study skill-pack integration closure (2026-09-18)

- Task ID: `study_skills_integration_20260918`. Deployment ID/state:
  `study_skills_integration_20260918` / `complete` for the requested Study
  scope.
- Source/evidence: the supplied Study pack was extracted under
  `E:\LamTools\.tmp\study-skills-integration-20260918\study-skill-pack`;
  `INTEGRATION.md`, `study-system.md`, and all four skill files were read
  before implementation. The durable Study module contract remains in
  `core/docs/study.md`.
- Outcome/material changes: the four skills are registered as bundled Study
  skills and only load through the existing SkillRegistry/`load_skill` route
  for `study:study`. The backend auto-loads `study-system.md` and retains
  shared safety, permission, tool, and verification protocols while omitting
  generic business/project workflow prompts. Existing Agent Loop, tool IDs,
  live/queue `instructions` and `request_local_late_context` forwarding,
  `study:main`/node sessions, UI components, and right-click lightweight calls
  remain the single implementation path.
- Data/contract completion: notes, learning context, help records, evaluated
  state, answer isolation, private answer/rubric storage, batch-save versus
  explicit-submit exam lifecycle, isolated generation/grading, review evidence,
  validation/signing, and idempotent score writeback are covered. Public
  reads and grading output do not expose answer/rubric content. Textbook,
  PDF, knowledge-base, and RAG integration was deliberately not implemented;
  the Study UI was not redesigned.
- Verification performed: `py -3.14 -m pytest tests/test_study.py
  tests/test_bundled_plugins.py
  tests/test_workflow_operations.py::test_workflow_disabled_at_start_can_reenable_and_restart_watcher -q`
  passed `33`; `npm run test:contract -- --run tests/study.test.ts
  tests/core-live-composer-controller.test.ts` passed `19`; prior recorded
  typecheck, build, and full UI contract passed (`699` tests). Build warnings
  are the existing LightningCSS `::highlight` and ineffective dynamic-import
  warnings. A direct rerun of the eight known non-Study failures produced
  `57 passed, 8 failed`.
- Non-Study failures and evidence: the three persistence tests
  `test_core_operation_persists_run_items_and_snapshot`,
  `test_core_operation_publishes_run_items_while_turn_is_running`, and
  `test_core_approval_continuation_persists_approved_tool_and_final_snapshot`,
  plus the three live tests
  `test_live_turn_reuses_accepted_id_for_core_events_terminal_and_task_registry`,
  `test_live_turn_steer_reaches_the_next_model_call_before_a_no_tool_final`,
  `test_live_queue_guidance_reaches_the_next_model_call` fail because
  `core_projects` is absent. The live client E2E matrix and live resume
  page-cursor test return empty resume events. The full Core suite was not
  rerun after the unrelated Workflow expectation correction, so the earlier
  `2077 passed, 9 failed, 2 skipped` aggregate remains the only full-suite
  aggregate and is not silently upgraded to a claimed `2078/8` result.
- Limitations/next entry point: no Computer Use, Tauri manual, pixel-level,
  or real-model semantic acceptance was run. If requested, begin with a
  user-owned Tauri Study pass, then handle the eight Core baseline failures in
  a separate scope. No deployment-specific Study blocker is known.
- Git disposition: Archivist changed only the assigned progress and latest
  session documentation by appending this handoff. The shared tree remains
  dirty and uncommitted; unrelated/concurrent modifications and untracked
  Study files were preserved. No stage, commit, revert, cleanup, or diary
  edit was performed.

## Study v2 knowledge workspace closure

- Task ID/deployment/state: `study_v2_closure` /
  `study_complete_v2_20260918` / **paused at a stable, tested boundary**.
  The source package was extracted to
  `E:\LamTools\.tmp\study-complete-v2-20260918\Study_v2.0`; its README and
  design/contracts/performance documents were read before the repository
  audit. The P0–P3b implementation is present; P4 textbook/PDF/knowledge
  base/RAG and P5 remain deferred interfaces.
- Implemented architecture and principal paths: the bundled plugin under
  `core/src/lamtools_core/plugins/bundled/study/` owns the scoped SQLite
  `StudyStore`, backend adapter, exam/sign/marks handlers, operation/tool
  contracts, `study-system.md`, and the four requested skills. Existing
  tool IDs remain `get_knowledge_net`, `build_knowledge_net`, `exam`, and
  `sign`; the registry exposes their mapped operations only to Study. Core
  `base_agent.py` injects the Study prompt while preserving shared safety,
  permissions, tool protocol, streaming, cancellation, and session/message
  persistence. `core/ui/src/study/` adds the v2 Overview/Graph/Notes/Subject
  Tree semantics, scoped search/pins, local graph layout, node session
  bindings, marks, selection assistant, and note manager on the existing
  Workbench/chat components. Core `mem/` and `runtime/arrange.py` provide
  scoped memory and curation/fencing seams shared with Dreaming.
- Data/migration behavior: `study.db` is created in the runtime application
  data directory. Startup creates scoped records, separate structure/state
  revisions, signed cursors, request/sign receipts, an outbox, session
  bindings, notes/blocks, curation tasks, pins, and soft-delete snapshots.
  The idempotent migration copies legacy `study_entities`/`study_meta` into
  the explicit local-compatibility scope and repairs the note-block composite
  foreign key. Backups were made with SQLite `.backup` at
  `E:\LamTools\.tmp\study-v2-backup-20260918-0158` for
  `core/data/core.db` and `core/core.db`; both reported
  `integrity_check=ok`. No real `study.db` was present during audit, so the
  migration test is synthetic and does not represent a user-library run.
- Verification evidence: recorded full Core result is `2113 passed, 2
  failed, 2 skipped`; the two failures are pre-existing
  `thread.resume` snapshot-only protocol mismatches. Shared UI result is 92
  files / 702 tests; typecheck and production build passed. Independent
  reruns on 2026-09-18: `tests/test_study.py` 36 passed,
  `tests/test_memory_v2.py` 12 passed, and `tests/test_arrange_fencing.py`
  3 passed. Build warnings are the existing LightningCSS `::highlight` and
  ineffective dynamic-import warnings. The P0 audit remains
  `core/docs/AUDIT_STUDY.md`; module usage is documented in
  `core/docs/study.md`.
- Material incomplete items: `operations.jsonc` still declares Study RPCs
  `auto_allow`, so action-level approval/policy is not complete. Exam and
  lightweight text calls still use the context LLM client directly and need
  the shared Direct ModelGateway retry/cancel/usage accounting. The runtime
  SQLite versions are Python 3.50.4 and CLI 3.50.6, below the design
  3.51.3 WAL-fix floor; no engine upgrade was performed. No real-model
  semantic test, Tauri/mobile visual test, or performance-budget run was
  executed. These are release/acceptance gaps, not claims of failure in the
  completed local contracts.
- Exact continuation point: implement and test the Study action-policy/
  approval boundary, route isolated exam/quick-assist model calls through the
  shared Direct ModelGateway, and establish the supported SQLite engine and
  per-connection policy. Then run the migration-copy against an approved
  user backup, real-model isolation/quality, Tauri visual, and performance
  acceptance suites. Preserve the existing Core loop/UI and the current
  backups while doing so.
- Git/read-only handoff: baseline was
  `56d45e4e9257ec1be9c98a948783b23ff598183d` on
  `codex/multiplatform-dev`; the worktree was already heavily dirty and Study
  files were mostly untracked. The Study-specific paths above and the
  cross-cutting Core/UI edits overlap concurrent user work, so attribution is
  intentionally conservative. This closure changed only
  `agent_docs/project_progress.md`, `agent_docs/latest_session_work.md`, and
  `core/docs/study.md`; no stage, commit, reset, checkout, clean, database
  deletion, push, or release was performed. Exact next entry point is the
  action-policy/Direct-Gateway/SQLite follow-up above.

## Study reset and performance closure

- Task ID/deployment/state: `study_perf_reset_closure_20260918` /
  `study_perf_reset_20260918` / **complete**. Study content was backed up
  before clearing at `E:\LamTools\.tmp\study-reset-20260918-111814`;
  the directory contains `study.db` and `core.db`. After Tauri startup,
  exactly one empty `study:main` shell snapshot/binding was regenerated, with
  zero knowledge, notes, exams, marks, receipts, outbox, history, or runtime
  rows.
- Root cause/fixes: the unsupported `study.session.binding` alias caused the
  global five-retry exponential backoff (about 6.2 s worst case). The UI now
  uses canonical `study.session`; duplicate refresh/select work was removed;
  known bindings skip session refresh; binding and overview load in parallel;
  the sidebar does not eagerly fan out every course; graph get/layout are
  parallel; and VueFlow is split into an async `StudyGraph` chunk. Initial
  Study and `PluginModeHost` reuse `HistoryLoadingIndicator`; later switches
  retain the Core thread; mode changes preserve the connection-scoped App
  Server client; command catalog/goal/scroll work is parallelized.
- Runtime evidence: Tauri restarted with frontend `5173` and backend `59690`.
  On the empty DB, backend RPC elapsed time was 58.7 ms for `study.session`
  and 41.7 ms for `study.get`. CLI wall time was about 1 s because it includes
  process and WebSocket startup.
- Verification: focused UI 18/18; full UI 92 files / 706 tests; typecheck;
  `build:app`; backend 48 passed with 2 deprecation warnings; design audit
  84 files / 0 deviations; `git diff --check` had no errors (only normal
  line-ending warnings); independent Tester passed 3 files / 17 tests.
- Limitations/next entry point: no Computer Use or perceptual timing run was
  performed. Real Tauri visual/interaction timing remains user acceptance.
  The worktree is heavily dirty and this closure made no commit, reset,
  cleanup, database deletion beyond the explicitly backed-up Study reset,
  push, or release.

## Study graph primary-progress closure

- Task ID/deployment/state: `study_graph_primary_progress_20260918_closure` /
  `study_graph_primary_progress_20260918` / **complete**.
- The old Study overview UI/page was removed. The former sidebar location is
  now `管理你的知识`; `图谱` remains. The explicit `manage` action clears
  the selected node and restores the existing `map` primary binding/default
  main session, without a duplicate `study.session` request when the binding
  is cached. No backend, schema, or database changes were made.
- Top-level course nodes reuse the existing overview aggregate and render
  exact course names as large circular spheres with an external SVG progress
  ring and readable/clamped percentages (`total <= 0` renders 0%). Deeper
  nodes are unchanged. Ring bounds were aligned with the existing 112px
  layout spacing.
- Verification: focused Study 15/15; full UI 92 files / 708 tests; UI
  typecheck and `build:app` passed; backend Study 38 passed with 2
  deprecation warnings; design audit 84 files / 0 deviations; independent
  Tester PASS. Only existing `::highlight`, dynamic-import, and chunk build
  warnings remain. DOM/CSS/mock-RPC contracts were verified.
- Limitation/Git handoff: computer-use and live Tauri visual/perceptual
  inspection were intentionally not run; visual and interaction timing remain
  user acceptance. The worktree is heavily dirty and unrelated/concurrent
  changes were preserved; no production/test files, diary, commit, reset,
  cleanup, push, or release was performed by this closure.

## Glass material unification pause (2026-09-18)

- Task ID: `glass_material_unification_archive`. Deployment
  `glass_material_unification` is `paused` before implementation because the
  proposed all-glass-like-surface scope requires user confirmation.
- Evidence retained: the supplied Liquid Glass brief defines high-transmission,
  low-blur optical glass with restrained highlights, gray-green edge refraction,
  and soft short shadows; the repository has a shared `optical-glass.css`
  primitive; the read-only inventory and dirty-tree review were completed.
- Disposition: no production or test changes, no tests/build checks, no Tauri
  visual acceptance, and no Computer Use. `project_diary.md` and unrelated
  dirty/untracked work were preserved; nothing was staged, committed, reverted,
  cleaned, or attributed to this deployment.
- Exact next entry point: once the user confirms scope, unify true glass
  material surfaces through the shared primitive. Exclude mere modal dimmer
  backdrops and opaque panels; keep shape/layout decisions separate from
  material treatment.

## Study skill v3 refactor closure

- Task ID/deployment/state: `study_skill_refactor_v3_20260918_docs` /
  `study_skill_refactor_v3_20260918` / **complete**. Snapshot evidence is at
  `E:\LamTools\.tmp\study-skill-v3-snapshot-20260918-135315`. The exact v3
  package files for `build-map`, `teach`, `answer`, `take-exam`, and
  `prompts/study-system.md` were copied into
  `core/src/lamtools_core/plugins/bundled/study/`.
- `curate-notes` was retained at
  `core/src/lamtools_core/plugins/bundled/study/future/curate-notes` and is
  deliberately not registered because the Agent Loop lacks a callable notes
  tool/capability gate. `core/src/lamtools_core/plugins/bundled/study/eval_manifest.py` and
  additional `test_study` coverage provide the evaluation surface.
- Host smoke PASS: 4 active skills plus 1 future-gated skill, 14 references,
  and 40 evaluations with `run=0` / `NOT_RUN=40`. Focused Python coverage
  passed 50 tests. UI 708 tests, typecheck, UI build, desktop build, package
  validation, and examples 14/14 passed. Examples ran under Python 3.9
  because Python 3.14 lacks sympy. The stable Core full suite result is 2116
  passed / 2 skipped / 2 failed; both failures are unrelated existing
  `thread.resume` event-page tests.
- Audit gaps: no source version/archive service, no verified technical image
  generation, strict schema limitations, and no `study.text.cancel`.
  `quick_validate` cannot accept the package's standard compatibility
  frontmatter, so that validator result is not represented as a pass.
  Preserve the dirty worktree and treat these as follow-up items; this
  documentation closure changed no production/test files or diary and made
  no commit, reset, cleanup, push, or release.

## Glass material unification implementation closure (2026-09-18)

- Task ID: `glass_material_unification_impl_archive`. Deployment
  `glass_material_unification_impl` is **complete** and supersedes the
  earlier paused planning deployment after user confirmation.
- Material implementation: `.optical-glass` in the shared UI now centralizes
  tokenized transmission/blur, saturation, brightness, contrast, fallback,
  localized reflection, gray-green refraction, inset edge treatment, and soft
  shadow. Consumers are WorkspaceShell's right drawer; shared context-menu
  root/submenus; Study SelectionAssistant; Workflow node catalog popover and
  runtime dock; LamToolsApp jump-to-latest and Goal; and MobileTopBar's
  button/sync/account controls. `core/desktop/index.html` mirrors the same
  startup optics before Vue mounts, while the native desktop shell supplies
  Acrylic.
- Boundary: modal dimmer backdrops, ordinary opaque panels, the left drawer,
  and Workflow node cards are intentionally not glass. Independent Tester
  PASS followed repair of blue startup refraction and the 48% inset to
  gray-green and 56%.
- Verification: 93 UI files / 712 tests passed; focused glass/startup
  recheck 21 tests; UI typecheck/build, desktop Vite build, `cargo check`,
  LamTools audit 84 files / 0 deviations, and scoped/full diff checks passed.
  No Computer Use or Tauri visual validation was run per user instruction.
- Git/evidence handoff: retain the heavily dirty, concurrent, untracked tree.
  Archivist changed only these two documentation files; no diary edit, stage,
  commit, revert, cleanup, or unrelated attribution occurred. If visual
  acceptance is later authorized, begin with the listed consumers and the
  startup surface in Tauri.

## Glass specular quieting closure (2026-09-18)

- Task ID: `glass_specular_quieting_archive`. Deployment
  `glass_specular_quieting` is **complete** as a focused correction after the
  glass unification.
- Material delta: shared upper-left reflection changed from 26% to 10%, with
  footprint 92×42 reduced to 54×24. Startup light/dark optics and edge layers
  now use 38×20 at `.06/.05` and 26×4 at `.09/.08`; every other material
  parameter is unchanged.
- Verification: focused 2-file / 21-test glass/startup coverage passed;
  LamTools audit 84 files / 0 deviations passed; relevant diff check passed;
  independent Tester PASS. No Computer Use or Tauri visual validation was run
  per user instruction.
- Git disposition: heavily dirty, concurrent, and untracked work remains
  preserved. This closure changed only the two assigned documents; no diary or
  production/test files were edited, and nothing was staged, committed,
  reverted, or cleaned.

## 0.3.4 audit/build handoff (2026-09-18)

- Deployment: `audit_fix_bump_20260918`. Current version: `0.3.4`. No commit,
  tag, push, release, reset, clean, or unrelated-file rollback was performed.
- Correctness fixes: `thread.resume` now returns journal deltas alongside the
  optional snapshot; local HTTP readiness probes bypass configured proxies;
  mobile cached projects preserve and validate `iconKey/colorKey`; shared GSAP
  animation modules safely import without a browser `window`.
- Final checks: Python 2122 passed / 2 skipped; UI 93 files / 725 tests;
  mobile 11 files / 46 tests; desktop Rust 53 tests; relay 11 tests; UI/mobile
  typechecks and production builds passed; Rust fmt/check/clippy passed with
  non-blocking structural warnings; npm production audits found zero
  vulnerabilities; design audit was 84 files / 0 deviations; `git diff --check`
  had no whitespace errors.
- Package output:
  `E:\LamTools\core\desktop\src-tauri\target\release\bundle\inno\Sunday_0.3.4_x64-setup.exe`
  (93,961,819 bytes). It installed successfully to `E:\setuptest\0.3.4`; both
  installed executable paths and product version 0.3.4 were verified.
- Remaining verification: the installed app could not remain running because
  the pre-existing development executable
  `E:\LamTools\core\desktop\src-tauri\target\debug\lamcore.exe` (PID 7000)
  holds the global Tauri single-instance lock. It exited cleanly with code 0,
  and the setup skill forbids stopping other-directory/dev processes. After the
  developer closes that instance, rerun
  `.\.agents\skills\lamtools-setup-install\scripts\install_setup.ps1 -Version 0.3.4 -ForceCloseExisting`
  to capture installed main/backend PIDs.

## PDF ingestion fix handoff (2026-09-18)

- Root cause: `web_fetch` passed successful `application/pdf` responses to `httpx.Response.text`, so the model received `%PDF` binary garbage. The upload path separately labeled PDFs as unparsed/deferred, and both main/sub-agent assembly could drop valid text-only attachment context.
- Implemented shared in-memory PDF normalization in `tool/document_normalize.py`; `web_fetch` detects MIME or PDF magic and parses off-loop; attachment runtime parsing reuses the same normalizer; main/sub-agent assembly now preserves index text and performs blocking parsing/file reads through `asyncio.to_thread`.
- Added coverage for PDF MIME and magic detection, invalid PDFs, uploaded PDF extraction, and text-only sub-agent attachments. The real TI URL extracted successfully. Final verification: Core 2128 passed / 2 skipped; UI 727 passed plus typecheck/build; desktop Vite build passed; scoped and full diff checks passed. No version bump, package, commit, reset, cleanup, push, or release was performed.

## Study exam model-routing correction handoff (2026-09-18)

- Task ID: `study_exam_model_routing_fix_docs`. Deployment
  `study_exam_model_routing_fix` is **complete**. The source failure was an
  isolated Study exam call without the active runtime `model_id`, producing
  `model id is required when no routing setting is available`; the generic
  retry path then retried a deterministic configuration error.
- Implemented behavior: isolated Study exam authoring, grading, and review
  carry the active runtime model through approval. Explicit operation-level
  model selection overrides inherited state. Arrange and Workflow queue
  scheduling inherit and persist the runtime model, while explicit queue/node
  overrides win. Missing model/provider/base URL now fails immediately without
  silent provider/model fallback or retry churn.
- Source/test surfaces reviewed for this handoff include the bundled Study
  backend/exam/marks paths, live runtime stamping, `runtime/arrange.py`,
  Workflow operation/queue/runtime resolution, shared LLM retry classification,
  and `core/tests/test_study.py`, `test_workflow_operations.py`,
  `test_llm.py`, plus related provider/runtime tests. The main Agent Loop and
  existing Study UI were preserved.
- Verification evidence: targeted suites passed. The full Core run was
  `2142 passed, 2 skipped, 1 unrelated localhost HTTP probe timeout`; an
  isolated rerun of the timeout case passed `1`. A later focused
  provider/routing run passed `67 passed, 1 skipped`, and an independent
  verifier returned PASS. Do not collapse these into a claim of one clean
  full-suite run.
- Not run / limitations: no network or UI/Tauri test, real-model semantic
  acceptance, or database migration was executed for this fix. No database
  schema change was made. The worktree remains heavily dirty and uncommitted;
  unrelated user/concurrent changes were preserved. Exact next entry point is
  maintainer review of the routing diff, followed by user-owned Study/Tauri
  acceptance if desired.
- Git handoff: read-only status showed the pre-existing broad dirty tree,
  including the two assigned documentation files and concurrent Core/UI,
  Study, Workflow, and configuration edits. No stage, commit, reset, checkout,
  clean, database deletion, push, or release was performed.

## Study agent grading correction handoff (2026-09-19)

- Scope: repair formal Study exam grading so the current Agent can use the
  persisted reference answer only when the active context no longer contains
  the original exam standard, then directly judge the submitted work. The
  grading path no longer invokes an isolated model and no longer requires an
  exact match between a choice response and the stored option text.
- Behavior: the Agent owns semantic grading, including correct, partial, and
  incorrect outcomes and step-level allocation. The persisted exam record
  retains reference answers and scoring guidance for recovery. Saved grading
  preserves partial credit, `step_scores`, grading `version`, and idempotent
  writes; code-level checks remain limited to persistence and consistency
  invariants rather than interpreting answer wording.
- Evidence: focused Study grading coverage passed 50 tests. The full Core run
  recorded 2143 passed / 2 skipped / 1 temporary `PermissionError`; the
  affected test passed when rerun. UI and desktop builds passed, and an
  independent Tester passed the change.
- Limitations: no real production-model grading request and no Tauri/manual
  interaction retest has been executed. The user plans to retest the formal
  exam in the 极限 lesson. If it fails, begin with the persisted exam record,
  grading event, model request/response, and idempotency receipt for that exam;
  do not infer a semantic result from static tests.
- Continuation point: wait for the user's 极限-node retest, inspect the actual
  grading trace if needed, and then update this handoff with the observed live
  result. Preserve the dirty worktree and do not claim production-model or
  Tauri acceptance before that retest.

## Study note curation connection (2026-09-19)

- Inspected the persisted 极限 turn `8dcd14790c38`. The model explicitly found
  no notes tool, searched unrelated workspace directories, and returned a
  draft saying it could not save. No note database failure occurred.
- Added Study tool ID `notes` mapped to the existing `study.notes` operation,
  registered `curate-notes` only in `study:study`, and kept the tool visible
  from the first Study request so loading the skill does not mutate the model's
  tool prefix. No second note service, database, or UI was added.
- Agent note creates are normalized to unlocked AI blocks. The Agent path strips
  `user_edit`, so a forged request cannot overwrite an existing locked user
  block. Existing revision conflict behavior is unchanged.
- Verification completed: `tests/test_study.py` plus
  `tests/test_bundled_plugins.py` passed 50 tests; Study compileall passed. A
  full Core run reached 80% before being deliberately stopped because the
  cache-stability design changed, so it is not a completed result.
- Follow-up UI correction: the real saved 极限 note contained eight coherent
  sections, but `NotesManager.vue` rendered every AI block as a separate card
  and textarea. Reading mode now joins the ordered blocks into one Markdown
  document; block editors appear only after selecting Edit. Study UI tests
  passed 17/17, typecheck passed, and the UI build passed with only the known
  `::highlight` minifier warnings. Tauri received the change through HMR.

## Chat instruction navigator design pause (2026-09-19)

- Task ID/deployment/state: `chat_turn_navigator_design_20260919_archive` /
  `chat_turn_navigator_design_20260919` / **paused** pending user consensus.
  Scope was a read-only design/code audit for an ultra-minimal navigator in the
  Core chat area. No production or test files changed; the attached screenshot
  was treated only as visual reference.
- Verified implementation seams: `.thread` in
  `core/ui/src/app/LamToolsApp.vue` is the scroll container; each `MessageView`
  rendered by `core/ui/src/components/ChatThread.vue` receives
  `data-message-id`; `LamToolsApp.vue` already exposes `locateMessage`, which
  loads older history when needed and centers/highlights the target; history
  pagination is already buffered and anchored; the initial history request
  uses `turn_limit: 10`; `.optical-glass` is the shared glass primitive; and
  the narrow layout has a `@media (max-width: 640px)` boundary.
- Proposed direction: add a ChatGPT-style left-edge instruction navigator
  whose points correspond only to user messages. The active point is longest;
  inactive points progressively weaken. Hover/focus previews should use the
  shared optical-glass card, while click navigation should call
  `locateMessage`. Avoid a second scroll observer and reuse the existing
  scroll/history machinery.
- Decisions still required before implementation: (1) all historical user
  instructions versus only the currently loaded window; (2) preview content as
  user-only text versus user text plus a paired response summary; (3) mobile
  behavior as hidden versus a compact overlay. No Computer Use or Tauri run
  was performed. Relevant UI files are already dirty/concurrently edited and
  must be preserved.
- Verification/disposition: source seams were inspected read-only; no tests,
  builds, visual acceptance, staging, commit, reset, revert, or cleanup were
  performed. Next entry point is user resolution of the three decisions,
  followed by a bounded implementation and Tauri visual acceptance; do not
  infer acceptance from the reference screenshot.

## Chat instruction navigator implementation closure (2026-09-19)

- Task ID/deployment/state: `chat_turn_navigator_impl_archive` /
  `chat_turn_navigator_impl_20260919` / **complete**. The previously paused
  design was implemented in Core chat. The server-side outline is exposed as
  `thread.outline`, with CLI parity through `session outline`. It emits only
  top-level, renderable `userMessage` rows and pairs each prompt with a
  response excerpt, capping both excerpts at 240 characters.
- UI outcome: `ChatOutlineNavigator.vue` renders evenly indexed markers over
  the full history. The active marker is chosen from the mounted user message
  nearest 38% of the viewport. The preview uses shared `.optical-glass` and
  click selection calls the existing `locateMessage`, so unloaded targets still
  use established history pagination/centering behavior.
- Interaction/performance contract: keyboard focus and activation are wired;
  reduced-motion behavior is honored; marker geometry accounts for device
  pixel ratio; RAF and `ResizeObserver` resources are explicitly cleaned up.
  The navigator is hidden at `max-width: 640px`. No second scroll observer was
  introduced; the existing chat scroll machinery remains authoritative.
- Verification evidence: backend focused tests passed 50; the broader executor
  set passed 181. Final frontend focused tests passed 27; UI typecheck passed;
  `build:app` passed with existing warnings; the LamTools design audit covered
  85 files with 0 deviations. An independent Tester passed. Its earlier RAF
  S3 finding was repaired, after which the navigator-focused 7 tests and
  typecheck passed.
- Limitations/disposition: no Computer Use or Tauri visual validation was run
  at the user's request, so visual placement and interaction timing remain
  user-owned acceptance. Read-only Git handoff shows a dirty worktree with
  concurrent/untracked changes preserved; no commit, stage, reset, revert, or
  cleanup was performed. If visual acceptance is authorized, begin with the
  navigator in Tauri, then verify the <=640px hidden state and full-history
  navigation after pagination.

## Study Obsidian notes phase 1 closure (2026-09-19)

- Task ID/deployment/state: `study_obsidian_phase1_archive` /
  `study_obsidian_phase1` / **complete**. The existing NotesManager now
  reads the ordered NoteBlocks as one Markdown document, supports edit versus
  preview, extracts h1-h6 headings for an outline, and resolves
  `[[wikilink]]` targets for notes and knowledge nodes within the active Study
  scope. Backlinks use the same scoped resolution.
- Navigation uses stable note/node IDs. Unresolved wikilinks are preserved and
  do not block saving. The existing `update_blocks` write is atomic, retains
  the block/source rows, and rejects duplicate block IDs. This phase added no
  `.md` shadow store, link table, second Agent Loop, or wholesale UI rewrite.
- Verification evidence: focused backend tests passed 53; focused UI tests
  passed 21; final UI typecheck and build passed; design audit covered 85
  files with 0 deviations; and independent Tester verification was PASS.
  Full UI 739 passed and full Core 2152 passed / 2 skipped were run before the
  final narrow atomic-boundary fixes, followed by focused final rechecks.
  Existing `::highlight` and dynamic-import build warnings remain.
- Limitations and handoff: no Computer Use/manual Tauri acceptance, data
  migration/deletion, commit, push, or release was performed. Retest at
  Study > 笔记 using the existing 极限 note: edit, preview, save, then test
  `[[another note]]` and `[[knowledge node|label]]`. This is the exact next
  entry point; preserve the heavily dirty worktree and do not infer visual
  acceptance from static checks.

## Study packaged RPC hotfix closure (2026-09-19)

- Task ID/deployment/state: `study_rpc_packaged_hotfix_archive` /
  `study_rpc_packaged_hotfix_20260919` / **complete**. The production-only
  failure was the canonical Study backend import resolving `study-system.md`
  beside the module, although PyInstaller places the plugin data below the
  frozen bundled resource root. `bundled_plugins_dir()` now supplies that
  fallback; Agent Loop, Study RPC IDs, and UI contracts are unchanged.
- Packaging smoke now opens the WebSocket, initializes it, and performs a real
  `study.session` request. Source-focused coverage passed 55; independent
  checks passed Study 44 and bundled-boundary 10; PyInstaller packaged smoke
  passed. Installed `E:\setuptest\0.3.5` backend PID 29728 on port 49758
  returned non-empty `session_id` `study:main`.
- Rebuilt installer: 93,990,114 bytes,
  SHA256 `5E26B6F280DC5E8D8A4B20338569488A036E370E34695840493B592C3111BE5A`.
  The public download was replaced and the redownload hash matched. Server
  backups were created at
  `/var/www/lamtools/Sunday_0.3.5_x64-setup.exe.before-study-rpc-hotfix-20260919T143333Z`
  and the corresponding `Sunday-latest...` path; the temporary SSH key and
  upload directory were removed.
- Limits/Git handoff: no full repository test result is claimed. No commit,
  tag, or push was made; the heavily dirty worktree and unrelated user and
  concurrent changes remain preserved. Exact next entry point is installed
  0.3.5 Study acceptance. If it regresses, start with the frozen resource
  resolution and `bundled_plugins_dir()` evidence rather than changing the
  Study RPC or prompt contract.

## Study notes UX optimization closure (2026-09-20)

- Task ID/deployment/state: `study_notes_ux_20260920` /
  `study_notes_ux_20260920` / **complete**. This closure hardened the full
  Study notes path: trusted host writer and Agent ownership enforcement,
  precise `study/changed` broadcasts, code-safe typed wikilinks, node
  backlinks, and Study CLI `search`/`pin` parity. NotesManager now projects
  Markdown without trimming away syntax, reports detail loading/error/retry,
  refetches after save with stale-response protection, guards note-scoped
  navigation when drafts exist, shows provenance/unresolved-link feedback,
  handles setext/DOM outlines, and honors reduced motion. `curate-notes` is
  version 3.1.0; the Study system prompt documents read-first, minimal
  incremental writes, ownership, conflict, source-honesty, and receipts.
- Verification evidence: backend Study trio 59 passed; focused frontend 31
  passed; `npm run typecheck` passed; `npm run build` passed with the existing
  lightningcss `::highlight` and ineffective dynamic-import warnings;
  compileall and scoped whitespace checks passed; the LamTools design audit
  covered 85 files with 0 deviations. Independent Tester conclusion: no P0-P2
  defects remained after the CommonMark indented-code wikilink fix.
- Scope deliberately excludes auto-save and delete/restore. No Computer Use or
  Tauri visual acceptance was run. Read-only Git handoff confirms a heavily
  dirty/untracked workspace, including Study files and concurrent edits; no
  stage, commit, reset, revert, cleanup, or release occurred. Exact next entry
  point, if visual acceptance is requested: Study > 笔记, then exercise
  read/edit/preview/save, draft navigation, typed links/backlinks, search,
  pinning, and retry/error states. Do not infer this acceptance from static
  checks.

## Linux/macOS desktop distribution planning handoff (2026-09-20)

- Task ID/deployment/state: `multiplatform_planning_archive` /
  `linux_macos_desktop_20260920` / **paused** pending user consensus. Goal:
  plan Linux and macOS desktop distributions without attributing changes to
  the already heavily dirty workspace.
- Verified blockers: the current package handoff discovers the Windows
  `LamCore.exe` sidecar; packaging is PowerShell/Inno-only; release and update
  code select only `Sunday_*_x64-setup.exe`; Linux secure storage is currently
  in-memory; install-adjacent user data does not map safely to a signed macOS
  `.app` or an AppImage; hook fallback uses Windows `APPDATA`/`AppData`; and
  there is no native Linux/macOS desktop CI. These are blockers to a reliable
  distribution, not claims that the shared application architecture is
  non-portable.
- Portable base and constraint: the shared `LamToolsApp`/Workbench and
  transport contract, Rust/Tauri shell, Python Core backend, JSONC config, and
  CLI are reusable. PyInstaller and Tauri artifacts must be built on native
  runners for each target OS; a Windows build cannot certify Linux/macOS
  artifacts.
- Recommended scope, not yet approved: Linux x64 AppImage + `.deb`; separate
  Intel and Apple Silicon DMGs; Linux/macOS standard data roots while
  preserving Windows paths; Secret Service/Keychain secret storage; native
  packaged smoke tests; and platform-aware update plus website download
  assets.
- Required decisions: confirm Apple Developer ID signing/notarization
  credentials and whether they are in scope; confirm whether this deployment
  only implements/tests or also bumps versions, tags, and publishes releases.
  No implementation should begin before those decisions.
- Work performed and limits: read-only audit only. No production or test
  files changed; no package build, CI run, signing, notarization, release, or
  Computer Use occurred. Read-only Git handoff found the existing dirty/
  untracked worktree and left it untouched; no stage, commit, reset, revert,
  cleanup, push, attribution, or `project_diary.md` edit occurred.
- Evidence: `core/desktop/PACKAGING.md`, `scripts/package.ps1`,
  `.github/workflows/release.yml`,
  `core/src/lamtools_core/update/checker.py`,
  `core/src/lamtools_core/plugins/hook_config.py`, plus the shared UI,
  transport, Tauri, and CLI paths. No test or build result is claimed for this
  planning deployment.
- Exact next entry point: after user consensus, define native-runner CI,
  platform data/secret roots, package names/assets, smoke contracts, and
  update/download selection; then implement and verify only the approved
  scope. Until then the plan remains paused.

## Study three-layer notes deployment closure (2026-09-20)

- Task ID/deployment/state: `study_notes_three_layer_20260920_archive` /
  `study_notes_three_layer_20260920` / **complete**. This closure updates the
  public Study documentation after the implementation and independent review.
- Current architecture: Raw is a trusted, immutable host snapshot of session,
  mark, exam, and node data; Resource is Agent-authored, versioned material
  with mandatory real `raw_ids`; Note is the user-visible multi-file Markdown
  vault. The `.md` body is the Note source of truth; SQLite retains index,
  relation, Resource/source links, revision/hash, and lock metadata. Historical
  NoteBlock tables are compatibility migration input only, not the runtime
  Note contract.
- Current Note UX: `path` builds the left Markdown file tree while
  `parent_id` remains a semantic parent relation. The Note page has top return
  and Notes-chat controls. Its overall relationship graph belongs to Note and
  is rendered in the right rail with Note-only wikilink and parent edges.
  Each Note references Resource and shows a low-key host-managed source footer.
- Editing contract: user and Agent edit the full Markdown document. Resource
  and Note writes use CAS; external file changes or stale revision/hash stop
  Agent overwrite. User-selected UTF-16 ranges block only Agent edits;
  `NOTE_REGION_LOCKED` returns the reason and overlap while the UI preserves
  the draft. User editing and lock management remain allowed.
- Verification evidence: Study backend trio 66 passed with 2 SQLite datetime
  deprecation warnings; Study frontend 31 passed; `npm run typecheck`,
  `npm run build`, Study compileall, and UTF-8 `curate-notes` quick validation
  passed; design audit 85 files / 0 deviations; independent Tester PASS. Build
  output has only existing `::highlight` and ineffective dynamic-import
  warnings.
- Limitations and Git handoff: no Computer Use/Tauri visual test, complete
  repository run, real-model semantic acceptance, real-user-library migration,
  package, commit, release, or data deletion was performed. Read-only Git
  inspection found the expected heavily dirty/untracked workspace; all user
  and concurrent changes remain untouched. Exact next entry point, if visual
  acceptance is requested, is Study > 笔记 with file-tree navigation, Notes
  chat, right-rail graph, source footer, full Markdown editing, CAS conflict,
  external-file handling, and user-lock overlap checks.

## Linux x64 desktop distribution implementation closure (2026-09-20)

- Task ID/deployment/state: `linux_desktop_closure_20260920` /
  `linux_desktop_implementation_20260920` / **complete**. This closes the
  approved Linux x64 implementation only. macOS is explicitly deferred; no
  macOS package, signing, notarization, or support claim was made.
- Outcome: the Linux desktop runtime selects a native extensionless `LamCore`
  sidecar and stores it in both package types as
  `lamcore-backend/LamCore`. Linux mutable state is rooted in Tauri
  `app_data_dir()`/XDG data paths, hooks honor `XDG_CONFIG_HOME`, and secure
  credentials use persistent Linux Secret Service storage. Windows retains its
  existing `.exe` sidecar and portable layout.
- Build entry point: `scripts/package-linux.sh`. It stages the repository in
  Ubuntu 22.04 WSL2 on the E-backed distro root
  `E:\WSL\Ubuntu-22.04`, keeps the Node/uv/Python/Rust toolchains, caches, and
  build staging on the Linux filesystem, and rejects `/mnt/c`. The script
  builds the Linux frontend and PyInstaller sidecar, produces AppImage and
  `.deb`, checks package contents, and runs backend plus Xvfb/isolated-D-Bus
  smoke. `.github/workflows/ci.yml` and `release.yml` call this script. The
  update checker prefers AppImage and falls back to `.deb`; the website links
  to both versioned GitHub `latest/download` assets.
- Final local artifacts for version `0.3.5` (not uploaded or published):

  - `core/desktop/src-tauri/target/release/bundle/appimage/Sunday_0.3.5_amd64.AppImage`
    — 186,821,112 bytes — SHA256
    `9A714A659577D6DBBC5DBF28B05ECB7FA6EDD4EABF607F6E1652E2879C47C345`.
  - `core/desktop/src-tauri/target/release/bundle/deb/Sunday_0.3.5_amd64.deb`
    — 120,093,070 bytes — SHA256
    `B869BF672284EA32F08FA9DAA8EB9DD8C9CFE428867F3B6E08FE63A32BB6B0C7`.
  - `artifacts/linux-x64/sidecar/LamCore` — 17,551,704 bytes — SHA256
    `77545A21C1BF49674043DCC2354BD662EB5F1FF004DA76371AAB5FAC6088ED8F`.

- Verification evidence: 15 Linux/update Python tests passed; website build,
  workflow YAML parsing, Bash syntax, `git diff --check`, and Rust release
  `cargo check` passed. REST/WebSocket/Study packaged smoke passed. The final
  AppImage and `.deb` were recognized as valid Linux packages and the `.deb`
  contained the executable sidecar. Independent AppImage smoke observed
  bundled `LamCore` PID 3883, returned expected timeout rc=124, and left no
  sidecar survivors. The broader run was 50/55; the five failures were
  pre-existing concurrent-network failures unrelated to this delta.
- Git/release handoff: read-only status showed a heavily dirty worktree with
  user and concurrent changes; it was not cleaned or attributed. No version
  bump, stage, commit, tag, push, GitHub release, or publication occurred.
  Exact next entry point is an explicitly authorized release review using the
  three hashes above. Any macOS work must begin with a separate native runner,
  data/secret-root contract, and signing/notarization decision.

## Mobile code review, refactor, and bug-fix closure (2026-09-20)

- Task ID/deployment/state: `mobile_review_refactor_closure_20260920` /
  `mobile_review_refactor_20260920` / **complete**. The mobile review fixed
  account refresh single-flight and logout/session-generation races, serialized
  account/workspace transitions, and fenced initialization after unmount.
  Connection/resume generations now reject stale results; Noise handshake
  message waits are bounded, cancellable, and cleaned up; SyncEngine close is
  fenced against started repository writes; and scoped memory-cache recovery
  restores the active bucket.
- The non-native credential default is memory-only. Tunnel cancellation and
  frame/type validation are hardened, and Capacitor identifies the app as
  `Sunday`. These changes preserve the mobile boundary around pairing,
  lifecycle, trusted devices, connection/wire, native capabilities, and local
  cache behavior.
- Independent Tester verification: `npm test -- --reporter=dot` passed 12
  files / 54 tests; `npm run typecheck`, `npm run build`, `npm run cap:sync`,
  and `git diff --check -- core/mobile` passed. Capacitor sync produced no
  visible native Git diff; build output contained only chunk/dynamic-import
  warnings.
- Limitations: no real Android/iOS device, LAN, Relay, or Tauri visual runtime
  acceptance was run; Windows CocoaPods/xcodebuild checks were skipped. Git
  handoff before this documentation amend was commit `bae53c33`; only
  `.tmp_glass_rg.txt`, `MyProject/`, `artifacts/`, and `docs.7z` remain
  intentionally untracked. Next entry point: real device/network acceptance
  of pairing, reconnect/resume, workspace switching, and cache recovery.

## DSH prompt comparison and Core prompt optimization handoff (2026-09-20)

- Task ID/deployment/state: `prompt_comparison_20260920` / **complete for the
  documented implementation scope**. This handoff records the selected prompt
  optimizations after comparing LamTools with DeepSeek Harness (DSH). DSH was
  pinned to official commit `ddefc45fbc7f8e46dd73185e68295696d1297887`
  (`0.1.6-alpha.2`, 2026-09-17), using the native text-turn expected snapshot
  and the system-prompt assembly design. Baseline evidence was about 4,276
  bytes for DSH native and 13,117 characters / 245 lines for the LamTools
  prompt. The post-change prompt measured 11,264 characters / 194 lines; the
  Skill index fell from 3,341 to 1,878 characters.
- Implemented prompt changes: `base_agent.py`, `default_agent.py`,
  `http_agent_app.py`, and `cli.py` now share the one-line identity
  `你是 Sunday Agent。`; `base_agent.py` centralizes the common
  Shell/file/search/web/Skill/evidence/progress rules; MCP server activation
  is described as on-demand and its output as untrusted external data. Study
  retains its narrower prompt while using the shared safety subset.
- Context and loading changes: `project_context.py` skips the exact seeded
  global `AGENTS.md` and `memory.md` templates but keeps customized content;
  `skills.py` emits compact trigger hints and leaves full Skill instructions to
  `load_skill`. The full project `AGENTS.md`, the guide/strategy/role layers,
  and existing plugin/MCP capability model were not removed or rewritten in
  this scope.
- Cache/compaction changes: the active plan and loop repair guidance now use
  late `user` messages tagged `metadata={"internal": true}`. This keeps the
  stable system prefix reusable while allowing the shared history to retain
  the guidance. Internal messages are excluded from recent-user selection and
  semantic compaction grouping; internal metadata is stripped before model
  dispatch. Guidance keys cover duplicate input, payload reassessment,
  no-progress recovery, tool-progress gates, failure diagnosis, and goal
  completion repair.
- Evidence references: `core/src/lamtools_core/app/base_agent.py:97`,
  `:101`, `:445`, `:479`, `:534`; `core/src/lamtools_core/app/project_context.py:119`
  and `:134`; `core/src/lamtools_core/skills.py:65` and `:97`;
  `core/src/lamtools_core/kernel/loop.py:868`, `:1024`, `:1116`, `:1144`,
  `:1158`, `:1188`, and `:1299`; and
  `core/src/lamtools_core/context_compaction/planner.py:135` and `:238`.
- Verification status: regression tests were added for the canonical identity
  and consolidated tool protocol, seeded-template filtering, compact Skill
  index/full on-demand load, late internal plan messages, internal repair
  metadata, and compaction grouping. The focused suite passed 259 tests; the
  entrypoint/plugin/Study suite passed 237 with 1 skip. `compileall` and
  `git diff --check` passed. No Tauri visual check is applicable to this
  backend prompt change.
- Git/disposition: read-only inspection found the expected heavily dirty,
  concurrently edited worktree. No stage, commit, reset, revert, cleanup,
  release, or attribution was performed; `project_diary.md` was left
  unchanged. Exact next entry point: decide whether to add a DSH-style prompt
  snapshot, duplicate/order checks, and a character/token budget gate. Keep
  the existing guide/strategy/role injection unchanged unless separately
  approved.

## Standalone mobile architecture decision handoff (2026-09-20)

- Task ID/deployment/state: `mobile_standalone_scope_archive` /
  `mobile_standalone_foundation_20260920` / **paused** pending user consensus.
  Confirmed sequencing: deliver standalone basic functions first; defer the
  communication/protocol refactor until later.
- Verified context: mobile `App.vue` currently injects only
  `RemoteTransport`/`ConnectionManager` and the local sync cache. Relay's
  README/control/main paths say Relay stores no Core work data and forwards
  opaque Noise frames. The shared Workbench requires
  `LamToolsTransport`/App Server semantics, while Python Core owns LLM,
  runtime, and tool execution.
- Proposed minimum scope, not approved or implemented: phone-local text-only
  model access and local sessions, with existing paired desktop/Relay still
  available. Exclude file read/write, command/terminal, MCP/plugins, and host
  tools. A cloud Core Worker alternative would materially expand security and
  deployment scope and is not implemented.
- Prior validation for targeted stabilization commit `b2761c06`: mobile
  14 files / 60 tests, typecheck, build, Capacitor sync, and Gradle
  `assembleDebug` passed. This is stabilization evidence only, not standalone
  architecture acceptance.
- Exact next decision: local direct provider/API-key access with local-only
  sessions versus a server-hosted Core. Read-only Git handoff: concurrent
  prompt/backend edits and the documented personal/generated paths remain
  untouched; this closure did not modify production/tests/diary or stage,
  commit, reset, or clean anything. Do not infer approval or implementation
  from the preceding checks.

## Mobile standalone foundation current contract (2026-09-20)

- The current mobile entry is local-first: it opens an independent local mode
  through a login-free panel. Local projects and sessions use SQLite, and the
  phone can connect directly to OpenAI-compatible or Anthropic providers. The
  paired desktop/Relay route remains available separately; communication and
  protocol refactoring is not part of this foundation.
- The sync path is device → project → remote control/import. Browsing cache is
  independent from sync, offline mode disables remote control, and import uses
  pagination to retrieve the complete session history. The mobile surface
  hides session-title and window-switch controls.
- Transport switching now disconnects before replacement and clears the old
  App Server client's reconnect timers, preventing that stale client from
  closing the new remote-control connection. The overall communication
  protocol refactor remains deferred.
- Verification evidence: mobile tests passed 16 files / 77 tests; the shared
  UI passed 96 files / 757 tests and typecheck; mobile `npm run typecheck`,
  `npm run cap:sync`, and Android `assembleDebug` passed. ADB
  overlay installation on vivo V2536A running Android 16 verified the
  login-free entry, surface-matched dynamic safe area, compact left sidebar,
  long-press context menu, and import.
- The current offline device's remote-control behavior was not verified. This
  handoff does not claim a broader communication/protocol refactor or any
  other remote-control device acceptance. Next entry point is to repeat the
  remote-control path only when a connected device/network is available.
- Disposition: this records verified local-foundation behavior only. It does
  not claim a cloud Core Worker, communication/protocol refactor, or physical
  device acceptance beyond the listed vivo checks. Preserve unrelated and
  concurrent worktree changes.

## Mobile floating command dock closure (2026-09-20)

- Task/deployment/state: `mobile_floating_command_dock_20260920` / **complete
  with install confirmation pending**. The mobile right-side optical-glass
  command dock directly lists all app/plugin modes and includes search,
  settings, and account. The left sidebar still owns plugin management and
  its session/project opener; mobile hides duplicate search/settings actions,
  while desktop defaults remain unchanged.
- GSAP Draggable persists and clamps position, separates drag from click, and
  keeps panel geometry within 12px at 280px and 390px widths. Reduced-motion
  and ARIA listbox/option behavior are covered. Independent review found and
  the main agent fixed horizontal overflow and listitem semantics; recheck
  passed.
- Verification: UI typecheck passed; UI coverage passed 96 files / 761 tests;
  mobile typecheck passed; mobile coverage passed 17 files / 79 tests;
  `npm run cap:sync` and Android `assembleDebug` passed.
- Wireless ADB installation on vivo reaches OEM package confirmation but
  cannot complete without confirmation on the device. No real-touch
  verification is claimed. Next entry point: confirm installation on-device,
  then test dock drag/click separation, mode selection, search/settings/account,
  and 280/390px geometry.
- Read-only Git handoff — intended files:
  `core/mobile/src/App.vue`,
  `core/mobile/tests/mobile-command-dock-contract.test.ts`,
  `core/ui/src/app/LamToolsApp.vue`,
  `core/ui/src/components/LeftSidebarShell.vue`,
  `core/ui/src/components/MobileTopBar.vue`,
  `core/ui/src/components/WorkspaceShell.vue`,
  `core/ui/tests/left-sidebar-shell.test.ts`,
  `core/ui/tests/mobile-top-bar.test.ts`, and
  `core/ui/tests/optical-glass-contract.test.ts`.
  Unrelated dirty paths to exclude are `agent_docs/project_diary.md`, the
  modified `core/src/lamtools_core/**` prompt/compaction files and their
  `core/tests/test_context_compaction.py`, `test_core_default_agent.py`,
  `test_kernel.py`, `test_project_context.py`, `test_skill_runtime.py`,
  `test_tool_result_model_evidence.py`, plus `.tmp_glass_rg.txt`, `MyProject/`,
  `artifacts/`, and `docs.7z`. No commit or cleanup was performed.

## Mobile Tunnel protocol/transport refactor closure (2026-09-20)

- Task ID/deployment/state: `mobile_tunnel_protocol_archive_20260920` /
  `mobile_tunnel_protocol_refactor_20260920` / **complete**. The external
  Tunnel v1 wire schema stayed unchanged while protocol representation and
  transport orchestration were separated. One golden fixture consumed by both
  TypeScript and Rust covers the shared frame contract; UTF-8 limits and
  boundaries are byte based, sequence values are JavaScript-safe, and
  continuation frames must match the initial
  version/type/stream/request envelope. Unknown channels are still rejected.
- LAN, Relay, and Noise compatibility was preserved, including opaque Relay
  forwarding. No P0-P2 issue was found.
- Verification recorded by the deployment: mobile 17 files / 90 tests,
  typecheck, build; Rust format, `cargo check`, and all tests 59/59 (remote
  tunnel 8/8, gateway 12/12); Android `assembleDebug`; and
  `git diff --check`. No real-device install or runtime test was run.
- Git handoff is read-only: unrelated pre-existing backend/context-compaction
  changes and untracked `.tmp_glass_rg.txt`, `MyProject/`, `artifacts/`, and
  `docs.7z` remain untouched. Next entry point: real-device and LAN/Relay
  acceptance for pairing, reconnect/resume, and remote control.

## Desktop 0.3.6 / Android 0.1.2 release and website deployment

- Task ID/deployment/state: `close_release_036_website_20260921` /
  `release_036_mobile_012_website_20260921` / **complete**. Desktop `0.3.6`
  and Android `0.1.2` (`versionCode 33`) are released. The website is live at
  `https://47.114.43.99.nip.io/`.
- Website downloads were verified as HTTP 200 with matching lengths and hashes:
  Windows `/downloads/Sunday-latest-x64-setup.exe` — 94,081,829 bytes,
  SHA256 `2C0F61C0D613DC0C5313E393DE87A6202C3C7D12EC1327A83EFA1B37AE68934A`;
  Android `/downloads/Sunday-mobile-latest.apk` — 31,701,668 bytes, SHA256
  `5E60F49BBC7280E849CAB89A0B620AA67719CB3652B63E6F420CACBA92F1A3F2`.
- GitHub Release:
  `https://github.com/Lam-Arc/LamTools/releases/tag/v0.3.6`. Release CI run
  `35524142986` is all green; Windows took 10m47s and Linux 9m24s. Its three
  desktop assets are Windows setup 57,333,030 bytes, AppImage 186,640,888
  bytes, and `.deb` 120,141,358 bytes. Do not compare these CI sizes with the
  separately built website Windows package.
- Local acceptance installed the Windows setup under `E:\setuptest\0.3.6` and
  passed startup, health, WebSocket, Study, and websearch-snapshot checks.
  The application update check returned `up_to_date`. The Android release APK
  passed V2/single-signer, version, non-debuggable, and non-test-only checks;
  the mobile suite passed 18 files / 97 tests. The service and relay were
  active during online verification.
- Known non-blocking warnings: existing frontend chunk/dynamic-import build
  warnings and the intentional local-package/CI-package size difference. No
  release blocker remains. The pre-existing untracked `.tmp_glass_rg.txt`,
  `MyProject/`, `artifacts/`, and `docs.7z` were preserved. Exact next entry
  point: continue development from the published `v0.3.6` baseline.

## Model catalog/provider refactor closure (2026-09-21)

- Task ID/deployment/state: `archivist_model_catalog_20260921` /
  `commandcode_provider_20260921` / **complete**.
- Outcome and durable contract: model JSONC records carry a safe internal
  record ID used by defaults, UI selection, and group membership, while the
  upstream `model_id` is retained exactly for API calls. Provider JSONC owns
  base URL, API type, key, defaults, and provider-level request adaptation;
  model JSONC owns model metadata plus optional model-level adaptation. Model
  adaptation wins over provider adaptation, and provider inline overrides are
  merged before model inline overrides.
- `model_groups.jsonc` stores unique named groups, stable IDs, ordered
  many-to-many memberships, and revision checks. `config.model_groups.list`,
  `config.model_group.create|update|delete`,
  `config.model_group.members.set`, `config.model_groups.reorder`, and
  `config.model.create_with_provider` are registered RPCs. The CLI mirrors
  these under `models groups` and `models create --group`. Existing-model
  membership validates local record IDs; deleting a model/provider removes its
  membership, while deleting only a group preserves models.
- Group-view model creation requires an API base URL. An existing provider must
  match that URL; a new provider can be created with the model and membership,
  with cleanup on composite failure. Missing model records are reported as
  dangling memberships and ungrouped models are shown under “未分组”.
- UI entry points: the main chat execution control opens the model picker and
  shows the shared compact `CoreModelCatalogViewToggle` at the top; 设置 →
  模型与供应商 uses the same toggle for its catalog rail/detail view. The
  selection is loaded/saved through `settings.jsonc` at
  `core.modelCatalog.classification`.
- Preset outcome: Command Code and Command Code Free use the verified provider
  base URL and model-specific DeepSeek/Qwen/GLM adapter profiles; OpenCode Free
  was refreshed to Chat-compatible free entries. Additional Free presets are
  SambaNova, Groq, Google Gemini, Cloudflare Workers AI (editable account URL),
  and OpenRouter. Each exposes an API-key/documentation link through the
  external URL bridge; preset-created models are merged into the user `Free`
  group.
- Verification evidence: backend full run `2201 passed`, isolated
  environment-jitter rerun passed, then independent full run `2202 passed`;
  Core UI 96 files / 773 tests passed; UI typecheck and desktop build passed.
  No manual Tauri visual acceptance or real provider request is claimed here.
- Git/disposition: read-only handoff only; the expected heavily dirty
  worktree and concurrent changes were preserved, with no reset, cleanup,
  stage, commit, release, or attribution. `project_diary.md` was intentionally
  left outside this assignment. Exact next entry point: launch the Tauri
  desktop, inspect the two catalog entry points above, then test a real
  configured provider/model request and API-key link.

## Website Windows installer refresh (2026-09-22)

- Deployment `website_installer_20260922` is complete. Current version `0.3.6`
  was rebuilt from the existing dirty worktree; no version bump, commit, tag,
  push, or GitHub Release was performed.
- Local artifact:
  `core/desktop/src-tauri/target/release/bundle/inno/Sunday_0.3.6_x64-setup.exe`,
  94,124,582 bytes, SHA256
  `41FEDC6C7F14ED7A6B5F9420DD2CDA780CD386B499E915B85873F60091711343`.
- Packaging passed frontend build, PyInstaller boundary validation, packaged
  REST/WebSocket/Study/websearch smoke, Tauri release build, and Inno Setup.
  Setup acceptance installed and launched from `E:\setuptest\0.3.6` with main
  PID 19560 and backend PID 10424.
- Website deployment replaced
  `/var/www/lamtools/Sunday-latest-x64-setup.exe`; public URL
  `https://47.114.43.99.nip.io/downloads/Sunday-latest-x64-setup.exe` returned
  HTTP 200 and Content-Length 94,124,582, and the server SHA256 matched.
  Rollback file:
  `/var/www/lamtools/Sunday-latest-x64-setup.exe.before-20260922T023008Z`.
- Cloud Assistant evidence: inspection `t-hz06xsk3t5o53pc`, deployment
  `t-hz06xsknl5f7pxc`, final verification `t-hz06xskptyuge80`. The temporary
  SSH public key was removed, relay stayed active, and unrelated worktree files
  remain untouched.

## Android bundled catalog repair and website refresh (2026-09-22)

- Root cause: Android standalone mode implemented model configuration but did
  not implement `plugin.list`, `skill.list`, `hook.list`, or `plugin.ui.list`,
  so the shared desktop UI correctly rendered empty extension pages and never
  registered Study. `StandaloneExtensionsStore` now supplies the bundled
  plugin/core-skill/Study-skill catalog, Study and Workflow UI descriptors, and
  persisted plugin/skill switches. The shared plugin editor now honors the
  backend `builtin` flag and recognizes Study/Workflow.
- Verification passed: focused mobile tests 2 files / 6 tests, mobile
  typecheck, Vite production build, Capacitor Android sync, Gradle release,
  non-debuggable/non-test-only metadata checks, and APK V2 signature check.
- Published artifact: `release/mobile/Sunday-mobile_0.1.2.apk`, 31,709,068
  bytes, SHA256
  `58E0E54BCD21602A3AD9E4DA186276701CA15929D1943C97B65568C0BE19035A`.
  Website URL `https://47.114.43.99.nip.io/downloads/Sunday-mobile-latest.apk`
  returns HTTP 200 and Content-Length 31,709,068. Rollback file:
  `/var/www/lamtools/Sunday-mobile-latest.apk.before-20260922T033646Z`.
- Aliyun audit: status inspection RequestId
  `01A0C72E-7DB3-5D60-B00B-357A01D905C6`; temporary authorization inspection
  `01A0C72E-FF71-5900-8D80-7ECDDF4ACFAA` / `c-hz06xsqi4t7ss1s` /
  `t-hz06xsqi4tfah34`; deployment `01A0C72F-FB18-576D-B420-D59B10C438E0` /
  `c-hz06xsqlktwb5s0` / `t-hz06xsqlku6ar5s`; verification
  `01A0C730-6A9C-5F2D-AB3A-0F6CA7E68B4C` / `c-hz06xsqn3smvy0w` /
  `t-hz06xsqn3srvqps`. Final server state: matching hash/size, temporary key
  removed, relay active. The local temporary key directory was deleted.

## Android Tauri 2 + shared Rust Agent P1 release candidate (2026-09-22)

- Task/deployment/state: `mobile_tauri_rust_release_20260922` / **release
  candidate built; real-device upgrade gate pending**. Do not replace the
  website APK until that gate passes.
- Architecture boundary completed in this slice:
  `core/mobile/src/standalone/StandaloneTransport.ts` no longer owns any
  Capacitor/fetch model request or TypeScript tool loop. Standalone turns enter
  `runEmbeddedSundayTurn`, cross the Tauri command boundary, and run in
  `core/runtime-rs`. Contract tests reject reintroduction of
  `chat/completions`, `CapacitorHttp`, `postModelJson`, or `fetch(` in that
  transport. Rust project-file tools now cover write/read/list plus directory
  traversal rejection.
- CI: `.github/workflows/ci.yml` contains `mobile-android`, which installs Java
  21, Android 36, NDK 28.2 and the aarch64 Rust target, then runs mobile tests,
  typecheck/build, shared-runtime tests, and an actual Tauri Android aarch64
  debug APK build. The YAML parsed successfully and the local Tauri CLI
  confirmed the selected build flags.
- Packaging hardening: `scripts/package-mobile.ps1` now validates the exact
  `arm64-v8a`/`armeabi-v7a` application-library set, `zipalign -P 16`, and all
  arm64 ELF LOAD alignments (`0x4000`) in addition to signature, metadata and
  release flags.
- Final local artifact:
  `E:\LamTools\release\mobile\Sunday-mobile_0.1.2.apk`;
  package `com.lamtools.mobile`; versionName `0.1.2`; versionCode `1002`;
  41,785,124 bytes; SHA256
  `0D72E68CEB487CFB676E8B20AD46F21BBE6969F0C3669D30437355A883EF203C`.
  It verifies with one V2 signer, certificate SHA256
  `045567d59580c97311203453e104938ad09d9f79e1e78e028f607cdbc4ecb4fb`,
  two physical-device ABIs, 16 KiB APK alignment, and arm64 16 KiB ELF LOAD
  alignment. It is non-debuggable and non-testOnly.
- Black-screen diagnosis and repair: the failure was reproduced on the API 36
  x86_64 emulator. Logcat showed `WebAssembly.Module()` rejected because the
  Tauri CSP did not allow `unsafe-eval`; the call originates from
  `noise-handshake` → `xsalsa20` during top-level module initialization, before
  Vue can mount. `tauri.conf.json` now grants the narrower
  `'wasm-unsafe-eval'` source instead of `'unsafe-eval'`; `src/main.ts` loads
  `App.vue` dynamically and renders an explicit startup-error surface on import
  or mount failure. The packaging script also removes stale `x86`/`x86_64`
  generated JNI directories before the release build.
- Regression evidence: mobile 19 files / 108 tests passed; mobile typecheck and
  production build passed; shared runtime 2/2 tests and Tauri host 2/2 tests
  passed; `cargo fmt --check` for both crates and `git diff --check` passed.
  Existing Vite chunk/dynamic-import and Gradle deprecation notices remain
  non-blocking.
- Runtime evidence: the corrected x86_64 debug APK launched on the API 36
  emulator, displayed the Sunday onboarding screen, and emitted no CSP,
  `CompileError`, or startup exception in logcat. Screenshot:
  `E:\LamTools\release\mobile\emulator-fixed-screen.png`.
- Upgrade evidence: the public 31,709,068-byte APK was downloaded read-only and
  its V2 certificate digest exactly matched the new Tauri package, so Android
  signature continuity is established. The emulator launch does not replace
  the required prior-install phone test; old-package overlay install, Capacitor
  SQLite import, secure-key migration, and post-restart project/session
  persistence are **not tested**. The public website file remains unchanged.
- Security cleanup: the prior temporary server authorization had already been
  removed (`KEY_COUNT=0`); the remaining local APK-inspection directory was
  sent to the Recycle Bin, and the temporary published-APK download was
  deleted after certificate comparison.
- Scope boundary: this is the P1 shared Rust Agent loop, not full Python Core
  parity. Hooks, MCP, subagents, context compaction, memory, and complete
  Study/Workflow services remain unmigrated; model-level official thinking
  parameters are also not yet wired through the Rust provider config.
- Exact next entry point: connect the phone that has the currently published
  APK, archive its expected local state, install this APK with `adb install -r`,
  verify database/key migration and local Agent file-tool behavior across an
  app restart, then atomically update the website APK only if every check passes.

## Shared Rust migration continuation (2026-09-22)

- Active goal: `01a0bad2-6dfd-79b3-b832-3403fcf1e1a1`; do not mark complete or
  replace the website APK until P0-P8 and the real-device upgrade matrix pass.
- Added native OpenAI Responses and Gemini Generative Language support in
  `core/runtime-rs/src/provider.rs`, including native request envelopes, tools,
  output-token fields, official thinking parameters, reasoning extraction,
  provider-state replay restricted to the same model, and upstream model-id
  reporting. Runtime tests are 11/11.
- Added serializable tool approval continuations to `core/runtime-rs/src/lib.rs`.
  Read/list project tools auto-allow, writes ask, and unknown tools hard-block.
  Android persists approval requests in the Core snapshot and resumes them via
  `sunday_agent_resume`; mobile regression is 22 files / 114 tests.
- Added Rust SQLite-backed `StandaloneStateStorage` for model/provider settings
  and plugin/skill switches. It imports legacy localStorage once when native
  state is empty and surfaces Rust/SQLite failures instead of falling back.
- Added native project file list/read/write commands and routed the shared UI
  project client to them. These commands and `ProjectFileTools` use the same
  `app_data_dir()/projects/<id>` root; old repository files lazily migrate on
  first list/read. Tauri host tests are 5/5.
- Added shared `AgentContext`; Android reads project `AGENTS.md` and `MEMORY.md`.
  Projectless sessions now use `session-<thread-id>` workspaces, which removes
  the prior Study conversation failure caused by an empty project id.
- Verification passed: `cargo test` in runtime and mobile host, Rust formatting,
  mobile Vitest/typecheck/Vite build, `git diff --check`, and
  `tauri android build --apk --debug --target aarch64 --ci`. The generated debug
  APK is under `core/mobile/src-tauri/gen/android/app/build/outputs/apk/universal/debug/`.
- No new signed release APK was produced; the earlier release hash does not
  include this continuation work. Next implementation package should migrate
  Hooks/trust/config execution, then MCP and subagents, followed by compaction,
  memory/Dreaming, Study/Workflow, desktop/CLI host replacement, and final
  physical-device/cross-platform acceptance.

## Shared Rust Hooks + MCP continuation (2026-09-22)

- `core/runtime-rs/src/hooks.rs` now owns hook models, config registry, stable
  trust identity, cumulative decisions, Prompt/HTTP/MCP/Command execution and
  platform-runner boundaries. `AgentRuntime` fires SessionStart,
  UserPromptSubmit, PreToolUse, PermissionRequest, PostToolUse,
  PostToolUseFailure and Stop, preserving hook state through approval
  continuations.
- `StandaloneExtensionsStore` now implements hook list/config/trust/untrust/
  delete against native persisted state. Android explicitly treats command
  hooks as unavailable unless a host runner exists; required commands block.
- `core/runtime-rs/src/mcp.rs` adds MCP config, stdio clients, both existing
  framing modes, discovery, permission-aware dynamic tools, safe output and a
  composite tool runtime. The Android host loads global/project MCP configs and
  shares the same MCP runtime with Agent tools and MCP Hooks.
- Current verification: runtime 18/18, Tauri host 5/5, mobile 115/115,
  typecheck and production build pass. `tauri android build --apk --debug`
  compiled aarch64, armv7, i686 and x86_64 and emitted
  `core/mobile/src-tauri/gen/android/app/build/outputs/apk/universal/debug/app-universal-debug.apk`.
  `adb devices -l` reported no connected device, so no new launch/upgrade run
  was possible.
- Goal `01a0bad2-6dfd-79b3-b832-3403fcf1e1a1` stays active. Next code package:
  shared subagents, then compaction and memory/Dreaming. Website APK must remain
  unchanged until the full migration and physical-device gate pass.

## Shared Rust Sub Agent + compaction + Dreaming continuation (2026-09-22)

- Goal `01a0bad2-6dfd-79b3-b832-3403fcf1e1a1` remains active. Black-screen
  repair is in place, but the full P0-P8 migration and real-device upgrade gate
  are not complete; do not replace the website APK.
- Added `core/runtime-rs/src/sub_agent.rs`: strict create/close/message tools,
  reusable asynchronous children, `consider`/`execute`, model/reasoning
  validation, independent history, durable parent/child mail, late guidance,
  child approval continuation, parent messages, and recursive delegation
  blocking. Android supplies a SQLite store and a process-level `SubAgentHub`.
- Android turn payloads now include every configured model with its provider
  key. Parent tools are Project + MCP + Sub Agent; child tools are Project +
  MCP + parent message. `sub_agent.list`, `sub_agent.snapshot`, and
  `sub_agent.approval.respond` route to Rust. Global/project Sub Agent guide,
  role settings, and delegation strategy are persisted; `forbidden` removes
  delegation tools.
- Added `core/runtime-rs/src/compaction.rs`. Automatic compaction uses the
  active context window, 80% trigger, 60% target, model-backed segmented
  summaries with deterministic fallback, the configured retained-step count,
  and a bounded recent-user section. Final Rust runtime history is persisted in
  native session metadata and reused next turn instead of being reconstructed
  from UI strings.
- Added `core/runtime-rs/src/memory.rs` and Android SQLite dreaming checkpoints.
  Existing `core.dreaming` settings drive best-effort consolidation after a
  worthy turn; existing `MEMORY.md` content is preserved verbatim and new
  durable bullets are appended. Failure does not fail the main turn.
- Verification: runtime 23/23; mobile host 7/7; mobile Vitest 22 files / 117
  tests; mobile typecheck passed; production Vite build passed; aarch64 Tauri
  Android debug APK rebuilt successfully at
  `core/mobile/src-tauri/gen/android/app/build/outputs/apk/universal/debug/app-universal-debug.apk`.
- Exact next implementation package: replace the mobile Study stubs with the
  shared Rust Study store/tools/RPC, then migrate Workflow, desktop host and
  CLI; after that run the physical-device upgrade/data/key matrix and the full
  cross-platform release gate.

## Shared Rust Study backend for the native host (2026-09-22)

- Goal `01a0bad2-6dfd-79b3-b832-3403fcf1e1a1` stays **active**. The website APK
  remains the earlier Capacitor build; nothing was published or replaced.
- Added `core/runtime-rs/src/study.rs`, the first shared Study implementation
  outside the bundled Python plugin. It owns the scoped knowledge graph over
  SQLite (`study_records`, `study_scope_meta`, `study_receipts`,
  `study_outbox`, `study_session_bindings`, `study_pins`,
  `study_course_removals`) with the existing Python contract:
  - `read` for the overview / course / module / node layers, including the
    32 KiB response cap, revision-bound HMAC cursors, `CURSOR_REQUIRED` for
    deep offsets, and `STALE_CURSOR` / `INVALID_CURSOR` failures.
  - `build` for 1–100 create/update/delete/remove/restore/merge operations at a
    matching structure revision, with the same validation set (name,
    description, node-content and per-course-note limits; module-cycle
    rejection; node type/course/orphan rules; duplicate-node detection;
    relation direction normalization; `prerequisite`/`contains`/`advances`
    acyclicity; `passed`/`mastery` refused with "use sign"), plus `request_id`
    receipts and `study.graph.changed` outbox events.
  - `search` inside the trusted scope only, `pins` projected from host-supplied
    session targets, `layout` / presentation `state`, `outbox`,
    `ensure_binding` / `primary_binding`, `current`, and `integrity`.
  - `marks` with the `SELECTION_PROMPT_VERSION = 3` migration, anchor
    normalization (240-character prefix/suffix, 8000-character quote) and
    identity deduplication, plus `answer` for translate/explain/ask: the local
    lexicon resolves `translate` without a model, everything else calls the
    configured model with the target-first selection prompt.
  - `context` returns the canonical `study-system.md` prompt, embedded with
    `include_str!` from the bundled plugin so the two hosts cannot drift, plus
    a `latest_context` built from host-owned session metadata. Notes sessions
    deliberately ignore the mutable graph selection.
  - `study_tool_definitions` reads the bundled `tools.jsonc` and exposes only
    `get_knowledge_net` and `build_knowledge_net`; `StudyTools` runs them
    against the same store.
- `core/mobile/src-tauri` now owns the native Study boundary: `sunday_study_rpc`
  dispatches every migrated operation into the store at
  `app_data_dir()/state/study.db` under `StudyScope::local_compatibility()`,
  passes the active provider for `study.text`, and exposes the Study tools to
  the agent loop only when the transport marks the session as Study.
  `study.exam`, `study.sign` and `study.notes` fail loudly instead of returning
  empty success data.
- The mobile standalone stubs are gone: `StandaloneTransport` delegates every
  `study.*` call to the runtime and keeps only session creation
  (`study.session`) and the selected-node teaching position (`study.current`)
  host-side, because this transport owns the session store. It supplies
  host-owned session metadata and pin targets across the boundary, and builds
  the Study mode context from the shared prompt plus latest context instead of
  a hand-written string. Study failures reject with the structured
  `error`/`reason` payload the shared UI already reads.
- Verification: `core/runtime-rs` 23 lib tests + 11 Study integration tests;
  Tauri host 9 tests; mobile 23 files / 125 tests; mobile `vue-tsc` typecheck,
  Vite production build, `cargo fmt --check` for both crates, and
  `git diff --check` all pass.
- Still Python-only, and not claimed as migrated: the Note vault/Raw/Resource
  graph (`study.notes` and note pins), exams and evidence-checked `sign`, and
  the `study.text.cancel` streaming path.
- Next implementation packages in the migration order: Study notes and exams,
  then the Workflow backend, then the desktop host/CLI Rust replacement and the
  cross-platform release gate.

## Compaction equivalence fix and Dreaming divergence finding (2026-09-22)

- Goal `01a0bad2-6dfd-79b3-b832-3403fcf1e1a1` stays **active**.
- Context compaction in `core/runtime-rs/src/compaction.rs` now matches the
  shared Python policy in `context_compaction_budget.py` and `tokens.py`:
  - The token estimator is no longer a byte-length heuristic. It categorises
    characters the same way `estimate_text_tokens` does (ASCII / 3.5,
    CJK / 1.5, emoji × 2, other / 2) and charges the documented per-message
    overhead (200 exact, 100 fast) plus 50 tokens per tool call. The previous
    `bytes / 4` estimate undercounted ASCII text by roughly 12 % and charged
    almost no per-message overhead, so the native host compacted later than the
    Python host for the same conversation.
  - The trigger decision uses `measure_for_compaction_trigger` semantics: the
    fast estimate is trusted only while `fast × 8 < trigger`, otherwise the
    exact estimator runs. This is the guard the Python comment added because
    Unicode-heavy text can be substantially undercounted.
  - An explicit `compact_trigger_tokens`/`compact_limit_tokens` of `0` is
    treated as unset and falls back to the shared 80 % / 60 % ratios, matching
    Python's `X or default`.
  - `align_tail_start` documents and enforces the retention invariant that the
    retained tail never begins on a tool result, so a request can never carry a
    tool result whose assistant tool call was summarized away. Python needs the
    same guard in its history trim (`while history[cut].role == "tool"`); in
    Rust the split is always anchored on a user message, so this is a defended
    invariant rather than a live defect.
  - Tests: `token_estimation_follows_the_shared_unicode_policy`,
    `an_explicit_zero_budget_keeps_the_shared_ratio_policy`, and
    `compaction_never_orphans_a_tool_result`. Runtime is now 26 lib tests.
- **Verified defect, not yet fixed — Dreaming is not equivalent.** Rust
  `core/runtime-rs/src/memory.rs` writes `MEMORY.md` in a different format than
  the Python implementation in `mem/memory_file.py`:
  - Python owns a structured, sectioned document: the fixed `# Memory` header,
    the five sections `Preferences` / `Facts` / `Decisions` / `Todo` /
    `Deprecated`, `- [YYYY-MM-DD] content — source: <id>` entry lines with
    human-authored entries (no `source`) preserved forever, in-place update of
    an existing `(source, section)` pair, and a 20 000-character budget that
    trims machine entries before human ones.
  - Rust appends every extracted fact under an unprefixed `## Dreaming update`
    heading with plain `- ` bullets, uses a different header line, and guards a
    262 144-character limit instead of 20 000.
  - Consequences, in order of severity: (1) `MEMORY.md` grown by the native
    host exceeds `MAX_MEMORY_MD_CHARS = 20000` and
    `ProjectContextLoader`'s per-file read cap, so memory silently stops
    reaching the system prompt while dreaming keeps appending; (2) Python never
    parses Rust's `## Dreaming update` bullets as structured entries, so they
    are carried verbatim, can never be de-duplicated or suppressed, and the
    section grows without bound; (3) Rust's `existing_memory.contains(update)`
    is a substring check rather than Python's per-`(source, section)` update.
    Python preserves unknown lines verbatim, so this is not data loss — it is a
    format split plus silent truncation of the loaded memory.
  - Required fix: port `mem/memory_file.py` (parse / render / append-new-entries
    / section-tail / budget trim / merge / suppress) into the shared runtime and
    have `dream_with_model` return structured entries that the host merges with
    those semantics. Nothing was claimed as migrated here; the file-format split
    is recorded so the next Dreaming package fixes it rather than adding another
    strategy.
- Verification after this pass: `core/runtime-rs` 26 lib tests + 11 Study
  integration tests, Tauri host 9 tests, mobile 23 files / 125 tests, mobile
  `vue-tsc` typecheck, Vite production build, `cargo fmt --check` for both
  crates, and `git diff --check` all pass. No APK was rebuilt and the website
  APK is unchanged.

## Shared Rust Study exams and assessment signing (2026-09-22)

- Goal `01a0bad2-6dfd-79b3-b832-3403fcf1e1a1` stays **active**. No version was
  published; the website APK is unchanged.
- Added `core/runtime-rs/src/study_exams.rs` (declared from `study.rs` as
  `mod exams`) porting the bundled plugin's `exams.py` and the `sign` path from
  `store.py`:
  - `study.exam` with `create` / `list` / `get` / `reference` /
    `save_answers` / `submit` / `help` and the versioned `grade` / `review`
    pair.  Public reads allowlist learner-safe fields, so the private
    answer/rubric never leaks through an ordinary exam response, and `help` is
    only projected for the requested question.
  - Validation matches the reference: question type/prompt/node ownership,
    positive bounded scores, choice options, private grading-step limits,
    per-question results covering every question exactly once, assessed and
    incorrect node ownership, and `uncertain` results carrying no evidence.
  - Scores stay authoritative: a coarse or stale `state` is normalized from the
    score instead of rejecting a semantically valid model grade, and helped
    questions are excluded from independent mastery evidence.
  - Grading versions increment only on a real change; an exact retry or a
    repeat of the last `grading_hash` returns the stored document without a new
    version, `grading_history` keeps the previous grade, and
    `request_id` receipts reject a conflicting retry.
  - Auto-derived suggestions reproduce the reference thresholds (pass at 0.6,
    `medium` at 0.8 with two or more unhelped questions, `high` only at 1.0 with
    a prior pass on a different exam) and quote the supporting question ids.
  - `study.sign` requires a graded exam, the current `grading_version` and exact
    supporting `question_ids`; it rejects caller-supplied evidence fields,
    matches the graded suggestion (including mastery and reason), refuses
    helped, uncertain or malformed question evidence, resolves merge aliases,
    writes `assessment` records with retained history, bumps the node's
    `state_revision`, emits a `study.mastery.changed` outbox event and stores a
    `study_sign_receipts` row so retries replay the original result.
- Host wiring: `sunday_study_rpc` now routes `study.exam` and `study.sign`, and
  the Study tool list exposes `sign` and `exam` from the plugin's own
  `tools.jsonc`.  `study.notes` remains the only Study operation that fails
  loudly because the Note vault is still Python-only.
- Tests: `core/runtime-rs/tests/study_exam.rs` adds 8 contract tests covering
  public/private separation, creation guards, grading guards, derived mastery
  and idempotency, state normalization with helped questions, evidence-checked
  signing, and unknown-id rejection.  The Tauri host adds an end-to-end
  create → submit → grade → sign round trip through `dispatch_study`.
- Verification: runtime 26 lib + 11 Study + 8 exam tests; Tauri host 10 tests;
  mobile 23 files / 125 tests; mobile `vue-tsc`, Vite production build, both
  `cargo fmt --check` runs and `git diff --check` all pass.
- Still Python-only and not claimed as migrated: the Study Note vault
  (`study.notes`, note pins and the Raw/Resource layers), the Workflow backend
  (20,843 Python lines across 27 modules), and the desktop host/CLI Rust
  replacement (the Python application is 102,722 lines).  Those are multi-session
  packages, not single-session ones.

## Study Note vault disabled on the mobile host via a capability declaration (2026-09-22)

- Goal `01a0bad2-6dfd-79b3-b832-3403fcf1e1a1` stays **active**. The Rust Study
  migration does not include the Note vault yet, so the mobile host previously
  offered a "笔记" entry that could only fail. That entry is now gone instead of
  being reachable-but-broken.
- The gate is a general host capability declaration rather than a mobile special
  case, because the Note vault is a host capability and not a UI preference:
  - `PluginUIEntry.capabilities?: string[]` (`core/ui/src/plugins/types.ts`)
    declares what a mode can serve. Absence means the host makes no claim and
    every surface stays available; an empty list claims the host supports none.
  - `PluginModeHost` publishes the active mode's declaration through
    `CorePluginModeContext.modeCapabilities`.
  - `StudyView` derives `notesEnabled` from it, refuses `navigate('notes')` when
    the capability is absent, and passes the flag to the sidebar host.
  - `StudySidebar` hides the 笔记 entry when the host has no vault, while 图谱,
    搜索 and 管理你的知识 stay available.
- Desktop keeps the vault: `study/plugin.json` now declares
  `"capabilities": ["notes"]`, and the Python manifest parser, model and
  `plugin.ui.list` serializer pass the declaration through. Undeclared modes
  (for example `workflow`) omit the field so the UI keeps their surfaces.
- Mobile declares `capabilities: []` for Study in
  `StandaloneExtensionsStore.plugin.ui.list`, and `study.notes` still fails
  loudly at the RPC boundary as a second line of defence.
- Tests: Python covers optional parsing, empty-versus-absent separation, invalid
  declarations being skipped at discovery, and the declaration surviving the
  `plugin.ui.list` boundary; the shared UI covers the hidden entry plus the
  guarded navigation and capability read; mobile asserts the declared empty
  capability.
- Verification: `core/ui` 96 files / 778 tests and its typecheck, `core/mobile`
  23 files / 125 tests plus typecheck and production build, Python plugin tests
  139 passed plus 16 registry tests, and the desktop frontend build all pass.
  The running Tauri dev instance stayed healthy and reloaded both sides.

## Mobile runtime acceptance on the Android emulator (2026-09-22)

- Goal `01a0bad2-6dfd-79b3-b832-3403fcf1e1a1` stays **active**. This pass closes
  the gap that matters most: the Rust Study migration had only ever been
  compiled and unit-tested on the host target, never built for Android and never
  run on a device.
- Android target builds: `npx tauri android build --debug --apk --target
  aarch64 --ci` and the same with `--target x86_64` both succeed. This is the
  first proof that the `rusqlite` `bundled` dependency added to
  `core/runtime-rs` cross-compiles SQLite for Android.
- Runtime evidence on the API 36 x86_64 emulator (`lamtools_api36`), fresh
  install of the x86_64 debug APK:
  - The app launches with no black screen, and logcat contains no CSP,
    `WebAssembly`, `CompileError` or JavaScript error; the first-run onboarding
    renders normally.
  - Creating a project works, and Study mode activates with its own header and
    composer placeholder.
  - The Study navigator shows 搜索 / 管理你的知识 / 图谱 and **no 笔记 entry**,
    which is the capability gate working on a real device: the desktop
    navigator still has 笔记 in the same position.
  - Selecting 图谱 renders the empty-graph state ("0 个节点 0 条关系") instead of
    an error surface, so `study.get` round-tripped through
    `StandaloneTransport` → Tauri command → `StudyStore`.
  - `state/study.db` exists next to the other native state files, and its schema
    is exactly `StudyStore::ensure_schema`: `study_records`,
    `study_scope_meta`, `study_receipts`, `study_sign_receipts`,
    `study_outbox`, `study_session_bindings`, `study_pins`,
    `study_course_removals`, with `study_scope_meta` holding
    `structure_revision` and `state_revision` under the
    `local-userlocal-environmentdefault` compatibility scope key.
- Still **not** verified, and not claimed: a real model turn (no provider
  credential on the device), graph writes from the agent, the exam and signing
  flows end to end on a device, and any physical-device (as opposed to
  emulator) upgrade or data-migration run. The desktop host received only
  startup-level verification (window, backend connection, successful RPCs on
  the Python side), not interactive feature acceptance.
- Screenshots and the pulled database are under `artifacts/mobile-acceptance/`.

## Desktop 0.3.7-beta.1 build and installer fix (2026-09-23)

- Goal `01a0bad2-6dfd-79b3-b832-3403fcf1e1a1` stays **active**. Nothing was
  published, tagged, or pushed; the website APK and GitHub Releases are
  untouched.
- Version raised to `0.3.7-beta.1` in all five locations (tauri.conf.json,
  Cargo.toml, desktop package.json, pyproject.toml, `__init__.py`). The beta
  suffix is deliberate and safe in an unusual way:
  - `scripts/bump-version.ps1` and the `release.yml` tag guard both require a
    bare `x.y.z`, so `v0.3.7-beta.1` can never be published by the release
    workflow. A beta cannot be mistaken for a release.
  - `scripts/package.ps1` and `installer/build-installer.ps1` accept the
    suffixed form, so the local installer keeps the beta identity in its
    filename and in `AppVersion`.
  - `update.check` tolerates the suffix by design (`compare_versions` only
    reads dotted numeric segments), so a beta build never fails its update
    check.
  - Known limitation, pre-existing and not introduced here: because
    `compare_versions` ignores pre-release ordering, a `0.3.7-beta.1` install
    compares as newer than a future stable `0.3.7`, so it would not be offered
    that upgrade. Betas are for local acceptance, not distribution, so this was
    left alone rather than changing release semantics.
- Fixed the installer so a beta version can actually compile: Inno Setup's
  `VersionInfoVersion` is a numeric file version and rejected `0.3.7-beta.1`
  ("Value of [Setup] section directive VersionInfoVersion is invalid"), which
  aborted the installer at the last step. `Sunday.iss` now takes a separate
  numeric `VersionInfoVersion` define, and `build-installer.ps1` derives it by
  stripping the pre-release suffix and exports it in its result object
  (`version_info`). Display version and Windows file version are therefore
  independent, and a stable build's file version is unchanged.
- Acceptance (project skill `lamtools-setup-install`, Inno
  `/VERYSILENT /NORESTART /DIR=`): installed to `E:\setuptest\0.3.7-beta.1`
  and verified `app_file_version = 0.3.7-beta.1` with the main process and the
  packaged `lamcore-backend\LamCore.exe` both running from that directory.
  Installer: `core/desktop/src-tauri/target/release/bundle/inno/Sunday_0.3.7-beta.1_x64-setup.exe`,
  93,997,103 bytes, SHA256
  `de1549a7bf5f1f625febbc24314999a04020186498755a56ef49fc0259d2bf80`.
  The first acceptance attempt failed because a running `tauri dev` instance
  held the single-instance lock and the installed app handed off and exited;
  closing the dev instance made the verification pass. This is a test-environment
  conflict, not a product defect.
- Verification boundary: `package.ps1` steps 1-3 (frontend, PyInstaller backend,
  Tauri release executable) succeeded in the run that failed at step 4, and the
  repaired step 4 then succeeded on its own against that staged payload. A
  single end-to-end `package.ps1` run of the repaired script has not been done,
  so the full chain is not yet proven in one pass. `release.yml` runs the same
  path in CI.
- Mobile artifact for the same acceptance round:
  `release/mobile/Sunday-mobile_0.1.2-debug-aarch64.apk`, 203,208,324 bytes,
  SHA256 `9c1ddd87fd324c73d0f9009eb78ae58669324fa27fc23efbc819e6131a00d643`,
  arm64-v8a only, debug-signed (installable, not publishable).

## Fixed: structuredClone rejected reactive state in the mobile stores (2026-09-23)

- Reported error: `Failed to execute 'structuredClone' on 'Window': #<Object>
  could not be cloned.` The desktop chain is not the source: `core/desktop/src`,
  `core/ui/src`, `core/desktop/node_modules/@tauri-apps` and
  `core/mobile/node_modules/@tauri-apps` contain no `structuredClone` call, so
  every call site lives in the mobile standalone stores.
- Root cause, reproduced in a test (`structuredClone` on a `reactive(...)`
  object throws): the stores let Vue reactive proxies into persisted state and
  then cloned that state on read.
  - `StandaloneConfigStore` `settings.update` shallow-merged the caller's
    object (`{ ...existing, ...value }`) and `config.subagent.settings.set`
    assigned `current[key] = value`, so a reactive value written from a settings
    panel stayed in `state` as a proxy.
  - `settings.get` additionally returned `state.settings[namespace]` **by
    reference**, so the UI could mutate stored state and a reactive copy of it
    could leak back in from the other direction.
  - The reads in `settings()`, `normalizedSubAgentSettings()` and
    `StandaloneExtensionsStore.runtimeHooks()` then called
    `structuredClone(state...)` and threw.
  - `LocalRepository` had already been hardened for exactly this shape (its
    private `clone` catches and falls back to JSON), but that hardening was
    never shared with the other two stores — the same defect was fixed in one
    place and missed in three.
- Fix: one shared `cloneState` helper (`core/mobile/src/storage/cloneState.ts`)
  that prefers `structuredClone` and falls back to a JSON round-trip, now used
  by every call site. Writes are isolated (`settings.update`,
  `config.subagent.settings.set` clone before storing), reads are guarded
  (`settings()`, `normalizedSubAgentSettings()`, `runtimeHooks()`), and
  `settings.get` returns a copy instead of its internal object.
  `LocalRepository` reuses the same helper so the fallback has one home.
- Tests: `core/mobile/tests/clone-state.test.ts` asserts that
  `structuredClone` rejects a reactive proxy while `cloneState` accepts it, and
  covers the real paths — a reactive `settings.update` value read back through
  `settings()` and `settings.get`, a reactive Sub Agent role assignment read
  back through `subAgentRuntime()`, and the hook/MCP config read. Mobile is now
  24 files / 130 tests, plus typecheck and production build.
- Not covered: the desktop packages were not rebuilt for this change, because
  the fix is mobile-only and the desktop chain never calls `structuredClone`.
  The previously delivered mobile APK predates the fix and was rebuilt.

- Packaging note found while refreshing the mobile artifact: a debug APK came
  out at 399 MB with ~188 MB of unused gaps between zip entries (content was
  correct and `testzip` passed, but the file was nearly twice the necessary
  size). The cause is Gradle incremental packaging: it reuses the previous
  APK's entry layout, so after an x86_64 build the arm64 `lib/arm64-v8a/` entry
  is rewritten at the old ~203 MB offset and the space before it is left empty.
  Deleting `app/build/outputs/apk` (and keeping `jniLibs` free of stale ABIs)
  before rebuilding yields a compact 203 MB arm64-v8a APK. `scripts/package-mobile.ps1`
  already performs the ABI cleanup for release packaging; the outputs directory
  must be cleared for local debug rebuilds.

## Mobile: model requests had no timeout, so a stalled turn never returned (2026-09-23)

- Reported symptom: in Agent mode a message produced no reply and no error, the
  turn stayed running with the elapsed time counting up, and the composer kept
  showing the stop action. A previous turn had surfaced the `structuredClone`
  error (fixed separately).
- Root cause, located at `core/runtime-rs/src/provider.rs`: the HTTP client was
  built with headers only —
  `reqwest::Client::builder().default_headers(headers).build()` — with no
  `.timeout()` and no `.connect_timeout()`. reqwest applies no request timeout by
  default, so when the target address never answers (DNS black hole, stalled TLS
  handshake, server that accepts but never responds) the `send()` future never
  resolves. The turn then holds neither a result nor an error, which is exactly
  the observed shape: UI running, elapsed time growing, no output.
- The Python host does bound this: `config/retry_store.py` defines
  `DEFAULT_MODEL_RETRY_CONFIG` with `model_timeout_seconds: 360`,
  `model_retries: 10`, `retry_delays_seconds: [1, 1, 2, 5, 5]`, `jitter: true`
  and `empty_response_retries: 3`. None of that had been ported to the Rust
  provider.
- Fix, aligned to those defaults rather than inventing a policy: added a
  `RetryPolicy` (attempts 10, timeout 360 s, delays 1/1/2/5/5 with the tail
  repeating, clock-seeded 0.5x–1.5x jitter) and `HttpModelBackend::with_retry_policy`;
  the client now sets `.timeout(policy.timeout)`, and `complete` sends through
  `send_with_retry`, which retries transport failures, timeouts, 5xx and 429
  within the attempt budget and returns a real error otherwise. A 4xx stays
  fatal because retrying cannot help it.
- Tests in `provider.rs`: the wait rhythm matches the shared baseline, jitter
  stays inside 0.5x–1.5x, and — the one that matters — a provider that accepts a
  connection and never answers now fails inside the bound instead of hanging
  (a local listener that reads the request and stays silent; the call returns an
  error in ~1 s with a 1 s timeout where it previously never returned at all).
- Not yet ported, recorded rather than implied: `empty_response_retries`
  (re-issuing after an empty completion) and the streaming idle timeout, which
  does not apply while the Rust provider sends `stream: false`.
- The delivered debug APK was rebuilt with the request-timeout fix; later
  mobile trace and layout changes require their own rebuilt artifact before
  device verification.

## Mobile layout and request-trace fixes (2026-09-23)

- The narrow sidebar fix removes the 18px peek constraint while the drawer is
  open. The Android native inset bridge supplies the status-bar top inset, and
  the app retries a temporary zero value. The shared desktop TitleBar is now
  explicitly hidden when `runtime.platform` is mobile, avoiding the fixed
  desktop titlebar overlapping Android status content.
- Verification: mobile layout contract 4/4; mobile suite 154/154; focused UI
  tests 36/36; mobile and shared UI typechecks passed. The in-chat trace begins
  before model lookup and the first message save, avoids intermediate
  persistence, and passed targeted coverage 28/28.
- ARM64 debug-signed APK:
  `core/mobile/artifacts/Sunday-mobile-trace-debug-0.1.2-20260923-debug-signed.apk`
  (216,634,556 bytes; SHA256
  `C2561DE2AF20D07B0186C14299F73ECF8DCF5F29D54A68DCF7468C282D87A41C`;
  signing certificate `a6fed859…a30c`, matching the prior debug signer).
- ARM64 release-signed APK:
  `core/mobile/artifacts/Sunday-mobile-trace-debug-0.1.2-20260923-release-signed.apk`
  (216,634,556 bytes; SHA256
  `220222D066E0F6AAF8C08BBAFB6B1D8C3C756B6829EDE4E3C4C87AB5DFEA0B1D`;
  signing certificate `045567d5…4fb`, matching the prior release signer).
  Both packages are `com.lamtools.mobile`, versionName `0.1.2`, versionCode
  `1002`, ARM64, targetSdk 36. Neither has been phone-tested or visually
  accepted.
- This earlier trace build was superseded by the network-stall follow-up below.
  The Rust refactor remains incomplete.

## Desktop command shell setting (`shell_session_fix_20260923`)

- Closure state: complete. Desktop Python shell selection is configured by `core.commandShell`, available in GUI Settings and `command-shell get/set`. Windows auto-selects WSL → Git Bash → PowerShell; unavailable manual choices fall back safely. Linux retains native command behavior; Android hides the setting.
- Agent and Workflow execution use a shared shell resolver. WSL probing is cached and bounded to 4 seconds; WSL commands receive the working directory through `--cd`, Workflow explicitly forwards required variables with `WSLENV`, and validation quotes paths for the selected shell.
- UI fixes cover duplicate error notice routing; stale terminal replay no longer closes a newer running turn; `final_response` / `has_tool_calls` are projected while interim text stays in process state; send/stop glyphs and composer trail use the composer's themed background and gradient.
- Verification: 5 UI files / 75 tests, 4 Python suites / 111 tests, and `npm run typecheck` passed; `git diff --check` exited 0.
- Limits: real WSL cwd execution could not be verified because WSL hung for >50 seconds; the bounded probe falls back. No Tauri UI or Android device observation was done, per code-only verification. Rust/mobile refactor files were untouched. No commit/tag/push.
- Read-only Git handoff: the working tree remains broadly dirty with unrelated ongoing Rust/mobile refactor changes and uncommitted files. This deployment made no commit, tag, push, cleanup, or edits to those Rust/mobile refactor files; preserve the existing user work.

## Rust runtime and mobile Tauri migration — paused (rust_refactor_20260923; 2026-09-23)

- The full Rust refactor remains incomplete. Rust internal Study, model, and
  Workflow runners are partial; do not describe them as a complete replacement
  for Python. The mobile app has a Tauri host, Stop handling, and snapshot-based
  recovery.
- Mobile sidebar/inset fixes and the mobile TitleBar visibility correction are
  present. The ARM64 trace APKs described in this historical checkpoint were
  superseded by the network-stall variants documented below; those latest
  variants have not been phone-tested.
- Operational observation from the user: the provider console showed no
  request, and restarting the app preserved the running turn. This leaves the
  stalled-turn investigation open and does not establish a successful model
  request.
- Python suite status: the latest full run passed 2260 tests with 2 skipped in
  347.68 seconds, after fixing a transient Windows atomic-replace issue in
  `MEMORY.md` handling. Mobile suite passed 154/154; focused UI tests passed
  36/36, and mobile/shared UI typechecks passed.
- Scoped verification: the Rust full suite passed 111 tests; mobile passed
  154/154, focused UI 36/36, mobile and shared UI typechecks passed, mobile
  layout contract passed 4/4, and targeted trace tests passed 28/28. Both
  rebuilt ARM64 APK variants are documented above; neither has been phone-tested.
  These checks do not establish phone visual acceptance or completion of the
  Rust migration.
- This checkpoint is superseded by the follow-up below: the phone trace is now
  available, and closure is paused awaiting a test of the refreshed APK. The
  working tree remains broadly dirty across desktop, Python, shared UI, mobile,
  and Rust runtime; preserve in-progress code and user changes. This
  documentation handoff made no code changes, commit, or cleanup.

## Mobile HTTP send stall follow-up (mobile_http_send_stall_20260923; 2026-09-23)

- Phone trace evidence: at 12:04:14 the turn reached `http_send_start`; by about
  12:11 it had emitted neither response headers nor an error stage. The provider
  console had no matching request. This places the stall at or before response
  headers, but does not identify whether DNS, TCP connect, TLS, routing, or
  another transport condition caused it.
- Rust provider now caps connection establishment at 15 seconds, shows a fixed
  waiting stage after 30 seconds, applies a 120-second deadline before response
  headers, and permits at most two pre-header attempts. The existing 360-second
  response-body timeout and retry behavior for 5xx responses remain. JavaScript
  trace stage labels are fixed for this path.
- Verification: `core/runtime-rs` cargo tests passed; mobile suite 154/154 and
  mobile typecheck passed. Two ARM64 APK variants were rebuilt, versionCode
  1002, versionName 0.1.2, targetSdk 36; their signing certificates match the
  corresponding previous debug/release variants. Neither new APK has been
  phone-tested.
- Debug-signed APK:
  `core/mobile/artifacts/Sunday-mobile-trace-network-0.1.2-20260923-debug-signed.apk`
  (216,802,308 bytes; SHA256
  `30501B9735ADD0C4E13FA0B3CDBBA041DC11C3E1264F2B0C5DC81DEC4F415405`).
- Release-signed APK:
  `core/mobile/artifacts/Sunday-mobile-trace-network-0.1.2-20260923-release-signed.apk`
  (216,802,308 bytes; SHA256
  `01D59CFA6A8F050693726A2A0617247013EE4219CA4BE6508D937E91B7E304FE`).
- This checkpoint is superseded by the isolated-send follow-up below. The
  12:47 trace exercised the request-build APK; the new isolated-send APK pair
  remains untested on the user's phone.

## Mobile request-build trace follow-up (mobile_http_send_stall_20260923_closure; 2026-09-23)

- The earlier 12:04 phone trace came from the older APK built at 11:24. It
  reached `http_send_start` without headers or an error by about 12:11, but it
  predates the latest request-build instrumentation and cannot verify that
  build. The screenshot's model label matches the Command Code preset; the
  actual provider configured on the phone is still unknown, so confirmation was
  requested. The phone-side network root cause remains unproven.
- Rust now builds the HTTP request before emitting the fixed
  `http_request_built` stage; build failures emit `http_request_build_error`.
  The bounded pre-header wait/retry is retained, and JavaScript maps both stages
  to fixed labels. Connection establishment is capped at 15 seconds, a fixed
  waiting stage appears after 30 seconds, the pre-header deadline is 120 seconds,
  and there are at most two pre-header attempts. The existing 360-second
  response-body timeout and 5xx retry policy remain.
- Verification: runtime Rust test groups passed 64 + 11 + 8 + 2 + 11 + 9 + 9;
  16 focused provider tests passed; mobile passed 154/154 and its typecheck
  passed. Both ARM64 APKs are version 0.1.2 / versionCode 1002 / targetSdk 36;
  the packaging script verified that their signatures match the corresponding
  previous debug and release signing identities. Neither new package has been
  tested on the user's phone.
- Release-signed APK:
  `core/mobile/artifacts/Sunday-mobile-trace-request-0.1.2-20260923-release-signed.apk`
  SHA256 `A9C8BEA0AF8095FA70B0CF4555093D7F55ECDCD59B7498F767187CCE14BF95D7`.
- Debug-signed APK:
  `core/mobile/artifacts/Sunday-mobile-trace-request-0.1.2-20260923-debug-signed.apk`
  SHA256 `E8A614FAEECAFCD12094EAF66F64DC01092DF5BEB3EB2B72C28AB9A9B70BC191`.
- This request-build checkpoint is superseded by the isolated-send follow-up
  below. The Rust refactor remains incomplete.

## Mobile HTTP stall second-trace handoff (mobile_http_send_stall_20260923_second_trace_handoff; 2026-09-23)

- New phone evidence: the request reached `http_request_built` at 12:47:08, then
  showed no native 30-second marker for more than two minutes. The phone showed
  Command Code selected. This still does not establish why the native request
  task is not progressing.
- Desktop control probe succeeded in about 25 seconds with one step and a final
  reply using `run-local --model-id deepseek/deepseek-v4.1-flash --no-thinking
  --max-tokens 128 你好` against `https://api.commandcode.ai/provider/v1`.
  This validates the desktop Python path only; it does not verify the Android
  request path or actual phone provider configuration.
- Rust now spawns the reqwest send task before publishing the built stage, with
  abort-on-drop and independent watchdogs. The JavaScript trace emits host-side
  wait markers at 35 and 125 seconds while the native invoke remains pending.
  `core/runtime-rs/Cargo.toml` enables Tokio macros as a normal dependency and
  multi-thread runtime support for dev tests. A standalone production check had
  previously failed without the macros feature; this was a feature-gating issue,
  not an Android runtime result.
- Verification: full Rust tests passed (67 unit tests and all integration
  suites); `cargo check --lib` passed; mobile passed 156/156 and typecheck passed.
- New ARM64, version 0.1.2, versionCode 1002, targetSdk 36 packages were signed
  and checked against the previous signing identities. The isolated request
  variants below have not yet been tested on the phone.
- Release-signed APK:
  `core/mobile/artifacts/Sunday-mobile-trace-isolated-0.1.2-20260923-release-signed.apk`
  SHA256 `D1FF09A435806655568D6AD043018A57448BBE71D5E6A456D8467698702A2FC6`.
- Debug-signed APK:
  `core/mobile/artifacts/Sunday-mobile-trace-isolated-0.1.2-20260923-debug-signed.apk`
  SHA256 `7E64BD32D4A3FFEA1D2E1AB914401D5258D9826012D067BFB296B315F324BB33`.
- State: paused pending a phone test of these isolated-send APKs and its new
  trace. Root cause remains unproven; broader Rust Workflow/refactor work is
  incomplete. The working tree is dirty; preserve unrelated changes. This is a
  read-only handoff with no commit or cleanup.

## Android TLS verifier follow-up (mobile_android_tls_fix_20260923; 2026-09-23)

- Closure state: paused pending the user's live-phone model request. The phone
  trace at 13:43:42 reached `http_request_built`, then reported
  `provider send task failed`; the provider console had no matching request.
- Android reqwest 0.13.5 uses rustls with `rustls-platform-verifier` 0.7. The
  missing Android JNI/Kotlin initialization was found and addressed: the
  mobile Tauri crate adds the Android JNI and verifier dependencies, initializes
  the verifier through Rust JNI, and `MainActivity` performs setup before Tauri.
  Gradle bundles the 0.1.1 Maven AAR and ProGuard keeps required classes. This
  is a probable root cause; the phone has not yet confirmed successful HTTPS.
- `core/runtime-rs/src/provider.rs` now distinguishes panicked from cancelled
  send tasks. Verification passed: full runtime Rust suite (119 tests), mobile
  suite 156/156 across 27 files, mobile Vue typecheck,
  `cargo fmt --all -- --check` for `core/runtime-rs` and
  `core/mobile/src-tauri`, Android `cargo check`, Gradle Kotlin compile, ARM64
  APK build, and independent source/APK review. APK inspection found verifier
  and JNI classes. Emulator install failed with `Can't find service: package`,
  so device HTTPS remains unverified.
- Diagnostic APK:
  `core/mobile/artifacts/Sunday-mobile-tls-fix-diagnostic-0.1.2-20260923-release-signed.apk`
  (218,850,516 bytes; SHA256
  `327DE6D3D0B11CBFC7EBFEC7112D68AAAAD62509C17BB7239F05BFC98E92C58A`;
  certificate SHA256 `045567d59580c97311203453e104938ad09d9f79e1e78e028f607cdbc4ecb4fb`;
  version 0.1.2, code 1002, targetSdk 36, arm64).
- Published diagnostic URL:
  `https://47.114.43.99.nip.io/downloads/Sunday-mobile-diagnostic-tls-0.1.2-20260923.apk`.
  HEAD and complete GET returned status 200; GET returned 218,850,516 bytes and
  its SHA256
  `327de6d3d0b11cbfc7ebfec7112d68aaaad62509c17bb7239f05bfc98e92c58a` matched
  the local APK. The existing `latest` artifact was not modified.
- Temporary SSH key material was deleted locally. The authorized-key append and
  staging directory were cleaned up; final server verification found zero key
  matches, no staging directory, and a matching published APK hash. The dirty
  working tree contains broad unrelated and in-progress changes; preserve them.
  No commit or cleanup was performed. Full Rust refactor remains incomplete.

## Mobile root project listing and animated long-run progress (2026-09-23)

- `root.list_files` accepts an empty path and returns `project_root`, so the
  project file browser can list from its root. Android projects are stored in
  `app_data_dir()/projects/<project ID>`. This app-private directory is usually
  not visible in the Android system file manager.
- Long-running chat execution logs are represented by an animated phase
  progress bar. After terminal success or failure, it hides after about 1.5
  seconds. Answer and error bodies remain distinct; execution logs are not
  appended to either body.
- Verification passed: Rust 119 tests; mobile 156 tests across 27 files; UI 793
  tests; mobile Vue typecheck; Android `cargo check`; Gradle Kotlin compilation;
  ARM64 build and signing; design scan 87 files / 0 deviations.
- Published signed diagnostic APK:
  [Sunday-mobile-progress-root-0.1.2-20260923.apk](https://47.114.43.99.nip.io/downloads/Sunday-mobile-progress-root-0.1.2-20260923.apk)
  (218,855,436 bytes; SHA256
  `7A845855B1830C80D4EE3D7FB599BAEF5585B3DFD007F63ED494384B9D5942BB`).
- No real-device verification is claimed. Earlier phone traces established a
  send-task failure after request construction; this artifact is available for
  renewed live-device HTTPS testing. The full Rust refactor remains incomplete.

## Mobile streaming repair and website APK switch (mobile_streaming_audit_20260923; 2026-09-23)

- Closure state: complete for the scoped Command Code/DeepSeek OpenAI Chat SSE
  repair and website download switch. The broader Rust refactor remains
  incomplete, and no real-phone behavior is claimed.
- Rust OpenAI Chat SSE now streams UTF-8 text and reasoning and indexed tool
  calls. Native deltas batch at 32 ms and JavaScript updates at 50 ms. Retry,
  reset, final-response authority, internal compaction/dreaming gates, and fixed
  release-stage handling are covered. Frontend terminal cleanup removes
  temporary reasoning state. Anthropic, OpenAI Responses, and Gemini currently
  remain final-only.
- Verification passed: runtime suite 122; mobile 158 tests / 27 files; shared
  UI 793 tests / 98 files; typecheck; mobile Vite production build; design scan
  87 files / 0 deviations; Android signed universal APK for ARM64 and ARMv7,
  including 16 KiB alignment. Artifact version is 0.1.2 / versionCode 1002 and
  its certificate matches the prior diagnostic build.
- Current local release APK:
  `release/mobile/Sunday-mobile_0.1.2.apk` (49,158,412 bytes; SHA256
  `57958F1C739B4B2FC65556D49AD567A80A3CF21DD1C352791D31200609CFB561`). The
  pre-stream local package was archived at
  `release/mobile/archive/Sunday-mobile_0.1.2-pre-stream-20260923.apk`
  (41,785,124 bytes; SHA256
  `0D72E68CEB487CFB676E8B20AD46F21BBE6969F0C3669D30437355A883EF203C`).
- Website source already points to `/downloads/Sunday-mobile-latest.apk`. The
  previous remote APK (31,709,068 bytes; SHA256
  `58E0E54BCD21602A3AD9E4DA186276701CA15929D1943C97B65568C0BE19035A`) was
  archived at
  `https://47.114.43.99.nip.io/downloads/Sunday-mobile-legacy-0.1.2-20260922.apk`.
  New versioned and stable URLs are
  `https://47.114.43.99.nip.io/downloads/Sunday-mobile-stream-0.1.2-20260923.apk`
  and `https://47.114.43.99.nip.io/downloads/Sunday-mobile-latest.apk`;
  both returned HTTP 200 and 49,158,412 bytes, and the complete stable GET
  matched the new local SHA256. Caddy-lamtools and relay were active at final
  verification; no staging file remained.
- Cloud Assistant mutation audit IDs: authorize RequestId
  `01A0CD8D-B2B0-5CA1-944B-DBDE3CCE6238` / `c-hz06xx5e4wuoe80` /
  `t-hz06xx5e4x4nzls`; archive `01A0CD91-F9C1-5E3E-84A3-CEB508170842` /
  `c-hz06xx5t50va800` / `t-hz06xx5t510a0ow`; publish
  `01A0CD92-BD44-5987-95C0-B9098911E2C0` / `c-hz06xx5vtj02ha8` /
  `t-hz06xx5vtjcjz0g`; revoke `01A0CD93-CE83-5A57-B09F-F0598679925E` /
  `c-hz06xx5zkfgnlds` / `t-hz06xx5zkfj5hq8`; final read-only verify
  `01A0CD95-19EC-52B5-B86E-6166DEE40625` / `c-hz06xx643qv5r7k` /
  `t-hz06xx643qxnnk0`. Times UTC: authorization 09:16:52; archive 09:21:32–33;
  publish 09:22:22–24; revoke 09:23:32; final verification 09:24:57–58.
  A harmless preflight queried `caddy.service` and failed at 09:12:47; the
  correct `caddy-lamtools.service` was inspected at 09:13:14 and found active.
- The temporary server SSH key was revoked. Local private/public key files
  remain at
  `C:\Users\ADMINI~1\AppData\Local\Temp\lamtools-mobile-stream-upload-20260923`
  because automatic exec approval rejected `Remove-Item` outside the workspace
  twice; the server no longer authorizes them. No staging file remains.
- Read-only Git handoff: the working tree is broadly dirty across desktop,
  Python, UI, mobile, and Rust migration work. Preserve all existing changes.
  This closure made no commit, tag, push, or cleanup. Broader Rust migration and
  real-phone verification remain open.

## Rust refactor follow-through and diagnostic APK (rust_refactor_followthrough_20260923; 2026-09-23)

- State: paused pending the user's 0.1.3 phone-test error text. At 17:36 the
  user tested the website stable 0.1.2 APK and received
  `provider connection failed before response headers`; root cause remains
  unproven and there is still no live phone HTTPS/stream success.
- Signed universal diagnostic APK:
  `release/mobile/Sunday-mobile_0.1.3.apk` (49,464,744 bytes; SHA256
  `D4FC6A8C759F25F68074784A2B1B692BE8A069ABEC73CC3819B6AEA26E7FF6BE`; version
  0.1.3 / code 1003; ARM64 and ARMv7; 16 KiB aligned; signing certificate
  matches the prior APK). Published URL:
  `https://47.114.43.99.nip.io/downloads/Sunday-mobile-diagnostic-0.1.3-20260923.apk`;
  complete public GET returned 200 and matching byte count/hash. Website latest
  remains 0.1.2 (`57958F1C739B4B2FC65556D49AD567A80A3CF21DD1C352791D31200609CFB561`);
  legacy 0.1.2 archive remains (`58E0E54BCD21602A3AD9E4DA186276701CA15929D1943C97B65568C0BE19035A`).
- Shipped 0.1.3 source includes safe Android connection-error categorization
  and rejects premature OpenAI Chat SSE EOF before `[DONE]` for reset/retry.
  The `finish_reason=length` nonretryable failure and provisional-response
  reset landed after the 0.1.3 build and is not in that APK. Native
  `workflow.run` handles a deterministic built-in-only subset with preflight
  and shaped results; queue, human-task, and host-backed nodes remain unported.
- Verification: complete Rust suite passed before the length-finish fix;
  provider-focused tests passed 29/29 after it; mobile-focused tests passed 34,
  and mobile typecheck/build passed. Earlier 0.1.2 verification included
  mobile 158 tests and UI 793 tests. No new live-phone success is claimed.
- Read-only Git handoff: working tree is broadly dirty; preserve all existing
  changes. Temporary server authorization was revoked, staging removed, and
  final checks found zero matching authorized keys and no staging directory.
  Caddy and relay were active. Rollback is limited to deleting the versioned
  0.1.3 diagnostic artifact; website latest was not changed. No commit or
  cleanup was performed. Broader Rust refactor remains incomplete.
- Aliyun audit (UTC; Cloud Assistant calls carry RequestId / command ID /
  invocation ID): read-only ECS preflight `DescribeInstances`, RequestId
  `01A0CDAC-9200-595B-9807-1CB3489D8D31`; read-only server preflight at
  09:50:54, `01A0CDAC-DB42-5D12-89D9-36CC2623755C` /
  `c-hz06xx8ffp234zk` / `t-hz06xx8ffpc2qdc`; read-only authorized-key inspect
  at 09:51:31, `01A0CDAD-6D4E-5E86-9D1A-512A7B0BC3BE` /
  `c-hz06xx8hfjkyakg` / `t-hz06xx8hfjsfzls`. Temporary SSH authorization
  mutation at 09:51:51: `01A0CDAD-BB6A-5B8F-AB50-FBE230CE04DC` /
  `c-hz06xx8ii2f2ps0` / `t-hz06xx8ii2k2igw` (authorized key; subsequently
  revoked). SCP staged the APK as `/tmp/sunday-mobile-diagnostic-0.1.3-d4fc6a8c.upload`
  (upload mutation; no Aliyun invocation ID). Read-only staged-file hash/size
  check at 09:53:22: `01A0CDAF-1E23-5813-968E-EB0C4ACB1A16` /
  `c-hz06xx8nd0l239c` / `t-hz06xx8nd3rxf5s`. Publish mutation at 09:53:43:
  `01A0CDAF-6AE9-5651-A56E-734FBF80BC49` / `c-hz06xx8oevwncao` /
  `t-hz06xx8oew94u0w`, atomically publishing the versioned APK into the Caddy
  downloads path and removing the staged file. Authorization revoke at
  09:54:02 (exact authorized key only):
  `01A0CDAF-B874-502F-BDED-7D5BDAA63F35` / `c-hz06xx8ph565ngg` /
  `t-hz06xx8ph5in56o`; this invocation confirmed zero matches for that key.
  A separate local read-only public GET returned 200 with matching size/hash.
  Final read-only Cloud Assistant verification at 09:54:28:
  `01A0CDB0-1B52-58EF-A4AE-8E0C75C9EAB9` / `c-hz06xx8qtx3rz7k` /
  `t-hz06xx8qtxb9o8w`: server hashes matched, the staging file was absent, and
  services `caddy-lamtools` and `lamtools-relay` were active. Rollback: remove only the
  versioned 0.1.3 diagnostic download; stable/latest and legacy 0.1.2 paths
  were untouched.

## Sunday SVG system-prompt language experiment (sunday_svg_ab_closure; 2026-09-23)

- Task/deployment/state: `sunday_svg_ab_closure` / `sunday_svg_pelican_prompt_language_20260923` / **complete**.
- Method: one Sunday `run-local` run per language for “直接使用 SVG 画一个动态的鹈鹕骑自行车”. Both used
  `deepseek/deepseek-v4.1-flash`, thinking `max` (极高; budget 16,384), temperature 0.7, the same
  tool/config setup, and separate run-local databases. The Chinese run retained Sunday’s assembled
  system prompt; the control replaced it with an equivalent English prompt.
- Results: Chinese — 49 model steps, 52 tool calls, 13 failed (25.00%), 723.273 s, 4,053,398 reported
  tokens (3,954,320 input / 99,078 output); English — 22 steps, 29 calls, 3 failed (10.34%), 525.865 s,
  2,136,453 reported tokens (2,035,613 input / 100,840 output). The Chinese run had one empty response
  without provider usage, so its true token total cannot be calculated exactly; the reported total sums
  the other 48 requests. Cached input is included within input tokens.
- Artifacts and canonical detail: [report.md](../core/experiments/sunday_pelican_system_prompt_20260923/report.md),
  `core/experiments/sunday_pelican_system_prompt_20260923/runs/zh/outputs/pelican-bike.svg`, and
  `core/experiments/sunday_pelican_system_prompt_20260923/runs/en/outputs/pelican_bike.svg`.
  Both SVGs parsed, had complete internal references, and showed substantial code-driven pixel changes
  between 0 and 0.4 seconds. No human visual evaluation
  was performed. One run per language does not establish a causal language effect.
- Verification/disposition: report and run evidence were read-only checked; no production code changed,
  no commit/tag/push/cleanup was made, and the broadly dirty worktree was preserved. Exact next entry
  point: use the report and saved runs for review; repeat both variants with multiple runs if a causal
  comparison is needed.

## Sunday code-task system-prompt language experiment (sunday_code_dev_bug_ab_20260923; 2026-09-23)

- Task/deployment/state: `sunday_code_dev_bug_ab_closure` / `sunday_code_dev_bug_ab_20260923` / **complete**.
- Method: four `run-local` runs under DeepSeek V4.1 Flash, thinking `max` (极高; budget 16,384),
  temperature 0.7. The crossed conditions were from-scratch development and seeded bug repair, each
  with Sunday’s Chinese system prompt or its equivalent English replacement. The first batch ran
  `dev_zh` + `bug_en`; the second ran `dev_en` + `bug_zh`. Each final file independently passed all
  8 acceptance tests.
- Metrics (input includes cached input; total = input + output):

  | Condition | Steps | Time (s) | Input | Output | Total | Tool calls | Failed | Failure rate |
  | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
  | dev_zh | 8 | 95.212 | 171,457 | 14,396 | 185,853 | 8 | 1 | 12.5% |
  | dev_en | 8 | 78.329 | 140,191 | 10,046 | 150,237 | 8 | 1 | 12.5% |
  | bug_zh | 9 | 74.344 | 145,351 | 5,342 | 150,693 | 8 | 0 | 0% |
  | bug_en | 4 | 32.675 | 53,459 | 3,056 | 56,515 | 4 | 0 | 0% |

- Result: the two development outputs implement the stated order-quote rules and pass 8/8; both
  repairs correct the free-shipping predicate to use the pre-discount subtotal and pass 8/8. The
  negative seed remains 7/8 because only the shipping rule is intentionally wrong. Each development
  run had one rejected `run_command` path that recovered; repair runs had no tool failures.
- Canonical evidence: [REPORT.md](../core/experiments/sunday_code_dev_bug_ab_20260923/REPORT.md),
  `core/experiments/sunday_code_dev_bug_ab_20260923/runs/dev_zh/outputs/order_quote.py`,
  `runs/dev_en/outputs/order_quote.py`, `runs/bug_zh/outputs/order_quote.py`, and
  `runs/bug_en/outputs/order_quote.py`; independent acceptance is
  `core/experiments/sunday_code_dev_bug_ab_20260923/acceptance/test_order_quote.py`.
- Verification/disposition: report, summaries, outputs, and acceptance evidence were read-only
  checked. No production code or experiment artifact was changed; no commit, tag, push, or cleanup
  was made. One run per condition does not establish a causal language effect. Exact next entry point:
  use REPORT.md and the four archived outputs for review; repeat the crossed pairs for a stronger claim.

## Mobile Pad layout, launcher icon, and TLS diagnostic package (mobile_pad_icon_tls_docs_20260923; 2026-09-23)

- Pad layout now restores the pinned sidebar when transitioning from narrow to wide via `useShellLayout`; an open sidebar uses explicit full width. When the top-right float is hidden, its search/settings/mode/account actions return to the sidebar footer.
- Android launcher assets use the canonical dark Sunday smile under `core/mobile/src-tauri/icons/android`; package synchronization precedes the build and an APK pixel check guards against shipping the prior white/old icon.
- The signed universal APK is `release/mobile/Sunday-mobile_0.1.4.apk`, version 0.1.4 / versionCode 1004, 49,762,412 bytes, SHA256 `34FE6447B7AFEDFE0DA92197D075C289023C0A11D111336CCAC8A0E4D71814D1`, ARM64/ARMv7, 16 KiB aligned. Signature, version, alignment, and icon pixel QA passed. Mobile coverage passed 159/159; shared UI coverage passed 794/794.
- User's 0.1.3 phone result for `https://api.commandcode.ai/provider/v1` was `provider TLS certificate verification failed before response headers`. Version 0.1.4 adds finer certificate-failure categories; this is diagnostic detail, not a demonstrated connection fix. No successful phone HTTPS/stream call is established.
- Versioned package URL: `https://47.114.43.99.nip.io/downloads/Sunday-mobile-diagnostic-0.1.4-20260923.apk`. Published through SSH after Cloud Assistant API timeouts. Staged and destination hash/size matched; the exact temporary SSH key was revoked and `authorized_keys` is empty. Full public GET returned 49,762,412 bytes with the matching SHA256. Stable/latest and legacy paths are unchanged; no final Cloud Assistant service-health check is claimed. Website latest stays 0.1.2 and the legacy archive is unchanged.
- Desktop control probe: `py -3.14 -m lamtools_core.cli run-local --model-id deepseek/deepseek-v4.1-flash --no-thinking --max-tokens 128 --raw "你好，只回复你好"` exited 0 through the Command Code model record in one model round with no tools; final reply was `你好` (U+4F60 U+597D), run `a42f44e43942`, session `core-cli-7993f1df`. This confirms the desktop Python path only and does not verify Android connectivity.
- Broader Rust refactor remains incomplete. Preserve the broadly dirty worktree; no commit or cleanup is implied by this handoff.

## Sunday English system-prompt rollout (sunday_system_prompts_english_20260923; 2026-09-23)

- Task/deployment/state: `sunday_system_prompts_english_closure` / `sunday_system_prompts_english_20260923` / **complete**.
- Scope: Sunday-owned preset system prompts were translated to equivalent English across the Python
  main and auxiliary paths, shared Study Python/Rust, subagent defaults, mode/shell fragments, and the
  bundled skill index. User-authored prompts and the current global configuration were explicitly left
  unchanged.
- Compatibility: handoff export accepts the new English metadata prefixes while continuing to accept
  legacy Chinese prefixes, preserving export interoperability during the transition.
- Verification was code-only and focused: independent English prompt tests 9 passed; subagent/export
  72 passed; skill tests 12 passed; config defaults plus English prompt 10 passed; Study Python 48 and
  Study Rust 11 passed; auxiliary Python 146 passed; `git diff --check` passed. No broad full-suite or
  GUI run is claimed.
- Read-only Git handoff: this documentation update made no code, user-config, or experiment-artifact
  changes; no commit, tag, push, or cleanup was made. Preserve the existing broadly dirty worktree.
  Exact next entry point: keep both metadata-prefix forms covered and rerun the listed focused checks
  when a Sunday-owned prompt source changes.

## Android provider TLS revocation retrieval and 0.1.5 build (mobile_tls015_release_docs; 2026-09-23)

- User's 0.1.4 phone result: `provider TLS certificate revocation check failed before response headers`.
- Root cause verified in the Android 36 Java platform-verifier path: default OCSP PKIX verification fails when the responder is unavailable, while Android blocks the provider certificate's HTTP CRL retrieval. Runtime test logs are `core/mobile/artifacts/tls-015/baseline-runtime.log` and `production-config-runtime.log`. With the production Network Security Config, normal HTTPS chain validation succeeds, the signed CRL from `c.pki.goog` downloads over HTTP (200, 310 bytes), a generated good CRL-only chain passes, and a revoked certificate is rejected. No trust-all setting was introduced.
- Minimal fix is in the main Android Network Security Config: release keeps `cleartextTrafficPermitted=false` by default and allows the exact `c.pki.goog` domain (`includeSubdomains=false`) needed for signed CRL retrieval. The debug overlay retains the previous development cleartext behavior. Rust/AAR verification code and algorithm are unchanged. Upstream `rustls-platform-verifier` 0.7 maps all `CertificatePkiError` cases to `Revoked`, including missing OCSP responder data; this is why the client presented the revocation-specific message.
- Android 36 tester exercised the Java verifier/configuration boundary, not the full Rust app request. The subsequent user phone test with 0.1.5 reached the provider and returned HTTP 401 `InvalidAuthorization/token`; TLS now passes through to the HTTP layer, but successful authorization remains unverified.
- Contract suite: 4/4 passed. First package build failed lint because `includeSubdomains` was omitted; setting it explicitly to `false` fixed the issue and the final build passed. No whole-UI rerun was required for this native config change.
- Signed universal APK: `release/mobile/Sunday-mobile_0.1.5.apk`, version 0.1.5 / versionCode 1005, 49,764,032 bytes, SHA256 `4683AB85217DD1FB60DDA6FB6914ADC88701BFB246B1C51E064399426B84EAD6`; signer matches the prior package (`045567d59580c97311203453e104938ad09d9f79e1e78e028f607cdbc4ecb4fb`), non-debuggable, ARM64/ARMv7, 16 KiB aligned, Sunday icon verified. Build evidence: `core/mobile/artifacts/tls-015/release-015/build-final.log`, `apk-manifest.txt`, and `apk-network-security.txt`.
- Published diagnostic URL: `https://47.114.43.99.nip.io/downloads/Sunday-mobile-diagnostic-0.1.5-20260923.apk`. Public HEAD returned 200; complete GET at 2026-09-23 13:17:31.682 UTC returned 49,764,032 bytes with the expected SHA256. Cloud publish completed 13:14:46–49 UTC; exact command `c-hz06xxqm6yxe680`, invocation `t-hz06xxqm6z7drls`, run RequestId `01A0CE67-850D-53EB-9ED3-F8799355B2B9`, result RequestId `01A0CE68-8CDC-5BDE-9771-BB964F67137F`.
- Cleanup completed 13:18:00–02 UTC: exact temporary server key revoked (`authorized_keys` has 0 lines), staged and publish temp files absent, Caddy and relay active. Stable/latest SHA256 `57958F1C739B4B2FC65556D49AD567A80A3CF21DD1C352791D31200609CFB561`, diagnostic 0.1.4 SHA256 `34FE6447B7AFEDFE0DA92197D075C289023C0A11D111336CCAC8A0E4D71814D1`, and legacy 0.1.2 SHA256 `58E0E54BCD21602A3AD9E4DA186276701CA15929D1943C97B65568C0BE19035A` were unchanged. Full deployment audit: `core/mobile/artifacts/release-015/RELEASE.md`.
- The automatic approval review rejected deletion of the newly generated local temporary upload-key files with reason “blocked by policy”; no alternate deletion attempt was made. The server-side authorization is revoked. Phone verification reached the provider but returned HTTP 401 `InvalidAuthorization/token`; successful authorization remains open. This closes the 0.1.5 build/publication work only; broader Rust refactor remains incomplete. Preserve the broadly dirty worktree; no commit or cleanup beyond the documented release transaction was performed.

## Android provider credential normalization and 0.1.6 package (mobile_auth016_20260923; 2026-09-23)

- Phone evidence from 0.1.5: TLS completed and the provider returned HTTP 401 `InvalidAuthorization/token`. The actual phone credential is unavailable, so the precise 401 cause is not confirmed. Sol's source comparison found Rust and Python Bearer handling equivalent; a direct desktop request using the same base/model returned HTTP 200. That desktop result does not validate the phone credential.
- `StandaloneConfigStore` now strips pasted `Authorization:` and `Bearer` prefixes on create/update and normalizes legacy active-provider/runtime-model entries when read. Opaque bare tokens are preserved. Create rejects blank, masked, and whitespace-invalid keys before writing; an update containing `********` preserves the existing key. No Rust authentication code changed.
- Verification: focused provider credential tests passed 9/9 and mobile typecheck passed.
- Signed universal APK: `release/mobile/Sunday-mobile_0.1.6.apk`, version 0.1.6 / versionCode 1006, 49,763,916 bytes, SHA256 `7A47E53747FB8D0BF06F8343F8E4A97EC37114894A81247022C62014191D7A39`; same signing certificate as the preceding package, non-debuggable, ARM64/ARMv7, 16 KiB aligned, icon verified.
- Cloud publication completed using a short-lived forced-SFTP key with an OpenSSH 8.9-compatible expiry. The APK was staged and published with matching hashes; server authorization was revoked and `authorized_keys` is empty. Public HEAD returned HTTP 200 with the expected size; no complete public GET was run. The final transfer key file remains under `C:\Users\ADMINI~1\AppData\Local\Temp\sunday-mobile-016-upload-8drlg8yp` after server revocation; local deletion is not claimed. Stable/latest and 0.1.5 remain unchanged. A phone retest is needed to establish whether normalization fixes the 401.
- Broader Rust refactor remains incomplete; preserve unrelated dirty worktree changes.

- Publication audit with Cloud IDs, timestamps, verified result, and scoped rollback: `core/mobile/artifacts/release-016/RELEASE.md`. The 0.1.6 build and versioned delivery are complete; the phone's 401 cause and successful authorization remain unverified, and website stable/latest remains 0.1.2 pending phone retest.

## Mobile sidebar actions and Study note navigation (mobile_sidebar_navigation_20260923; 2026-09-23)

- Prior completed mobile changes were committed as `9cc01306` (154 source files, selective mixed UI hunks; unrelated edits were preserved). The scoped sidebar and navigation changes remain uncommitted for user phone feedback.
- Narrow viewports (≤640px) keep the bottom dock available independently of the temporary sidebar drawer and account-panel visibility. The dock includes plugins and arrange actions; the narrow sidebar footer no longer duplicates those entries. Wide layout restores modes, account, search, settings, plugins, and arrange actions.
- In Study Notes, “返回学习” uses the resolved note-map binding to switch to its associated study session before changing page. Navigation cancellation or failure preserves the current note view and draft. A successful discard removes only the captured draft when it has not changed concurrently.
- Verification: Study main tests 27 passed; dock mobile tests 9 passed; UI tests 15 passed; final mobile/UI typechecks and scoped diff check passed. Independent review covered success, cancellation, and failure paths. No human visual/device acceptance is claimed.
- Release worker built signed 0.1.7 / versionCode 1007 at `release/mobile/Sunday-mobile_0.1.7.apk` (49,764,432 bytes; SHA256 `F6ECB4DD38366045B402C5513485B4F56342BFACCC67C6229AEE06B444C14386`). Package checks passed for signer, non-debuggable state, ARM64/ARMv7, 16 KiB alignment, icon, and manifest. Website build passed.
- Published links: [versioned APK](https://47.114.43.99.nip.io/downloads/Sunday-mobile-0.1.7.apk) and latest APK. Versioned/latest HEAD returned 200 with expected length; public homepage GET and main JS GET returned 200, and the JS hash matched the local website build and contained version 0.1.7. No full APK GET was performed. Server SHA verification passed; the temporary key was revoked, authorized_keys is empty, services active, and staging removed.
- The former stable 0.1.2 APK was preserved at `/var/www/lamtools/Sunday-mobile-latest-0.1.2-before-0.1.7-20260923.apk` with SHA256 `57958F1C739B4B2FC65556D49AD567A80A3CF21DD1C352791D31200609CFB561`. Website 0.3.6 was retained at `site-releases/0.3.6-mobile-0.1.7-20260923`; the live site was atomically switched to the refreshed release.
- Release operation audit is owned by `mobile_017_release`; public verification evidence is `core/mobile/artifacts/release-017/public-verification.json`. This scoped sidebar/navigation deployment is complete. Broader Rust refactor remains incomplete.
