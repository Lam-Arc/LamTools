---
name: refine-plan
description: Revise an existing plan (方案) from the user's feedback — change what they asked to change, keep everything else. Use when the user asks to adjust, correct, shorten, extend or re-think a plan that already exists as a file in the project's 方案/ folder. Read the file first; never rebuild it from memory. Refining is still a conversation: keep asking when the goal, the boundary or success is still unstated, record each question in the plan's 未答问题 section, and never let implementation detail leak into the plan's business sections.
metadata:
  version: "0.3.0"
  platforms: universal
---

# Refine a plan (方案)

In one sentence: change exactly what the user asked for, keep the rest — the file is the whole story, so what you leave alone stays as it was.

A refinement is still a conversation. The user's new sentence is often thinner than it sounds, and the fastest way to spoil a plan is to widen it with your own guesses.

## 1. Read it before you touch it

Find the file in `方案/` (read it with `read_file`; the 资料库 shows what is there). Read the whole document — 需求与边界, 取舍, 步骤, 目标与完成判据, 风险, 未答问题. Editing a plan you did not read first is how a plan loses decisions that were argued over.

There is only ever one plan file per piece of work, and it lives in this project's folder. If the user is talking about a plan they made somewhere else, say which copy you are editing — and that the other copy is a different file.

## 2. Change the least that satisfies the request

- Edit the file with `edit_file`, touching only the lines the user's feedback changes. Re-writing the whole document "to be safe" is how a reviewed section silently reverts.
- The file has no hidden revision history — what you write is what exists. Say what you changed and why; do not imply an undo exists.
- If the user's feedback contradicts something else in the plan (a non-goal, an assumption, a step), fix the contradiction too, and tell them you did — a plan with an admitted conflict is worse than a shorter plan.

## 3. Keep asking; a refinement arrives one message at a time

3.1) Treat refinement as the same chat as drafting: confirm what the user just said in one line, then ask. Each message usually carries one answer and one new gap.

3.2) Ask 2–3 questions at most in a turn, only where the answer changes the plan. For a new sub-request, the goal, the boundary and what success looks like are the questions that matter. Never pile them into a numbered questionnaire.

3.3) Record every unanswered question in the plan's 未答问题 section and ask it in the conversation, in the same turn. When the user answers one, strike it from 未答问题 and fold the answer into the section it belongs to — do not leave an answered question sitting open, and do not delete the answer's trace from the plan.

3.4) Do not invent the missing half of a request to make the edit feel complete. If the user says "再加个导出", that added part is a new requirement whose goal, format and boundary are unknown: ask, and write 还没定 until answered.

### One turn at a time (worked)

- "再加一条：别动我原来的文件夹结构。" → Right: add one line to 这次不做 under 需求与边界, keep 草稿, say what changed and that everything else is untouched. Wrong: rebuild 取舍 and the steps around a guess about the folder layout.
- Later: "整理完给我个清单就行。" → that answers an open question about success: write the answer into 需求与边界 and clear it from 未答问题.
- Later: "可以了，就照这个开工。" → with the goal, the boundary, the success and the steps now settled and each step verifiable, this is the moment to change `状态: 草稿` → `就绪` — not before.

## 4. Business language in, business language out

4.1) The same boundary as drafting holds after every edit: 需求与边界, 取舍, 目标与完成判据, 风险 and 未答问题 state what the user will see, what is out, and what worries them — never how you will build it.
4.2) 步骤 may name files, commands and libraries; it is the only section that may. A refinement that "adds detail" adds that detail in the steps, not in the requirement.
4.3) The user's own technical words are allowed where they apply: if they say "用 Python 写" or "改成用 SQLite 存", that is their decision — keep it. A technology nobody said still must not come in through a refinement.
4.4) Do not tidy the user's phrasing into terms when you edit a section; a refined section still holds their meaning in their register, in their language.

## 5. Where the status stands

- Keep `状态: 草稿` while any of these is missing: the user's agreement with the restatement, the user's own words for success and non-goals, at least one step that says how it is known done, and answers to the open questions that would change the plan.
- Move to `就绪` only when all of them are in and the user has confirmed. A `就绪` plan with no checkable steps is a lie nothing outside you would stop.
- If a refinement reopens something the user had settled — a non-goal is dropped, the goal changes — move it back to `草稿`. A plan that says `就绪` over an open question is the lie this prevents.

## 6. Keep the plan usable

After a change, re-check the three things that make a plan usable, and repair them if your edit broke one:

1. every step still says how you will know it is done;
2. 这次不做 still matches what the user said is out of scope;
3. every 未答问题 entry still blocks something real — answer it, or say what it blocks.

## 7. Hand back

Say the file path, what changed, what you left alone, and anything the user's request implies that they did not say (as an assumption, not as a silent edit). If the plan was already executed somewhere, say so and say what the change means for that execution — do not edit a finished plan into looking like it was always that way.
