# Plan document templates

A plan (方案) is one markdown file in the project's `方案/` folder — the shape below is the whole plan. Bigger work may also need supporting documents (a long design, a task list); their shapes follow at the end. Write only what the work needs — a one-day change does not need supporting documents, and an early draft needs none.

Read this file when you are about to write a plan: load it with `read_file` at `references/plan-template.md`, relative to the plan plugin's skill root. The plan file lives in the project; this one is a skill reference.

## The plan file — `方案/<标题>.md`

```markdown
---
状态: 草稿
摘要: 一句话，列表里能显示的那种
---

# <标题>

## 需求与边界

- 复述：把用户的请求用自己的话说回去 — 读者据此检查你理解对了。
- 完成后能看到：成功时用户将观察到什么。
- 这次不做：本可以顺手做、但用户明确划出去的东西。
- 假设：你没问就当了的默认 — 每条都可被推翻。

## 取舍

- 选定：<怎么做>，因为 <为什么赢过其他选择>。
- 被否：<别的方案> — <一句话输在哪>。

## 步骤

1. <改什么，动哪些文件> — 验证：<哪条命令/测试/观察，必须显示什么>
2. …

## 目标与完成判据

- 目标：<这件事是为了什么>
- 判据：<怎样算完成，逐条可查>

## 风险

- <风险> — <可能性> — <对策>。

## 未答问题

- <问题> — 卡住<哪一步/哪一节>。
```

The rules that keep this file honest:

- `状态` is 草稿 → 就绪 → 执行中 → 完成. `就绪` claims the user has agreed; a plan with no checkable steps must never carry it.
- **业务段落保持业务语言** — 需求与边界、取舍、目标与完成判据、风险、未答问题 state what the user will see, what is out, and what worries them, naming a technology only where the user named it. 步骤 is the only section where technical words belong.
- **一步一步可验证**：a step that cannot show evidence of being done is two things confused — split or sharpen it.
- **未答问题必须同时问出口**：a question that lives only in the file is never answered; one that lives only in chat dies with the session. Do both, every time.
- **Write in the user's language and register.** The section order is the contract; the headings may be the user's own words. Do not rewrite their register into jargon.
- **Edit in place as things change** (`edit_file`): the file is the single, current truth. There is no revision history behind it — say what you changed.

## Supporting documents (only when the work needs them)

Supporting documents live wherever the work needs them in the project (e.g. `docs/<slug>/design.md`), and the plan points at them from 取舍 or 步骤. Keep them short and factual; the plan file holds the decisions, these hold the detail.

### design.md — why this shape

```markdown
# <Title>

## Context
What is going on that makes this worth doing. Two or three sentences, no history lesson.

## Goal and non-goals
- Goal: the observable end state.
- Non-goals: what could reasonably be in scope and is deliberately not.

## Approach
The chosen approach in a paragraph, then the parts that carry the risk.

## Alternatives considered
- <Option>: rejected because <one line>.

## Open questions
- <Question> — blocks <which step>, needs <whose answer>.
```

The open questions here are the same ones in the plan's 未答问题 section. Keep the two in step; a document question with no plan entry is a question nobody will chase.

### plan.md — what will be done

```markdown
# <Title> implementation plan

Goal: <one sentence>
Approach: <two or three sentences>
Documents: <paths this plan refers to>

## Constraints
Anything the work must not do.

## Steps

### Step <n>: <what changes>
- Files: <paths to create or modify>
- Change: <what changes, concretely>
- Verification: <the command, test or observation that proves it, and what it must show>
- Depends on: <earlier step ids, if any>

## Risks
- <Risk> — <likelihood> — <what to do about it>.
```

This document carries the steps, so technical words belong here. Do not restate the goal or the non-goals in implementation terms when you copy them in.

### tasks.md — the same steps, trackable

```markdown
# <Title> tasks

- [ ] T1 <action, with its file path>
- [ ] T2 <action, with its file path>
```

Rules for the tasks list:

- one line per task, imperative, with the exact path;
- `[P]` marks a task that can run in parallel with the previous one (different files, no shared state);
- a task is only checked when its verification ran and passed — the evidence goes in the same message, not "should be fine";
- order by dependency, not by importance.

## Writing the files

- Paths are relative to the project, forward slashes, no climbing out of it.
- Supporting documents go under a folder named for the work, e.g. `docs/<slug>/design.md`.
- The plan file is written first (or as soon as anything is settled); supporting documents are written when there is something to write — a path the plan names with no file behind it is a broken promise.
- If a document is long, keep its decisions at the top — the executor reads the first screen first.
