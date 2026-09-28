---
name: refine-plan
description: Revise an existing plan package (方案) from the user's feedback — change what they asked to change, keep everything else, and record the revision. Use when the user asks to adjust, correct, shorten, extend or re-think a plan that already exists, including after it was stored on another device. Read the current package first with plan_package; never rebuild it from memory.
metadata:
  version: "0.1.0"
  platforms: universal
---

# Refine a plan package

In one sentence: change exactly what the user asked for, keep the rest, and let the history show what moved.

## 1. Read it before you touch it

Call `plan_package` with `action: "get"` and the id (or `action: "list"` to find it by title). Read the whole package — requirement, approach, steps, goal, risks, open questions. Editing a plan you did not read first is how a plan loses decisions that were argued over.

There is only ever one copy of a plan package per host, and each host keeps its own history: the phone's copy is the phone's. If the user is talking about a plan they made elsewhere, say which copy you are editing.

## 2. Change the least that satisfies the request

- A save is a **patch**: send only the fields you are changing, plus the id. Everything you leave out keeps its value — so never re-send the whole package "to be safe": it is how a reviewed field silently reverts.
- Send `expected_revision` when you have just read the plan, so a concurrent change is refused instead of overwritten.
- Every accepted save becomes a new revision; the old text is still there and can be restored. Say the revision number when you are done.
- If the user's feedback contradicts something in the package (a non-goal, an assumption, a step), fix the contradiction too, and tell them you did — a plan with an admitted conflict is worse than a shorter plan.

## 3. Keep the plan executable

After a change, re-check the three things that make a plan usable, and repair them if your edit broke one:

1. every step still says how you will know it is done;
2. `requirement.non_goals` still matches what the user said is out of scope;
3. every `open_questions` entry still blocks something real — answer it, or say what it blocks.

A plan needs at least one step before it can be marked `ready`; that is the moment it stops being a draft.

## 4. Hand back

State the revision number, what changed, what you left alone, and anything the user's request implies that they did not say (as an assumption, not as a silent edit). If the plan was already executed somewhere, say so and say what the change means for that execution — do not edit a finished plan into looking like it was always that way.
