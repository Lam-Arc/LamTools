---
name: draft-plan
description: Turn a user's request into a plan package (方案) — requirement and non-goals, the chosen approach and what was rejected, documents, a step list where each step says how you will know it is done, the goal, and the risks — then save it with the plan_package tool. Use when the user asks for a plan, a 方案, a design or approach before work starts, or asks to think something through before anyone builds it. Also use it when the user describes a piece of work they want to hand to the desktop later. Do not use it for the steps of the turn you are running now: that is write_checklist.
metadata:
  version: "0.1.0"
  platforms: universal
---

# Draft a plan package

In one sentence: turn what the user said into a document someone else can start from without asking you anything, and store it — not a chat answer that scrolls away.

The plan you write is a **document with a life**: it is saved, revised, and later executed on a machine that can see files you cannot see. Write for that reader.

## 1. Ask before writing, but not much

Ask at most **five** questions, **one at a time**, and only where the answer changes the plan:

- what "done" looks like for the user (the observable end state);
- what is explicitly out of scope this time;
- anything irreversible (deleting, publishing, paying, sending);
- the target: which project or workspace this belongs to, if the user has not said;
- who decides when the plan and reality disagree.

Then stop asking. For everything else, choose the industry default, do it, and list it under `assumptions` — an assumption the user can see is a decision; an unstated one is a trap. Never ask two questions in one message, and never ask a question you could answer from what you have already been told.

## 2. Write the package

Fill every field below. Empty is allowed for `open_questions`, `risks` and `rejected`, but only when it is true:

| field | what goes in it |
|---|---|
| `title` | what this is, in the user's words |
| `summary` | one line a list can show |
| `requirement.restatement` | the request said back in your own words — the reader checks you understood it |
| `requirement.success_looks_like` | what the user will be able to observe when it works |
| `requirement.non_goals` | things that could reasonably be in scope and are deliberately not |
| `requirement.assumptions` | what you assumed instead of asking, each one falsifiable |
| `approach.chosen` / `approach.why` | the approach, and why it beats the alternatives |
| `approach.rejected` | each alternative and the one-line reason it lost |
| `docs` | the documents to write, as paths inside the project (design, plan, tasks, notes) |
| `checklist.steps` | the work, ordered, each with `description` and `deliverables` |
| `goal.objective` / `goal.completion_criteria` | what the work is for, and the criteria that end it |
| `risks` | what could go wrong, how likely, what you would do |
| `open_questions` | what you could not settle — each one blocks something specific |

Rules that make the difference between a plan and a wish:

- **A step must say how you will know it is done.** Name the evidence for each step — a test that passes, a file that exists, a command whose output is what you expect. "Improve X", "handle edge cases", "add validation" are not steps; write what changes and what proves it changed.
- **Keep steps small enough to check.** Aim for 5–15 steps. A step that needs a paragraph to describe is two steps.
- **Write the documents as real files** in the project (a design note, the plan, the task list) before you save the package, and list them in `docs` with their `kind`. The package holds the paths; the files hold the text.
- **Say what you have not seen.** You cannot read the target machine's files. Where a step depends on how things really are there, say so in the step itself and put the verification in the step — the executor is expected to check before changing anything.
- **No technology you cannot justify.** If the user named a stack, use it. Otherwise pick the boring option and say why in `approach.why`.

## 3. Save it, then say what you left open

Call `plan_package` with `action: "save"`, the `project_id`, and the fields above. The first save is revision 1; every later save records another revision, so nothing is lost by saving early.

Then tell the user, in this order:

1. the title and where it is stored;
2. the open questions, if any, and what each one blocks;
3. the assumptions you made instead of asking;
4. that nothing has been executed — this is a document, and starting it is a separate decision.

Do not summarise the whole package back to the user; they can open it. Do not start working on it.
