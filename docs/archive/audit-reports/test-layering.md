# 测试分层说明

维护标注（2026-07-08）：当前活跃产品成员只有 Writer；已下线的旧成员不再作为测试分层对象。`scripts/test.ps1 all` 只覆盖 Core 后端和 Writer 后端，前端与 E2E 仍需按下方命令显式运行。

## 分层

| 层级 | 位置 | 速度 | 依赖 | 运行频率 |
|------|------|------|------|----------|
| **unit** | `members/writer/backend/tests/test_*.py` | 快（<1s/用例） | 纯逻辑，无 LLM、无 DB、无文件系统 | 每次提交 |
| **contract** | `members/writer/backend/tests/test_writer_core_http.py` 等 | 中 | 前后端协议 fixture，SSE 格式 | 每次提交 |
| **smoke e2e** | `e2e/tests/*.spec.ts` | 中 | 前端 dev server 在线 | CI 或手动 |
| **real e2e** | `members/writer/backend/tests/e2e_*.py`、`send_task.py` 等 | 慢（分钟级） | 真实 LLM、后端在线 | 夜间或手动 |

## unit

- 纯函数、纯逻辑
- 不依赖 LLM、数据库、文件系统
- 示例：`test_git_context.py`、`test_scope_guard.py`、`test_context_specs.py`
- 运行：`py -3.14 -m pytest members/writer/backend/tests/test_git_context.py -q`

## contract

- 验证前后端协议：SSE 事件格式、API 请求/响应结构
- 用 fixture 而非真实后端
- 示例：`test_writer_core_http.py`、`test_writer_core_kernel_adapter.py`

## smoke e2e

- 用 Playwright 打开前端页面
- 只验证 shell 加载（composer、session 区域存在）
- 不接真实 LLM
- 需要先启动前端 dev server
- 运行：`cd e2e && npm run test:smoke`

## real e2e

- 接真实 LLM，可能修改本地任务文件
- 脚本式 E2E 在 `members/writer/backend/tests/` 下
- **不能直接全量 pytest**——部分文件是脚本不是测试用例
- 已加 `if __name__ == "__main__":` 保护的文件：`bench_v2.py`、`bench_v3.py`、`self_contained_test.py`、`quick_api_test.py`、`send_task.py`、`demo_constraint_validator.py`
- 运行方式：单独执行脚本，如 `py -3.14 members/writer/backend/tests/send_task.py`

## 当前 pytest 安全范围

以下文件可以安全地一起 pytest 收集和运行：

```
members/writer/backend/tests/test_*.py
```

不要全量 `pytest members/writer/backend/tests/`，因为脚本式文件不是 pytest 用例。
