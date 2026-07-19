# CLI/GUI 入口优化实施审查（2026-06-30）

审查对象：`9eea308 Implement CLI and GUI entry unification` 及本轮维护修正。

## 结论

Phase 1 主干已落地，可以作为新的维护入口继续推进：

- Core 维护入口已有 `lamtools dev/build/test/open/doctor/members/scaffold`。
- Writer/Artist 会话重命名 GUI 已接线到持久化。
- Artist 根 CLI 已先在包装层提供子命令式 help 和稳定映射，旧快捷仍兼容。
- Writer `session rename/delete/show` 已补到统一会话入口。

## 本轮审查发现并处理

| 问题 | 分类 | 处理 |
|---|---|---|
| `writer session show` 出现在 help，但实际映射到 `status`，语义不准。 | 债务 | 改为请求 `/api/sessions/{id}` 并输出完整会话 JSON。 |
| `lamtools.cmd` 只检查 `py` 是否存在，不确认 `py -3.14` 可用。 | 债务 | 改为先探测 `py -3.14 --version`，失败再尝试 `python3`、`python`。 |
| `ports.json` 带 BOM 会让 Python 纯 UTF-8 读取失败。 | 已处理 | `lamtools_cli.py` 与 `member_cli.py` 均改用 `utf-8-sig`。 |
| GUI 会话重命名之前只是控件事件，没有父层持久化处理。 | 已处理 | Writer/Artist Workbench 均绑定 `rename-session`。 |

## 仍未完成

| 项 | 原因 | 下一步 |
|---|---|---|
| `writer/artist --json` 统一 envelope | 涉及成员 CLI 输出协议，不宜混在入口包装修复里。 | 单独做输出协议小阶段。 |
| `core/operations/*.json` 操作目录 | 需要定义 schema 和测试约束。 | 作为 Phase 3 实施。 |
| Provider/Model 配置 CLI | GUI 已有，CLI 对等能力未做。 | 先做查询/测试，再做 CRUD。 |
| Artist 后端 CLI 原生 argparse subparser | 当前先在根包装层收敛；后端 `app.cli` 仍是位置参数实现。 | 后续内部重构，不改变用户命令。 |
| Writer developer 命令下沉到 `writer dev ...` | 当前仍在原 `writer --help`。 | 做 alias 迁移和 deprecation。 |

## 当前推荐入口

```powershell
.\lamtools.cmd doctor all
.\lamtools.cmd dev writer all --open
.\lamtools.cmd dev artist all --open

writer run <任务...>
writer session show <session-id>
writer session rename <session-id> "新标题"

artist run <指令...>
artist session rename <session-id> "新标题"
```

## 验收建议

- 每次新增外部入口时同步 `docs/cli-guide.md`、`docs/gui-guide.md`。
- 新增成员能力前先决定是 Core 维护入口还是 Member 产品入口。
- 普通 help 不继续扩大，调试和开发入口迁到 developer 层。
