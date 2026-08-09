# 待办事项（按优先级排序）

> 排序依据：简单的在前 → 工程量大的在后 → 收益不明显的靠后。
> 记录日期：2026-08-09　完成日期：2026-08-09（全部完成）

## 1. 会话模型记忆（已完成）✅

- 每个会话记住自己选择的模型（如：会话 A 选 DeepSeek-V4 Pro，会话 B 选 MIMO V2.5），来回切换不串扰。
- 实现：切会话时从 `session.metadata.model_id` 恢复（`demo/App.vue` `restoreSessionModel`）；选模型时 PATCH 写入会话 metadata。分叉会话自动继承源会话模型。

## 2. 分叉（fork）bug 修复（已完成）✅

- 根因（3 处）：
  1. `_replace_session_id` 只重映射 dict 的 value 不重映射 key → 分叉后 items 字典与 item_order 失联，前端丢弃全部历史消息（新消息独占顶部）。
  2. fork 复制事件时 `event_id` 全局主键冲突 → 带事件的分叉直接 500。
  3. `_upsert_item` 用 payload seq（恒为 1）而非 envelope seq 做排序锚点。
- 均已修复 + 回归测试（`test_fork_with_events_remaps_item_keys_and_regenerates_event_ids`，验证还原旧代码会失败）。

## 3. 配置文件统一目录整理（已完成）✅

- 统一目录：`.lam/core/config/`（`core_config_dir()`，原 `.lam/core/config` 约定扩展为全部配置）。
- 首启自动创建并内置默认文件：loadtools.jsonc、access_tools.jsonc、hooks.json、AGENTS.md、load_context.jsonc、memory.md、subagent/guide.md、subagent/settings.json、models/（`config/defaults.py`，幂等不覆盖用户编辑）。
- 挂载点：desktop_backend 启动、cli serve、cli setup。
- 全局 AGENTS.md / models/ / subagent/ 从 `~/.lam/config` 迁入统一目录（旧路径保留只读回退）。
- 全局 load_context.jsonc 与 memory.md 新层级生效（叠加/注入所有工作区）。
- 打包：spec 补齐 config/resources、config/command、config/llm_adapters。
- 测试隔离：conftest autouse fixture 把所有配置根指到临时目录。

## 4. 节点回退重构（已完成）✅

- 6 上限按 **turn 计数**（`actor_kind == "main"`），回退产生的 undo/derived 记账节点不占窗口 → **保证始终可回退 6 次**（新增测试验证）。
- 懒加载保持：只备份工具将要修改的文件、回退只恢复这些文件；运行命令等不管。
- 绝不拍照：移除回退时对工作区的 `rglob` 全量扫描（`_remove_empty_directories` 改为仅沿恢复文件父目录向上清理）。
- 说明：已创建文件不回退删除（保守语义，只恢复备份过的修改）。
