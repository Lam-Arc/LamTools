# Artist Lineage DAG Implementation Plan

> **For agentic workers:** Use executing-plans skill to implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Artist image lineage work like git — every derivation is a DAG node with auto-branching, HEAD pointer, rollback, and branch naming. Frontend shows a side-drawer tree visualization.

**Architecture:** Every generated image is a `LineageNode` with `artifact_id`, `parent_artifact_id`, `root_artifact_id`, `branch_name`. The tree is rebuilt from message metadata (no new DB table). `ArtistSessionState` tracks `head_artifact_id`, `active_branch`, `branch_labels`. Frontend gets tree via API, renders in `LineageDrawer.vue`.

**Tech Stack:** Python 3.14+ / FastAPI / Pydantic / Vue3 / Pinia / CSS tree lines

---

## Task 1: Extend ArtistArtifact with branch_name

**Files:**
- `backend/app/core/artist/schemas.py`
- `backend/app/core/artist/artifacts.py`
- `backend/tests/test_artist_artifacts.py`

**Steps:**
- [ ] Step 1: In `schemas.py`, add `branch_name: str = ""` field to `ArtistArtifact` after `source_message_id`.
- [ ] Step 2: In `artifacts.py`, add `branch_name: str = ""` parameter to `build_image_artifacts()`, pass it to `ArtistArtifact(branch_name=branch_name)`.
- [ ] Step 3: In `test_artist_artifacts.py`, add `test_build_image_artifacts_sets_branch_name()` that calls `build_image_artifacts(urls=["https://x/a.png"], artifact_type="anchor", artist_turn_id="t1", group_id="g1", branch_name="main")` and asserts `arts[0].branch_name == "main"`.
- [ ] Step 4: Run `py -3.14 -m pytest tests/test_artist_artifacts.py -v` and confirm all pass.

**Verification:**
- [ ] `py -3.14 -m pytest tests/test_artist_artifacts.py -v` passes.

**Commit:** `feat: add branch_name to ArtistArtifact`

---

## Task 2: Extend ArtistSessionState with HEAD/branch fields

**Files:**
- `backend/app/core/artist/schemas.py`
- `backend/tests/test_artist_state_store.py`

**Steps:**
- [ ] Step 1: In `schemas.py`, add to `ArtistSessionState` after `anchor_first`:
  ```python
  head_artifact_id: str = ""
  active_branch: str = "main"
  branch_labels: dict[str, str] = {}
  branch_counter: int = 0
  ```
- [ ] Step 2: In `test_artist_state_store.py`, add `test_state_defaults_have_head_and_branch()` that creates a new state via `ArtistStateStore().get("s1")` and asserts `state.head_artifact_id == ""`, `state.active_branch == "main"`, `state.branch_labels == {}`, `state.branch_counter == 0`.
- [ ] Step 3: Add `test_state_update_head_and_branch()` that calls `store.update("s1", head_artifact_id="art-1", active_branch="分支-1", branch_counter=1)` and asserts the values are set.
- [ ] Step 4: Run `py -3.14 -m pytest tests/test_artist_state_store.py -v`.

**Verification:**
- [ ] `py -3.14 -m pytest tests/test_artist_state_store.py -v` passes.

**Commit:** `feat: add HEAD/branch fields to ArtistSessionState`

---

## Task 3: Create LineageNode and LineageTree dataclasses

**Files:**
- `backend/app/core/artist/schemas.py`
- `backend/tests/test_lineage_tree.py`

**Steps:**
- [ ] Step 1: In `schemas.py`, add after `ArtistArtifact`:
  ```python
  @dataclass
  class LineageNode:
      artifact_id: str
      url: str
      parent_artifact_id: str
      root_artifact_id: str
      branch_name: str
      artifact_type: str
      prompt: str
      children: list[str] = field(default_factory=list)
      created_at: str = ""

  @dataclass
  class LineageTree:
      nodes: dict[str, LineageNode] = field(default_factory=dict)
      roots: list[str] = field(default_factory=list)
      head_artifact_id: str = ""
      active_branch: str = "main"
      branch_labels: dict[str, str] = field(default_factory=dict)
  ```
  Add `from dataclasses import dataclass, field` import at top if not present.
- [ ] Step 2: Create `test_lineage_tree.py` with `test_lineage_node_defaults()` that creates a `LineageNode(artifact_id="a1", url="https://x/a.png", parent_artifact_id="", root_artifact_id="a1", branch_name="main", artifact_type="anchor", prompt="cat")` and asserts `children == []`.
- [ ] Step 3: Add `test_lineage_tree_defaults()` that creates `LineageTree()` and asserts `nodes == {}`, `roots == []`, `head_artifact_id == ""`, `active_branch == "main"`.
- [ ] Step 4: Run `py -3.14 -m pytest tests/test_lineage_tree.py -v`.

**Verification:**
- [ ] `py -3.14 -m pytest tests/test_lineage_tree.py -v` passes.

**Commit:** `feat: add LineageNode and LineageTree dataclasses`

---

## Task 4: Implement _execute_action lineage filling

**Files:**
- `backend/app/core/artist/runtime.py`
- `backend/tests/test_artist_runtime_unit.py`

**Steps:**
- [ ] Step 1: In `runtime.py`, modify `_execute_action()` to compute lineage before calling `build_image_artifacts()`. After `artifact_type = action_type_to_artifact_type(action.type)`, add lineage resolution logic:
  ```python
  parent_url = ""
  root_url = ""
  parent_artifact_id = ""
  root_artifact_id = ""
  branch_name = state.active_branch

  if artifact_type == "anchor":
      root_url = ""
      parent_artifact_id = ""
      root_artifact_id = ""
  elif state.head_artifact_id:
      head_id = state.head_artifact_id
      head_art = _find_artifact_in_recent(state, head_id)
      if head_art:
          parent_url = head_art.get("url", "")
          root_url = head_art.get("root_url", "") or parent_url
          parent_artifact_id = head_id
          root_artifact_id = head_art.get("root_artifact_id", "") or head_id
  ```
- [ ] Step 2: Pass lineage params to `build_image_artifacts()`:
  ```python
  arts = build_image_artifacts(
      urls=urls,
      artifact_type=artifact_type,
      artist_turn_id=artist_turn_id,
      group_id=group_id,
      prompt=action.prompt,
      parent_url=parent_url,
      root_url=root_url,
      parent_artifact_id=parent_artifact_id,
      root_artifact_id=root_artifact_id,
      branch_name=branch_name,
  )
  ```
- [ ] Step 3: For anchor artifacts, set `root_url` and `root_artifact_id` after creation:
  ```python
  if artifact_type == "anchor" and arts:
      for art in arts:
          art.root_url = art.url
          art.root_artifact_id = art.artifact_id
  ```
- [ ] Step 4: Add helper function `_find_artifact_in_recent()` that searches recent artifacts from the state's last known data. Since state doesn't store artifact history, use a simple approach: store `last_artifacts: list[dict]` in state or pass from `handle_turn`. For now, add `last_head_url: str = ""` and `last_head_root_url: str = ""` and `last_head_root_artifact_id: str = ""` to `ArtistSessionState` as cache fields, updated in `_state_updates()`.
- [ ] Step 5: In `_state_updates()`, add:
  ```python
  if artifacts:
      first = artifacts[0]
      updates["head_artifact_id"] = first.artifact_id
      updates["last_head_url"] = first.url
      updates["last_head_root_url"] = first.root_url or first.url
      updates["last_head_root_artifact_id"] = first.root_artifact_id or first.artifact_id
  ```
- [ ] Step 6: In `test_artist_runtime_unit.py`, add `test_runtime_anchor_sets_root_lineage()` that runs a `generate_anchor` action and asserts `art.root_url == art.url` and `art.root_artifact_id == art.artifact_id` and `art.branch_name == "main"`.
- [ ] Step 7: Add `test_runtime_refine_inherits_root_lineage()` that first sets `state.head_artifact_id = "art-prev"`, `state.last_head_url = "https://x/prev.png"`, `state.last_head_root_url = "https://x/root.png"`, `state.last_head_root_artifact_id = "art-root"`, then runs a `refine_target` action and asserts `art.parent_url == "https://x/prev.png"` and `art.root_url == "https://x/root.png"` and `art.parent_artifact_id == "art-prev"`.
- [ ] Step 8: Run `py -3.14 -m pytest tests/test_artist_runtime_unit.py -v`.

**Verification:**
- [ ] `py -3.14 -m pytest tests/test_artist_runtime_unit.py -v` passes.

**Commit:** `feat: fill lineage fields in _execute_action`

---

## Task 5: Implement auto-fork when HEAD has children

**Files:**
- `backend/app/core/artist/runtime.py`
- `backend/app/core/artist/schemas.py`
- `backend/tests/test_artist_runtime_unit.py`

**Steps:**
- [ ] Step 1: Add `head_children: list[str] = []` to `ArtistSessionState` to track which artifact_ids are children of the current HEAD.
- [ ] Step 2: In `_state_updates()`, when updating `head_artifact_id`, also update `head_children = []` (new HEAD has no children yet). When the previous HEAD gets a new child, append the new artifact's `artifact_id` to the old HEAD's children list. Since we don't store old HEADs, use a simpler approach: add `previous_head_children: list[str] = []` to state, and in `_state_updates()`:
  ```python
  if artifacts and state.head_artifact_id:
      updates.setdefault("previous_head_children", list(state.previous_head_children or []))
      updates["previous_head_children"].append(artifacts[0].artifact_id)
  ```
- [ ] Step 3: In `_execute_action()`, before building artifacts, check if HEAD already has children:
  ```python
  if state.head_artifact_id and state.previous_head_children and artifact_type not in ("anchor",):
      state.branch_counter += 1
      branch_name = f"分支-{state.branch_counter}"
      state.active_branch = branch_name
  ```
- [ ] Step 4: In `test_artist_runtime_unit.py`, add `test_runtime_auto_fork_on_second_refine()` that:
  1. Sets `state.head_artifact_id = "art-1"`, `state.previous_head_children = ["art-2"]`, `state.branch_counter = 0`
  2. Runs a `refine_target` action
  3. Asserts `state.branch_counter == 1` and the new artifact's `branch_name == "分支-1"`
- [ ] Step 5: Run `py -3.14 -m pytest tests/test_artist_runtime_unit.py -v`.

**Verification:**
- [ ] `py -3.14 -m pytest tests/test_artist_runtime_unit.py -v` passes.

**Commit:** `feat: auto-fork branch when HEAD has children`

---

## Task 6: Implement rollback intent detection in resolver

**Files:**
- `backend/app/services/image_context_resolver.py`
- `backend/tests/test_image_context_resolver.py`

**Steps:**
- [ ] Step 1: Add `ROLLBACK_REF_PATTERN = re.compile(r"回到|回退|退回|回到.*那张|回到.*版本")` after `ORIGINAL_REF_PATTERN`.
- [ ] Step 2: Add `is_rollback_ref(prompt: str) -> bool` function that returns `bool(ROLLBACK_REF_PATTERN.search(prompt))`.
- [ ] Step 3: In `resolve_image_context()`, add Priority 2c after the original-ref block:
  ```python
  if is_rollback_ref(prompt):
      target = self._resolve_rollback_target(prompt, session_images)
      if target:
          return ImageContextResolution(
              mode="edit_target",
              target_images=[target],
              reason="rollback reference resolved",
              confidence=0.85,
          )
      return ImageContextResolution(
          mode="ask_clarification",
          clarification="你想回到哪个版本？请指定具体的图片。",
          reason="rollback ambiguous: no target found",
          confidence=0.4,
      )
  ```
- [ ] Step 4: Add `_resolve_rollback_target()` method that:
  1. Checks for explicit image refs (第N张) in the prompt
  2. If found, returns that image's URL
  3. If not found, returns None (ambiguous)
- [ ] Step 5: In `test_image_context_resolver.py`, add `test_rollback_ref_with_explicit_target()` with prompt `"回到第2张换个方向"` and 3 session images, asserting `mode == "edit_target"` and `target_images == [images[1].url]`.
- [ ] Step 6: Add `test_rollback_ref_ambiguous_asks_clarification()` with prompt `"回到之前的版本"` and multiple images, asserting `mode == "ask_clarification"`.
- [ ] Step 7: Run `py -3.14 -m pytest tests/test_image_context_resolver.py -v`.

**Verification:**
- [ ] `py -3.14 -m pytest tests/test_image_context_resolver.py -v` passes.

**Commit:** `feat: detect rollback intent in image context resolver`

---

## Task 7: Implement _build_lineage_tree() rebuild

**Files:**
- `backend/app/services/generate_service.py`
- `backend/tests/test_lineage_tree.py`

**Steps:**
- [ ] Step 1: In `generate_service.py`, add function `build_lineage_tree(session_images: list[SessionImage], head_artifact_id: str = "", active_branch: str = "main", branch_labels: dict[str, str] | None = None) -> LineageTree`:
  ```python
  from app.core.artist.schemas import LineageNode, LineageTree

  def build_lineage_tree(session_images, head_artifact_id="", active_branch="main", branch_labels=None):
      nodes = {}
      for img in session_images:
          aid = img.artifact_id
          if not aid:
              continue
          nodes[aid] = LineageNode(
              artifact_id=aid,
              url=img.url,
              parent_artifact_id=img.parent_artifact_id,
              root_artifact_id=img.root_artifact_id,
              branch_name="",
              artifact_type=img.artifact_type,
              prompt="",
          )
      for aid, node in nodes.items():
          if node.parent_artifact_id and node.parent_artifact_id in nodes:
              parent = nodes[node.parent_artifact_id]
              if aid not in parent.children:
                  parent.children.append(aid)
      roots = [aid for aid, n in nodes.items() if not n.parent_artifact_id]
      if not head_artifact_id and nodes:
          leaves = [aid for aid, n in nodes.items() if not n.children]
          head_artifact_id = leaves[-1] if leaves else roots[-1]
      return LineageTree(
          nodes=nodes,
          roots=roots,
          head_artifact_id=head_artifact_id,
          active_branch=active_branch,
          branch_labels=branch_labels or {},
      )
  ```
- [ ] Step 2: In `test_lineage_tree.py`, add `test_build_lineage_tree_simple_chain()`:
  Create 3 `SessionImage` objects: art-1 (anchor, root), art-2 (pack, parent=art-1), art-3 (refine, parent=art-2). Call `build_lineage_tree()`. Assert `tree.roots == ["art-1"]`, `tree.nodes["art-1"].children == ["art-2"]`, `tree.nodes["art-2"].children == ["art-3"]`, `tree.head_artifact_id == "art-3"`.
- [ ] Step 3: Add `test_build_lineage_tree_fork()`:
  Create 4 `SessionImage` objects: art-1 (anchor), art-2 (pack, parent=art-1), art-3 (refine, parent=art-2), art-4 (refine, parent=art-2). Assert `tree.nodes["art-2"].children == ["art-3", "art-4"]`, `tree.roots == ["art-1"]`.
- [ ] Step 4: Add `test_build_lineage_tree_empty()`:
  Call with empty list, assert `tree.nodes == {}`, `tree.roots == []`.
- [ ] Step 5: Run `py -3.14 -m pytest tests/test_lineage_tree.py -v`.

**Verification:**
- [ ] `py -3.14 -m pytest tests/test_lineage_tree.py -v` passes.

**Commit:** `feat: implement build_lineage_tree from session images`

---

## Task 8: Add lineage API endpoints

**Files:**
- `backend/app/routers/session.py`
- `backend/app/services/generate_service.py`
- `backend/tests/test_lineage_api.py`

**Steps:**
- [ ] Step 1: In `session.py`, add three endpoints:
  ```python
  @router.get("/{session_id}/lineage-tree")
  async def get_lineage_tree(session_id: str, db: AsyncSession = Depends(get_db)):
      from app.services.generate_service import _build_session_images, build_lineage_tree
      from app.core.artist.state_store import ArtistStateStore
      images = await _build_session_images(db, session_id)
      store = ArtistStateStore()
      state = store.get(session_id)
      tree = build_lineage_tree(images, state.head_artifact_id, state.active_branch, state.branch_labels)
      return {
          "nodes": {aid: {"artifact_id": n.artifact_id, "url": n.url, "parent_artifact_id": n.parent_artifact_id, "root_artifact_id": n.root_artifact_id, "branch_name": n.branch_name, "artifact_type": n.artifact_type, "prompt": n.prompt, "children": n.children, "label": tree.branch_labels.get(aid, n.branch_name)} for aid, n in tree.nodes.items()},
          "roots": tree.roots,
          "head_artifact_id": tree.head_artifact_id,
          "active_branch": tree.active_branch,
          "branch_labels": tree.branch_labels,
      }

  class LineageHeadRequest(BaseModel):
      artifact_id: str
      branch_name: str | None = None

  @router.put("/{session_id}/lineage/head")
  async def set_lineage_head(session_id: str, req: LineageHeadRequest):
      from app.core.artist.state_store import ArtistStateStore
      store = ArtistStateStore()
      store.update(session_id, head_artifact_id=req.artifact_id, previous_head_children=[])
      if req.branch_name:
          store.update(session_id, active_branch=req.branch_name)
      return {"ok": True, "head_artifact_id": req.artifact_id}

  class BranchRenameRequest(BaseModel):
      artifact_id: str
      name: str

  @router.put("/{session_id}/lineage/branch-rename")
  async def rename_branch(session_id: str, req: BranchRenameRequest):
      from app.core.artist.state_store import ArtistStateStore
      store = ArtistStateStore()
      state = store.get(session_id)
      state.branch_labels[req.artifact_id] = req.name
      return {"ok": True, "branch_labels": state.branch_labels}
  ```
- [ ] Step 2: Make `_build_session_images` importable by ensuring it's a module-level function (it already is).
- [ ] Step 3: In `test_lineage_api.py`, add `test_lineage_tree_endpoint_structure()` that calls `build_lineage_tree()` directly with test data and verifies the dict structure matches the API response format.
- [ ] Step 4: Add `test_set_head_updates_state()` that creates a store, calls the update logic, and verifies `head_artifact_id` is set.
- [ ] Step 5: Add `test_rename_branch_updates_labels()` that creates a store, calls rename logic, and verifies `branch_labels` is updated.
- [ ] Step 6: Run `py -3.14 -m pytest tests/test_lineage_api.py -v`.

**Verification:**
- [ ] `py -3.14 -m pytest tests/test_lineage_api.py -v` passes.

**Commit:** `feat: add lineage API endpoints`

---

## Task 9: Update SSE artist_turn_done with HEAD info

**Files:**
- `backend/app/core/artist/events.py`
- `backend/app/core/artist/runtime.py`
- `backend/tests/test_artist_events.py`

**Steps:**
- [ ] Step 1: In `events.py`, modify `artist_turn_done()` to accept optional `head_artifact_id` and `active_branch`:
  ```python
  def artist_turn_done(session_id: str, artist_turn_id: str, phase: str, head_artifact_id: str = "", active_branch: str = "") -> dict:
      payload = {
          "type": "artist_turn_done",
          "session_id": session_id,
          "artist_turn_id": artist_turn_id,
          "phase": phase,
      }
      if head_artifact_id:
          payload["head_artifact_id"] = head_artifact_id
      if active_branch:
          payload["active_branch"] = active_branch
      return payload
  ```
- [ ] Step 2: In `runtime.py`, modify the `artist_turn_done` call in `handle_turn()` to pass HEAD info:
  ```python
  updated_state = self.deps.state_store.get(session_id)
  await self.deps.event_publish(artist_turn_done(
      session_id, artist_turn_id, new_phase,
      head_artifact_id=updated_state.head_artifact_id,
      active_branch=updated_state.active_branch,
  ))
  ```
- [ ] Step 3: In `test_artist_events.py`, add `test_artist_turn_done_with_head_info()` that calls `artist_turn_done("s1", "t1", "refining", head_artifact_id="art-3", active_branch="分支-1")` and asserts `payload["head_artifact_id"] == "art-3"` and `payload["active_branch"] == "分支-1"`.
- [ ] Step 4: Add `test_artist_turn_done_without_head_info()` that calls without HEAD params and asserts those keys are absent.
- [ ] Step 5: Run `py -3.14 -m pytest tests/test_artist_events.py -v`.

**Verification:**
- [ ] `py -3.14 -m pytest tests/test_artist_events.py -v` passes.

**Commit:** `feat: add HEAD info to artist_turn_done SSE event`

---

## Task 10: Update artist_service.py lineage passthrough

**Files:**
- `backend/app/services/artist_service.py`
- `backend/tests/test_artist_message_persistence.py`

**Steps:**
- [ ] Step 1: In `artist_service.py`, update the artifact dict construction (around line 234) to include `branch_name` from `art.branch_name`.
- [ ] Step 2: Update `build_artist_image_message_metadata()` in `generate_service.py` to include `branch_name` in the artifact metadata dict.
- [ ] Step 3: In `test_artist_message_persistence.py`, add `test_build_artist_image_message_metadata_preserves_branch_name()` that creates an artifact with `branch_name="分支-1"` and asserts it appears in the metadata.
- [ ] Step 4: Run `py -3.14 -m pytest tests/test_artist_message_persistence.py -v`.

**Verification:**
- [ ] `py -3.14 -m pytest tests/test_artist_message_persistence.py -v` passes.

**Commit:** `feat: pass branch_name through artist metadata pipeline`

---

## Task 11: Update _build_session_images to populate branch_name

**Files:**
- `backend/app/services/generate_service.py`
- `backend/tests/test_image_context_resolver.py`

**Steps:**
- [ ] Step 1: In `_build_session_images()`, when creating `SessionImage` from `artist_artifacts`, add `branch_name=art.get("branch_name", "")` field. Since `SessionImage` doesn't have `branch_name` yet, add it to the dataclass: `branch_name: str = ""`.
- [ ] Step 2: In `image_context_resolver.py`, add `branch_name: str = ""` to `SessionImage` dataclass.
- [ ] Step 3: In `test_image_context_resolver.py`, add `test_session_image_branch_name_field()` that creates a `SessionImage` with `branch_name="分支-1"` and asserts the value.
- [ ] Step 4: Run `py -3.14 -m pytest tests/test_image_context_resolver.py -v`.

**Verification:**
- [ ] `py -3.14 -m pytest tests/test_image_context_resolver.py -v` passes.

**Commit:** `feat: add branch_name to SessionImage and _build_session_images`

---

## Task 12: Frontend types and API client

**Files:**
- `frontend/src/types/index.ts`
- `frontend/src/api/session.ts`

**Steps:**
- [ ] Step 1: In `types/index.ts`, extend `ArtistStreamState.artifacts` type to include lineage fields:
  ```typescript
  artifacts: Array<{
    artist_turn_id: string
    artifact_type: string
    url: string
    group_id: string
    index_in_group: number
    prompt: string
    artifact_id: string
    parent_artifact_id: string
    root_artifact_id: string
    parent_url: string
    root_url: string
    branch_name: string
  }>
  ```
- [ ] Step 2: Add `LineageNode` and `LineageTree` types:
  ```typescript
  export interface LineageNode {
    artifact_id: string
    url: string
    parent_artifact_id: string
    root_artifact_id: string
    branch_name: string
    artifact_type: string
    prompt: string
    children: string[]
    label: string
  }

  export interface LineageTree {
    nodes: Record<string, LineageNode>
    roots: string[]
    head_artifact_id: string
    active_branch: string
    branch_labels: Record<string, string>
  }
  ```
- [ ] Step 3: In `api/session.ts`, add lineage API methods:
  ```typescript
  getLineageTree: (id: string) => api.get<LineageTree>(`/sessions/${id}/lineage-tree`),

  setLineageHead: (id: string, data: { artifact_id: string; branch_name?: string }) =>
    api.put(`/sessions/${id}/lineage/head`, data),

  renameBranch: (id: string, data: { artifact_id: string; name: string }) =>
    api.put(`/sessions/${id}/lineage/branch-rename`, data),
  ```
- [ ] Step 4: Run `npm run build` in frontend to verify types compile.

**Verification:**
- [ ] `npm run build` succeeds in frontend.

**Commit:** `feat: add lineage types and API client`

---

## Task 13: Create LineageNode.vue component

**Files:**
- `frontend/src/components/session/LineageNode.vue`

**Steps:**
- [ ] Step 1: Create `LineageNode.vue` with props `node: LineageNode`, `isHead: boolean`, `isActive: boolean`, `depth: number`. Template:
  ```html
  <div class="lineage-node" :class="{ head: isHead, active: isActive }">
    <div class="node-content">
      <img :src="node.url" class="node-thumb" @click="$emit('select', node.artifact_id)" />
      <div class="node-info">
        <span class="node-label">{{ node.label || node.branch_name }}</span>
        <span class="node-type">{{ node.artifact_type }}</span>
        <span v-if="isHead" class="head-mark">HEAD</span>
      </div>
    </div>
    <div class="node-children" v-if="node.children.length">
      <div class="tree-line"></div>
      <LineageNode
        v-for="cid in node.children"
        :key="cid"
        :node="treeNodes[cid]"
        :is-head="cid === headId"
        :is-active="cid === headId"
        :depth="depth + 1"
        :tree-nodes="treeNodes"
        :head-id="headId"
        @select="$emit('select', $event)"
        @rename="$emit('rename', $event)"
      />
    </div>
  </div>
  ```
- [ ] Step 2: Add scoped styles:
  ```css
  .lineage-node { margin-left: 20px; position: relative; }
  .node-content { display: flex; align-items: center; gap: 8px; padding: 4px 8px; border: 1px solid #e5e5e5; border-radius: 4px; background: #fafafa; cursor: pointer; }
  .node-content:hover { border-color: #999; }
  .head .node-content { border-color: #000; border-width: 2px; }
  .node-thumb { width: 48px; height: 48px; border-radius: 4px; object-fit: cover; }
  .node-info { display: flex; flex-direction: column; gap: 2px; }
  .node-label { font-size: 12px; color: #666; }
  .node-type { font-size: 10px; color: #999; text-transform: uppercase; }
  .head-mark { font-size: 10px; color: #000; font-weight: 600; }
  .tree-line { position: absolute; left: -10px; top: 0; bottom: 0; width: 1px; background: #e5e5e5; }
  .node-children { margin-top: 4px; }
  ```
- [ ] Step 3: Run `npm run build` to verify.

**Verification:**
- [ ] `npm run build` succeeds.

**Commit:** `feat: create LineageNode.vue tree component`

---

## Task 14: Create LineageDrawer.vue component

**Files:**
- `frontend/src/components/session/LineageDrawer.vue`

**Steps:**
- [ ] Step 1: Create `LineageDrawer.vue` with props `show: boolean`, `sessionId: string`. Template:
  ```html
  <Transition name="slide">
    <div v-if="show" class="lineage-drawer">
      <div class="drawer-header">
        <span class="drawer-title">谱系图</span>
        <button class="drawer-close" @click="$emit('close')">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      <div class="drawer-body" v-if="tree">
        <div v-for="rootId in tree.roots" :key="rootId" class="tree-root">
          <LineageNode
            :node="tree.nodes[rootId]"
            :is-head="rootId === tree.head_artifact_id"
            :is-active="rootId === tree.head_artifact_id"
            :depth="0"
            :tree-nodes="tree.nodes"
            :head-id="tree.head_artifact_id"
            @select="onNodeSelect"
            @rename="onNodeRename"
          />
        </div>
      </div>
      <div class="drawer-empty" v-else>暂无谱系数据</div>
      <div class="drawer-actions" v-if="selectedNodeId">
        <button class="btn btn-secondary" @click="rollbackToSelected">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
          回到此版本
        </button>
        <button class="btn btn-secondary" @click="startRename">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
          重命名
        </button>
      </div>
    </div>
  </Transition>
  ```
- [ ] Step 2: Script section:
  ```typescript
  import { ref, watch } from 'vue'
  import { sessionApi } from '../../api/session'
  import type { LineageTree } from '../../types'
  import LineageNode from './LineageNode.vue'

  const props = defineProps<{ show: boolean; sessionId: string }>()
  const emit = defineEmits<{ close: []; rollback: [artifactId: string] }>()

  const tree = ref<LineageTree | null>(null)
  const selectedNodeId = ref('')

  watch(() => props.show, async (v) => {
    if (v && props.sessionId) {
      const res = await sessionApi.getLineageTree(props.sessionId)
      tree.value = res.data
    }
  })

  function onNodeSelect(artifactId: string) { selectedNodeId.value = artifactId }

  async function rollbackToSelected() {
    if (!selectedNodeId.value || !props.sessionId) return
    await sessionApi.setLineageHead(props.sessionId, { artifact_id: selectedNodeId.value })
    emit('rollback', selectedNodeId.value)
    const res = await sessionApi.getLineageTree(props.sessionId)
    tree.value = res.data
  }

  async function onNodeRename(data: { artifactId: string; name: string }) {
    if (!props.sessionId) return
    await sessionApi.renameBranch(props.sessionId, { artifact_id: data.artifactId, name: data.name })
    const res = await sessionApi.getLineageTree(props.sessionId)
    tree.value = res.data
  }

  function startRename() {
    // handled by LineageNode inline edit
  }
  ```
- [ ] Step 3: Add scoped styles:
  ```css
  .lineage-drawer { position: fixed; top: 0; right: 0; width: 320px; height: 100vh; background: #fff; border-left: 1px solid #e5e5e5; z-index: 100; display: flex; flex-direction: column; }
  .drawer-header { display: flex; justify-content: space-between; align-items: center; padding: 16px; border-bottom: 1px solid #e5e5e5; }
  .drawer-title { font-size: 14px; font-weight: 600; }
  .drawer-close { background: none; border: none; cursor: pointer; color: #666; }
  .drawer-body { flex: 1; overflow-y: auto; padding: 16px; }
  .drawer-empty { flex: 1; display: flex; align-items: center; justify-content: center; color: #999; font-size: 13px; }
  .drawer-actions { padding: 12px 16px; border-top: 1px solid #e5e5e5; display: flex; gap: 8px; }
  .slide-enter-active, .slide-leave-active { transition: transform 0.2s ease; }
  .slide-enter-from, .slide-leave-to { transform: translateX(100%); }
  ```
- [ ] Step 4: Run `npm run build`.

**Verification:**
- [ ] `npm run build` succeeds.

**Commit:** `feat: create LineageDrawer.vue side drawer`

---

## Task 15: Wire LineageDrawer into Sessions.vue

**Files:**
- `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] Step 1: Import `LineageDrawer` component.
- [ ] Step 2: Add `showLineageDrawer` ref (default `false`).
- [ ] Step 3: Add toolbar button in the chat-area header (or near ComposerControls) with Lucide `GitBranch` icon:
  ```html
  <button class="btn btn-icon" @click="showLineageDrawer = true" title="谱系图">
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>
  </button>
  ```
- [ ] Step 4: Add `<LineageDrawer :show="showLineageDrawer" :session-id="currentSessionId || ''" @close="showLineageDrawer = false" @rollback="onLineageRollback" />` in template.
- [ ] Step 5: Add `onLineageRollback(artifactId: string)` function that refreshes messages after HEAD switch.
- [ ] Step 6: Run `npm run build`.

**Verification:**
- [ ] `npm run build` succeeds.

**Commit:** `feat: wire LineageDrawer into Sessions.vue`

---

## Task 16: Handle artist_turn_done HEAD update in frontend store

**Files:**
- `frontend/src/stores/session.ts`

**Steps:**
- [ ] Step 1: In `session.ts`, find the `handleArtistDone` or equivalent handler for `artist_turn_done` events.
- [ ] Step 2: When processing `artist_turn_done`, extract `head_artifact_id` and `active_branch` from the event payload and store them in a reactive map: `const lineageHeads = reactive(new Map<string, { headArtifactId: string; activeBranch: string }>())`.
- [ ] Step 3: Expose `getLineageHead(sessionId: string)` function from the store.
- [ ] Step 4: Run `npm run build`.

**Verification:**
- [ ] `npm run build` succeeds.

**Commit:** `feat: track lineage HEAD in frontend store`

---

## Task 17: Full backend test suite

**Files:** (no new files)

**Steps:**
- [ ] Step 1: Run `py -3.14 -m pytest tests/ --tb=short -q` and confirm all pass.
- [ ] Step 2: Fix any failures.

**Verification:**
- [ ] `py -3.14 -m pytest tests/ --tb=short -q` passes with 0 failures.

**Commit:** `test: verify full backend test suite`

---

## Task 18: Frontend build clean

**Files:** (no new files)

**Steps:**
- [ ] Step 1: Run `npm run build` in frontend.
- [ ] Step 2: Fix any type errors or build failures.

**Verification:**
- [ ] `npm run build` succeeds with 0 errors.

**Commit:** `build: verify frontend build clean`

---

## Task 19: Update AGENTS.md and PLAN.md

**Files:**
- `AGENTS.md`
- `docs/plans/PLAN.md`

**Steps:**
- [ ] Step 1: In `AGENTS.md` Code Index, add entries for `LineageNode`, `LineageTree`, `build_lineage_tree()`, `LineageDrawer.vue`, `LineageNode.vue`, lineage API endpoints.
- [ ] Step 2: In `AGENTS.md` Key Patterns, add "Lineage DAG" pattern describing auto-fork, HEAD, rollback, branch naming.
- [ ] Step 3: In `PLAN.md`, update P3B status for lineage DAG feature.

**Verification:**
- [ ] AGENTS.md and PLAN.md updated.

**Commit:** `docs: update AGENTS.md and PLAN.md for lineage DAG`
