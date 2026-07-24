# Artist 跨轮次图片上下文改进 Implementation Plan

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Artist LLM 能看到历史轮次中讨论过的图片，并在"参照X改Y"意图时正确识别和区分参考图与目标图。

**Architecture:** 三层改进：(1) 在构建 Artist 历史消息时，把历史图片作为 vision content block 注入；(2) 在 artist_service 中从 DB 查询历史 session_images 并传入 context_images；(3) 为 turn_parser 的空 actions 场景增加警告日志。

**Tech Stack:** Python / FastAPI / SQLAlchemy async / OpenAI vision API

---

## Task 1: 增加历史图片 vision 注入

**Files:** `backend/app/services/artist_service.py`

**Steps:**
- [ ] 在 `artist_orchestrate` 函数中，新增参数 `history_context_images: list[str] | None = None`
- [ ] 在构建历史消息的循环中（约 line 139-160），当遍历 `history_messages` 时，对每条 user 消息检查其 metadata 中的 `reference_images`（base64 图片）或 `image_urls`（HTTP URL），将图片作为 `image_url` content block 注入到对应的历史 user 消息中
- [ ] 对历史 assistant 消息，如果 metadata 中有 `artist_artifacts` 且包含 `url`，同样注入为 vision block
- [ ] 限制历史 vision 图片数量最多 6 张（取最近的），避免 token 爆炸
- [ ] 使用 `ImageClient.urls_to_base64` 转换 localhost URL 为 base64，和现有 context_images 逻辑一致

**Verification:**
- [ ] 启动后端，在 Artist 会话中先发图1问风格，再发图2说"参照之前那张改"，检查 Artist 回复是否能看到图1
- [ ] 检查 LLM messages 中历史 user 消息是否包含 image_url content blocks

**Commit:** `feat(artist): inject historical images as vision blocks into Artist LLM messages`

---

## Task 2: 从 DB 查询历史 session_images 并传入 Artist

**Files:** `backend/app/services/generate_service.py`, `backend/app/services/artist_service.py`

**Steps:**
- [ ] 在 `_run_artist_orchestrate` 中（约 line 875-920），调用 `_build_session_images(db, session_id)` 获取历史图片列表
- [ ] 从 session_images 中提取 HTTP URL（排除 data: base64，因为太大），按时间倒序取最近 4 张
- [ ] 将这些 URL 作为新参数 `history_context_images` 传入 `artist_orchestrate`
- [ ] 在 `artist_orchestrate` 中将这些 URL 转为 base64（使用 `ImageClient.urls_to_base64`），注入到历史消息的 vision blocks

**Verification:**
- [ ] 在 Artist 会话中先生成一张图，再在新轮次中说"改成线稿"，检查 Artist 是否能看到之前生成的图
- [ ] 检查 `_build_session_images` 返回的数据是否包含 HTTP URL

**Commit:** `feat(artist): pass historical session images from DB to Artist orchestration`

---

## Task 3: 为 turn_parser 增加空 actions 警告日志

**Files:** `backend/app/core/artist/turn_parser.py`

**Steps:**
- [ ] 在 `parse_artist_turn` 函数中（约 line 52），当 `actions` 为空时，增加 `logger.warning` 记录原始文本前 500 字符
- [ ] 在 `runtime.py` `_handle_turn_inner` 中（约 line 197-198），在 `parse_artist_turn` 返回后增加日志：`logger.info(f"Artist turn parsed: actions={len(turn.actions)}, phase={turn.next_phase}")`
- [ ] 当 `turn.actions` 为空时，增加 `logger.warning(f"Artist turn has NO actions: raw_text preview={full_text[:300]}")`

**Verification:**
- [ ] 运行后端，触发 Artist 纯聊天回复（无 generate action），检查日志中出现 WARNING
- [ ] 确认日志不会泄露完整 base64 图片数据（截断到合理长度）

**Commit:** `feat(artist): add warning logging when Artist turn has no actions`

---

## Task 4: 改进 image_context_resolver 的 STYLE_REF 模式匹配

**Files:** `backend/app/services/image_context_resolver.py`

**Steps:**
- [ ] 在 `STYLE_REF_INTENT_PATTERNS` 中（约 line 60-66）增加更多自然表达模式：`r"参照.*改", r"参考.*改", r"用.*改", r"参照.*修改", r"参考.*修改", r"照.*改", r"用.*风格改", r"参照.*风格.*改", r"参考.*来改"`
- [ ] 在 `resolve_image_context` 方法中，当 intent 为 `style_reference` 且有多张 session_images 时，把最近的图作为 edit target，把之前的图作为 style reference（而不是把最近图当 reference）

**Verification:**
- [ ] 测试 `detect_image_intent("你能参照这个图来改一下我现在发你这张吗？")` 返回 `style_reference` 而非 `edit_target`
- [ ] 测试 `detect_image_intent("参考之前的风格改这张")` 返回 `style_reference`

**Commit:** `feat(resolver): expand STYLE_REF patterns and improve multi-image style_reference resolution`

---

## Task 5: 扩展 `_extract_context_image_urls_from_messages` 提取用户上传图片

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] 在 `_extract_context_image_urls_from_messages`（约 line 1370-1378）中，除了提取 `image_urls`，也提取用户消息 metadata 中的 `reference_images`（HTTP URL 部分，过滤掉 data: base64）
- [ ] 对 `reference_images` 中的 data: URL，因为 base64 太大不适合作为 LLM vision 输入的 URL（需要先转成可访问的 HTTP URL），暂不处理，只提取 HTTP URL

**Verification:**
- [ ] 检查 context_images 是否包含用户之前上传的图片的 HTTP URL
- [ ] 确认 data: URL 不会被错误提取（过滤条件正确）

**Commit:** `feat(generate): extract user upload URLs from metadata into context_images`

---

## Task 6: 综合验证 — 重现原始 bug 并确认修复

**Files:** 无代码修改，仅验证

**Steps:**
- [ ] 启动后端 + 前端
- [ ] 新建 Artist 会话，发图1问"这个图是什么风格"
- [ ] Artist 回复后，发图2说"参照之前那张图来改这张"
- [ ] 验证 Artist 回复中能识别图1作为参考图，不再说"我这边只看到你要改的这张"
- [ ] 验证 Artist 触发了 generate action（不再是纯 chat_only）
- [ ] 检查日志确认 actions 不为空

**Verification:**
- [ ] Artist 在第2轮对话中能看到图1的像素内容
- [ ] Artist 不再说"请发参考图"
- [ ] 日志中有 actions 解析记录

**Commit:** 无（验证任务）