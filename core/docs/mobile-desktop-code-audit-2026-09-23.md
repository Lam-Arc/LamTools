# 移动端与桌面端完整代码审计

日期：2026-09-23。状态：**审计已形成结论，能力对等未通过；发现项尚待修复。**

## 基线与范围

- 仓库 HEAD：`9cc013066f6229ce48a0cf4784cdb9e9f6503019`；审计对象是其上的**当前工作树**，含未提交的 Study 装配、导航及颜色修改。不是仅审计该 commit 的 diff。
- 主要调用边界文件的 SHA256 记录在 [baseline.json](audits/mobile-desktop-2026-09-23/baseline.json)，用于区分后续修改后的源码；它是主要文件清单，不是全仓库快照。
- 已发布 APK：**0.1.7 / 1007**。本轮没有构建、发布或替换 APK；下一实际出包版本应递增为 **0.1.8 / 1008**。
- 对比桌面 Python Core/Tauri 宿主、Android standalone 的 TypeScript/Tauri/Rust、paired remote 转发，以及共享 Vue UI 的入口。网站和归档 member 不属于这次移动/桌面能力审计。
- 覆盖 UI → RPC/HTTP/原生命令 → 工具/模型 → 持久化/恢复，包含配置、插件/技能、Study、Workflow、权限、子代理、附件、流式、项目/文件、同步、Android 桥接、日志和 CLI。
- 使用代码、CLI、现有 APK 的 merged manifest 和本地模拟测试；按用户要求未做 GUI、浏览器或手机操作。静态覆盖所有上述模块不等于穷尽每一种运行组合；真机权限、后台调度、恢复和系统选择器仍有验证边界。

## 审计结论

**目前移动端与桌面端的差异明显超过屏幕适配及 Android 权限限制，不能验收为能力一致。** 存在内容丢失、权限指令未执行、工具装配遗漏，以及目录/配置宣称可用但执行链不完整的问题。

尤其需要先处理：附件上传假成功、Hook 权限绕过、Study 并发覆盖、加密备份恢复失败、普通技能和 Study 子代理装配遗漏。它们与此前 Command Code 的 TLS/401 故障是不同问题，本审计没有将其冒认为那次故障原因。

### P1：优先修复

| 编号 | 确定问题及影响 | 证据与复现 |
|---|---|---|
| A01 | PreToolUse Hook 返回 `deny` 或 `ask_user`，Rust 仍执行 AutoAllow 工具，违反权限契约 | [运行时扩展](audits/mobile-desktop-2026-09-23/extensions.md)，**已执行独立本地 fixture 复现** |
| A02 | 附件上传返回 201，却未保存 bytes；入模只有文件名，图片/文件内容丢失 | [模型链路 M1](audits/mobile-desktop-2026-09-23/model.md) |
| A03 | 0.1.7 APK 未排除 Keystore 加密偏好备份；跨设备恢复只有密文而没有原密钥时，身份初始化失败并中止后续启动 | [原生与状态](audits/mobile-desktop-2026-09-23/native-state.md)，已核对实际 APK manifest；未做真机恢复 |
| A04 | 同一 Study 文本批注并发请求，模型返回后用旧对象整体覆盖，后完成者可抹掉先完成者已保存的回答 | [Study](audits/mobile-desktop-2026-09-23/study.md)，明确 read→await→write 竞争时序 |
| A05 | 普通 Core 技能列在技能目录中，运行时却没有对应通用加载器；插件目录也不能代表工具已装配 | [业务与 RPC](audits/mobile-desktop-2026-09-23/business.md)；本次只补齐了 Study 主 Agent 技能 |
| A06 | Study 子代理没有 Study 图谱、笔记和技能工具；有提示词/目录却不能执行相应任务 | [运行时扩展](audits/mobile-desktop-2026-09-23/extensions.md)，初次与恢复装配均受影响 |
| A07 | 主回合经审批恢复后新建的子代理使用空 context，仅剩子代理 guide，丢失原项目指令、记忆和模式上下文 | [运行时扩展](audits/mobile-desktop-2026-09-23/extensions.md)；不等同于恢复已有子代理 continuation |

### P2/P3：功能与可靠性差异

| 编号 | 优先级 | 问题 | 详细依据 |
|---|---|---|---|
| A08 | P2 | Study 搜索只搜图谱节点，遗漏 Note 内容、学习会话标题和消息 | [Study](audits/mobile-desktop-2026-09-23/study.md)，同一唯一关键字在两端结果不同 |
| A09 | P2 | 只有 OpenAI Chat 接入真流式；Responses/Anthropic/Gemini native 协议等待完整响应 | [模型 M2](audits/mobile-desktop-2026-09-23/model.md) |
| A10 | P2 | Rust 固定默认重试策略，未接模型重试配置和流式空闲超时 | [模型 M3](audits/mobile-desktop-2026-09-23/model.md) |
| A11 | P2 | 模型备注可以编辑提交，但移动模型 upsert 丢弃 notes，模型提示词也不注入 | [模型 M4](audits/mobile-desktop-2026-09-23/model.md) |
| A12 | P2 | 普通会话上下文漏全局指令/记忆及自定义 load-context 文件；Study 却可能读入桌面刻意隔离的项目指令 | [运行时扩展](audits/mobile-desktop-2026-09-23/extensions.md)，分模式列出触发条件 |
| A13 | P2 | MCP 启动/工具发现错误已收集但没有展示给移动端，配置后工具缺失可能没有原因提示 | [运行时扩展](audits/mobile-desktop-2026-09-23/extensions.md) |
| A14 | P2 | 全局搜索 Files/Content 调用未实现的 `workspace.search`，界面可到达并报错 | [业务与 RPC](audits/mobile-desktop-2026-09-23/business.md) |
| A15 | P2 | 命令、排队/引导、长期安排、导出、更新等工作台链路存在缺口；区分可达 UI、HTTP 缺项和纯 RPC 缺项 | [业务与 RPC](audits/mobile-desktop-2026-09-23/business.md) 的逐入口复核 |
| A16 | P2 | 模型组、高级配置、全局指令、工具配置等桌面配置能力未完整接入；通用 settings 保存不代表运行时会消费 | [业务与 RPC](audits/mobile-desktop-2026-09-23/business.md) |
| A17 | P2 | Workflow 有文档存储、导入导出和内置节点执行，但隐藏模式入口，缺调度/激活/持久队列/人工任务/外部执行等 | [业务与 RPC](audits/mobile-desktop-2026-09-23/business.md)，多数未实现 RPC 暂无本地 UI 入口 |
| A18 | P2 | 文件列表扁平化、无目录节点；目录浏览返回空值（尚未找到该浏览方法的现有 UI 调用） | [原生与状态](audits/mobile-desktop-2026-09-23/native-state.md) |
| A19 | P2 | 项目写文件直接覆盖、非原子；LocalRepository 在持久化成功前发布内存状态，写失败可出现内存/磁盘分叉 | [原生与状态](audits/mobile-desktop-2026-09-23/native-state.md) |
| A20 | P2/条件性 | 项目路径只做词法限制；若已有 symlink，可跟随到项目外；尚未确认当前 Android 入口能创建此链接 | [原生与状态](audits/mobile-desktop-2026-09-23/native-state.md)，属于条件性路径隔离缺陷 |
| A21 | P2 | Study 对话 context 不含进行中的考试信息 | [Study](audits/mobile-desktop-2026-09-23/study.md) |
| A22 | P2 | Rust 向 Agent 宣称通知可用，但原生通知没有发送实现；共享 UI 已正确标 false | [原生与状态](audits/mobile-desktop-2026-09-23/native-state.md) |
| A23 | P2 | Tauri 下 LAN discovery 走 Capacitor 判断并返回空，数字码局域网配对需手填地址或另走账户/Relay | [原生与状态](audits/mobile-desktop-2026-09-23/native-state.md) |
| A24 | P2 | Android 本机 Agent/Study/Workflow/配置没有对应 CLI；现有 Python mobile CLI 控制桌面 gateway，不能操作手机私有状态 | [原生与状态](audits/mobile-desktop-2026-09-23/native-state.md)，违反项目 GUI/CLI 对应要求 |
| A25 | P2/诊断缺口 | 有阶段事件与 transport console 诊断，缺少用户可用的专门移动日志导出入口；不能声称日志已保存到某个外部文件夹 | [原生与状态](audits/mobile-desktop-2026-09-23/native-state.md) |
| A26 | P3/兼容性 | Study legacy `task_*` / `curate_*` 笔记任务 API 未实现；未发现现有 UI/活跃技能调用 | [Study](audits/mobile-desktop-2026-09-23/study.md) |

编号按可执行修复范围归并，不是漏洞数量；P2 条件项和功能缺口不等于已经发生的数据损坏。

## 覆盖矩阵与不能混淆的结论

| 模块 | Android standalone 状态 | paired remote / 桌面对照 |
|---|---|---|
| 会话与执行 | 本地 CRUD、执行、审批、取消、孤儿回合恢复已有；排队/steer 等仍缺 | remote 转发宿主 RPC；不能据此宣称本机具备所有能力 |
| 项目 | **项目 CRUD、会话、AGENTS、文件读写已有独立 CoreProjectClient**；文件层级、原子性另有问题 | 项目 RPC 缺失不等于项目 UI 不可用，已纠正初查误判 |
| 模型协议 | 四类协议非流式装配已有，OpenAI Chat 增量已有；其他协议流式与设置消费不完整 | 桌面按协议解析增量事件 |
| 插件/技能 | Study 主 Agent 装配本次已修；普通技能、插件工具和子代理仍不完整 | 桌面动态 registry 与工具/技能过滤是比较基线 |
| Study | 图谱、考试评分/签证据、Raw→Resource→Note、历史/锁、pins/bindings/outbox 已有 | 搜索、批注并发、考试 context 和 legacy 任务仍有差异 |
| Workflow | 文档/修订/导入导出/编译/内置执行已有；不等于完整任务调度系统 | 桌面外部节点、队列、人工任务等需分别移植 |
| Hook / MCP | 事件、trust、required hook 失败阻断、stdio 超时已有；PreToolUse 权限与 MCP 错误展示有问题 | URL-only MCP 在两端都不支持，**不列为移动独有缺失** |
| 上下文/压缩/记忆 | 有上下文压缩、工具尾部对齐、Dreaming 与原子 MEMORY 写入 | 不应误报为“没有记忆”；加载作用域和子代理恢复另有缺陷 |
| 文件与 Android 存储 | 本机项目在应用私有目录，系统文件管理器通常看不到 | 外部导入导出需 SAF/系统选择器适配；不是取消附件或项目功能的理由 |
| 安全存储/状态/同步 | 同设备旧密文格式兼容、SQLite 事务、取消世代隔离、同步消息缓冲已有 | 备份恢复、上层状态发布仍有缺陷；未发现已证实的隧道重放/游标损坏 |
| 导航与样式 | 窄屏浮钮/宽屏侧栏回退、Study 笔记返回、顶栏原生 inset 桥接在源码存在 | 未发现新的确定 Pad/inset 缺陷；代码通过不等于真机视觉验收 |
| 原生适配 | 生命周期 focus/visibility fallback、DOM 文件选择器已有 | 相机选择器、后台保活/恢复、旋转 inset 需真机；不能仅凭 fallback 判定必坏 |
| Shell/Git | 当前未装配相关本机执行能力 | 不把“当前未实现”包装为 Android 一律禁止；需明确可打包执行器、权限和替代路径 |
| CLI/日志 | 本机原生命令只由 Tauri WebView invoke；诊断未形成可导出完整日志 | 桌面 CLI 不自动覆盖 Android 本机数据与密钥 |

## 本次已经修好的源码，尚未发布

1. Study `active_mode` 接受 `study` 和真实 UI 的 `study:study`，初次与审批恢复均传递模式和禁用技能列表；插件禁用时明确报错。
2. Study 主 Agent 从同一份 canonical 资源嵌入 **5 个 SKILL.md 和 14 个 references**，提供 `load_skill` / `read_skill_reference`，拒绝越界路径并落实禁用列表，修正 `future/curate-notes` 目录。
3. Study 提示词简要说明建图、教学、答疑、测评和笔记能力；只有工具成功后才可声称已保存。
4. 移动端附件来源菜单与“回到最新消息”按钮文字色改为对应玻璃背景的主题文字 token。

**这些不在现有 0.1.7 APK 中。** 本次脚本模型主 Agent 建图验证通过，不代表子代理已经具备同样工具；A06/A07 仍待修。

## 验证记录

| 检查 | 结果 | 能说明什么 |
|---|---|---|
| mobile `npm test` | 29 文件 / 175 通过 | 当前移动 TS 既有断言通过 |
| Rust runtime `cargo test` | 130 通过（80 单元、50 集成） | provider、Hook/MCP、Study、Workflow、记忆等既有断言通过 |
| mobile native `cargo test --lib` | 18 通过 | 原生桥接、状态、取消及 Study 主 Agent 技能→建图链路通过 |
| mobile `vue-tsc --noEmit` | 通过 | TS/Vue 类型检查通过 |
| 0.1.7 `aapt dump xmltree` | targetSdk 36，无 backup exclusion 属性 | 加密偏好恢复风险有实际发布包证据 |
| 独立 PreToolUse fixture | deny/ask_user 均 `completed`，工具执行计数均为 1 | 确实复现权限契约违反，**不是通过结果** |

可重现权限 fixture：`cargo run --manifest-path core/docs/audits/mobile-desktop-2026-09-23/pre-hook-repro/Cargo.toml --quiet`。无网络模型请求，不操作用户文件；只计数一个模拟工具。

以上 **323 项现有测试通过**，与已确认缺陷同时成立：缺的是跨端契约覆盖，不能拿测试数量证明能力一致。没有执行真实供应商请求、Android 备份恢复、进程写入中断、手机视觉或完整远程双端联调。

## 修复顺序与验收条件

1. **权限与数据完整性**：先修 A01–A04/A19，补 Hook deny/ask_user 行为、附件存取及入模、同 mark 并发、持久化失败和密钥失效恢复测试。
2. **技能与上下文装配**：让列表来自真实可执行能力，补普通技能、Study 子代理和审批后 context；按模式对照首个模型请求的 system/tools 及后续真实工具回执。
3. **用户可达功能**：补 Study/项目搜索、附件预览/导出、排队/长期安排、模型配置消费及各协议真流式；不能靠隐藏功能或返回空成功宣称修好。
4. **完整原生对等**：补 Workflow 执行/调度、平台可用的执行器、文件导入导出、通知/LAN、CLI 和日志导出；确属 OS 限制的项写清替代流程。
5. **交付**：修复后按差异矩阵复验，出包递增版本，并更新官网链接、保留旧包；本轮未做这一步。

完整审计材料：[业务/RPC](audits/mobile-desktop-2026-09-23/business.md)、[模型](audits/mobile-desktop-2026-09-23/model.md)、[扩展/权限/子代理](audits/mobile-desktop-2026-09-23/extensions.md)、[Study](audits/mobile-desktop-2026-09-23/study.md)、[原生/存储/CLI](audits/mobile-desktop-2026-09-23/native-state.md)。
