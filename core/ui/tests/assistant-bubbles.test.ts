import { describe, expect, it } from 'vitest'
import { ASSISTANT_BUBBLE_MARKER, splitAssistantBubbles } from '../src/helpers/assistantBubbles'

/**
 * 展示层气泡拆分：只有模型标记与结构规则两个来源，且代码块、公式、表格必须整体保留。
 */
describe('splitAssistantBubbles', () => {
  it('returns a single bubble for plain text without split points', () => {
    const text = '第一段。\n\n第二段，没有分隔线也没有标题。'
    const bubbles = splitAssistantBubbles(text, { structural: true })
    expect(bubbles).toHaveLength(1)
    expect(bubbles[0].content).toBe(text)
  })

  it('splits on the model marker and hides the marker itself', () => {
    const text = `第一句。\n${ASSISTANT_BUBBLE_MARKER}\n第二句。`
    const bubbles = splitAssistantBubbles(text)
    expect(bubbles.map(bubble => bubble.content)).toEqual(['第一句。', '第二句。'])
    expect(bubbles.some(bubble => bubble.content.includes(ASSISTANT_BUBBLE_MARKER))).toBe(false)
  })

  it('splits on an inline marker without leaving an empty bubble', () => {
    const text = `先说明。${ASSISTANT_BUBBLE_MARKER}\n再展开。`
    const bubbles = splitAssistantBubbles(text)
    expect(bubbles.map(bubble => bubble.content)).toEqual(['先说明。', '再展开。'])
  })

  it('ignores a marker inside inline code', () => {
    const text = `看这个 \`${ASSISTANT_BUBBLE_MARKER}\` 片段。`
    const bubbles = splitAssistantBubbles(text)
    expect(bubbles).toHaveLength(1)
    expect(bubbles[0].content).toContain(ASSISTANT_BUBBLE_MARKER)
  })

  it('never splits inside a fenced code block', () => {
    const text = [
      '说明如下：',
      '```ts',
      `const marker = '${ASSISTANT_BUBBLE_MARKER}'`,
      '---',
      '## 不是标题',
      '| a | b |',
      '```',
      '代码之后继续。',
    ].join('\n')
    const bubbles = splitAssistantBubbles(text, { structural: true })
    expect(bubbles).toHaveLength(1)
    expect(bubbles[0].content).toContain('## 不是标题')
    expect(bubbles[0].content).toContain(`const marker = '${ASSISTANT_BUBBLE_MARKER}'`)
  })

  it('never splits inside a display math block', () => {
    const text = [
      '推导：',
      '$$',
      'a = b',
      ASSISTANT_BUBBLE_MARKER,
      '---',
      '$$',
      '结论如上。',
    ].join('\n')
    const bubbles = splitAssistantBubbles(text, { structural: true })
    expect(bubbles).toHaveLength(1)
    expect(bubbles[0].content).toContain(ASSISTANT_BUBBLE_MARKER)
  })

  it('never splits inside a table', () => {
    const text = [
      '参数表：',
      '',
      '| 名称 | 值 |',
      '| --- | --- |',
      '| a | 1 |',
      '',
      '以上。',
    ].join('\n')
    const bubbles = splitAssistantBubbles(text, { structural: true })
    expect(bubbles).toHaveLength(1)
    expect(bubbles[0].content).toContain('| a | 1 |')
  })

  it('structural fallback splits at horizontal rules and swallows the rule', () => {
    const text = '第一段。\n\n---\n\n第二段。'
    const bubbles = splitAssistantBubbles(text, { structural: true })
    expect(bubbles.map(bubble => bubble.content)).toEqual(['第一段。', '第二段。'])
  })

  it('structural fallback splits before a section heading', () => {
    const text = '开头。\n\n## 第一部分\n\n内容一。\n\n## 第二部分\n\n内容二。'
    const bubbles = splitAssistantBubbles(text, { structural: true })
    expect(bubbles).toHaveLength(3)
    expect(bubbles[1].content.startsWith('## 第一部分')).toBe(true)
    expect(bubbles[2].content.startsWith('## 第二部分')).toBe(true)
  })

  it('does not split on heading or rules when structural fallback is off', () => {
    const text = '第一段。\n\n---\n\n第二段。\n\n## 标题\n\n内容。'
    const bubbles = splitAssistantBubbles(text, { structural: false })
    expect(bubbles).toHaveLength(1)
    expect(bubbles[0].content).toBe(text)
  })

  it('splits long paragraphs at blank lines once the budget is exceeded', () => {
    const long = 'x'.repeat(200)
    const text = `${long}\n\n${long}\n\n${long}`
    const bubbles = splitAssistantBubbles(text, { structural: true, budget: 320 })
    expect(bubbles.length).toBeGreaterThan(1)
  })

  it('hides a partially streamed marker at the end of the text', () => {
    const text = `第一句。\n${ASSISTANT_BUBBLE_MARKER.slice(0, 5)}`
    const bubbles = splitAssistantBubbles(text, { streaming: true })
    expect(bubbles).toHaveLength(1)
    expect(bubbles[0].content).toBe('第一句。')
  })

  it('keeps code block inner blank lines intact', () => {
    const text = ['```js', 'a', '', '', 'b', '```', '结尾。'].join('\n')
    const bubbles = splitAssistantBubbles(text, { structural: true })
    expect(bubbles[0].content).toBe(text)
  })

  it('returns no bubbles for empty text', () => {
    expect(splitAssistantBubbles('   ')).toEqual([])
  })
})
