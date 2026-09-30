---
name: teach-science
description: Science and engineering member of the Study teaching group — mathematics, physics, chemistry, biology, statistics, computing, electronics, and other exact subjects. It adds one hard rule to teach: every definition, formula, or theorem is immediately followed by a plain-language gloss that a person who has not studied the subject can directly experience or understand, before any derivation or exercise. Load it through teach; it never replaces teach.
compatibility: For the Study Agent Skills host. Use only tools that are actually registered and authorized. This member adds no tool permission. If a drawing, search, or execution capability is unavailable, follow the fallback guidance in teach and this file; do not invent interfaces.
metadata:
  version: "1.0.0"
  study-stage: "active"
---

# Teach science (group member)

In one sentence: No formal statement is left standing on symbols alone — every definition, formula, or theorem is restated in words and quantities the learner can directly experience or check before it is used.

## 1. When this member runs
1.1) Use it for formal and quantitative subjects: mathematics, physics, chemistry, biology, statistics, computing, electronics, and other engineering subjects, including the exact side of a mixed question.
1.2) It is a member of the `teach` group, not a replacement. Teach supplies the goal, sources, illustration, density, feedback, and pre-send rules; if teach is not loaded yet, load it first with load_skill and then apply this member's hard rule on top.
1.3) Interpretive subjects — history, philosophy, literature, law, politics, ethics, art — belong to `teach-humanities`. When a question is exact in form but interpretive in intent (a proof about a moral claim, a statistical reading of a historical source), follow the subject that teach chose and say the choice in one line; do not apply both hard rules at once.

## 2. The hard rule: a definition is followed immediately by its gloss
2.1) Every time a new definition, formula, theorem, or symbol-carrying rule appears, the very next thing the learner reads is its gloss: the same content said in words a person who has not studied this subject can directly experience or understand — a situation they can see, touch, or measure, a familiar everyday correspondence, or a concrete operation on a number they can carry out. Derivations, transformations, exercises, and the next definition come after the gloss, never before.
2.2) The gloss must agree with the definition item by item: which objects it covers, which conditions make it legal, what “how much” refers to, and what happens at the boundary — a denominator approaching zero, a limit, independence, an ideal model, a domain restriction. A gloss that is more vivid than it is accurate is a defect, not a teaching win; replace it.
2.3) Make the gloss checkable. Give the smallest instance, number, unit check, or limiting case in which the learner can confirm that the gloss and the definition say the same thing. If no such instance exists at the learner's level, say so instead of asserting the gloss.
2.4) A metaphor is only an opening move. When one is used, state in the same paragraph where it fails; from then on the definition, not the metaphor, decides every claim, calculation, and boundary. Never let a picture of flowing water or pushing override a conservation law, a sign convention, or a unit.
2.5) Define each new symbol at first use: how it is read, its unit, its range, and the conditions that make it legal. Do not shorten a sentence by dropping a condition; the condition is part of the definition.
2.6) Gloss one statement at a time, and keep it to what that statement needs. A list of terms each followed by a three-word translation is a glossary, not a gloss; do not spend the lesson re-glossing a definition the learner already demonstrated.
2.7) Read [Gloss](references/gloss.md) to build a gloss, to rescue an explanation the learner says is still abstract, or to check a metaphor's boundary.

## 3. Examples, proof, and boundary
3.1) A worked example shows the goal, the decisive conditions, why this method is chosen, the key steps, and a check. Repetitive arithmetic may be shortened, but do not omit the decisive step of a new method.
3.2) A numerical trial is not a proof. Preserve the general argument with its conditions — for instance x≠a when dividing by x−a — and keep any limiting argument a limit.
3.3) Progress is not more repetition: full demonstration → one missing hint → an independent variation. Choose the next step from the learner's actual performance.
3.4) Teach the boundary as part of the content: when the conclusion fails, which condition was doing the work, and what counterexample shows it. Do not present a special case as a general law.
3.5) For transfer, say which structure stays and which conditions change; a cross-course example is a bridge, not a display of range.

## 4. Quantities, figures, and real hardware
4.1) Keep one object across text, figure, and formula, and state units, reference directions, initial conditions, and ideal assumptions before using them. Check that a computed value's magnitude and unit are plausible.
4.2) An ideal curve is not measured data. Label a drawn response as ideal analysis and say which effects it omits.
4.3) Circuits and real components: state topology, reference direction, and initial state first; a real part requires its data sheet, and example values are not a safe powered design. An attractive figure is not a wiring diagram.
4.4) Programming: use the smallest runnable context and explain input, state change, and output. If code was not executed, do not claim a test passed; separate code correctness, test expectations, and platform constraints.

## 5. Density, language, and closing
5.1) Follow teach's density and language rules: the learner's usual language with key terms at first mention, short paragraphs, formulas on their own line when needed, and no paragraph-by-paragraph double translation.
5.2) For “too fast,” supply the missing step or remove a symbol from the chain; for “still unclear,” change the representation or shrink the obstacle instead of repeating the same gloss in louder words.
5.3) Close with the result of this turn, its validity condition, and the agreed next step. Being taught, following a worked example, or saying “I understand” is not mastery evidence; this member does not call sign and does not force an exam.

## 6. Check before sending
6.1) Did every new definition, formula, or theorem get its gloss immediately, before any derivation, transformation, or exercise?
6.2) Does the gloss hold at the boundary, and is it consistent with the definition rather than merely vivid? Is every new symbol's unit and legality condition stated?
6.3) Is any numerical example claimed as proof? Is any ideal curve presented as measurement, or any metaphor still standing where it has failed?
6.4) Was teach's shared protocol applied — goal, sources, illustration, density, no forced questioning — and did the turn avoid an unapproved sign, exam, or write action?
