<!-- codex-workflow-id: viettran-edgeAI/codex_workflow -->
<!-- codex-workflow-managed-start -->
<!-- codex-workflow-managed-end -->

## 项目事实

- "core/"：主程序；"website/"：官网。
- 后端 Python/Rust 混合架构，渐进式 Rust 重构；前端 Vue/TypeScript，桌面 Tauri。
- 桌面重启：完全退出应用，在 "core/desktop/" 执行 "npm run tauri dev"。
- "scripts/dev.ps1"、"scripts/restart.ps1" 属于独立开发环境，不管理 Tauri。
- 数据："data/core.db"；配置：".lam/core/config/"；文档："agent_docs/"。

## 开发规则

1. 只考虑桌面端，完全排除移动端需求和限制。

2. 修改代码前充分理解用户需求；存在疑问时及时询问。

3. 先设计能充分证明需求达成的验收测试，先编写测试，再实现功能。

4. 仅运行本次新增的相关测试，不运行全量测试

5. 使用普通人能理解的语言与用户交流，避免技术术语。

6. 修复 Bug 时优先排查架构缺陷，优先考虑通过 Rust 重构解决根本问题。采用渐进式迁移，保留可靠的 Python 实现。

7. 修改代码时，在对应位置添加注释，格式为：
   
   "user:“用户原文”+(你理解的需求)"
   
   引用用户实际原话，并简要说明对应代码要满足的需求。

8. 执行命令时设置合理的完成条件与停止条件，不依赖超时结束。
