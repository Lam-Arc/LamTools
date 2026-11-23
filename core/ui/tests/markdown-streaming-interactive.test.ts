import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import MarkdownRenderer from '../src/components/MarkdownRenderer.vue'

// Mermaid 只在收尾重渲染里懒加载，这里挡掉，避免 jsdom 跑真实渲染器。
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn().mockResolvedValue({ svg: '<svg data-mermaid="stub"></svg>' }),
  },
}))

// 交互块运行时地址来自插件资源；测试里不需要真的加载那个页面。
vi.mock('@/plugins/assets', () => ({
  inlineVisualizationRuntimeUrl: () => 'about:blank',
}))

const FENCE_LINES = ['```interactive-html', '<div id="demo">hi</div>', '```']
const CLOSED_FENCE = FENCE_LINES.join('\n')
const OPEN_FENCE = FENCE_LINES.slice(0, 2).join('\n')

/**
 * user:“交互式 UI 不要正文完全落定再显示，流式出来了闭合了就显示，多媒体加载也是同理”
 * +(流式分段的已闭合围栏当场挂载交互块，只有还没闭合的那截继续按代码块显示。)
 */

// 方案 C：chunk 只标脏，画面在下一帧合并渲染 —— 断言前先等一帧。
async function nextFrame(): Promise<void> {
  // 假定时器下 rAF 也被接管：直接推进时间，别让断言等真帧。
  if (vi.isFakeTimers()) {
    await vi.advanceTimersByTimeAsync(20)
    return
  }
  await new Promise<void>((resolve) => {
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => resolve())
    else setTimeout(resolve, 16)
  })
}

describe('MarkdownRenderer progressive heavy blocks while streaming', () => {
  it('mounts a closed interactive fence while the reply is still streaming', async () => {
    const wrapper = mount(MarkdownRenderer, {
      props: {
        content: `开场一段。\n\n${CLOSED_FENCE}\n\n后面还在写。`,
        streaming: true,
        interactive: true,
      },
    })
    await nextFrame()
  await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-inline-visualization]').exists()).toBe(true)
    expect(wrapper.find('.inline-visualization-frame').exists()).toBe(true)
    wrapper.unmount()
  })

  it('keeps an unclosed fence as a code block and mounts it the moment it closes', async () => {
    const wrapper = mount(MarkdownRenderer, {
      props: { content: `开场一段。\n\n${OPEN_FENCE}`, streaming: true, interactive: true },
    })
    await nextFrame()
  await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-inline-visualization]').exists()).toBe(false)
    expect(wrapper.find('pre code').exists()).toBe(true)

    await wrapper.setProps({ content: `开场一段。\n\n${CLOSED_FENCE}\n\n后面还在写。` })
    await nextFrame()
  await wrapper.vm.$nextTick()

    expect(wrapper.find('.inline-visualization-frame').exists()).toBe(true)
    wrapper.unmount()
  })

  it('never runs interactive fences on a surface that does not allow them', async () => {
    const wrapper = mount(MarkdownRenderer, {
      props: { content: `开场一段。\n\n${CLOSED_FENCE}`, streaming: true, interactive: false },
    })
    await nextFrame()
  await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-inline-visualization]').exists()).toBe(false)
    wrapper.unmount()
  })
})

/**
 * user:“SVG 现在还不是流式渲染”+(矢量图围栏一闭合就要出图，不再等整条回复收尾。)
 */

describe('MarkdownRenderer progressive svg', () => {
  const SVG = '<svg viewBox="0 0 100 50"><title>KVL</title><text x="5" y="15">R1</text></svg>'

  it('renders a closed svg fence while the reply is still streaming', async () => {
    const wrapper = mount(MarkdownRenderer, {
      props: { content: `开场。\n\n\`\`\`svg\n${SVG}\n\`\`\`\n\n还在写。`, streaming: true },
    })
    await nextFrame()
  await wrapper.vm.$nextTick()

    expect(wrapper.find('.study-inline-svg').exists()).toBe(true)
    expect(wrapper.find('.study-inline-svg svg').exists()).toBe(true)
    wrapper.unmount()
  })

  it('keeps a half-written svg as source instead of drawing a broken picture', async () => {
    // 只写了半截标签：解析不过，就不能提前当图渲染
    const wrapper = mount(MarkdownRenderer, {
      props: { content: `开场。\n\n\`\`\`svg\n<svg viewBox="0 0 100 50"><text x="5" y="15">R1`, streaming: true },
    })
    await nextFrame()
  await wrapper.vm.$nextTick()

    expect(wrapper.find('.study-inline-svg').exists()).toBe(false)
    expect(wrapper.text()).toContain('<svg')
    wrapper.unmount()
  })
})
