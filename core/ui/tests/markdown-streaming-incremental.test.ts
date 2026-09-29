import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import MarkdownRenderer from '../src/components/MarkdownRenderer.vue'

// Mermaid is lazy-loaded only when a ```mermaid block reaches the finished
// (heavy) render; stub it so jsdom never runs the real renderer.
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn().mockResolvedValue({ svg: '<svg data-mermaid="stub"></svg>' }),
  },
}))

/**
 * Streaming renderer contract:
 * 1. Every segment — closed or open — goes through the shared full-segment
 *    renderer (`renderSegment` with heavy=false), so the DOM matches the
 *    reference string render composed from it.
 * 2. Closed segments keep their exact DOM nodes across ticks — only the open
 *    tail is rebuilt (the O(tail) per-frame guarantee).
 * 3. The segment scan never splits inside a fenced code block or a `$$` block,
 *    and an unclosed fence is always the open tail.
 * 4. The tail parse is rate limited for large tails, never for small ones, and
 *    a queued parse can never write stale content anywhere.
 * 5. Heavy output (mermaid / Study SVG / auto plots) is deferred to the
 *    finished render.
 */

interface StreamingStats {
  closedParses: number
  tailParses: number
  segmentCacheHits: number
}

interface RendererApi {
  renderSegment(source: string, heavy: boolean): string
  splitStreamingSegments(content: string): string[]
  streamingStats: StreamingStats
}

function api(wrapper: unknown): RendererApi {
  return (wrapper as { vm: RendererApi }).vm
}

async function mountStreaming(content: string) {
  const wrapper = mount(MarkdownRenderer, { props: { content, streaming: true } })
  await wrapper.vm.$nextTick()
  return wrapper
}

// Compare by block tag + textContent: jsdom serializes katex spans /
// unclosed-tag nesting slightly differently than an independent container, so
// byte-level innerHTML comparison is a false positive; block structure +
// visible text are the reliable "rendered the same" signal.
function blockSignature(root: Element): string {
  return Array.from(root.children).map(node => `${node.tagName}|${node.textContent}`).join('\n')
}

function referenceSignature(wrapper: unknown, content: string): string {
  const vm = api(wrapper)
  const ref = vm
    .splitStreamingSegments(content)
    .map(segment => vm.renderSegment(segment, false))
    .join('')
  const temp = document.createElement('div')
  temp.innerHTML = ref
  return blockSignature(temp)
}

const LONG_TAIL = '长'.repeat(1100)

afterEach(() => {
  vi.useRealTimers()
})

describe('MarkdownRenderer incremental streaming', () => {
  it('produces DOM identical to the shared segment reference renderer, tick by tick', async () => {
    const steps = [
      '第一段',
      '第一段，包含 **加粗** 和 `code`。',
      '第一段，包含 **加粗** 和 `code`。\n\n第二段：\n- 一\n- 二',
      '第一段，包含 **加粗** 和 `code`。\n\n第二段：\n- 一\n- 二\n\n```py\nprint(1)\n```',
    ]
    const wrapper = await mountStreaming(steps[0])
    expect(blockSignature(wrapper.find('.markdown-body').element)).toBe(referenceSignature(wrapper, steps[0]))
    for (const step of steps.slice(1)) {
      await wrapper.setProps({ content: step })
      await wrapper.vm.$nextTick()
      expect(blockSignature(wrapper.find('.markdown-body').element), `step: ${JSON.stringify(step)}`).toBe(referenceSignature(wrapper, step))
    }
    wrapper.unmount()
  })

  it('reuses closed segment DOM nodes across ticks; only the tail is rebuilt', async () => {
    const wrapper = await mountStreaming('甲段\n\n乙段\n\n丙段')
    const container = wrapper.find('.markdown-body').element
    const before = Array.from(container.children)

    // Tail growth: 丁段 appended → the first three segments keep their nodes.
    await wrapper.setProps({ content: '甲段\n\n乙段\n\n丙段\n\n丁段' })
    await wrapper.vm.$nextTick()
    const after = Array.from(container.children)
    expect(after.length).toBe(4)
    for (let i = 0; i < 3; i += 1) {
      expect(after[i]).toBe(before[i])
    }
    expect(after[3]).not.toBe(before[3])

    // Tail modification: the open segment is replaced, closed ones stay.
    const beforeSecondTick = Array.from(container.children)
    await wrapper.setProps({ content: '甲段\n\n乙段\n\n丙段\n\n丁段加长内容' })
    await wrapper.vm.$nextTick()
    const afterSecondTick = Array.from(container.children)
    expect(afterSecondTick[0]).toBe(beforeSecondTick[0])
    expect(afterSecondTick[1]).toBe(beforeSecondTick[1])
    expect(afterSecondTick[2]).toBe(beforeSecondTick[2])
    expect(afterSecondTick[3]).not.toBe(beforeSecondTick[3])
    expect(afterSecondTick[3].textContent).toBe('丁段加长内容')
    wrapper.unmount()
  })

  it('cleans up DOM when streaming ends', async () => {
    const wrapper = await mountStreaming('一段')
    await wrapper.setProps({ content: '一段', streaming: false })
    await wrapper.vm.$nextTick()
    // Non-streaming path renders via v-html (full markdown).
    expect(wrapper.find('.markdown-body').exists()).toBe(true)
    wrapper.unmount()
  })

  it('keeps the markdown shell and content node stable when streaming ends', async () => {
    const wrapper = await mountStreaming('流式内容')
    const shell = wrapper.find('.markdown-renderer').element
    const content = wrapper.find('.markdown-renderer__content').element

    await wrapper.setProps({ streaming: false })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.markdown-renderer').element).toBe(shell)
    expect(wrapper.find('.markdown-renderer__content').element).toBe(content)
    expect(wrapper.find('.markdown-renderer--streaming').exists()).toBe(false)
    wrapper.unmount()
  })

  it('forms headings, tables, quotes, links, emphasis and nested lists while streaming', async () => {
    const content = [
      '# 一级标题',
      '',
      '> 引用 **加粗**',
      '',
      '| 甲 | 乙 |',
      '| --- | --- |',
      '| 1 | 2 |',
      '',
      '1. 第一步',
      '2. 第二步',
      '',
      '- 父项',
      '  - 子项',
      '',
      '```py',
      'print(1)',
      '```',
      '',
      '链接 [示例](https://example.test/doc) 与 *斜体* 收尾。',
    ].join('\n')
    const wrapper = await mountStreaming(content)

    expect(wrapper.find('h1').text()).toBe('一级标题')
    expect(wrapper.find('blockquote strong').text()).toBe('加粗')
    // Table shell/scroll container is built during streaming too, exactly like
    // the finished render (asserted by markdown-table / narrow-viewport tests).
    expect(wrapper.find('.markdown-table-shell table thead th').text()).toBe('甲')
    expect(wrapper.findAll('.markdown-table-shell tbody tr')).toHaveLength(1)
    expect(wrapper.findAll('ol > li')).toHaveLength(2)
    expect(wrapper.find('ul li ul li').text()).toBe('子项')
    expect(wrapper.find('a[href="https://example.test/doc"]').exists()).toBe(true)
    expect(wrapper.find('em').text()).toBe('斜体')
    // Code blocks carry the finished-state copy structure while streaming.
    expect(wrapper.find('.code-block pre code').text()).toBe('print(1)')
    expect(wrapper.find('.code-block .code-copy').exists()).toBe(true)
    expect(wrapper.find('.code-block .code-source').text()).toBe('print(1)')
    wrapper.unmount()
  })

  it('keeps a fenced code block containing blank lines as one block, open or closed', async () => {
    const openFence = '正文\n\n```py\nprint(1)\n\nprint(2)\n'
    const wrapper = await mountStreaming(openFence)

    // Unclosed fence: marked closes it at EOF, so no literal ``` leaks out and
    // the blank line inside must not split the block.
    expect(wrapper.findAll('.code-block')).toHaveLength(1)
    expect(wrapper.find('.code-block pre code').text()).toContain('print(2)')
    expect(wrapper.find('.markdown-body').text()).not.toContain('```')
    expect(wrapper.findAll('.markdown-body > *')).toHaveLength(2)

    await wrapper.setProps({ content: `${openFence}\`\`\`\n\n结尾` })
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.code-block')).toHaveLength(1)
    const code = wrapper.find('.code-block pre code')
    expect(code.text()).toContain('print(1)')
    expect(code.text()).toContain('print(2)')
    expect(wrapper.find('.markdown-body').text()).not.toContain('```')
    expect(wrapper.findAll('.markdown-body > *')).toHaveLength(3)
    wrapper.unmount()
  })

  it('uses one segment per tick for a small tail (live text contract)', async () => {
    const wrapper = await mountStreaming('一句')
    const stats = api(wrapper).streamingStats

    await wrapper.setProps({ content: '一句正在增长' })
    await wrapper.vm.$nextTick()

    expect(stats.tailParses).toBe(2)
    expect(stats.closedParses).toBe(0)
    expect(wrapper.find('.markdown-body').text()).toContain('一句正在增长')
    wrapper.unmount()
  })

  it('rate limits tail parses for a large tail without dropping the newest content', async () => {
    vi.useFakeTimers()
    const wrapper = mount(MarkdownRenderer, { props: { content: LONG_TAIL, streaming: true } })
    await wrapper.vm.$nextTick()
    const stats = api(wrapper).streamingStats
    expect(stats.tailParses).toBe(1)

    const updates = [1, 2, 3, 4, 5].map(count => LONG_TAIL + '新'.repeat(count))
    for (const content of updates) {
      await wrapper.setProps({ content })
      await wrapper.vm.$nextTick()
    }
    // All five updates landed inside one throttle window.
    expect(stats.tailParses).toBe(1)
    expect(wrapper.find('.markdown-body').text()).not.toContain('新')

    // The queued tail parse renders the newest content: nothing is lost.
    vi.advanceTimersByTime(400)
    await wrapper.vm.$nextTick()
    expect(stats.tailParses).toBe(2)
    expect(stats.tailParses).toBeLessThan(updates.length)
    expect(wrapper.find('.markdown-body').text()).toContain(LONG_TAIL + '新'.repeat(5))
    wrapper.unmount()
  })

  it('keeps the last rendered tail visible while a rate-limited parse is pending', async () => {
    vi.useFakeTimers()
    const wrapper = mount(MarkdownRenderer, { props: { content: LONG_TAIL, streaming: true } })
    await wrapper.vm.$nextTick()

    await wrapper.setProps({ content: `${LONG_TAIL}新增的一段话` })
    await wrapper.vm.$nextTick()
    // Deferred re-parse: the stale tail stays put (lagging, never blank).
    expect(wrapper.find('.markdown-body').text()).toContain(LONG_TAIL)
    expect(wrapper.find('.markdown-body').text()).not.toContain('新增的一段话')

    vi.advanceTimersByTime(400)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.markdown-body').text()).toContain(`${LONG_TAIL}新增的一段话`)

    // Closing that segment renders it immediately — again with no blank gap.
    await wrapper.setProps({ content: `${LONG_TAIL}新增的一段话\n\n结尾段` })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.markdown-body').text()).toContain(`${LONG_TAIL}新增的一段话`)
    expect(wrapper.find('.markdown-body').text()).toContain('结尾段')
    wrapper.unmount()
  })

  it('never lets a queued tail parse write into content it no longer owns', async () => {
    vi.useFakeTimers()
    const wrapper = mount(MarkdownRenderer, { props: { content: LONG_TAIL, streaming: true } })
    await wrapper.vm.$nextTick()
    const stats = api(wrapper).streamingStats

    // Queue a throttled tail parse ...
    await wrapper.setProps({ content: `${LONG_TAIL}新内容` })
    await wrapper.vm.$nextTick()
    expect(stats.tailParses).toBe(1)

    // ... then leave streaming mode before it fires.
    await wrapper.setProps({ streaming: false })
    await wrapper.vm.$nextTick()
    const settled = wrapper.find('.markdown-body').element.innerHTML
    vi.advanceTimersByTime(400)
    await wrapper.vm.$nextTick()

    expect(stats.tailParses).toBe(1)
    expect(wrapper.find('.markdown-body').element.innerHTML).toBe(settled)
    expect(wrapper.find('.markdown-body').text()).toContain(`${LONG_TAIL}新内容`)
    wrapper.unmount()

    // A queued parse must also die with the component.
    const second = mount(MarkdownRenderer, { props: { content: LONG_TAIL, streaming: true } })
    await second.vm.$nextTick()
    const secondStats = api(second).streamingStats
    await second.setProps({ content: `${LONG_TAIL}另一句` })
    await second.vm.$nextTick()
    second.unmount()
    vi.advanceTimersByTime(400)
    expect(secondStats.tailParses).toBe(1)
  })

  it('deferred heavy output appears once streaming ends', async () => {
    const mermaidSource = 'graph TD\n  A-->B'
    const svgSource = '<svg viewBox="0 0 100 50"><title>KVL</title><path d="M0 0H10"/></svg>'
    const formula = '$$f(x)=x^2-2x+1$$'
    const content = [
      '文案开头',
      '',
      formula,
      '',
      '```mermaid',
      mermaidSource,
      '```',
      '',
      '```svg',
      svgSource,
      '```',
    ].join('\n')
    const wrapper = mount(MarkdownRenderer, {
      props: { content, streaming: true, autoPlotMath: true },
    })
    await wrapper.vm.$nextTick()

    // While streaming: formulas render, heavy output stays a placeholder-free
    // code block / plain formula.
    expect(wrapper.find('.katex').exists()).toBe(true)
    expect(wrapper.find('.math-auto-plot').exists()).toBe(false)
    expect(wrapper.find('.math-auto-plot-anchor').exists()).toBe(false)
    expect(wrapper.find('.mermaid-placeholder').exists()).toBe(false)
    expect(wrapper.find('.mermaid-diagram').exists()).toBe(false)
    expect(wrapper.find('.study-inline-svg').exists()).toBe(false)
    expect(wrapper.find('code.language-mermaid').text()).toBe(mermaidSource)
    expect(wrapper.find('code.language-svg').text()).toBe(svgSource)

    await wrapper.setProps({ streaming: false })
    await wrapper.vm.$nextTick()
    await flushPromises()
    await wrapper.vm.$nextTick()

    // The finished render is authoritative: heavy output appears exactly once.
    expect(wrapper.find('.math-auto-plot').exists()).toBe(true)
    expect(wrapper.find('.mermaid-diagram').exists()).toBe(true)
    expect(wrapper.find('.mermaid-placeholder').exists()).toBe(false)
    expect(wrapper.find('.study-inline-svg').exists()).toBe(true)
    wrapper.unmount()
  })

  it('parses each closed segment exactly once', async () => {
    vi.useFakeTimers()
    const wrapper = mount(MarkdownRenderer, { props: { content: LONG_TAIL, streaming: true } })
    await wrapper.vm.$nextTick()
    const stats = api(wrapper).streamingStats

    // The throttled tail is stale when its segment closes, so closing it costs
    // exactly one render.
    await wrapper.setProps({ content: `${LONG_TAIL}补一句` })
    await wrapper.vm.$nextTick()
    await wrapper.setProps({ content: `${LONG_TAIL}补一句\n\n第二段` })
    await wrapper.vm.$nextTick()
    expect(stats.closedParses).toBe(1)

    for (const suffix of ['一', '一二', '一二三', '一二三四']) {
      await wrapper.setProps({ content: `${LONG_TAIL}补一句\n\n第二段${suffix}` })
      await wrapper.vm.$nextTick()
    }
    vi.advanceTimersByTime(400)
    await wrapper.vm.$nextTick()

    // Tail-only ticks never re-parse a closed segment (per-frame O(tail)).
    expect(stats.closedParses).toBe(1)
    expect(stats.closedParses + stats.tailParses).toBeLessThanOrEqual(8)
    expect(wrapper.find('.markdown-body').text()).toContain('第二段一二三四')
    wrapper.unmount()
  })
})
