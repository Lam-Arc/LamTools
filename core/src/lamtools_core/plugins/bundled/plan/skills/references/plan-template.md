# Plan document templates

Three documents carry a plan package's text. Keep them short and factual; the package holds the decisions, these hold the detail. Write only the ones the work needs — a one-day change does not need all three.

Read this file when you are about to write a plan's documents (`read_skill_reference` with `name: draft-plan`, `path: ../references/plan-template.md`).

## design.md — why this shape

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

## plan.md — what will be done

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

## tasks.md — the same steps, trackable

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

## Writing the documents

- Paths are relative to the project, forward slashes, no climbing out of it.
- Put them under a folder named for the work, e.g. `docs/<slug>/design.md`, and list them in the package's `docs` field with their `kind` (`design`, `plan`, `tasks`, `research`, `spec`, `notes`).
- Write the files first, then save the package that points at them: a path in the package that has no file behind it is a broken promise.
- If a document is long, keep its decisions at the top — the executor reads the first screen first.
