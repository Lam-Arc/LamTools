---
name: take-exam
description: Create a complete test for learning goals in Study, accept written or image submissions, grade the whole submission, and update knowledge state from evidence. Also use for homework grading, retesting errors, and grade review. Do not automatically test after every explanation or treat helped or illegible answers as evidence of independent ability.
compatibility: For the Study Agent Skills host. Use only tools that are actually registered and authorized. If graph, exam, note, or media capabilities are unavailable, follow the fallback guidance below; do not invent interfaces.
metadata:
  version: "3.0.0"
  study-stage: "active"
---

# Take an exam

In one sentence: Assess whether the user can independently explain, choose, and apply what they learned, rather than merely reproduce a recently seen answer. Grades and mastery conclusions must correspond to checkable evidence.

## 1. Design the assessment before writing questions
1.1) Use this skill when the user requests a test or one was agreed. Prioritize a specified scope; otherwise use the most recently completed teaching unit. Read relevant goals, necessary history, and help records without expanding to the entire subject.
1.2) Build a brief blueprint: target node → observable ability → question type and grading grounds. Distinguish recall, method selection, condition judgment, calculation, explanation, and transfer. Question count is not the same as coverage.
1.3) If no count is specified, a small test of 3–6 questions can be a starting point; adjust for goals and time. This is not a scientifically optimal number. Explain sampling limits for a broad scope; do not use one short test to grade an entire subject.
1.4) For beginners, emphasize taught representative tasks and a few reasonable variations. For experienced learners, add method selection and transfer. Variations may change surface conditions while preserving taught principles; do not quietly assess new knowledge. Announce any diagnostic assessment of untaught knowledge beforehand.
1.5) When the user submits existing homework for grading, use the original questions. Obtain missing problem statements first; do not create an unrelated test. For a detailed blueprint, read [Assessment design](references/assessment.md).

## 2. Create and check the exam
2.1) Use the actual exam tool to save the exam ID, question numbers, nodes, question text, point values, reference solutions, and predetermined grading criteria in one operation. The reference solutions are durable grounds that the current Agent can recover after a long or compacted conversation, not secrets requiring separate execution. Do not call another model just to create a normal exam. When showing the complete test to the user, do not proactively include the reference solutions.
2.2) For multiple-choice questions, check whether one or several choices are allowed, how choices relate, and whether they unintentionally reveal answers. Accept equivalent wording and valid alternative solutions for free-response questions. Avoid repeating a single calculation with new numbers; do not create difficulty with obscure wording or rare traps.
2.3) Solve independently before publishing, checking conditions, units, results, diagrams, and whether answers can be graded. Use authorized calculation when needed; random numerical checks do not replace a proof. Do not publish an unverified question unless it is clearly marked as requiring manual verification.
2.4) Do not search by default for stable original practice questions. Check primary sources for requested authentic past papers, specific years or latest formats, real-world data, or uncertain rules. Distinguish authentic questions from original imitations. Do not fabricate years, sources, or copyright permission. For sources and images, read [Resources](references/resources.md).
2.5) Present the whole test at once. Except for English classes, use the user's usual language as primary; necessary English terminology must not add an unintended language assessment. A diagram must not reveal the answer, and one question must not inadvertently leak another question's independent target.

## 3. Collect answers and record help
3.1) Save partial answers by exam ID and question number. A single image does not automatically submit the exam. Grade the current submission as a whole only after the user explicitly submits, clicks Submit, or directly asks to grade this homework.
3.2) Mark an unclear image, uncertain question mapping, or ambiguous symbol as pending clarification; do not guess and then mark it wrong. Clear portions may be graded first. After explicit submission, a truly blank answer is unanswered, distinct from illegible work.
3.3) Route requests for help during an exam to answer. Record the questions or steps actually helped and the degree of help. Asking for help is not failure. An answer or key hint already revealed cannot support an independent-ability conclusion for that portion; judge untouched portions separately.
3.4) If image understanding, privacy authorization, or a compliant attachment path is absent, explain the gap and request the necessary text or a clear problem image. Do not pretend to have recognized it.

## 4. Grade diagnostically and allow corrections
4.1) The current Agent grades the whole submission against the established reference solution, point values, and criteria. Do not grade even multiple-choice questions by strict raw string comparison. Allow equivalent expressions, valid alternate solutions, and partial credit. A correct result may have unsound reasoning, and different wording may still be correct. Read saved reference answers by exam ID only if reliable original grounds are no longer in context; do not reread them every time.
4.2) Distinguish concept, condition, method choice, execution, and incidental calculation errors for each question. If a question relates to several nodes, attribute evidence only to visible steps, not the whole exam score to every node.
4.3) Focus feedback on which step, why it matters, and how to fix it. Present a concise result and key issues first; expand complete solutions on request. Do not use one grade to assess intelligence, effort, or ability across an entire subject.
4.4) If a question is ambiguous, the reference answer is wrong, or grading conditions are unfair, correct or void the affected item and recalculate. An exam author's error must not lower the user's state. Leave unresolved work pending.
4.5) Save each question's earned points, possible points, key-step points, and feedback. Mark uncertain work for clarification rather than failing the entire test for formatting differences. When the user disputes grading, consider valid alternate solutions and record the review version and reason. For detailed rules, read [Grading](references/grading.md).

## 5. Bound mastery updates
5.1) Save valid grading first, then use sign to submit the corresponding exam, questions, grading version, and reasons. Reuse idempotency so retries do not add or subtract points twice. Update only nodes supported by sufficient evidence; leave untested, unresolved, or helped portions without independent evidence unchanged.
5.2) Passing means meeting predetermined basic requirements. Low means the basics are met but unstable; medium requires reliable independent work on representative tasks; high requires repeated, reliable, independent evidence across different contexts. These are initial product rules, not a validated psychometric scale.
5.3) Do not jump to high mastery from one perfect short test or erase all history for one slip. Consider original evidence and recent changes; do not grade from a model confidence percentage.
5.4) A review corrects the original evidence; it is not a new independent exam. A changed historical grade should trigger validity checks for related notes or memory, not direct edits to the user's notes.
5.5) On request, retest the same goals with new questions. Suggest delayed review if agreed, but do not create reminders or background jobs on your own. After the exam, use answer for missed questions or teach for missing basics; do not force another question-by-question round.
