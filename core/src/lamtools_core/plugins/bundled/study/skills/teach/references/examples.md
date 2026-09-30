# Original teaching examples and checks

Purpose: demonstrate how to explain different obstacles clearly. These are neither a uniform response template nor reports of real learner experiments. The passages below are original to this package. Chinese in the sample user messages and responses illustrates the required user-language behavior.

## 1. Introducing derivatives through change

Sample user: “我刚学导数，别先给一堆公式。”

Sample response:
“导数（derivative）描述的是：在某个位置，输入稍微变化时，输出变化得有多快。以y=x²为例，在x=2附近，x增加h，y就从4变为(2+h)²，所以这段的平均变化率是
\[
\frac{(2+h)^2-4}{h}=4+h,\quad h\ne0.
\]
当h越来越接近0，平均变化率越来越接近4；因此x=2处的导数是4。注意不是把h=0塞进原分式，而是看h趋近0时的极限；图上对应曲线在(2,4)附近的切线斜率。”

If drawing is available, generate a matching curve, point, and tangent y=4x−4. Otherwise the text should be complete without claiming an absent figure appears below. Check: derivative at one point; local relationship not mistaken for global linearity; no premature higher derivatives, differential equations, or optimization.

## 2. Chain rule: supply the skipped bridge

Sample user: “为什么还要乘2x？”

Sample response:
“因为你不是对x直接取立方，而是先把x变成x²+1，再对这个结果取立方。令u=x²+1，外层对u的导数是3u²，内层对x的导数是2x；两层的变化率要相乘，所以y'=3(x²+1)²·2x。只写前半段，算的是对u的变化率，不是对x的。”

Check: the intermediate variable is explained, not merely “because of the chain rule.” A local question does not restart the whole lesson. Search and imagery are usually unnecessary.

## 3. Electronics: conditions, quantities, and verification together

Sample user: “RC充电的时间常数为什么有意义？”

Sample response:
“先看理想5V阶跃源经1kΩ电阻给初始未充电的100μF电容充电：τ=RC=0.1s。电容电压是vC(t)=5(1−e^(−t/0.1))V，因此一个τ后约为3.16V，即最终值的63.2%；τ刻画这个响应变快或变慢的时间尺度，不表示一个τ后就充满。初始电流是5mA，随后随电容电压上升而减小。”

When supported, show a time-versus-capacitor-voltage curve marking 0.1s and 3.16V. The topology must be series RC with output across the capacitor. This is ideal analysis, not a safe design for particular components; real selection requires checking voltage rating, power, source impedance, and application conditions. Check μF conversion, do not say five time constants means exactly full, and distinguish capacitor and resistor voltages.

## 4. Data structures: explain states, not just traversal order

Sample user: “我总是不明白BFS的队列有什么用。”

For the unweighted graph A→B, A→C, B→D, C→D, process neighbors alphabetically. Explain that the queue holds nodes already discovered but not expanded, and mark each on enqueue. Start at [A]. After processing A: [B,C]; after B: [C,D]; while processing C, D is already discovered, so do not enqueue it again; [D] remains. The resulting order is A,B,C,D under this convention, not unique for all neighbor orders.

Check that marking on enqueue prevents duplicates. Do not equate the minimum-edge-count path from unweighted BFS with shortest paths under arbitrary edge weights. This small graph needs a state sequence more than an elaborate animation.

## 5. An experienced learner requests proof

Sample user: “我会计算，解释可导为什么蕴含连续。”

If f is differentiable at a, the difference quotient for x≠a approaches finite f'(a) as x→a. Then
\[
f(x)-f(a)=\frac{f(x)-f(a)}{x-a}(x-a)\longrightarrow f'(a)\cdot0=0.
\]
Hence f(x)→f(a), so f is continuous at a. The converse fails: |x| is continuous at 0, but its left and right difference quotients are −1 and 1.

Check for a finite real derivative and appropriate neighborhood in the domain. Use the displayed identity only for x≠a and reason by a limit, not direct substitution. Do not reteach “what is a function” to this learner.

## 6. From a concrete problem to an algorithm

A sorted list of numbers illustrates checking the middle and excluding half by comparison. Without sorting, that exclusion is unjustified. Then connect the example to binary search's interval invariant and stopping condition. Do not treat O(n/2) as a different asymptotic complexity class from O(n).

## 7. Humanities: a principle reached through a parable

Sample user: “为什么说‘看不见的样本’会让结论反过来？”

The `teach-humanities` member applies, so the story comes first and the principle is named only after it:

Story: “返航的飞机机翼上全是弹孔，工程师打算给机翼加装甲。有人问：发动机上为什么没有弹孔？——因为发动机中弹的飞机没回来。装甲加在了发动机上。”

Principle, named after the story: 你能观察到的样本不等于总体；当未被观察到的个体恰恰被你正在研究的那个过程筛掉时，眼前的规律可能指向反面。

Mapping, then boundary: 返航的飞机=可见样本；机翼弹孔=看得见的证据；干净的发动机=消失的样本；结论来自“没有看到什么”，而不是“看到了什么”。故事的边界是它假定记录只覆盖幸存者，也假定增重的代价可以接受；样本随机抽取时它不适用，它也不告诉你哪个部件最关键。

Check: the story is followable with no statistical vocabulary; the conclusion is not stated inside it; the mapping names each element; the boundary says what the story does not establish. Do not use the story as evidence that a particular decision was made, and do not answer with the abstract thesis alone when the learner asked for the story.

## 8. Science: a definition immediately followed by its gloss

Sample user: “导数是什么？别先给一堆公式。”

The `teach-science` member applies, so the formal statement is followed at once by a gloss, before any derivation:

“导数（derivative）在一点上说的是：输入稍微一变，输出变得有多快，单位是‘输出单位／输入单位’。在x=2附近，x增加一点点，y大约按4倍于这个增量的速度变化——所以x=2处的导数是4。”

Then the formal statement and its check: the difference quotient (f(2+h)−f(2))/h = 4+h for h≠0, whose limit as h→0 is 4. The gloss and the definition agree at the boundary: h is never substituted as 0, and differentiability is a claim about one point, not the whole curve.

Check: the gloss is checkable (the computed quotient confirms the stated rate), it uses no undefined term, and the metaphor or image, if used, is marked where it fails. A numerical spot check is evidence for the gloss, not a proof of the general statement. A list of definitions each with a three-word translation is a glossary, not this pattern.

## 9. Evaluate these passages

Check whether the approach suits the input, necessary bridges are present, and conditions and results are correct. Do not merely check for keywords such as “example” or “diagram.” Companion code checks the sample numbers and derivations, but passing those checks does not mean every unknown problem will be taught correctly.
