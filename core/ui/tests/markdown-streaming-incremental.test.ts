import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import MarkdownRenderer from '../src/components/MarkdownRenderer.vue'
import { REVEAL_TOTAL_MS } from '../src/components/streamingTextFade.ts'

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
  await nextFrame()
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


// 方案 C：chunk 只标脏，画面在下一帧合并渲染 —— 断言前先等一帧。
async function nextFrame(): Promise<void> {
  // 假定时器下 rAF 也被接管：直接推进时间，别让断言等真帧。
  if (vi.isFakeTimers()) {
    await vi.advanceTimersByTimeAsync(16)
    return
  }
  await new Promise<void>((resolve) => {
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => resolve())
    else setTimeout(resolve, 16)
  })
}

describe('MarkdownRenderer incremental streaming', () => {
  it('只在行写完时落一次动画，旧文本不重放（方案 C）', async () => {
    vi.useFakeTimers()
    const wrapper = await mountStreaming('Earlier text')
    await nextFrame()
    await wrapper.vm.$nextTick()
    // 还没换行：不算写完，什么都不动。
    expect(wrapper.find('.stream-block-enter').exists()).toBe(false)

    await wrapper.setProps({ content: 'Earlier text arrives\n' })
    await nextFrame()
    await wrapper.vm.$nextTick()
    // 这一块写完了：整块落一次动画（旧块的动画节点会被回收，页面上只有新块那一段）。
    expect(wrapper.findAll('.stream-block-enter').map(span => span.text()).join('')).toBe('Earlier text arrives')
    expect(wrapper.text()).toContain('Earlier text arrives')

    await wrapper.setProps({ content: 'Earlier text arrives\n\nNext paragraph' })
    await nextFrame()
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Next paragraph')

    // 新的一段随空白行一起落定（页面上只有它带 .stream-block-enter）。
    expect(wrapper.findAll('.stream-block-enter').map(span => span.text()).join('')).toBe('Next paragraph')

    await wrapper.setProps({ content: 'Earlier text arrives\n\nNext paragraph\n' })
    await nextFrame()
    await wrapper.vm.$nextTick()
    // 只多了换行、没有新文字：不产生新的动画节点。
    expect(wrapper.find('.stream-block-enter').exists()).toBe(false)

    await wrapper.setProps({ streaming: false })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.stream-block-enter').exists()).toBe(false)
    wrapper.unmount()
  })

  it('同一帧内的多次 chunk 只渲染一次（帧速不再等于 chunk 速）', async () => {
    vi.useFakeTimers()
    const wrapper = await mountStreaming('')
    const stats = api(wrapper).streamingStats
    const before = stats.tailParses
    for (let index = 1; index <= 12; index += 1) {
      await wrapper.setProps({ content: '字'.repeat(index) })
    }
    await nextFrame()
    await wrapper.vm.$nextTick()
    expect(stats.tailParses - before).toBeLessThanOrEqual(1)
    expect(wrapper.text()).toContain('字'.repeat(12))
    wrapper.unmount()
  })

  it('一次到达的块才动画；重置快照与按钮文字不动画（方案 C）', async () => {
    const wrapper = await mountStreaming('')
    // 整段代码带闭合围栏一次到达：算“写完”，整块落一次动画。
    await wrapper.setProps({ content: '```js\nconst answer = 42\n```\n' })
    await nextFrame()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('code .stream-block-enter').exists()).toBe(true)
    expect(wrapper.find('button .stream-block-enter').exists()).toBe(false)

    // 内容变短（重新生成/回滚）：不把旧动画留在页面上。
    await wrapper.setProps({ content: 'Reset' })
    await nextFrame()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.stream-block-enter').exists()).toBe(false)
    expect(wrapper.text()).toBe('Reset')
    wrapper.unmount()
  })

  it('行写完才落定，Unicode 不被拆开（方案 C）', async () => {
    vi.useFakeTimers()
    const wrapper = await mountStreaming('Read')
    await wrapper.setProps({ content: 'Read 😀 now\n\nNext' })
    await nextFrame()
    await wrapper.vm.$nextTick()
    const first = wrapper.find('p')
    expect(first.text()).toBe('Read 😀 now')
    // 整块落一次动画；emoji 整颗，不会被拆成两个 span。
    expect(first.find('.stream-block-enter').text()).toBe('Read 😀 now')
    expect(first.findAll('.stream-block-enter')).toHaveLength(1)

    const closed = first.element
    await wrapper.setProps({ content: 'Read 😀 now\n\nNext update' })
    await nextFrame()
    await wrapper.vm.$nextTick()
    // 已闭合的段落复用同一个 DOM 节点（不重建、不重放动画）。
    expect(wrapper.find('p').element).toBe(closed)
    expect(wrapper.text()).toContain('Read 😀 now')
    wrapper.unmount()
  })

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
      await nextFrame()
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
    await nextFrame()
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
    await nextFrame()
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
    await nextFrame()
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
    await nextFrame()
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
    await nextFrame()
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
    await nextFrame()
  await wrapper.vm.$nextTick()

    expect(stats.tailParses).toBe(2)
    expect(stats.closedParses).toBe(0)
    expect(wrapper.find('.markdown-body').text()).toContain('一句正在增长')
    wrapper.unmount()
  })

  it('rate limits tail parses for a large tail without dropping the newest content', async () => {
    vi.useFakeTimers()
    const wrapper = mount(MarkdownRenderer, { props: { content: LONG_TAIL, streaming: true } })
    await nextFrame()
  await wrapper.vm.$nextTick()
    const stats = api(wrapper).streamingStats
    expect(stats.tailParses).toBe(1)

    const updates = [1, 2, 3, 4, 5].map(count => LONG_TAIL + '新'.repeat(count))
    for (const content of updates) {
      await wrapper.setProps({ content })
      await nextFrame()
  await wrapper.vm.$nextTick()
    }
    // All five updates landed inside one throttle window.
    expect(stats.tailParses).toBe(1)
    expect(wrapper.find('.markdown-body').text()).not.toContain('新')

    // The queued tail parse renders the newest content: nothing is lost.
    vi.advanceTimersByTime(400)
    await nextFrame()
  await wrapper.vm.$nextTick()
    expect(stats.tailParses).toBe(2)
    expect(stats.tailParses).toBeLessThan(updates.length)
    expect(wrapper.find('.markdown-body').text()).toContain(LONG_TAIL + '新'.repeat(5))
    wrapper.unmount()
  })

  it('keeps the last rendered tail visible while a rate-limited parse is pending', async () => {
    vi.useFakeTimers()
    const wrapper = mount(MarkdownRenderer, { props: { content: LONG_TAIL, streaming: true } })
    await nextFrame()
  await wrapper.vm.$nextTick()

    await wrapper.setProps({ content: `${LONG_TAIL}新增的一段话` })
    await nextFrame()
  await wrapper.vm.$nextTick()
    // Deferred re-parse: the stale tail stays put (lagging, never blank).
    expect(wrapper.find('.markdown-body').text()).toContain(LONG_TAIL)
    expect(wrapper.find('.markdown-body').text()).not.toContain('新增的一段话')

    vi.advanceTimersByTime(400)
    await nextFrame()
  await wrapper.vm.$nextTick()
    expect(wrapper.find('.markdown-body').text()).toContain(`${LONG_TAIL}新增的一段话`)

    // Closing that segment renders it immediately — again with no blank gap.
    await wrapper.setProps({ content: `${LONG_TAIL}新增的一段话\n\n结尾段` })
    await nextFrame()
  await wrapper.vm.$nextTick()
    expect(wrapper.find('.markdown-body').text()).toContain(`${LONG_TAIL}新增的一段话`)
    expect(wrapper.find('.markdown-body').text()).toContain('结尾段')
    wrapper.unmount()
  })

  it('never lets a queued tail parse write into content it no longer owns', async () => {
    vi.useFakeTimers()
    const wrapper = mount(MarkdownRenderer, { props: { content: LONG_TAIL, streaming: true } })
    await nextFrame()
  await wrapper.vm.$nextTick()
    const stats = api(wrapper).streamingStats

    // Queue a throttled tail parse ...
    await wrapper.setProps({ content: `${LONG_TAIL}新内容` })
    await nextFrame()
  await wrapper.vm.$nextTick()
    expect(stats.tailParses).toBe(1)

    // ... then leave streaming mode before it fires.
    await wrapper.setProps({ streaming: false })
    await nextFrame()
  await wrapper.vm.$nextTick()
    const settled = wrapper.find('.markdown-body').element.innerHTML
    vi.advanceTimersByTime(400)
    await nextFrame()
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
    await nextFrame()
  await wrapper.vm.$nextTick()

    // While streaming: formulas render, heavy output stays a placeholder-free
    // code block / plain formula.
    expect(wrapper.find('.katex').exists()).toBe(true)
    expect(wrapper.find('.math-auto-plot').exists()).toBe(false)
    expect(wrapper.find('.math-auto-plot-anchor').exists()).toBe(false)
    expect(wrapper.find('.mermaid-placeholder').exists()).toBe(false)
    expect(wrapper.find('.mermaid-diagram').exists()).toBe(false)
    // user:“SVG 现在还不是流式渲染”+(矢量图围栏闭合就出图，不再等收尾；mermaid 仍延后)
    expect(wrapper.find('.study-inline-svg').exists()).toBe(true)
    expect(wrapper.find('code.language-mermaid').text()).toBe(mermaidSource)

    await wrapper.setProps({ streaming: false })
    await nextFrame()
  await wrapper.vm.$nextTick()
    await flushPromises()
    await nextFrame()
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
    await nextFrame()
  await wrapper.vm.$nextTick()
    const stats = api(wrapper).streamingStats

    // The throttled tail is stale when its segment closes, so closing it costs
    // exactly one render.
    await wrapper.setProps({ content: `${LONG_TAIL}补一句` })
    await nextFrame()
  await wrapper.vm.$nextTick()
    await wrapper.setProps({ content: `${LONG_TAIL}补一句\n\n第二段` })
    await nextFrame()
  await wrapper.vm.$nextTick()
    expect(stats.closedParses).toBe(1)

    for (const suffix of ['一', '一二', '一二三', '一二三四']) {
      await wrapper.setProps({ content: `${LONG_TAIL}补一句\n\n第二段${suffix}` })
      await nextFrame()
  await wrapper.vm.$nextTick()
    }
    vi.advanceTimersByTime(400)
    await nextFrame()
  await wrapper.vm.$nextTick()

    // Tail-only ticks never re-parse a closed segment (per-frame O(tail)).
    expect(stats.closedParses).toBe(1)
    expect(stats.closedParses + stats.tailParses).toBeLessThanOrEqual(8)
    expect(wrapper.find('.markdown-body').text()).toContain('第二段一二三四')
    wrapper.unmount()
  })
})

// user:“收尾那一次必须立即刷新，不能因为待着的定时器而让最后几个字晚 120ms 出现或残留 span”
// +(尾段 120ms 节流只允许发生在流式过程中；一旦退出 streaming，最后几个字必须立刻出现在
// 收尾整体渲染里，并且动画 span 同步清掉 —— 不推进任何定时器也要成立。)
describe('MarkdownRenderer 收尾即时性', () => {
  it('退出 streaming 时最后几个字立即可见，且动画 span 同步清干净（不推进任何定时器）', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-16T00:00:00Z'))
    // 尾段长度 ≥ EAGER_TAIL_PARSE_LIMIT，才会走 120ms 节流这条路径
    const base = '长'.repeat(1100)
    const wrapper = await mountStreaming(base)
    await wrapper.setProps({ content: `${base}末` })
    // 此刻尾段解析被 scheduleTailParse 挂起，靠定时器才可能刷新
    await wrapper.setProps({ streaming: false })
    await nextFrame()
  await wrapper.vm.$nextTick()
    await flushPromises()
    expect(wrapper.text()).toContain('末')
    expect(wrapper.find('.stream-block-enter').exists()).toBe(false)
    wrapper.unmount()
  })
})
