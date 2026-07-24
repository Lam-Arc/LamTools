# Artist Image Lineage DAG — Branch / Tag / HEAD / Rollback

> **For agentic workers:** Use executing-plans skill to implement task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Make Artist image lineage work like git — every derivation is a DAG node with auto-branching, HEAD pointer, rollback, and branch naming. Frontend shows a side-drawer tree visualization.

**Architecture:** Every generated image is a `LineageNode` with `artifact_id`, `parent_artifact_id`, `root_artifact_id`, `branch_name`. The tree is rebuilt from message metadata (no new DB table). `ArtistSessionState` tracks `head_artifact_id`, `active_branch`, `branch_labels`. Frontend gets tree via API, renders in `LineageDrawer.vue`.

**Approach:** C — message metadata as source of truth, dynamic tree rebuild, no DB migration.

**Key Decisions:**
- Every derivation auto-forks a new branch when HEAD already has children
- Branch naming: auto ("分支-1") + user rename
- Rollback: switch HEAD only, old branches preserved (git checkout semantics)
- Frontend: side drawer with recursive tree, Lucide icons, black/white/grey palette
- No new DB table; `LineageTree` rebuilt from `artist_artifacts` in message metadata

---

## Data Model

### ArtistArtifact (extend existing)
- `branch_name: str = ""` — which branch this artifact belongs to

### ArtistSessionState (extend existing)
- `head_artifact_id: str = ""` — current HEAD artifact
- `active_branch: str = "main"` — current active branch name
- `branch_labels: dict[str, str] = {}` — `{artifact_id: display_name}` for renamed branches
- `branch_counter: int = 0` — auto-naming counter

### LineageNode (new, runtime only)
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
    children: list[str]       # child artifact_ids
    created_at: str = ""
```

### LineageTree (new, runtime only)
```python
@dataclass
class LineageTree:
    nodes: dict[str, LineageNode]
    roots: list[str]
    head_artifact_id: str
    active_branch: str
    branch_labels: dict[str, str]
```

---

## Runtime Behavior

### _execute_action() lineage filling
- **anchor**: `root_artifact_id = artifact_id`, `root_url = url`, `parent_artifact_id = ""`, `branch_name = "main"`
- **pack**: inherit anchor's `root_artifact_id`/`root_url`, `parent_artifact_id = anchor_artifact_id`, `branch_name = "main"`
- **refine/replace**: `parent_artifact_id = HEAD artifact_id`, inherit `root_artifact_id`/`root_url`, `branch_name = active_branch`
- **auto-fork**: if HEAD already has children, `branch_counter += 1`, new branch = `f"分支-{branch_counter}"`, `active_branch = new branch`

### HEAD switch (rollback)
- New pattern: `ROLLBACK_REF_PATTERN` = `回到|回退|退回|回到.*那张`
- Resolver identifies rollback intent → sets `state.head_artifact_id = target`
- `state.active_branch = target_node.branch_name`
- Old branches preserved

### Branch naming
- Initial: `"main"`
- Auto-fork: `"分支-1"`, `"分支-2"`, ...
- User rename: `state.branch_labels[artifact_id] = new_name`
- Display priority: `branch_labels > branch_name > auto_name`

### _build_lineage_tree() rebuild
1. Scan recent N messages, collect all `artist_artifacts`
2. Deduplicate by `artifact_id`, build `LineageNode` dict
3. Fill `children` by reverse-lookup of `parent_artifact_id`
4. Find roots (`parent_artifact_id == ""`)
5. Read `head_artifact_id`, `active_branch`, `branch_labels` from state

### State persistence
- `head_artifact_id`: after rebuild, default to latest leaf node
- `active_branch`: HEAD node's `branch_name`
- `branch_labels`: stored in message metadata (`branch_labels` dict per artist message), merged on rebuild

---

## API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/sessions/{id}/lineage-tree` | GET | Return `LineageTree` JSON |
| `/api/sessions/{id}/lineage/head` | PUT | Switch HEAD (`{artifact_id, branch_name?}`) |
| `/api/sessions/{id}/lineage/branch-rename` | PUT | Rename branch (`{artifact_id, name}`) |

### lineage-tree response
```json
{
  "nodes": {
    "art-1": {
      "artifact_id": "art-1",
      "url": "https://...",
      "parent_artifact_id": "",
      "root_artifact_id": "art-1",
      "branch_name": "main",
      "artifact_type": "anchor",
      "prompt": "a cat",
      "children": ["art-2", "art-3"],
      "label": "main"
    }
  },
  "roots": ["art-1"],
  "head_artifact_id": "art-3",
  "active_branch": "分支-1",
  "branch_labels": {"art-3": "赛博风"}
}
```

### SSE changes
- `artist_image_ready`: already carries full `ArtistArtifact`, lineage fields auto-included
- `artist_turn_done`: add `head_artifact_id`, `active_branch` to payload

---

## Frontend

### LineageDrawer.vue (side drawer)
- Triggered by toolbar button (Lucide `GitBranch` icon)
- Calls GET `/lineage-tree`, renders recursive tree

### Component tree
- `LineageDrawer.vue` — drawer container
- `LineageTree.vue` — recursive tree component
- `LineageNode.vue` — single node: thumbnail + branch name + type label + HEAD mark

### Interactions
- Click node: highlight, show action buttons (rename / rollback)
- Double-click branch name: inline edit rename
- "回到此版本": PUT `/lineage/head`
- HEAD node: `★` mark + black border
- Active branch: highlighted

### Style (black/white/grey minimal)
- Node: `#FAFAFA` bg, `1px #E5E5E5` border
- HEAD: `#000` border
- Branch name: 12px `#666`
- Lines: `1px #E5E5E5`, CSS border-left + pseudo-elements
- Thumbnail: 48x48, border-radius 4px
- Icons: `GitBranch` (toolbar), `RotateCcw` (rollback), `Pencil` (rename)

### Frontend type changes
```typescript
interface ArtistArtifactFE {
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
}
```
