# 17 设置与编辑组件 审计报告

- 审计时间：2026-08-13
- 审计范围：core/ui/src/components/ 下设置/编辑/向导组件及关联 composables、调用方 demo/App.vue，交叉验证后端契约（config/operations.py、plugins/operations.py、config/imagegen_store.py、app/http_agent_app.py）
- 审计方式：全程只读（grep / read），未运行测试与 dev server
- 严重度统计：S1 = 0，S2 = 2，S3 = 12，S4 = 7，共 21 条

## 1. 概况

本区由「设置弹层（CoreSettings + SettingsShell）」+「子编辑器（Hooks / LoadTools / Skills / ImageGen / WebSearch / SubAgent）」+「引导与项目（OnboardingWizard / CoreProjectCreate / CoreProjectSettings）」+「会话回滚（CoreSessionRollback）」+「主题（ThemeEditor / ThemeAreaEditor）」构成，调用方为 core/ui/src/demo/App.vue（打包为桌面端设置界面）。

总体质量较高：保存链路统一为「await RPC → 重新拉取回显」，无乐观更新漂移（除 2 处例外，见问题 9）；provider 密钥打码与「留空保留」契约与后端完全对齐；服务端 settings.update 为浅合并，前端「只发变更键」的模式安全；回滚组件的并发防护与事件清理完备。主要问题集中在三类：**草稿丢失无保护**（dirty 追踪缺失、分区切换/关闭即弃）、**JSON 容错过宽导致配置被静默覆盖**、**表单校验依赖失效的原生校验/错误提示不可见**。

## 2. 问题清单

### S2

- **[S2] CoreLoadToolsEditor：dirty 标记不追踪编辑，修改后无法保存**
  - 位置：`core/ui/src/components/CoreLoadToolsEditor.vue:121, 173-190`（dirty 定义与仅 addMode/removeMode 置位）、`:15`（保存按钮 `:disabled="loading || saving || !dirty"`）
  - 问题：`dirty` 只在「新增模式 / 删除模式」时置 true。加载后用户直接修改模式名（`v-model="mode.name"` :27）、描述（:39）、勾选工具（:57）、切换 unlimited（:47）均不触发 dirty，保存按钮保持禁用。
  - 影响：最常见的编辑操作（调整工具白名单）完成后无法保存，改动只能静默丢弃，界面没有任何提示，用户会以为保存成功或怀疑按钮失效。属功能性缺陷。
  - 修复建议：对 modes 深度 watch 或在 v-model 处统一置 dirty；或改为「有未保存修改即常亮保存」+ 保存后回读比对。

- **[S2] CoreHooksEditor：新增 Hook 时若既有配置解析失败，整个 hooks.json 被静默清空**
  - 位置：`core/ui/src/components/CoreHooksEditor.vue:449-456`（`JSON.parse(rawContent)` catch 后 `config = {}`）、`:475`（写回 `hook.config.update`）
  - 问题：`saveHookForm` 先读现有 hooks.json 再合并新 hook。当文件不是严格 JSON（外部工具手改、含注释、半截写入损坏）时，catch 分支静默退化为 `{}`，随后保存的配置只含新建的这一个 hook。
  - 影响：既有全部 hook 配置被覆盖丢失，且无任何错误提示。后端 hook_config.py:100-102 对不可解析的 hooks.json 也是静默跳过（不加载），但前端这次写回会**永久覆盖**文件，用户手写的配置不可恢复。
  - 修复建议：解析失败时中止提交并报错（如「hooks.json 无法解析，请先到原始配置视图修复」），严禁以空对象兜底写回；保存前做一次严格 JSON 校验。

### S3

- **[S3] CoreSettings：provider/model 表单校验错误提示被编辑浮层遮挡不可见**
  - 位置：`core/ui/src/components/CoreSettings.vue:21`（noticeText 渲染在 models 分区顶部）、`:432-433`（editor-overlay 以 `position:absolute; inset:0` 覆盖整个 settings-card，z-index 为 var(--z-popover)）、`:1196-1206`（parseExtraJson 失败写 noticeText）、`:1183-1186`（无供应商写 noticeText）
  - 问题：提交校验失败（「高级适配 JSON 必须是对象」「请先选择供应商」）时消息写在浮层**背后**的分区里，被 35% 黑色 + blur 遮罩盖住。
  - 影响：用户点击保存后界面毫无反馈，反复点提交无响应，无法定位是哪个字段错了。表单校验反馈形同虚设。
  - 修复建议：把错误提示放进浮层内部（如表单顶部）或通过浮层自身展示错误；noticeText 改为浮层级 ref。

- **[S3] SettingsShell：切换分区强制重挂载内容，未保存草稿静默丢失**
  - 位置：`core/ui/src/components/SettingsShell.vue:43`（`<div class="settings-content" :key="activeSection">`）
  - 问题：内容区以 activeSection 为 key，切换分区即卸载子组件。CoreHooksEditor 的 configDraft、CoreLoadToolsEditor 的模式草稿、CoreWebSearchEditor 的 configDraft、CoreSubAgentEditor 的 guide 草稿全部随之销毁。
  - 影响：用户编辑一半切去别的分区再切回来，草稿丢失，无 dirty 拦截、无确认提示。CoreSettings 内建分区（AGENTS.md/memory/load_context）因状态在父级不受影响，子编辑器全部受影响。
  - 修复建议：去掉 key 强制重挂载（改用 v-show），或为带草稿的子组件提供 keep-alive / 脏检查。

- **[S3] CoreSettings：Esc / 点击遮罩关闭设置，未保存内容无任何保护**
  - 位置：`core/ui/src/components/CoreSettings.vue:5`（`@click.self="$emit('close')"`）、`:1230-1243`（onKeydown Escape → close）；`CoreProjectSettings.vue:232-237` 同型
  - 问题：关闭设置弹层不检查任何草稿/未保存状态，误触 Esc 或误点背景即丢弃全部编辑内容。
  - 影响：与上一条叠加，本区所有编辑入口都无「未保存修改」护栏。
  - 修复建议：维护全局 dirty 标志（任一子编辑器上报），关闭前确认或先自动保存。

- **[S3] CoreImageGenEditor：api_key 明文回显且清空即删除，无「留空保留」语义**
  - 位置：`core/ui/src/components/CoreImageGenEditor.vue:102`（`form.api_key = String(value.api_key || '')`）、`:127-147`（saveConfig 无条件发送 api_key）；后端 `core/src/lamtools_core/config/imagegen_store.py:37-44`（明文写入 jsonc）、`config/operations.py:224-228`（settings.get 原样返回）
  - 问题：后端把真实密钥明文回传，前端直接填入 password 输入框（值存在于 DOM）；保存时始终提交 api_key，用户清空字段保存即永久删除密钥，无确认、无占位提示。对比 provider 编辑器有「留空以保留现有密钥」占位（CoreSettings.vue:468）与后端空值保留契约（operations.py:346-358），imagegen 路径完全缺失该契约。
  - 影响：误清空保存 = 密钥配置丢失；密钥以明文形式存在于前端内存与 DOM 值（虽为 password 掩码）。密钥字段处理前后端契约不一致。
  - 修复建议：后端对 settings.get 打码返回（与 provider 一致）；前端空值提交时省略 api_key 字段或明确提示清空将删除密钥。

- **[S3] CoreWebSearchEditor：JSONC 注释剥离正则破坏字符串内的 `//`**
  - 位置：`core/ui/src/components/CoreWebSearchEditor.vue:158-161`（`(^|[^:])\/\/.*$/gm`）；后端同型缺陷 `core/src/lamtools_core/plugins/operations.py:225-228`
  - 问题：前端 stripper 只保护 `:` 前的 `//`，`"url": "//host/path"`、`"base": "a//b"` 这类字符串值中的 `//` 会被当注释剥掉，解析回显数据被静默破坏。后端 stripper 连 `:` 保护都没有：含 `http://` 的合法配置（UI 文档卡片给出的外部内核示例）保存时被剥成残缺 JSON 而拒绝，报「Invalid JSON/JSONC」。
  - 影响：读取回显可能得到错误表单值；UI 文档中明确展示的 `http://` 示例配置实际无法通过原始配置编辑器保存。
  - 修复建议：两端都改为感知字符串上下文的 JSONC 解析（如使用完整 jsonc 解析库），或后端直接使用 load_jsonc 校验。

- **[S3] CoreWebSearchEditor：表单保存覆盖原始配置中的扩展字段**
  - 位置：`core/ui/src/components/CoreWebSearchEditor.vue:197-219`（toJsoncContent 仅输出 provider/limit/timeout）
  - 问题：原始配置支持 transport/url/command 等外部内核字段（UI 文档明示），但点表单的「保存」会用仅含 3 个字段的内容整体覆盖文件。
  - 影响：用户按文档配好自定义搜索内核后，误点表单保存即静默丢弃扩展配置，搜索内核失效。
  - 修复建议：表单保存改为在原始配置基础上合并字段，或保存前提示「将覆盖自定义扩展字段」。

- **[S3] demo/App.vue：权限模式与工作目录开关乐观更新无失败回滚**
  - 位置：`core/ui/src/demo/App.vue:1921-1933`（updatePermissionMode / updateAllowAccessOutsideWorkdir 先写本地 ref 再 await RPC，无 try/catch）
  - 问题：RPC 失败时本地已显示新状态，后端未保存；异常未被捕获，产生未处理 Promise rejection。
  - 影响：界面状态与后端配置漂移（展示「允许访问工作目录以外」实际未生效），且为安全相关开关，用户可能误信已生效。
  - 修复建议：失败时回滚本地值并展示错误（参照 CoreSkillsEditor.toggleAllowInstall 的 `catch` 回滚写法，CoreSkillsEditor.vue:129-141）。

- **[S3] CoreSessionRollback：未知恢复范围默认「全部恢复」**
  - 位置：`core/ui/src/components/CoreSessionRollback.vue:526-529`（normalizeRestoreScope 未知值默认返回 'all'）
  - 问题：后端返回的 scope 不在预期集合时，静默升级为最破坏性的「全部恢复」（对话 + 文件覆盖）。
  - 影响：后端契约演进或异常返回会导致用户一键触发超预期的全量回滚。
  - 修复建议：未知 scope 应报错中止（fail-safe），而不是默认 'all'。

- **[S3] CoreHooksEditor：删除 Hook 无确认，「全部信任」一键绕过审核**
  - 位置：`core/ui/src/components/CoreHooksEditor.vue:204-209`（删除按钮直接调 deleteHook）、`:389-402`（trustAll 无确认）
  - 问题：删除 hook（含 config 来源、可执行任意命令的 command hook）单次点击即生效、不可撤销；「全部信任」一次点击信任全部待审核 hook，绕过「逐条审核」机制。
  - 影响：误删/误信任即执行风险；与页面头部「未信任的 Hook 不会执行，需在此审核后启用」的承诺相悖。
  - 修复建议：删除前 confirm（调用方 demo/App.vue 对 provider/model 删除有 confirm，hook 删除缺失）；全部信任前二次确认并提示数量。

- **[S3] CoreLoadToolsEditor：模式重名/空名保存时静默丢弃**
  - 位置：`core/ui/src/components/CoreLoadToolsEditor.vue:196-204`（`payload[name] = ...` 字典键冲突覆盖；`if (!name) continue` 空名跳过）
  - 问题：两个模式改同名后保存，后遍历者覆盖先者，先者无声消失；空名模式被静默丢弃（仅 addMode 保证初始唯一）。
  - 影响：重命名冲突造成模式配置丢失，无任何校验或提示。
  - 修复建议：保存前校验名称唯一性与非空，冲突时提示用户。

- **[S3] CoreSettings：编辑模型时合法 0 值被默认值替换**
  - 位置：`core/ui/src/components/CoreSettings.vue:1168-1171`（`context_window: model.context_window || 128000`、`max_output_tokens || 16384`、`thinking_budget || 10000`）
  - 问题：用 `||` 兜底导致 0 值被替换为默认值。thinking_budget=0（禁用推理预算）等合法配置在编辑回填时变成默认值，保存后即回写改变用户配置（temperature 用了 `??` 是正确的，此处不一致）。
  - 修复建议：改为 `??` 判空；`startModelUpdate` 与 `startModelCreate` 保持同一兜底语义。

- **[S3] CoreSettings：记忆整理最小轮数输入无实际校验（原生 min/max 不生效）**
  - 位置：`core/ui/src/components/CoreSettings.vue:317-326`（input 的 min=1/max=20 无 form 包裹，原生校验不触发）、`:910-924`（saveDreamingSettings 只做 `|| 3` 兜底）
  - 问题：该输入不在任何 <form> 内，min/max 属性纯装饰；可输入 0、-5、999 并保存，后端 settings.update 为通用合并（operations.py:230-243）不做范围校验。
  - 影响：非法值持久化到 core.dreaming 配置，影响记忆整理触发逻辑。
  - 修复建议：JS 层钳制（clamp 1-20）或提交时校验报错；context 添加项的 priority 输入（:255）同理。

### S4

- **[S4] CoreHooksEditor：删除未信任 hook 时 trustedCount 误减**
  - 位置：`core/ui/src/components/CoreHooksEditor.vue:404-413`（deleteHook 无条件 `trustedCount--`，仅 Math.max(0) 兜底）
  - 问题：删除「待审核」hook 也会递减已信任计数，顶部统计漂移。
  - 修复建议：按被删 hook 的 trusted 状态决定是否递减。

- **[S4] CoreSubAgentEditor：默认多模态模型失效值残留并回写**
  - 位置：`core/ui/src/components/CoreSubAgentEditor.vue:140-154, 170-182`（defaultMmModel 不在选项列表时 UiSelect 显示占位符但 stale 值保留）
  - 问题：已配置的默认模型被删除后，下拉显示「未指定」，但点保存仍会把失效 id 写回。
  - 修复建议：fetch 后校验值是否在选项内，不在则清空或提示。

- **[S4] CoreProjectSettings：父级数据刷新覆盖正在编辑的草稿**
  - 位置：`core/ui/src/components/CoreProjectSettings.vue:187-193`（watch agentsContent/projectNameDraft 直接覆盖本地草稿）
  - 问题：用户在输入时若父级恰好推送更新（其他入口刷新），正在编辑的内容被覆盖。
  - 修复建议：仅在「无本地修改」或「非聚焦」时同步。

- **[S4] ThemeAreaEditor：直接改 props 深部对象 + key=index 编辑焦点跳动**
  - 位置：`core/ui/src/components/ThemeAreaEditor.vue:6`（`:key="index"`）、`:11-27`（`v-model="stop.color"` 直接修改 props 数组元素）、`:14/:19`（change 触发 sort-stops）
  - 问题：颜色编辑绕过 update:stops 事件契约，依赖父级持有同一响应式对象才生效（与 emit 设计不一致）；sort-stops 重排序导致 v-for key 变化，编辑中控件失焦跳动。
  - 修复建议：颜色/文本改动走 `update:stops` emit（与 angle/opacity 一致）；排序改为提交时进行或稳定 key。

- **[S4] useCoreUiPreferences：本地写入成功但服务端同步失败无提示无重试**
  - 位置：`core/ui/src/composables/useCoreUiPreferences.ts:38-42`（先写 localStorage 再 `await adapter.write`，调用方 `void save()` 吞掉 rejection）
  - 问题：适配器写失败时本地与远端永久分叉，用户无感知。
  - 修复建议：失败回滚本地或提示；连续拖动节流（每次拖动都触发一次 RPC 写）。

- **[S4] CoreProjectCreate：项目路径仅非空校验**
  - 位置：`core/ui/src/components/CoreProjectCreate.vue:106-110`（submit 只检查 `workRoot.trim()`）
  - 问题：任意字符串路径可提交，非法路径错误只能等后端返回，缺少前端预校验（存在性/可写性）。
  - 修复建议：提交前做轻量路径形态校验或依赖后端错误回显即可（低优先）。

- **[S4] OnboardingWizard：Esc/跳过无确认且跳过即持久化完成标记**
  - 位置：`core/ui/src/components/OnboardingWizard.vue:117, 231-233`（跳过按钮与 Esc 均 emit skip）；`core/ui/src/demo/App.vue:1860-1870`（skipOnboarding 写 completed:true）
  - 问题：误按 Esc 即退出引导并持久化「已完成」标记，之后不再自动弹出。
  - 修复建议：Esc 不触发 skip（或仅关闭不标记完成）；跳过加确认。

## 3. 该区 Top 3 问题

1. **CoreLoadToolsEditor 修改无法保存（S2）**：工具模式是执行期强制拦截的安全相关配置，dirty 追踪缺失导致最常见的编辑动作保存按钮永远禁用、改动静默丢失，且界面无任何提示，属于本区最高频触达的功能缺陷。
2. **CoreHooksEditor 新增 Hook 可整体清空 hooks.json（S2）**：解析失败静默兜底 `{}` 后写回，一但触发即不可恢复地丢失全部 hook 配置（含信任状态），且无错误提示，属配置丢失型严重缺陷。
3. **CoreImageGenEditor 密钥回显与删除语义（S3）**：api_key 明文回显 + 清空即删，与 provider 编辑器的「留空保留」契约不一致，是密钥字段处理中最容易造成误删的位置。

## 4. 亮点

- **保存链路一致性**：demo/App.vue 的 mutateConfig 统一「await RPC → 重新拉取」而非乐观更新，失败展示错误，无状态漂移（除问题 9 两处开关）。
- **密钥契约对齐**：provider api_key 后端打码（provider_store.py:49-50 mask_api_key）、空值保留（operations.py:346-358），前端「留空以保留现有密钥」占位 + 空值省略字段（CoreSettings.vue:1098）完全匹配。
- **服务端合并语义**：settings.update 为服务端浅合并（operations.py:230-243），前端「只发变更键」（imagegen enabled、runtimeControls 各开关）不会互相覆盖。
- **并发与生命周期防护**：CoreSessionRollback 的 loadSequence 竞态守卫（:295-322）、busy 互斥（:431-497）、document 事件成对清理（:419-427）；CoreSettings/OnboardingWizard/CoreProjectSettings 的 keydown 监听均正确注册/卸载。
- **失败回滚范例**：CoreSkillsEditor.toggleAllowInstall（:129-141）与 CoreHooksEditor.toggleAllowCreate（:347-359）均为乐观更新 + catch 回滚 + 错误回显的正确实现。
- **安全细节**：本区无 v-html；密钥输入 type=password + autocomplete=new-password/off；危险删除（provider/model）在调用方有 window.confirm 且提示级联删除模型。

## 5. 审计范围与方法

- 前端文件（全部通读）：CoreSettings.vue、SettingsShell.vue、CoreHooksEditor.vue、CoreLoadToolsEditor.vue、CoreSkillsEditor.vue、CoreAgentsEditor.vue、CoreSubAgentEditor.vue、CoreWebSearchEditor.vue、CoreImageGenEditor.vue、OnboardingWizard.vue、CoreProjectCreate.vue、CoreProjectSettings.vue、CoreSessionRollback.vue、ThemeEditor.vue、ThemeAreaEditor.vue、UiSelect.vue（部分）
- 调用方：core/ui/src/demo/App.vue（CoreSettings 事件的唯一生产调用方，含 mutateConfig / onboarding / 权限开关）
- Composables：useCoreConfigState.ts、useCoreUpdateState.ts、useCoreUiPreferences.ts
- 后端契约交叉验证（只读 grep/sed）：core/src/lamtools_core/config/operations.py（provider/model CRUD、settings.get/update、_provider_update_fields）、plugins/operations.py（hook/websearch config 校验）、config/imagegen_store.py、config/provider_store.py、config/model_store.py、app/http_agent_app.py（loadtools/agents_md/memory/load_context、subagent settings）
- 方法：按「表单校验 → 保存链路 → JSON/JSONC 处理 → 密钥字段 → 状态泄漏 → 危险操作 → 死代码/绑定」七个维度逐文件检查，所有结论均回链到 file:line 与后端契约实码核实；未执行任何写操作、未运行测试。
