# 当前项目会话列表控制器

user:“每一个地方 sunday 都有等价或者近似接口”+(为固定上游session.list提供明确的当前项目近似，不把插件权限扩展成全局Peer访问)。

固定上游 `deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3` 的 [`session-controller/src/index.ts`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/src/index.ts) 将 `session.list` 声明为Remote；请求和摘要字段定义见同提交的 [`session-controller/src/types.ts`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/src/types.ts)。它的请求只带可选游标，返回全局当前可见会话摘要，并逐项通过原 `remoteAccess.allows({kind:'session', id})` 过滤；完整摘要含Agent可用性、更新时间、运行/空白状态和可选父会话、cwd及投影提示。固定中文手册为同提交的 [`session-controller/README.zh.md`](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/api/session-controller/README.zh.md)。

Sunday 增加 `await context.session_controller.list_current_project(limit=50, cursor=None)`。它从受管插件上下文的固定 `work_root` 调用原 `project.resolve`，再调用已有 `workspace_registry.sessions`，沿用原SQLite会话查询、可见性复核、每页1–100项上限及绑定插件启动代/项目/工作根的不透明游标。不会启动或恢复Agent。非当前项目、不存在或被隐藏的会话不进入结果；项目或会话读取期间宿主、工作根或插件启动代失效时拒绝旧结果。取消沿原有重复取消清理等待边界结算后释放作用域租约。

参数与响应也需适配：固定上游请求只有可选 `cursor`，响应为 `{ items }`；Sunday调用还可指定 `limit`，并返回 `next_cursor`、`has_more`。迁移建议不会自动改写这些字段。

返回专用 `ProjectSessionQueryPage`：`items` 每项含 `session_id`、`title`、`status`、`title_truncated`、`updated_at_ms`、`cwd`、`running`及可空的`last_prompt_received_at_ms`，另含 `next_cursor`、`has_more`。`running`取自原会话控制服务的`SessionState.running`（有效活动回合或原运行任务），不将持久`status`用作推断；它不等同于上游独立的`agentAvailable`。时间从原Core记录 `updated_at` 转为Unix毫秒；缺失或不可转换时报 `session-query/invalid-result`。`last_prompt_received_at_ms`从本页已准入会话的原`turn/accepted`事件取最近序号的`created_at`，表示Core输入接收/写入时间；它是`lastPromptAt`的可追溯近似，不是DSH的`user/message`事件时间，也不能证明提示来源身份；没有接收事件时为`null`。DSH的`blank`由该上游自己的`turn/start`折叠语义决定，Core没有对应持久投影，不能从`snapshot_seq`或`status`推断。`cwd`仅取已验证的当前项目根，作为路径近似；它不是Sunday未持久化的逐会话运行目录。`updated_at_ms`不等同固定上游 `SessionSummary.lastPromptAt`，`cwd`也不等同 `SessionHeader.cwd`。原通用 `SessionQueryPage` 不变。项目未登记时抛 `session-controller/project-unavailable`；原项目/查询提供方会保留自己的有类型错误；无效分页参数及游标沿用 `session-query/invalid-query` 或 `session-query/invalid-cursor`。显式HTTP/Remote仍须由插件映射到自己的token POST操作；Core与插件认证、操作归属和审批继续由原路由检查。

该入口只覆盖当前插件项目，分页按原扫描顺序，不是上游全局活动顺序或完整 `SessionSummary`；Core时间近似仍无法复现精确`lastPromptAt`/`blank`，`cwd`也只是项目根提示。Sunday没有上游 `Principal`、Peer角色/授权或跨Peer列表过滤。迁移报告只给人工建议映射，不自动重写Remote调用。

新增 `core/tests/test_plugin_session_controller_current_project_list.py` 的5项验收覆盖当前项目分页、隐藏及跨项目隔离、认证HTTP、项目解析/会话扫描期间重复取消清理和迁移映射差异。解析阶段测试实际复现了重复取消后误返回成功，现由原只读清理助手等待结算并保持取消结果。仅运行该新增测试文件，5项通过。
