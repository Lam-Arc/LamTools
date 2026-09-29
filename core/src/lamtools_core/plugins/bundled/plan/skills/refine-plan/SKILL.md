---
name: refine-plan
description: Revise an existing plan package (方案) from the user's feedback — change what they asked to change, keep everything else, and record the revision. Use when the user asks to adjust, correct, shorten, extend or re-think a plan that already exists, including after it was stored on another device. Read the current package first with plan_package; never rebuild it from memory. Refining is still a conversation: keep asking when the goal, the boundary or success is still unstated, record each question in open_questions, and never let implementation detail leak into the plan's business fields.
metadata:
  version: "0.2.0"
  platforms: universal
---

# Refine a plan package

In one sentence: change exactly what the user asked for, keep the rest, and let the history show what moved.

A refinement is still a conversation. The user's new sentence is often thinner than it sounds, and the fastest way to spoil a plan is to widen it with your own guesses.

## 1. Read it before you touch it

Call `plan_package` with `action: "get"` and the id (or `action: "list"` to find it by title). Read the whole package — requirement, approach, steps, goal, risks, open questions. Editing a plan you did not read first is how a plan loses decisions that were argued over.

There is only ever one copy of a plan package per host, and each host keeps its own history: the phone's copy is the phone's. If the user is talking about a plan they made elsewhere, say which copy you are editing.

## 2. Change the least that satisfies the request

- A save is a **patch**: send only the fields you are changing, plus the id. Everything you leave out keeps its value — so never re-send the whole package "to be safe": it is how a reviewed field silently reverts.
- Send `expected_revision` when you have just read the plan, so a concurrent change is refused instead of overwritten.
- Every accepted save becomes a new revision; the old text is still there and can be restored. Say the revision number when you are done.
- If the user's feedback contradicts something in the package (a non-goal, an assumption, a step), fix the contradiction too, and tell them you did — a plan with an admitted conflict is worse than a shorter plan.

## 3. Keep asking; a refinement arrives one message at a time

3.1) Treat refinement as the same chat as drafting: confirm what the user just said in one line, then ask. Each message usually carries one answer and one new gap.

3.2) Ask 2–3 questions at most in a turn, only where the answer changes the plan. For a new sub-request, the goal, the boundary and what success looks like are the questions that matter. Never pile them into a numbered questionnaire.

3.3) Record every unanswered question in `open_questions` and ask it in the conversation, in the same turn. When the user answers one, set its `status` to `"answered"` and write the `answer` — do not leave an answered question sitting open, and do not delete it. The (question, answer) pair is the decision record.

3.4) Do not invent the missing half of a request to make the edit feel complete. If the user says "再加个导出", that added part is a new requirement whose goal, format and boundary are unknown: ask, and leave those fields empty until answered.

### One turn at a time (worked)

- "再加一条：别动我原来的文件夹结构。" → Right: save `requirement.non_goals` + 1, keep `draft`, and say what changed and that everything else is untouched. Wrong: rebuild `approach` and the steps around a guess about the folder layout.
- Later: "整理完给我个清单就行。" → answer the open question about success, write the answer, keep `draft`.
- Later: "可以了，就照这个开工。" → with the goal, the boundary, the success and the steps now settled and each step verifiable, this is the moment to move `draft` → `ready` — not before.

## 4. Business language in, business language out

4.1) The same boundary as drafting holds after every edit: `requirement.*`, `approach`, `docs`, `risks` and `open_questions` state what the user will see, what is out, and what worries them — never how you will build it.
4.2) `checklist.steps` may name files, commands and libraries; it is the only field that may. A refinement that "adds detail" adds that detail in the steps, not in the requirement.
4.3) The user's own technical words are allowed where they apply: if they say "用 Python 写" or "改成用 SQLite 存", that is their decision — keep it. A technology nobody said still must not come in through a refinement.
4.4) Do not tidy the user's phrasing into terms when you patch a field; a refined field still holds their meaning in their register, in their language.

## 5. Where the status stands

- Keep `draft` while any of these is missing: the user's agreement with the restatement, the user's own words for success and non-goals, at least one step that says how it is known done, and answers to the open questions that would change the plan.
- Move to `ready` only when all of them are in and the user has confirmed. The backend refuses `ready` with no steps.
- If a refinement reopens something the user had settled — a non-goal is dropped, the goal changes — move it back to `draft`. That transition is allowed, and a plan that says `ready` over an open question is the lie this prevents.

## 6. Keep the plan executable

After a change, re-check the three things that make a plan usable, and repair them if your edit broke one:

1. every step still says how you will know it is done;
2. `requirement.non_goals` still matches what the user said is out of scope;
3. every `open_questions` entry still blocks something real — answer it, or say what it blocks.

A plan needs at least one step before it can be marked `ready`; that is the moment it stops being a draft.

## 7. Hand back

State the revision number, what changed, what you left alone, and anything the user's request implies that they did not say (as an assumption, not as a silent edit). If the plan was already executed somewhere, say so and say what the change means for that execution — do not edit a finished plan into looking like it was always that way.
