---
name: execute-plan
description: Execute a stored plan package (方案) on this machine — reconcile the plan with what the files actually say, record the rulings, install the goal and the checklist, then work the steps in order. Use when a plan is handed over for execution, when the user asks to start, run or carry out a plan, or when a session was opened from a plan. Desktop only: a plan written elsewhere never saw this repository.
metadata:
  version: "0.1.0"
  platforms: desktop
---

# Execute a plan package

In one sentence: the plan was written on a machine that could not see these files — find out where it is wrong before you act on it, and say what you changed.

## 1. Reconcile before you build

Read the package (`plan_package` with `action: "get"`) and the documents it lists, then check it against reality, cheapest checks first:

- do the named paths exist, and do they still do what the plan says they do?
- do the interfaces, commands, dependencies and versions the plan assumes match what is here?
- is there already a half-finished attempt, a branch, or a note that supersedes part of the plan?
- do the plan's steps contradict each other or the repository's own rules?

Then, for every disagreement, make a call and write it down in this form:

`Ruling: <what you decided> — <why> — <what it costs if you are wrong>`

Fix the plan itself with `plan_package` (`action: "save"`, send only the changed fields, include `expected_revision`) so the revision history carries the correction, and read the corrected step back before working it. A plan quietly executed against a wrong assumption is the failure this step exists to prevent.

Stop and ask only when the answer is genuinely the user's to give: something irreversible, something that spends money, something that touches systems outside this workspace, or a plan so far from reality that every path forward is a guess.

## 2. Install the work

- Create or adopt the goal from `goal.objective` and `goal.completion_criteria`, so the run is measured against the same criteria the plan states.
- Put `checklist.steps` into the session checklist (`write_checklist`) as the first thing you do, so the user can see the same list the plan describes, and keep it current as you go — the checklist is the live state, the plan is the document.
- Write the plan's documents into the project if they are not already there, at the paths the package names.

## 3. Work it

- One step at a time, in order; a step is done when its verification passes, not when the code looks right. Show the evidence (the command and its output, the test result) rather than asserting success.
- When reality forces a change of approach mid-step, update the plan as well as the checklist, and say so in the same turn.
- Never widen the scope on your own: `requirement.non_goals` is binding. If a step cannot be done without crossing one, stop and ask.
- If a step is blocked, mark it blocked, say what would unblock it, and move to the next step that is not blocked by it. Do not quietly skip it.

## 4. Close it out

When the criteria in `goal.completion_criteria` are met and shown, mark the goal complete and the plan `done` (a new save — the earlier revisions stay readable). Then give the user: what was built, where it lives, the evidence for each completion criterion, the rulings you made along the way, and anything you deliberately left out.
