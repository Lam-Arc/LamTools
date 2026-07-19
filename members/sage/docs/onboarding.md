# LamSage 接入说明

## 产品层

- `backend/app/member/`：Sage 身份、系统策略、manifest 与验证规则。
- `plugin/sage-builtin/`：可在任意用户工作区发现的内置 Skills 与 Trace/Map 契约。
- `frontend/`：共享 WorkspaceShell 上的 Sage 会话、运行状态、Goal 和 Arrange 界面。

## Core 复用

- 后端由 `create_core_agent_http_app` 装配 Sage spec，不复制 HTTP、Loop 或 app-server。
- `read_file` 在 Core 内统一处理文本、DOCX 与 PDF。
- GUI 和 CLI 都连接 `/api/core/app-server`；同步 HTTP `/turns` 用于简单调用方。
- Goal、Arrange、observer、审批、附件、事件、快照和重启恢复均使用 Core 实现。

## 新增 Sage 工作流

只有可复用的研究方法才新增 Skill。每个 Skill 必须：

1. 说明触发条件和完成标准；
2. 读取并遵守 `TRACE_MAP_CONTRACT.md`；
3. 默认寻找独立来源、冲突和反证；
4. 明确一次性执行与持续执行的边界；
5. 委派时要求 evidence package 或受限写入范围内的 artifact path。

不要为单个工作流新增平行路由、Loop、数据库或专用 Agent 服务。
