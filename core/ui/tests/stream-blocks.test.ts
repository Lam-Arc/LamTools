import { describe, expect, it, vi } from 'vitest'
import { lastNewlineFrom, markBlockEnter } from '../src/components/streamBlocks'

// user:“做C”+(块级落定：源文本出现换行 = 这一块写完；只给新出现的可见文字包一次动画)。
describe('块级落定：什么时候算写完', () => {
  it('没有换行就不算写完', () => {
    expect(lastNewlineFrom('只有一行还没换行', 0)).toBe(-1)
  })

  it('换行在起点之后才算', () => {
    const text = '第一行\n第二行'
    expect(lastNewlineFrom(text, 0)).toBe(3)
    expect(lastNewlineFrom(text, 4)).toBe(-1)
  })

  it('最后一个换行优先（一次到达多行时整块落定）', () => {
    const text = 'a\nb\nc'
    expect(lastNewlineFrom(text, 0)).toBe(3)
  })
})

describe('块级落定：动画节点', () => {
  function mount(content: string): HTMLElement {
    const container = document.createElement('div')
    container.innerHTML = content
    document.body.appendChild(container)
    return container
  }

  it('从 0 开始：整段包一次，且只有一个动画节点', () => {
    const container = mount('<p>第一段</p><p>第二段</p>')
    const next = markBlockEnter(container, 0)
    expect(next).toBe(6)
    // 每个文本节点各包一层：两段文字 → 两个 span，但合起来只覆盖这一次落定的内容。
    const spans = Array.from(container.querySelectorAll('span.stream-block-enter'))
    expect(spans.map(span => span.textContent).join('')).toBe('第一段第二段')
    container.remove()
  })

  it('第二次落定会回收上一次的节点，只留新块', () => {
    const container = mount('<p>第一段</p>')
    markBlockEnter(container, 0)
    container.insertAdjacentHTML('beforeend', '<p>第二段</p>')
    const next = markBlockEnter(container, 3)
    expect(next).toBe(6)
    const spans = Array.from(container.querySelectorAll('span.stream-block-enter'))
    expect(spans).toHaveLength(1)
    expect(spans[0].textContent).toBe('第二段')
    container.remove()
  })

  it('emoji 不会被拆开', () => {
    const container = mount('<p>a😀b</p>')
    markBlockEnter(container, 1)
    const span = container.querySelector('span.stream-block-enter')
    expect(span?.textContent).toBe('😀b')
    container.remove()
  })

  it('按钮与公式里的文字不参与动画', () => {
    const container = mount('<p>正文</p><button>按钮</button><span class="katex">公式</span>')
    const next = markBlockEnter(container, 0)
    expect(next).toBe(2)
    expect(container.querySelector('button span.stream-block-enter')).toBeNull()
    expect(container.querySelector('.katex span.stream-block-enter')).toBeNull()
    container.remove()
  })

  it('没有新文字时什么都不做（不重放旧块）', () => {
    const container = mount('<p>已经落定</p>')
    markBlockEnter(container, 0)
    expect(markBlockEnter(container, 5)).toBe(5)
    expect(container.querySelector('span.stream-block-enter')).toBeNull()
    container.remove()
  })

  // user:“优化完继续track，找到下一个最大卡顿点，然后修复”+(长回复落定时只记录需要动画的新文字，同一批普通段落不逐节点检查祖先)。
  it('avoids per-node selector checks on a long plain reply', () => {
    const previousBlocks = 2000
    const container = mount('<p>旧段</p>'.repeat(previousBlocks) + '<p>新段</p>')
    const ancestorChecks = vi.spyOn(Element.prototype, 'closest')
    try {
      expect(markBlockEnter(container, previousBlocks * 2)).toBe(previousBlocks * 2 + 2)
      expect(container.querySelector('.stream-block-enter')?.textContent).toBe('新段')
      expect(ancestorChecks.mock.calls.length).toBeLessThan(5)
    } finally {
      ancestorChecks.mockRestore()
      container.remove()
    }
  })

  it('keeps a mixed reply’s offsets based on its visible text', () => {
    const container = mount('<p>旧段</p><div><span class="katex"><i>formula</i></span></div><p>新<b>段</b></p>')
    try {
      expect(markBlockEnter(container, 2)).toBe(4)
      expect(Array.from(container.querySelectorAll('.stream-block-enter'), node => node.textContent)).toEqual(['新', '段'])
    } finally {
      container.remove()
    }
  })
})
