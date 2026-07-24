# 未修复 Bug 清单

> 审计日期: 2026-05-13 | 共 27 项未修复

---

## 一、改动风险大于收益 (2项)

### B-04: Checkpoint resume 逻辑中 `replan` 状态处理可能有误

- **文件**: `backend/app/services/generate_service.py:944-946`
- **描述**: 当 `decision_node` 返回 `replan` 时，代码使用 `Command(resume=action)` 恢复 graph。如果 LangGraph 的 checkpoint 机制不支持从 `replan` 跳回 `planner`，则 replan 功能将失效。
- **不修原因**: LangGraph 的 `Command(resume=)` 机制本身设计为从中断点恢复后由 graph 内部路由决定下一步节点。`decision_node` 返回 `replan` 后，graph 内部的条件边会将流程重定向到 `planner_node`，这是 LangGraph 的正常工作方式。改动需要深入理解 LangGraph checkpoint 机制，风险高且当前行为可能本身就是正确的。

### B-09: `Message.metadata_` 与 Schema `metadata` 名称不一致

- **文件**: `backend/app/models/message.py:35` vs `backend/app/schemas/session.py:42`
- **描述**: ORM 属性名为 `metadata_`（因为 `metadata` 是 SQLAlchemy 保留字），Schema 期望 `metadata`。`MessageResponse` 标注了 `from_attributes=True`，直接 `model_validate(orm_obj)` 时 `metadata` 字段会丢失。
- **不修原因**: 当前所有代码路径都通过 `message_to_response()` 手动映射（`"metadata": msg.metadata_ or {}`），运行时不会出错。修改需要重命名 ORM 属性或添加 Pydantic validator，改动面大且可能引入回归。

---

## 二、无实际影响 (4项)

### B-13: `activeTasks` Map 的 delete 和属性修改不触发 Vue 响应性

- **文件**: `frontend/src/views/Sessions.vue:312,461,999`
- **描述**: `ref<Map>` 的 `.delete()` 和 Map 中对象的属性修改不触发 Vue 响应性更新。
- **不修原因**: 实际影响有限——`activeTasks` 的 UI 表现（进度条、状态徽章）在 SSE 事件到达时通过其他机制（如 `agentStreamState`）同步更新。Map 响应性失效只影响极少数边界场景，改动需要重构整个 `activeTasks` 的使用方式。

### B-17: 下载到服务器本地目录功能前端完全不可用

- **文件**: 后端 `POST /api/download/image` 存在，但前端无 API 封装
- **描述**: `useDownload.ts` composable 只做了客户端下载（blob URL），没有调用后端下载端点。
- **不修原因**: 这是**功能缺失**而非 bug。后端端点存在且可用，前端只是没有封装调用。添加此功能需要 UI 设计（下载目录配置、下载按钮交互等），属于新功能开发，不在 bug 修复范围。

### B-23: SSE 事件处理中 `agentStreamState` 的竞态条件

- **文件**: `frontend/src/views/Sessions.vue:499-620`
- **描述**: 快速切换会话时，旧会话的 SSE 事件仍会到达。虽然有 `session_id` 过滤，但 `agentStreamState.value` 可能已被新会话的事件覆盖。浅拷贝 `steps` 数组中的对象仍是引用。
- **不修原因**: B-08 修复后 `_broadcast` 已按 session 路由，SSE 事件不会串到其他会话。`publish` 方法本身已有 session 过滤。实际使用中快速切换会话时旧连接会被 abort（B-12 已修），竞态窗口极小。

### B-24: `onUnmounted` 未清理所有 setTimeout

- **文件**: `frontend/src/views/Sessions.vue:461,999`
- **描述**: `setTimeout(() => activeTasks.value.delete(...), 3000)` 等定时器未保存引用，组件卸载后仍会执行。
- **不修原因**: Sessions.vue 是应用主页面，组件生命周期与应用一致，实际上不会被卸载。定时器回调操作 `activeTasks` 是安全的（ref 在模块作用域不会销毁），只是不够优雅。

---

## 三、类型重构范围过大 (4项)

### B-18: `generateData` 使用 `any` 类型丧失类型检查

- **文件**: `frontend/src/views/Sessions.vue:967`
- **描述**: 整个生成请求数据对象被声明为 `any`，应使用 `GenerateRequest` 类型。
- **不修原因**: `generateData` 的结构因 `agent_mode`、`reference_images`、`plan_strategy` 等条件分支而动态变化，没有现成的 TypeScript 类型能完整描述。创建精确类型需要定义 3-4 个变体接口并处理联合类型，改动面大且容易引入新类型错误。

### B-19: 多处 `as any` 类型断言违反项目规则

- **文件**: Sessions.vue:1137,1377,1512 / ApiManage.vue:273,332 / AgentStreamCard.vue:60,64 / PlanMessageCard.vue:18
- **描述**: 多处使用 `as any` 绕过类型检查。
- **不修原因**: 每处 `as any` 的根因不同——有的是后端返回类型与前端接口不匹配（如 `image_urls` 是 `string[]` 但类型定义为 `{}`），有的是动态属性访问。修复需要逐一重新设计类型定义，部分还需要修改后端 Schema，改动面大且风险高。

### B-26: `AssistantSidebar.vue` 局部接口含 `[key: string]: any`

- **文件**: `frontend/src/components/session/AssistantSidebar.vue:255,269`
- **描述**: PlanTemplate 和 Skill 接口使用索引签名 `any`。
- **不修原因**: 这些是组件内部的局部接口，用于简化模板中的属性访问。替换为精确类型需要从 `types/index.ts` 导入并确保所有字段匹配，改动收益有限。

### B-27: `TemplateVariable.default` 类型为 `string | any[]`

- **文件**: `frontend/src/types/index.ts:229`
- **描述**: 应为 `string | string[]`。
- **不修原因**: 后端 `variables` 字段是 `list[dict]`，`default` 的实际类型取决于变量定义，可能是字符串也可能是字符串数组。改为 `string | string[]` 可能不够准确，需要与后端 Schema 对齐后统一修改。

---

## 四、死代码不影响运行 (1项)

### B-28: Vendor Model 更新/删除 API 前端定义了后端不存在的路由

- **文件**: `frontend/src/api/apiProvider.ts:29-33`
- **描述**: `vendorApi.updateModel()` 和 `vendorApi.deleteModel()` 调用的路径在后端不存在。
- **不修原因**: 这两个方法在前端代码中**未被实际调用**（store 中使用的是 `providerApi.update()` 和 `providerApi.delete()`），属于死代码。删除它们是代码清理而非 bug 修复，可留待后续统一清理。

---

## 五、代码风格 / 低优先级 (16项)

### B-30: `Message.role == "user"` 应使用 `MessageRole.user`

- **文件**: `backend/app/services/executors/radiate.py:315`
- **不修原因**: SQLAlchemy 枚举列的 `==` 操作同时支持枚举值和字符串比较，功能完全正确。改为枚举比较是代码风格优化。

### B-31: 同步文件 IO 在异步端点中阻塞事件循环

- **文件**: `backend/app/routers/download.py:69,104`
- **不修原因**: `filepath.exists()` 和 `filepath.write_bytes()` 是同步操作，但下载端点不是高频调用路径，阻塞时间极短（微秒级文件存在检查 + 毫秒级文件写入）。改为 `asyncio.to_thread()` 包装会增加代码复杂度，收益不明显。

### B-32: `settings.py` 的 `value: dict` 参数类型注解不精确

- **文件**: `backend/app/routers/settings.py:31`
- **不修原因**: FastAPI 的 Body 解析会将 `{"value": <actual>}` 正确提取为 `value` 参数。当前类型注解虽然不精确，但运行时行为正确。修改需要验证所有调用端的请求体格式。

### B-33: `calc_cost` 未知计费类型静默返回 0

- **文件**: `backend/app/services/billing_service.py:16-22`
- **不修原因**: 当前系统只使用 `per_token` 和 `per_call` 两种计费类型。未知类型返回 0 是安全的默认行为（不产生错误计费），添加警告日志即可，不影响功能。

### B-34: 单例模式 `__new__` 非线程安全

- **文件**: `backend/app/services/task_manager.py:36-40`
- **不修原因**: 项目规则明确禁止使用 free-threaded 模式（`python3.14t`），GIL 保证了 `__new__` 的原子性。当前运行环境下完全安全。

### B-35: 模块级 `lastEventId` 跨组件实例共享

- **文件**: `frontend/src/composables/useSessionEvents.ts:3`
- **不修原因**: Sessions.vue 是唯一调用 `useSessionEvents()` 的组件，不存在多实例共享问题。改为实例级变量需要重构 SSE 连接管理逻辑。

### B-36: Map 响应式触发方式低效但正确

- **文件**: `frontend/src/stores/session.ts:21`
- **不修原因**: `new Map(oldMap)` 是 Vue3 中 `ref<Map>` 触发响应性的标准做法。当前操作频率低（每次 agent 事件更新一次），性能影响可忽略。

### B-37: `watch(messages)` 触发 `refreshAutoContext` 无防抖

- **文件**: `frontend/src/views/Sessions.vue:670`
- **不修原因**: `refreshAutoContext` 内部有条件判断（只处理最近4张图片），重复调用不会产生错误结果，只是多做了一次计算。添加防抖增加代码复杂度，收益有限。

### B-38: 9个 Schema 文件使用了 `from __future__ import annotations`

- **文件**: `backend/app/schemas/` 下 9 个文件
- **不修原因**: Python 3.14 已默认启用延迟注解求值，`from __future__ import annotations` 虽然冗余但不会产生错误。批量删除需要验证所有 Schema 的 Pydantic 行为不受影响。

### B-39: `api_manager.py` 使用 `Optional[X]` 而非 `X | None`

- **文件**: `backend/app/services/api_manager.py:2`
- **不修原因**: 纯代码风格问题，`Optional[X]` 和 `X | None` 功能完全等价。

### B-40: `prompt.py` Schema 使用 `Optional[list[dict]]`

- **文件**: `backend/app/schemas/prompt.py:11`
- **不修原因**: 同 B-39，纯代码风格问题。

### B-41: 多个 Response Schema 标注 `from_attributes=True` 但实际无法直接从 ORM 转换

- **文件**: `VendorResponse`, `ApiProviderResponse`, `SessionResponse` 等
- **不修原因**: 这些 Schema 都通过手动构造 dict 传入（如 `vendor_to_response()`），`from_attributes=True` 虽然误导但不会导致错误。移除需要验证所有构造路径。

### B-42: `ApiProvider.base_url`/`api_key_enc` nullable 与实际使用不一致

- **文件**: `backend/app/models/api_provider.py:42-44`
- **不修原因**: 模型 `nullable=True` 但 service 层存空字符串。改为 `nullable=False` 需要数据库迁移，且当前行为（存空字符串）不会导致错误。

### B-43: Plan Template Apply 前端响应类型只声明 `steps`，后端返回 `plan`+`steps`+`strategy`

- **文件**: `frontend/src/api/planTemplate.ts:15-16`
- **不修原因**: 多余字段被 TypeScript 静默忽略，不影响运行。前端当前不需要 `plan` 和 `strategy` 字段。

### B-44: Checkpoint 前端未发送 `retry_level` 字段

- **文件**: `frontend/src/api/session.ts:34-35`
- **不修原因**: 后端从 `action` 字段推导 `retry_level`，当前逻辑可正确工作。前端缺少独立控制能力但不影响功能。

### B-45: Health check 端点前端无调用

- **文件**: 后端 `GET /api/health` 存在但前端无调用
- **不修原因**: 健康检查端点用于运维监控，前端不调用是合理的设计。

---

## 分类统计

| 不修原因 | 数量 | 编号 |
|---------|------|------|
| 改动风险大于收益 | 2 | B-04, B-09 |
| 无实际影响 | 4 | B-13, B-17, B-23, B-24 |
| 类型重构范围过大 | 4 | B-18, B-19, B-26, B-27 |
| 死代码不影响运行 | 1 | B-28 |
| 代码风格/低优先级 | 16 | B-30~B-45 |
| **合计** | **27** | |
