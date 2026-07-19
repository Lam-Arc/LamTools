<!-- 历史参考，不代表当前架构 -->
# 阶段五：Writer / Artist 遗留小毛病修复

## Artist 修复

### 1. `has_passed_output_artifact` 排除 imported_context 产物

**问题**：`has_passed_output_artifact` 把 `imported_context=True` 的参考图当作"已通过输出产物"，导致目标需要图片输出时，仅凭参考图就误判为"已有通过产物"，提前完成。

**修复**：`visual_review.py:89-99` — 增加 `imported_context` 跳过。

**测试覆盖**：`test_new_batch_request_cannot_complete_from_prior_passed_image` — 第一次 LLM 返回 `is_complete=true` 但没有实际产出，必须继续循环。

### 2. Artist 工具规格独立化

**问题**：Artist 的 4 个工具（generate_image, delegate_agent, finish, ask_user）只定义在系统提示词中，没有独立的 schema/权限/失败形态描述。

**修复**：新增 `tool_specs.py`，包含：
- `ARTIST_TOOL_SPECS`：每个工具的 name、description、input_schema、permission、failure_modes、recovery
- `ARTIST_TOOL_PERMISSIONS`：工具→权限层级映射
- `artist_tool_spec(name)`：按名查找

**风险**：低。新文件，不影响现有行为。现有系统提示词中的工具描述保持不变。

## Writer 修复

### 无新修复

Writer 的 147 个核心测试全部通过。Writer runtime.py 6241 行，修改风险高，本轮不动。

## 未修项（记录，不硬改）

| 问题 | 原因 | 建议 |
|------|------|------|
| Writer hooks 散落在 runtime.py | 6241 行，改错代价大 | 后续 Writer runtime 拆分时统一 |
| Writer 上下文注入分散 | 多处 inline 注入 | 抽成 hooks 模块 |
| Writer 最终验收只看 CompletionVerifier | 不结合产物/测试/未解决问题 | 增强验收逻辑 |
| Artist delegate_agent 仍是 stub | service/CLI 传入 None | 需要实现侧配合 |
| Artist CLI 和 HTTP 表现不完全一致 | CLI 直接构造 runtime，HTTP 走 service | 后续统一入口 |
