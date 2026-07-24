# LamImager — AI Image Generation Manager

开发过程中严禁使用批量替换功能

## Quick Reference

- Architecture: Python 3.14+ / FastAPI / SQLAlchemy async / Vue3 / Pinia
- UI: 黑白灰极简 (#FAFAFA / #000 / #E5E5E5), Lucide icons, 无 emoji
- Entry: `backend/app/main.py` → routers → services → models
- Frontend: `frontend/src/views/Sessions.vue` (主页面, 三栏布局)
- Plan authority: `docs/plans/PLAN.md` controls execution order; `docs/ROADMAP.md` defines P3/P4 technical tasks

## Doc Index

| Topic | File |
|-------|------|
| 总控计划 / 执行顺序 | `docs/plans/PLAN.md` |
| P3/P4 技术路线 | `docs/ROADMAP.md` |
| PER/CON/PLAN/Skill/MEM 心智模型 | `docs/mental-model.md` |
| LamTools 哲学探讨 | `docs/lamtools-philosophy.md` |
| LamTwo 人格画像 | `docs/lamtwo-persona-v0.1.md` |
| LamTools 生态设计 | `docs/lamtools-ecosystem.md` |
| Artist P4 前完成计划 | `docs/plans/2026-05-18-artist-before-p4-completion.md` |
| Artist 真人感架构设计 | `docs/plans/2026-05-19-artist-realism-architecture.md` |
| 设计语言 / 品牌语义 | `docs/design-language.md` |
| Coder/Writer 设计 | `docs/coder-architecture.md`, `docs/coder-per-v1.md` |
| Writer 架构设计 | `docs/plans/2026-05-20-writer-architecture.md` |
| Mate 架构设计 | `docs/plans/2026-05-21-mate-architecture.md` |
| Butler 人格设计 | `docs/butler-per-v1.md` |

## Code Index

| Topic | File |
|-------|------|
| Runtime 主入口 | `backend/app/services/generate_service.py` (`handle_generate` → `handle_artist_generate`) |
| 统一执行引擎 | `backend/app/services/executors/engine.py` |
| 图像生成核心 | `backend/app/utils/image_client.py` |
| Artist 编排 | `backend/app/services/artist_service.py` |
| Artist Runtime | `backend/app/core/artist/runtime.py` (`ArtistRuntime`, `handle_turn`) |
| Artist Schemas | `backend/app/core/artist/schemas.py` (`ArtistAction`, `ArtistTurn`, `ArtistSessionState`, `ArtistArtifact`) |
| Artist State Store | `backend/app/core/artist/state_store.py` |
| Artist Turn Parser | `backend/app/core/artist/turn_parser.py` |
| Artist Events | `backend/app/core/artist/events.py` |
| Artist Artifacts | `backend/app/core/artist/artifacts.py` |
| Artist Transitions | `backend/app/core/artist/transitions.py` |
| Artist Feedback | `backend/app/core/artist/feedback.py` |
| Artist Tool Loop | `backend/app/core/artist/tools.py`, `backend/app/core/artist/complex_task.py` |
| Image Context Resolver | `backend/app/services/image_context_resolver.py` (`SessionImage`, `is_original_ref`, `is_rollback_ref`, `_resolve_rollback_target`, `PREV_REF_PATTERN`) |
| Visual Workspace | `backend/app/services/visual_workspace.py` |
| Lineage Tree Builder | `backend/app/services/lineage_service.py` |
| Lineage API | `backend/app/routers/session.py` (`GET /lineage-tree`, `PUT /lineage/head`, `PUT /lineage/branch-rename`) |
| Artist 路由 | `backend/app/services/generate_service.py` (`handle_artist_generate`) |
| SSE 事件 | `backend/app/core/events/` |
| 前端组件 | `frontend/src/components/session/` |
| 前端 Runtime progress | `frontend/src/stores/session.ts` (`runtimeProgressStates`, `handleRuntimeEvent`) |
| API 端点 | `backend/app/routers/` |

## Non-Authoritative References

- `docs/progress-log.md` is a history log, not current architecture truth.
- `docs/plans/archive/`, `docs/learning files/`, and `reference-repos/` are background references only.
- `docs/architecture*.md`, `docs/api-reference*.md`, and `docs/runbook*.md` may lag behind code; verify against source before relying on details.

## Key Patterns

- Runtime-only: all generate requests enter Artist Runtime; old Agent/Skill/Rule/PlanTemplate paths are removed from active API/UI.
- Artist Mode: Runtime prompt + CON/visual workspace → LLM/VLM → JSON(message + actions/tool calls) → schema parse → execute actions → artist_* SSE → artifact metadata → CON/writeback.
- Artist SSE: artist_turn_started → artist_reply_delta → artist_action_started → artist_image_ready → artist_turn_done (plus legacy artist_token/artist_done)
- img2img fallback: chat_edit → edit → vision+generate
- Strategy routing: Artist actions → ExecutionEngine strategy + PlanStep.
- Artist turn: LLM outputs JSON with `message` + `actions`; backend parses via `turn_parser`, executes through Runtime tools, returns `blocks` + `artifacts`.
- Artist options: `artist_pack_count` / `artist_model_mode` / `artist_anchor_first` from GenerateRequest → artist_orchestrate → ArtistRuntime.handle_turn
- Artist clarification: `ask_clarification` action → `phase=waiting_clarification` → message saved with `metadata.clarification=true`
- Lineage DAG: message metadata as source of truth → `build_lineage_tree()` rebuilds from `SessionImage` list → auto-fork when HEAD has children → rollback = switch HEAD only (git checkout semantics) → branch auto-name + user rename
- Removed feature log: `docs/runtime-removed-feature-inventory.md`

## Dev Commands

```bash
cd backend && py -3.14 -m uvicorn app.main:app --reload --port 6171
cd frontend && npm run dev
```

### Artist CLI

```bash
cd backend
py -3.14 artist.py session new
py -3.14 artist.py session ls
py -3.14 artist.py session <uuid>
py -3.14 artist.py session <uuid> "用户消息"
py -3.14 artist.py ct "复杂任务目标"
py -3.14 artist.py image "生图 prompt"
py -3.14 artist.py --mock image session <uuid> "用户消息"
py -3.14 artist.py --mock all "用户消息"
```

- `session new` 新建会话，`session ls` 列出会话名称与 UUID。
- `session <uuid>` 进入同一会话的交互模式；`session <uuid> "用户消息"` 等同于在前端向该会话发送一轮消息。
- `ct "复杂任务目标"` 进入 complex_task 实验模式，内部按 observe → decide → tool → observe 的 loop 执行，可用 `--max-steps` 控制轮数。
- `image "生图 prompt"` 绕过 Artist，直接把 prompt 发送给默认生图 API。
- `--mock` / `--mock image` 只拦截生图，LLM 仍真实调用；`--mock all` 同时拦截 LLM 与生图。

## Rules

- No emoji, Lucide SVG only
- No card stacking, tables + side drawers
- Billing in topbar
- API keys: AES-256-GCM encrypted
- 添加功能前先检查已有路径/服务/组件能否复用，优先扩展而非新增。新加复杂度远超价值时，选更简单的方案。
- New endpoint: router → service → schema → api client → store
- 说中文

### 测试规则（严格执行）

> **进行 e2e 测试时使用 `e2e-testing` skill** —— 执行 `skill(name="e2e-testing")` 加载完整规范。

**三种测试类型，边界不可混淆：**

| 类型 | 文件命名 | Mock 允许？ | 定义 |
|------|---------|------------|------|
| **单元测试** | `test_*_unit.py` | ✅ 允许 mock 外部依赖 | 测试单个函数/类的逻辑正确性 |
| **集成测试** | `test_*_pipeline.py` | ⚠️ 可 mock 外部 API（LLM/生图），不可 mock 内部模块 | 测试多个模块之间的协作流程 |
| **端到端测试 (e2e)** | `test_*_e2e.py` | ❌ **严禁任何 mock** | 从 HTTP 客户端发送消息到后端，完整链路，真实 API 调用 |

**e2e 测试铁律：**
- 必须启动真实后端服务（`uvicorn`）
- 必须配置真实 API provider（LLM + 生图），不可 mock `LLMClient`、`generate_images_core`、`ImageClient`
- 必须通过 HTTP 客户端（`httpx` / `requests` / 前端 Playwright）发送请求
- 必须验证真实返回结果（文本内容、图片 URL 可访问性、SSE 事件序列）
- **所有测试场景必须在同一个 session 内完成**——创建一次 session，多轮对话，模拟真实用户在同一个窗口中的聊天流程。每个测试函数独立创建 session 视为违规
- `test_*_e2e.py` 中出现 `mocker.patch`、`AsyncMock`、`MagicMock`、`unittest.mock` 视为**违规**
- 如果 API 不可用，e2e 测试标记 `skip`，不得退化为 mock 测试

**示例——e2e 测试正确写法（单 session 多轮对话）：**
```python
# test_artist_e2e.py — 无 mock，一个 session 内完成所有对话
import httpx

@pytest.mark.e2e
async def test_artist_full_conversation():
    async with httpx.AsyncClient(base_url="http://localhost:6171") as client:
        sid = await create_session(client)  # 只创建一次

        # Turn 1: 寒暄
        await chat(client, sid, "你好呀")
        msg = await wait_for_artist_reply(client, sid)
        assert msg["message_type"] == "artist"
        assert msg.get("content")  # 有回复文本

        # Turn 2: 知识问答（同一 session）
        await chat(client, sid, "什么是赛博朋克风格")
        msg = await wait_for_artist_reply(client, sid)
        assert len(msg.get("content", "")) > 20  # 长回复未截断

        # Turn 3: 生图（同一 session）
        await chat(client, sid, "画一只赛博朋克风格的猫")
        msg = await wait_for_artist_reply(client, sid)
        assert len(msg["metadata"].get("artifacts", [])) >= 1  # 有图片
```

**示例——集成 pipeline 测试正确写法：**
```python
# test_artist_pipeline.py — 只 mock 外部 API，内部模块真实调用
mocker.patch("app.services.artist_service.LLMClient.chat_stream", new=...)  # mock LLM
result = await handle_artist_generate(test_db, ...)  # 内部模块全真
assert result["phase"] == "idle"
```
