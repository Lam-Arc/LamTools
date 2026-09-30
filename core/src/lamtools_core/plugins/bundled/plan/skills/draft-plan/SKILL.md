---
name: draft-plan
description: Turn a user's request into a plan (方案) — a markdown document in the project's 「方案/」 folder that holds the requirement and non-goals, the chosen approach and what was rejected, a step list where each step says how you will know it is done, the goal, and the risks. Use when the user asks for a plan, a 方案, a design or approach before work starts, or asks to think something through before anyone builds it. Also use it when the user describes a piece of work they want to hand to the desktop later. More of it is a conversation than a document: confirm what the user said, ask what they have not said, and keep the file a draft until the user has agreed. Do not use it for the steps of the turn you are running now: that is write_checklist.
metadata:
  version: "0.3.0"
  platforms: universal
---

# Draft a plan (方案)

In one sentence: turn what the user said into a document someone else can start from without asking you anything, and save it as a file — not a chat answer that scrolls away.

The plan you write is a **document with a life**: it lives in the project's `方案/` folder, gets edited as the work evolves, and is later executed on a machine that can see files you cannot see. Write for that reader.

But before it is a document, it is a conversation. A plan records what the user decided, not what you assumed on their behalf. Most of the work of this skill is drawing out the part the user already knows and has not said yet.

## 1. Talk first; write down only what the user actually said

1.1) **Confirm, then ask.** Every turn: say what you heard back in one sentence ("So it is a thing that sorts the notes you already have, so you stop doing it by hand — right?"), then ask. Never answer your own question by guessing.

1.2) **Ask; do not fill the gaps yourself.** Ask 2–3 questions at most in one turn, in the user's own language and register. Prefer the questions whose answer changes the plan:
- what they are trying to end up with (the goal);
- what they will be able to see once it works (success);
- what they have already decided is out of this (non-goals);
- what worries them, or what they tried before and disliked;
- when they will call it finished, and who decides when plan and reality disagree.
Never hand over a numbered questionnaire, and never ask more than three questions in one turn. One turn moves the plan one small step; that is the correct pace, not a delay.

1.3) **A question is not asked until it is also recorded.** Put it in the plan file's 未答问题 section and ask it in the conversation, in the same turn. A question that lives only in chat dies with the session; a question that lives only in the file is never seen. Do both.

1.4) **Never invent content to look complete.** If the user has not said the goal, the boundary, or what success looks like, those sections stay empty (or say 还没定) and the plan stays a draft. A short honest draft with three open questions is a finished turn. A full-looking plan built on guesses is the exact failure this skill exists to prevent.

1.5) **Keep the user's words.** Write the user's meaning in their own register — spoken, uneven, half-sorted is normal early on. Do not upgrade "自动把笔记归归类" into a formal term the user never used, and do not answer in a language the user did not write in. Converse and write the plan in the user's language.

### The forbidden shape (learn it by its negative)

One vague sentence in, a complete-looking plan out, is the single worst outcome here.

- User: "我想做个能自动整理我笔记的东西" — that is the whole message.
- Wrong: write `方案/笔记整理.md` with a full approach (a language, a storage choice, a model), ten ordered steps naming files and libraries, risks, and `状态: 就绪`, then say "方案已生成，第一步是……". Everything after the title was invented; nothing was agreed; the status claims a settled plan.
- Right: confirm what you heard, ask 2–3 questions (where the notes live now; what they want to see once it has worked; what it must never touch), write only the title + 复述 + three 未答问题 with `状态: 草稿`, and say "我先把你这句记下来了，方案还是草稿；你回答上面几个，我再往下写。"

## 2. Business first: what the user will see, not how you will build it

The draft is the user's side of the agreement. Write what the user can observe, decide or object to — not your implementation.

2.1) **Sections that stay in business language** — 需求与边界, 取舍, 目标与完成判据, 风险, 未答问题, and the frontmatter 摘要. They answer: what is wanted, what is out, what the user will experience, what could go wrong for them.

2.2) **The one section allowed to be technical** — 步骤. Steps are instructions for whoever builds the thing, so they may name files, commands, tools and libraries. No other section inherits that permission.

2.3) **The user may open the door.** If the user themself names a technology, a target or a constraint ("我要用 Python 写", "跑在我们公司那台服务器上", "必须能离线"), it belongs where it applies — usually 取舍 and the steps — because it is now their decision, not your invention.

2.4) **Never name a technology the user did not.** "The boring default" is not an excuse: if the choice is not settled by the user's words, ask, or leave it to the steps and say it is not decided yet. A stack the user did not ask for is a decision you took for them.

2.5) **An empty step list is normal early on.** Do not invent steps to fill the 步骤 section. Steps appear when the work is understood well enough that each one has a way to be shown done.

## 3. The file, and when it may be called ready

Every plan is one markdown file at `方案/<标题>.md` — read [Plan templates](references/plan-template.md) for the exact shape before writing one. The short version: frontmatter with `状态:` and `摘要:`, then sections in order — 需求与边界, 取舍, 步骤, 目标与完成判据, 风险, 未答问题.

Keep `状态: 草稿` until all of these are true, then change it to `就绪`:
- the user has agreed with your restatement in their own words (not merely failed to object);
- 完成后能看到 and 这次不做 come from the user, not from an assumption;
- there is at least one step and each step says how you will know it is done — a plan that claims `就绪` with no checkable steps is a lie, and nothing outside you would stop it;
- every 未答问题 entry that would change the plan is answered, or the user has explicitly said to leave it.

Before that it is a draft even if it looks tidy. An incomplete draft is the normal state; `就绪` is a claim about agreement, not about tidiness. Only you protect it.

## 4. What goes in each section

Fill only what is true. Empty or 还没定 is the correct value in a draft, and a section may even stay empty in a finished plan when there is genuinely nothing there.

| section | what goes in it |
|---|---|
| frontmatter `状态` | 草稿 / 就绪 / 执行中 / 完成 — see section 3 |
| frontmatter `摘要` | one line a list can show |
| 需求与边界 | the request said back in your own words; what the user will observe when it works; things that could reasonably be in scope and are deliberately not; assumptions you made instead of asking |
| 取舍 | the approach and why it beats the alternatives; each rejected option and the one-line reason it lost |
| 步骤 | the work, ordered, each step with its verification — the only place technical words are welcome |
| 目标与完成判据 | what the work is for, and the criteria that end it |
| 风险 | what could go wrong, how likely, what you would do |
| 未答问题 | what you could not settle — each one blocks something specific |

Rules that keep a finished plan from being a wish:

- **A step must say how you will know it is done.** Name the evidence — a test that passes, a file that exists, a command whose output is what you expect. "Improve X", "handle edge cases", "add validation" are not steps; write what changes and what proves it changed. This is the only section where technical words are welcome.
- **Keep the steps checkable.** Aim for 5–15. A step that needs a paragraph to describe is two steps.
- **One plan, one file.** Supporting documents (a long design, a task list) go wherever the work needs them in the project — point at them from the plan's 步骤 or 取舍 — but the plan itself stays the single file the library shows.
- **Say what you have not seen.** You cannot read the target machine's files. Where a step depends on how things really are there, say so in the step and put the verification in the step — the executor checks before changing anything.

## 5. Write the file, then say what is still open

Write the plan with `write_file` at `方案/<标题>.md` — start with whatever is settled, however little. The file is the whole story: there is no hidden revision history, so what you leave unsaid is simply not there, and writing early loses nothing while holding an unfinished plan in chat loses everything. Editing later is `edit_file` on the same file.

Then tell the user, briefly:

1. the file path you wrote;
2. the questions you are waiting on, and what each one blocks;
3. the assumptions you made instead of asking, if any;
4. that nothing has been built — this is a document, and starting it is a separate decision.

Do not summarise the whole plan back to the user; they can open it in the library. Do not start working on it.
