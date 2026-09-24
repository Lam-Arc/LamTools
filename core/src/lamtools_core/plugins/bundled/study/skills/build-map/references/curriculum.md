# Curriculum design: work backward from achievable tasks

Read when creating a complete course, a cross-course system, checking coverage, or finding that a map has only chapter titles.

## 1. Align three layers

1.1) Learning goals: what the learner can explain, judge, calculate, prove, implement, or design after the course.
1.2) Evidence: what responses or work would show those abilities, and what merely repeats memorized material.
1.3) Teaching: which knowledge and examples enable the goals. Order by real prerequisites, not table-of-contents position.
1.4) Do not generate a large table for every small node. Keep necessary alignment at course and module level; leaf nodes inherit applicable requirements.

## 2. Original derivative-unit design example

Goal: explain a derivative at a point through the difference quotient, use the chain rule correctly, and distinguish differentiability from continuity.
Content: function change, difference quotient and limit, point derivative and derivative function, basic differentiation, composite functions and chain rule, conditions and counterexamples.
Teaching: connect quotient and tangent with the same x² example; demonstrate a complete composite differentiation; use |x| as a counterexample through one-sided rates of change.
Evidence: explain why h cannot be set directly to zero in the quotient; independently differentiate a composite with a nontrivial inner function; evaluate “continuous implies differentiable” with a reason or counterexample.
Scope: the unit does not automatically include partial derivatives, gradient descent, or differential equations, though it may link to them meaningfully later.

## 3. Prerequisites and associations

3.1) Separate administrative course prerequisites from knowledge actually needed. MIT 18.06SC's syllabus distinguishes an institution's multivariable-calculus requirement from calculus not being necessary to learn linear algebra itself. Do not copy enrollment conditions as hard knowledge dependencies.
3.2) Use stable IDs for shared concepts and place course-specific requirements on the course or membership. A vector linear combination may link to circuit equation systems, but explain the actual linear model and applicability.
3.3) A course may have several learning routes. A route changes teaching order, not automatically hides confirmed content. A large graph's nodes and edges do not prescribe one lesson order.
3.4) Check unreasonable cycles and vague dependencies. Hard prerequisite A→B and B→A calls for decomposition or association instead. Ordinary bidirectional references are not errors.

## 4. Comprehensive within bounds

4.1) Preserve the scope source and version and track “framework,” “needs detail,” and “needs verification” by module. Store each independent formula and its conditions, but equivalent transformations may live in one node.
4.2) Check completeness against a scope list and read the original syllabus or course requirements when needed. Without an actual source, call the result a general draft rather than a guaranteed exam scope.
4.3) It is valid to build a reliable framework and refine it in batches, but do not call the first batch a complete course. Do not promise ongoing background map building without scheduling capability.
4.4) Existing knowledge nodes may briefly note example choice, common confusions, boundaries, and directions for independent assessment. Leave empty when there is nothing useful; do not mass-generate vague slogans.

## 5. What to borrow from courses

MIT 18.06SC combines units, explanations, worked examples, and practice into learning sessions. Borrow the organization, not all prerequisites or question counts. https://ocw.mit.edu/courses/18-06sc-linear-algebra-fall-2011/pages/syllabus/
CS50 Lecture 0 connects one search problem to everyday action, pseudocode, and algorithm selection. Borrow its concrete-to-abstract continuity, not entertainment as evidence of learning. https://cs50.harvard.edu/x/2025/notes/0/
CMU emphasizes aligning goals, assessment, and teaching. Borrow the design method; a curriculum graph alone is not proof that a learner mastered it. https://www.cmu.edu/teaching/designteach/design/learningobjectives.html
