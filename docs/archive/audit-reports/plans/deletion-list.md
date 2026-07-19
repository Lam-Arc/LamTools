# 删除清单

## 已删除

| 文件/路径 | 原因 | 删除时间 |
|-----------|------|----------|
| members/writer/backend/app/core/writer/runtime.py | WriterRuntime 类已删除，架构 100% 单轨 | 2026-06-07 |
| members/artist/backend/app/core/artist/runtime.py | ArtistRuntime 类已删除，架构 100% 单轨 | 2026-06-07 |
| members/writer/frontend/src/views/WorkbenchView.vue | Writer 旧 WorkbenchView 已删除，前端已迁移到 slot 驱动 | 2026-06-07 |
| members/artist/frontend/src/views/WorkbenchView.vue | Artist 旧 WorkbenchView 已删除，前端已迁移到 slot 驱动 | 2026-06-07 |
| core/references/ | 参考文件目录已删除 | 2026-06-07 |
| Writer 旧 runtime 测试 | 已随 WriterRuntime 一起删除 | 2026-06-07 |
| Artist 旧 runtime 测试 | 已随 ArtistRuntime 一起删除 | 2026-06-07 |
| Writer compat shims（get_active_runtime、resume_session） | 不再需要 | 2026-06-07 |

## 已从主路径移除（代码路径）

| 路径 | 原因 |
|------|------|
| artist_service.py 中 ArtistRuntime(deps=deps).handle_turn() | 已切换到 run_core_kernel() |
| app/cli.py 中 ArtistRuntime(deps=...).handle_turn() | 已切换到 run_core_kernel() |
| LAMWRITER_CORE_KERNEL 环境变量开关 | 已不存在 |
| LAMARTIST_ARTIST_CORE_KERNEL 环境变量开关 | 已不存在 |
| run_core_kernel_with_config（旧 compat 入口，接受 runtime: ArtistRuntime） | 已重命名为 run_core_kernel |
| ARTIST_RUNTIME_SYSTEM 从 runtime.py 导入 | 现从 identity.py 导入 |
| ArtistDeps 从 runtime.py 导入 | 现从 deps.py 导入 |

## 不删除

| 文件 | 原因 |
|------|------|
| WriterKit (core_kernel_adapter.py) | 仍是主路径的 Kit 实现 |
| ArtistKit (core_kernel_adapter.py) | 仍是主路径的 Kit 实现 |
| WriterHookSet (hooks.py) | 仍是主路径的 Hook 实现 |
| ArtistHookSet (hooks.py) | 仍是主路径的 Hook 实现 |
