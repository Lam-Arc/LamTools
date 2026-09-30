# Glosses: the restatement that follows a definition

Read when building a definition for a first lesson, when the learner says an explanation is still abstract, or when a metaphor may be doing work the definition should do.

## 1. What counts as a gloss

1.1) Three tests, all of them required:

- A person outside the subject can say, after reading it, what the statement is about, what makes the quantity bigger or smaller, and when it applies.
- It is checkable: you can name a measurement, an operation, or a case that would show the gloss is wrong.
- It adds no undefined term; every term it uses was defined earlier or is defined inside it.

1.2) A gloss is not a synonym, a translation of the notation, or the same claim in a second set of symbols. “The derivative is the instantaneous rate of change” repeats the definition; “nudge the input a little and this is how much faster the output moves, in output units per input unit” is a gloss.
1.3) A gloss can be short. One or two sentences are normal; length is not the test, and a longer gloss that stays abstract fails anyway.

## 2. Build it in four moves

2.1) Objects and conditions: what the statement is about, and what must be true for it to apply.
2.2) The measurable relation: which thing responds to which, in what direction and by how much, in what units, with what held fixed.
2.3) A direct referent: a situation the learner can see, touch, or measure — a speedometer, a slope walked up, a scale reading, a water level, a temperature, a running time, a queue at a counter.
2.4) The boundary: what happens at the edge of the conditions, and where the direct referent stops matching.

## 3. Worked example: derivative and differentiability at a point

Formal statement: f is differentiable at a when the difference quotient (f(a+h)−f(a))/h has a finite limit as h→0, and that limit is f′(a).

Gloss: “Near a, the output moves almost proportionally to the input: nudge the input by a small amount, and the output changes by about f′(a) times that amount, measured in output units per input unit. Differentiable means one such number describes the neighbourhood — the graph has a definite tilt there.”

Boundary: h is never zero in the quotient; the claim is local, about one point, not the whole curve; a finite limit is required, so a vertical tangent or a corner fails it.

Check instance: f(x)=x² at a=2 gives the quotient 4+h, and the gloss says the output changes by about 4 per unit of input near 2 — the computed quotient agrees.

Metaphor and its failure: “speedometer reading” carries the rate idea but drops the local-versus-global distinction; a car at constant speed shows the same reading everywhere, while differentiability is a claim about one point.

## 4. Worked example: resistance and the time constant

Formal statement: for an ideal series RC circuit driven by a voltage step, τ=RC and v_C(t)=V(1−e^(−t/τ)).

Gloss: “After the switch, the capacitor voltage climbs toward the supply voltage. τ is the time it takes to close about 63% of whatever gap is left. A larger resistor or a larger capacitor makes the climb slower, because less current flows or more charge is needed for the same voltage.”

Boundary: ideal source, no series resistance inside the capacitor, no leakage; τ is a time scale, not the moment of full charge, and five τ is about 99.3%, not exactly full.

Check instance: 5 V, 1 kΩ, 100 μF gives τ=0.1 s and v_C(τ)≈3.16 V, which the formula reproduces.

Metaphor and its failure: “filling a bucket through a narrow pipe” carries the slower-fill idea but misses that the driving voltage falls as the capacitor charges, so the fill rate is not constant.

## 5. Failure modes to check

- Deriving or transforming immediately after a definition, with the gloss deferred or omitted.
- “Intuitively obvious” offered in place of an actual restatement.
- A vivid metaphor standing in for the definition, with no stated point of failure.
- A gloss that smuggles in a new undefined term, so the learner is still blocked.
- A gloss inconsistent with the conditions: substituting h=0, dropping a nonzero denominator, or ignoring independence.
- A glossary — many terms, three words each — presented as glossing.
- An ideal curve or a generated figure presented as measurement.
- A numerical spot check claimed as proof of the general statement.
- Re-glossing what the learner already demonstrated instead of teaching the current obstacle.

## 6. Check before sending

6.1) Would a person outside the subject pass the three tests in 1.1 on your gloss, without seeing the formal statement?
6.2) Can you name the instance that would falsify the gloss, and does the gloss still agree with the definition at the boundary?
6.3) If a metaphor is present, is its failure point stated in the same paragraph?
