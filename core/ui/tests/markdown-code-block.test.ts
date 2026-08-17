import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import MarkdownRenderer from '../src/components/MarkdownRenderer.vue'

// Mermaid is lazy-loaded only when a ```mermaid block exists; stub the module
// so jsdom never needs to run the real (browser-oriented) renderer.
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn().mockResolvedValue({ svg: '<svg></svg>' }),
  },
}))

function stubClipboard(): ReturnType<typeof vi.fn> {
  const writeText = vi.fn().mockResolvedValue(undefined)
  try {
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  } catch {
    // Non-configurable in this jsdom — replace the whole global instead.
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
  }
  return writeText
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  try {
    delete (navigator as { clipboard?: unknown }).clipboard
  } catch {
    // ignore — clipboard was never stubbed
  }
  vi.restoreAllMocks()
})

describe('MarkdownRenderer code blocks', () => {
  it('renders ```markdown blocks as nested documents with a copy button carrying the raw source', async () => {
    const source = '# 标题\n\n- 一\n- 二'
    const wrapper = mount(MarkdownRenderer, { props: { content: `\`\`\`markdown\n${source}\n\`\`\`` } })
    await wrapper.vm.$nextTick()

    const block = wrapper.find('.code-block')
    expect(block.exists()).toBe(true)
    expect(block.find('.nested-markdown h1').text()).toBe('标题')
    expect(block.find('.nested-markdown li').text()).toBe('一')
    expect(block.find('.code-source').text()).toBe(source)
    wrapper.unmount()
  })

  it('keeps the copy source lossless for `<`, `&`, `"`, `-->` and `</script>`', async () => {
    const source = 'print("<a>&</a>")\n// --> done\nconst s = "</script>"'
    const wrapper = mount(MarkdownRenderer, { props: { content: `\`\`\`py\n${source}\n\`\`\`` } })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.code-block pre code').text()).toBe(source)
    expect(wrapper.find('.code-source').text()).toBe(source)
    wrapper.unmount()
  })

  it('wraps ```mermaid blocks in a code block with a copy button', async () => {
    const source = 'graph TD\n  A-->B'
    const wrapper = mount(MarkdownRenderer, { props: { content: `\`\`\`mermaid\n${source}\n\`\`\`` } })
    await wrapper.vm.$nextTick()
    await flushPromises()

    const block = wrapper.find('.code-block')
    expect(block.exists()).toBe(true)
    // The placeholder is processed (replaced by the diagram or the error fallback).
    expect(block.find('.mermaid-placeholder').exists()).toBe(false)
    expect(block.find('.code-source').text()).toBe(source)
    wrapper.unmount()
  })

  it('streaming code blocks carry the same copy button structure', async () => {
    const source = 'print(1)'
    const wrapper = mount(MarkdownRenderer, {
      props: { content: `\`\`\`py\n${source}\n\`\`\``, streaming: true },
    })
    await wrapper.vm.$nextTick()

    const block = wrapper.find('.code-block')
    expect(block.find('pre code').text()).toBe(source)
    expect(block.find('.code-source').text()).toBe(source)
    wrapper.unmount()
  })

  it('copies the raw source on click and shows the copied state for 1400ms', async () => {
    vi.useFakeTimers()
    const writeText = stubClipboard()
    const source = 'x = 1'
    const wrapper = mount(MarkdownRenderer, { props: { content: `\`\`\`py\n${source}\n\`\`\`` } })
    await wrapper.vm.$nextTick()

    const button = wrapper.find('.code-copy')
    await button.trigger('click')
    expect(writeText).toHaveBeenCalledWith(source)
    expect(button.attributes('data-copied')).toBeDefined()

    vi.advanceTimersByTime(1400)
    expect(button.attributes('data-copied')).toBeUndefined()
    wrapper.unmount()
  })
})
