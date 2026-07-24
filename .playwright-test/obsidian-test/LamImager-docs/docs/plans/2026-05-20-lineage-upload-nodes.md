# 谱系树包含用户上传参考图 Implementation Plan

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 谱系树展示用户上传参考图，并通过连线展示参考图与生成图之间的血缘关系。

**Architecture:** 在 `_build_session_images` 中，将 anchor artifact 的 `parent_artifact_id` 指向对应的用户上传图（`upload-{msg.id}-{i}`）。在 `build_lineage_tree` 中不再过滤 `is_user_upload`，让上传图作为根节点出现在树中。前端 `LineageNode` 对上传节点做视觉区分（不同图标/标签）。

**Tech Stack:** Python / FastAPI / Vue3 / TypeScript

---

## Task 1: `_build_session_images` 关联 anchor 与上传图

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] 在 `_build_session_images` 中，查询所有消息（user + assistant）按时间排序，追踪"最近一个带 reference_images 的用户消息"
- [ ] 当遇到 anchor artifact（`artifact_type == "anchor"` 且 `parent_artifact_id == ""`）时，检查是否有对应的上传图
- [ ] 如果有，将 anchor 的 `parent_artifact_id` 设为 `upload-{msg.id}-{i}`（第一个上传图的 artifact_id）
- [ ] 如果有多个上传图，anchor 的 `parent_artifact_id` 指向第一个，其余上传图通过 `parent_artifact_id` 串联（或都指向 anchor 作为 sibling）
- [ ] 为上传图的 `SessionImage` 补充 `artifact_type = "upload"` 和 `root_artifact_id = artifact_id`

**Verification:**
- [ ] 运行 `test_user_upload_in_session_images_for_original_ref` 通过
- [ ] 运行 `test_user_upload_filtered_from_lineage_tree` 需要更新（因为不再过滤）

**Commit:** `feat(lineage): anchor artifacts link to user upload parents`

---

## Task 2: `build_lineage_tree` 包含上传图节点

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] 移除 `if not aid or img.is_user_upload: continue` 中的 `img.is_user_upload` 过滤
- [ ] 上传图节点正常加入 `nodes` dict，其 `parent_artifact_id` 为空（作为根节点）
- [ ] anchor 的 `parent_artifact_id` 指向上传图，连线自动建立

**Verification:**
- [ ] 更新 `test_user_upload_filtered_from_lineage_tree` → 改为验证上传图**在**树中
- [ ] 运行全部测试通过

**Commit:** `feat(lineage): include user uploads in lineage tree`

---

## Task 3: Lineage API 清理上传图 data URL + 补充 artifact_type

**Files:** `backend/app/routers/session.py`

**Steps:**
- [ ] 在 `get_lineage_tree` 的 `_clean_url` 逻辑中，上传图的 data URL 已被清空（现有逻辑覆盖）
- [ ] 确认返回的节点中上传图有 `artifact_type: "upload"`，前端可据此做视觉区分

**Verification:**
- [ ] 手动调用 API 验证上传图节点出现在树中，`artifact_type` 为 `"upload"`

**Commit:** `fix(lineage): upload nodes have correct artifact_type in API`

---

## Task 4: 前端 `LineageNode` 区分上传节点

**Files:** `frontend/src/components/session/LineageNode.vue`

**Steps:**
- [ ] 当 `node.artifact_type === "upload"` 时，显示上传图标（Lucide `Upload` icon）而非图片缩略图
- [ ] 上传节点的标签显示"参考图"而非 branch_name
- [ ] 上传节点不可 rollback（不显示 HEAD 标记，不可选中回退）

**Verification:**
- [ ] `npm run build` 通过

**Commit:** `feat(lineage): visual distinction for upload nodes`

---

## Task 5: 测试覆盖

**Files:** `backend/tests/test_reference_images_roundtrip.py`

**Steps:**
- [ ] 更新 `test_user_upload_filtered_from_lineage_tree` → 验证上传图在树中作为根节点
- [ ] 新增测试：anchor 有 reference_images 时，其 `parent_artifact_id` 指向 `upload-*`
- [ ] 新增测试：上传图节点 `artifact_type == "upload"`
- [ ] 新增测试：无 reference_images 的 anchor，`parent_artifact_id` 为空

**Verification:**
- [ ] 全部测试通过

**Commit:** `test(lineage): upload nodes in lineage tree with parent linkage`
