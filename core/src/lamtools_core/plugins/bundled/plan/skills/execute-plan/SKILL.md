---
name: execute-plan
description: Execute a stored plan package (方案) on this machine — read the plan back with the user and confirm the business expectations, reconcile the plan with what the files actually say, record the rulings, install the goal and the checklist, then work the steps in order. Use when a plan is handed over for execution, when the user asks to start, run or carry out a plan, or when a session was opened from a plan. The checklist steps may carry implementation detail; the plan's requirement, success and non-goals stay in the user's business language. Desktop only: a plan written elsewhere never saw this repository.
metadata:
  version: "0.2.0"
  platforms: desktop
---

# Execute a plan package

In one sentence: the plan was written on a machine that could not see these files — find out where it is wrong before you act on it, and say what you changed.

## 1. Read the plan back before you touch anything

1.1) Read the package (`plan_package` with `action: "get"`) and the documents it lists.

1.2) Say the plan's business side back to the user in their language, in one short turn: what it is for, what they will be able to see once it is done, and what it will not touch. That is the confirmation that matters — the user is checking the outcome, not the implementation. Do not make them audit the technical steps before you start.

1.3) If they correct the outcome, fix the plan first (a `save`, then read the change back) instead of building the version they just disagreed with.

## 2. Reconcile before you build

Check the plan against reality, cheapest checks first:

- do the named paths exist, and do they still do what the plan says they do?
- do the interfaces, commands, dependencies and versions the plan assumes match what is here?
- is there already a half-finished attempt, a branch, or a note that supersedes part of the plan?
- do the plan's steps contradict each other or the repository's own rules?

Then, for every disagreement, make a call and write it down in this form:

`Ruling: <what you decided> — <why> — <what it costs if you are wrong>`

Fix the plan itself with `plan_package` (`action: "save"`, send only the changed fields, include `expected_revision`) so the revision history carries the correction, and read the corrected step back before working it. A plan quietly executed against a wrong assumption is the failure this step exists to prevent.

Stop and ask only when the answer is genuinely the user's to give: something irreversible, something that spends money, something that touches systems outside this workspace, or a plan so far from reality that every path forward is a guess.

## 3. Two languages at install time

3.1) `checklist.steps` is the field that may carry implementation detail — files, commands, libraries. Installing it into the session checklist (`write_checklist`) with that wording is correct: the checklist is the builder's list.

3.2) The plan's business fields keep their wording. `requirement.restatement`, `requirement.success_looks_like`, `requirement.non_goals`, `goal.objective`, `goal.completion_criteria`, `risks` and `open_questions` are the user's agreement; do not rewrite them into implementation language while you install or while you work. If reality forces the steps to change, change the steps and leave the agreement intact.

3.3) If reality genuinely contradicts the agreement — a non-goal has become impossible, success as stated cannot be observed — do not quietly redefine it in technical terms. Stop and put it to the user in their own language.

## 4. Install the work

- Create or adopt the goal from `goal.objective` and `goal.completion_criteria`, so the run is measured against the same criteria the plan states.
- Put `checklist.steps` into the session checklist (`write_checklist`) as the first thing you do, so the user can see the same list the plan describes, and keep it current as you go — the checklist is the live state, the plan is the document.
- Write the plan's documents into the project if they are not already there, at the paths the package names.

## 5. Work it

- One step at a time, in order; a step is done when its verification passes, not when the code looks right. Show the evidence (the command and its output, the test result) rather than asserting success.
- When reality forces a change of approach mid-step, update the plan as well as the checklist, and say so in the same turn.
- Never widen the scope on your own: `requirement.non_goals` is binding. If a step cannot be done without crossing one, stop and ask.
- If a step is blocked, mark it blocked, say what would unblock it, and move to the next step that is not blocked by it. Do not quietly skip it.

## 6. Close it out

When the criteria in `goal.completion_criteria` are met and shown, mark the goal complete and the plan `done` (a new save — the earlier revisions stay readable). Then give the user, in their language and in terms they can check: what was built, where it lives, the evidence for each completion criterion, the rulings you made along the way, and anything you deliberately left out.
