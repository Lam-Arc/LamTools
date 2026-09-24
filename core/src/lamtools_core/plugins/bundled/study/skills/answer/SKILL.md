---
name: answer
description: Resolve a specific knowledge question, skipped formula step, example error, code issue, or homework difficulty in Study. Give a hint or full explanation as requested; consult sources or use a minimal illustration when needed, and record relevant help during an exam. Use for “why,” “where is the error,” or “how does this step follow.” Do not restart a course or directly change mastery by default.
compatibility: For the Study Agent Skills host. Use only tools that are actually registered and authorized. If graph, exam, note, or media capabilities are unavailable, follow the fallback guidance below; do not invent interfaces.
metadata:
  version: "3.0.0"
  study-stage: "active"
---

# Answer a learning question

In one sentence: Identify the particular obstacle to understanding and give a checkable explanation or correction, without replacing an answer with a long lesson or a string of questions.

## 1. Locate the issue without interrogating the learner
1.1) Use the current question, selected passage, node, and available context to locate the obstacle. Do not first demand a full account of the learner's reasoning. Ask for necessary details only when an unclear problem statement, reference, version, or image truly prevents a correct answer.
1.2) Distinguish unfamiliar terms or notation, a skipped derivation step, confused conditions, method selection, calculation errors, language comprehension, and tool errors. Treat the diagnosis as a working hypothesis; do not label the user as weak.
1.3) Answer a simple question directly. Read related nodes or prerequisites only when relationships or mastery records would change the explanation; do not load a whole chapter or other node sessions first.

## 2. Give the requested level of help
2.1) State the requested conclusion or reason first, then show the necessary connecting steps. If the user asks only for a hint, do not reveal the full result prematurely. If they ask for a solution, explain it directly rather than forcing Socratic guessing.
2.2) Increase hints as needed: identify the condition → name a useful relationship → demonstrate a key step → explain fully. These are not mandatory rounds; the user may choose any depth immediately.
2.3) When correcting work, identify the first error that changes the result, explain why, and preserve the parts already correct. Do not merely replace the work with a standard answer. Even a correct result may have a gap in its justification; do not mark a valid answer wrong just because its form differs from the reference.
2.4) Correct a concept with one minimal contrast or counterexample. Present the correct rule first, then show where the mistaken rule fails; do not repeat the error at length. If the user still does not understand, switch to a more concrete representation instead of repeating the same words.
2.5) Define new symbols and formula validity conditions. For code, focus on the smallest relevant fragment and distinguish syntax errors, runtime behavior, and test-harness constraints. Do not claim an unverified formatting difference caused the problem.
2.6) Use short paragraphs and only necessary formulas or code. Use the primary language with English terms on first mention. Do not turn a local question into a multilevel outline. For detailed correction examples, read [Diagnosis](references/diagnosis.md).

## 3. Search and illustrate deliberately
3.1) You may verify a stable local derivation and answer directly. Check primary sources first for recent facts, specified software versions, official standards, component specifications, unfamiliar facts, or an explicit verification request. Read an unopened file or webpage before citing it.
3.2) Seek evidence that resolves this particular difficulty, not a list of related websites. Explain how it matches the conditions and cite the source. If verification fails, retain the specific uncertainty instead of making up an answer.
3.3) A minimal diagram or a few static states may explain a spatial, temporal, structural, or process issue. Use a checkable representation for precise technical diagrams and a reliable photograph for real appearance. If rendering is unavailable, fall back to text and do not claim a diagram was drawn.
3.4) Call only authorized, available tools. Read [Resources](references/resources.md) when source or media handling details matter. Do not force networking, drawing, or code execution for a simple answer.

## 4. Coordinate with an exam
4.1) Establish the actual exam ID, question number, and submission status. After submission, a full explanation is allowed. Before submission, still help as requested, but request authorized analysis only for the relevant question from the isolated exam service; do not read hidden answers for the whole exam.
4.2) Record the scope of substantive concept hints, key steps, or answers. Mere explanation of wording in the question is not automatically evidence of a knowledge gap. If help recording fails, do not claim a later response is confirmed independent evidence.
4.3) Do not present helped portions as independent mastery or treat asking for help as failure. Verify with a new problem if agreed. Do not call sign while answering a question.
4.4) If the question, reference answer, or grading seems wrong, check independently first. If needed, refer the original version to take-exam for recheck, retain the grounds, and do not silently create a new grade.

## 5. Finish and retain useful material
5.1) Stop when the issue is resolved. Do not automatically append three exercises, a chapter review, or an unrelated next step. Move to teach if the user requests systematic relearning, or to take-exam if they request a test.
5.2) Link an explanation worth retaining to its original node or question source as note material. Repeated questions may suggest an area to watch or a cause to verify; they do not automatically establish low mastery or a permanent personal label.
5.3) Before sending, check that you answered the actual question, kept correct work intact, included necessary conditions, stayed within the requested amount of help, and did not disclose unauthorized answers or invent tool results.
