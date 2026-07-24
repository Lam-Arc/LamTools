# Lineage E2E Test Plan

## 原则

- 自然语言输入，真实任务，不 mock
- 一个完整创作会话覆盖所有核心场景
- HEAD 切换用 API（等价于用户在 UI 点按钮）
- 验证只看输入项：prompt 是否合理、source_image_urls 是否指向正确的父图

## Infrastructure

- 后端 `http://127.0.0.1:6171/api`
- `POST /sessions` → 创建会话
- `POST /sessions/{id}/generate` → 发自然语言消息（只传 prompt + agent_mode）
- SSE 等待 `task_completed`
- `GET /sessions/{id}/messages` → 提取 metadata
- `GET /sessions/{id}/lineage-tree` → 谱系树
- `PUT /sessions/{id}/lineage/head` → 切 HEAD（UI 操作等价）
- `PUT /sessions/{id}/lineage/branch-rename` → 重命名分支

---

## 单会话测试：一个完整的设计迭代故事

### 会话主题：江南建筑风格探索 + 意图多样性

用户从线稿开始，探索漆画、水墨画、平涂三种风格，中途回到线稿做新尝试，
中途完全换一个新主题（确保 LLM 不把新主题误判为 edit_target），
中途用风格参考而非编辑，中途用结构化引用指定目标。

---

#### S1: 根节点 — 线稿

| 用户说 | `画一个江南水乡建筑线稿` |
|--------|------------------------|
| 模式 | agent_mode=True |
| 预期 | Gen0: source=[], mode=new_generation |

断言：Gen0.source_image_urls == []

---

#### S2: 线性迭代 — 改漆画

| 用户说 | `改成漆画风格` |
|--------|--------------|
| 模式 | agent_mode=True |
| 预期 | Gen1 → Gen0, mode=edit_target |

断言：Gen1.source_image_urls == [Gen0.url]

---

#### S3: 线性迭代 — 调亮度

| 用户说 | `画面太暗了，提亮一些` |
|--------|---------------------|
| 模式 | agent_mode=True |
| 预期 | Gen2 → Gen1, mode=edit_target |

断言：Gen2.source_image_urls == [Gen1.url]
此时谱系：Gen0 → Gen1 → Gen2（线性链）

---

#### S4: 自然语言定位 — "从漆画改成水墨画"

| 用户说 | `从漆画改成水墨画` |
|--------|------------------|
| 模式 | agent_mode=True |
| 预期 | Gen3 → Gen1（LLM 匹配"漆画"到 Gen1，不是 Gen2 也不是 Gen0）|

**这是核心测试**：LLM 应根据"漆画"匹配 Gen1 的 prompt，而非选 latest(Gen2) 或 HEAD。
断言：Gen3.source_image_urls == [Gen1.url]，不是 [Gen0.url] 或 [Gen2.url]

---

#### S5: 自然语言定位 — "在线稿基础上改成平涂"

| 用户说 | `在线稿基础上改成平涂风格` |
|--------|------------------------|
| 模式 | agent_mode=True |
| 预期 | Gen4 → Gen0（LLM 匹配"线稿"到 Gen0）|

断言：Gen4.source_image_urls == [Gen0.url]
此时 Gen0 有多个子节点——已经形成 fork

---

#### S6: 新主题 — "再画一只猫" (new_generation, 不引用旧图)

| 用户说 | `再画一只橘猫` |
|--------|-------------|
| 模式 | agent_mode=True |
| 预期 | Gen5: source=[], mode=new_generation |

**关键**：会话里已有 5 张建筑图，但用户说"再画一只橘猫"是完全不同的主题。
LLM 应识别为 new_generation，不应把任何建筑图作为 source。
断言：Gen5.source_image_urls == []

---

#### S7: 风格参考 — "参考漆画风格画一个山水"

| 用户说 | `参考漆画那种风格画一幅山水` |
|--------|--------------------------|
| 模式 | agent_mode=True |
| 预期 | Gen6: mode=style_reference, reference_images 包含 Gen1(漆画), 但不是 target |

**关键**：用户要的是"参考漆画风格"，不是"编辑漆画"。
LLM 应识别为 style_reference（用漆画做风格参考，生成全新的山水），
而不是 edit_target（直接修改漆画那张）。
断言：
- Gen6.generation_mode == "style_reference"（或 metadata 中有相关标记）
- Gen6 的图像不应是基于漆画的 img2img，而是全新生成但风格参考漆画

---

#### S8: 结构化引用 — "第2张改成油画"

| 用户说 | `第2张改成油画风格` |
|--------|------------------|
| 模式 | agent_mode=True |
| 预期 | 确定性路径解析"第2张" → 精准定位到按时间正序第 2 张图(Gen1=漆画) |

**关键**：这条走的是 `resolve_explicit_image_refs` 确定性路径，不经过 LLM。
断言：source_image_urls == [Gen1.url]（第2张=漆画），不是 Gen0 或 Gen2

---

#### S9: HEAD 切换 + 直接模式 — 回到漆画版本调色

| 操作 | PUT /lineage/head → Gen1（漆画）|
|------|-------------------------------|
| 用户说 | `颜色太淡了`（agent_mode=False）|
| 预期 | Gen7 → Gen1（直接模式走 HEAD）|

断言：Gen7.source_image_urls == [Gen1.url]，不是 [Gen6.url]（latest）

---

#### S10: 分支重命名

此时谱系树已有多个分支。查看 tree.branches，找到自动命名的分支（如 branch-1）。

| 操作 | PUT /lineage/branch-rename → 把某个 branch-N 重命名为"水墨探索" |
|------|-------------------------------------------------------|
| 预期 | branches 包含"水墨探索"，不含原 branch-N 名 |

断言：
- tree.branches 有"水墨探索"键
- HEAD、节点数、边关系均不变

---

#### S11: 最终谱系完整性验证

GET /lineage-tree，全局检查：

| 检查项 | 通过条件 |
|--------|---------|
| 节点数 | == 8 (Gen0-Gen7，Gen5和Gen6为独立节点或引用节点) |
| 根节点 | Gen0(线稿) + Gen5(橘猫) + Gen6(山水) — 至少 3 个根（source=[]的节点）|
| Gen0 子节点 | 包含 Gen1、Gen4 |
| Gen1 子节点 | 包含 Gen2、Gen3、Gen7 |
| fork 正确 | Gen0 有 ≥2 个子节点 |
| HEAD | == Gen7.url |
| 分支数 | >= 2 |
| 无孤立节点 | 除根节点外，每个节点 parent_urls 非空（根节点 source=[]）|
| metadata 一致性 | session.metadata_.lineage_head_url == tree.head_url |
| 重命名生效 | "水墨探索"分支存在 |

---

## 理想谱系图

```
Gen0 (线稿, root)
  ├── Gen1 (漆画)           [main]
  │     ├── Gen2 (提亮)     [main 续]
  │     ├── Gen3 (水墨画)   [分支: 水墨探索] ← "从漆画改成水墨画"
  │     └── Gen7 (调色)     [分支: 漆画调色] ← HEAD
  └── Gen4 (平涂)           [分支: 平涂线] ← "在线稿基础上改成平涂"

Gen5 (橘猫, root)           ← "再画一只橘猫" (new_generation)
Gen6 (山水, root?)          ← "参考漆画风格画山水" (style_reference)
``

---

## 执行步骤

1. 创建会话
2. S1 → SSE → Gen0 → 验证 source=[]
3. S2 → SSE → Gen1 → 验证 source=[Gen0]
4. S3 → SSE → Gen2 → 验证 source=[Gen1]
5. S4 → SSE → Gen3 → **核心：source=[Gen1]（漆画）**
6. S5 → SSE → Gen4 → 验证 source=[Gen0]（线稿）
7. S6 → SSE → Gen5 → 验证 source=[]（新主题）
8. S7 → SSE → Gen6 → 验证 style_reference 而非 edit_target
9. S8 → SSE → Gen7 → 验证 source=[Gen1]（结构化"第2张"=漆画）
10. PUT /lineage/head → Gen1
11. S9 → SSE → Gen8 → 验证 source=[Gen1]（HEAD）
12. GET lineage-tree → 找可重命名的分支
13. PUT branch-rename
14. GET lineage-tree → 全局完整性验证 (S11)
15. GET session → metadata 一致性

**1 个会话，9 次图像生成，1 次 HEAD 切换，1 次分支重命名。**

## 判定标准

| 检查项 | 通过条件 |
|--------|---------|
| source_image_urls | 指向正确的父图 URL |
| generation_mode | 符合预期（new_generation / edit_target / style_reference）|
| 谱系边 | parent_urls 正确 |
| **自然语言定位** | "从漆画改成"→Gen1, "在线稿基础上改"→Gen0 |
| **新主题识别** | "再画一只橘猫"→source=[], 不引用旧图 |
| **风格参考** | "参考漆画风格画山水"→style_reference, 不是 edit_target |
| **结构化引用** | "第2张"→确定性路径定位到正确图片 |
| **HEAD 语义** | 直接模式下 source == HEAD URL |
| 分支结构 | fork 正确，重命名生效 |
| metadata 一致 | session 和 tree 的 head_url 一致 |