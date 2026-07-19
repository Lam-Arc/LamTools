# Writer Frontend + CLI

Writer now has two supported clients:

- Web frontend: `frontend/`, served on port `6174`
- CLI: `backend/writer_cli`, run with `py -3.14 -m writer_cli`

The old Textual TUI remains in the tree for reference, but it is no longer the preferred client.

## Backend

```powershell
cd E:\LamTools\members\writer\backend
py -3.14 -m uvicorn app.main:app --reload --port 6173
```

## Frontend

```powershell
cd E:\LamTools\members\writer\frontend
npm.cmd run dev
```

Open:

```text
http://localhost:6174
```

No frontend install step is required. The app is static HTML/CSS/JS and talks to the backend at `http://127.0.0.1:6173`.
Do not use `file:///.../frontend/index.html` directly; the page redirects to the local server because browser module loading blocks local files.

## CLI

```powershell
cd E:\LamTools\members\writer\backend
py -3.14 -m writer_cli health
py -3.14 -m writer_cli list
py -3.14 -m writer_cli new "Writer Session" --work-root E:\LamTools\members\writer
py -3.14 -m writer_cli chat <session_id> "检查当前项目状态" --work-root E:\LamTools\members\writer
py -3.14 -m writer_cli quick "创建 hello.txt" --work-root E:\LamTools\members\writer
```

CLI 与前端使用同一条后端 `/chat` SSE 流。新代码优先消费 canonical 事件：

- `writer_progress.loop_position=llm_call_started` → `model request #N`
- `writer_message` → `message:*` 或 `reply`
- `writer_response output_type=thought` → `llm`
- `writer_step` → `tool` / `file` / `step` / `agent` / `verify`
- `writer_progress.workflow` → `workflow`
- `writer_progress.mode` → `mode`
- `writer_progress.verification` → `verify`
- `writer_decision` → 展示决策标题、原因、选项，并在交互模式下等待输入
- `writer_git` → Git 分支、快照、checkpoint、merge
- `writer_lifecycle` → done / failed / error / resumed / cancelled

旧事件名仍兼容，但不要再为 CLI 单独设计一套事件协议。CLI 除完整逐字日志外默认展示全部业务信息；后续显隐应按行首标签配置。

显示逻辑按最终归宿分组：`writer_reply`、`user_message`、`decision_card`、`sub_line`、`processed_flow`、`git_panel`、`error_card`、`status_bar`、`debug_log`。CLI 行首标签映射到这些分组；GUI 用同一组名决定气泡、决策卡、sub line、过程折叠、Git 面板或错误卡。

Set a different backend:

```powershell
$env:LAMWRITER_API_URL = "http://127.0.0.1:6173"
```
