import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import MarkdownRenderer from '../src/components/MarkdownRenderer.vue'

// user:“Sunday也可以实现吗？去实现”+(先验证显式交互块、流式行为与隔离边界)。
const source = '<button onclick="this.textContent=\'done\'">Try</button><script>window.demo=1</script>'
const fence = (html = source, lang = 'interactive-html') => `\`\`\`${lang}\n${html}\n\`\`\``

describe('inline interactive replies', () => {
  it('renders only opted-in interactive blocks in an opaque sandbox', async () => {
    const wrapper = mount(MarkdownRenderer, { props: { content: fence(), interactive: true } })
    await flushPromises()
    const frame = wrapper.find('iframe')
    expect(frame.exists()).toBe(true)
    expect(frame.attributes('sandbox')).toBe('allow-scripts')
    expect(frame.attributes('src')).toContain('/api/core/inline-visualizations/runtime')
    expect(frame.attributes('referrerpolicy')).toBe('no-referrer')
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.find('.code-source').text()).toBe(source)
    wrapper.unmount()
  })

  it('does not execute ordinary HTML, documents, or partial streaming content', async () => {
    // user:“测试，提交打包发布”+(各测试变体共用可选 streaming 参数，不由首个对象推断为禁止)。
    const cases: Array<{ content: string; interactive: boolean; streaming?: boolean }> = [
      { content: fence(), interactive: false },
      { content: fence(source, 'html'), interactive: true },
      { content: fence(), interactive: true, streaming: true },
      { content: fence().slice(0, -3), interactive: true, streaming: true },
      { content: fence().slice(0, -3), interactive: true },
    ]
    for (const props of cases) {
      const wrapper = mount(MarkdownRenderer, { props })
      await flushPromises()
      expect(wrapper.find('iframe').exists()).toBe(false)
      wrapper.unmount()
    }
  })

  it('preserves embedded file paths, URLs and script text losslessly', async () => {
    const raw = '<a href="/tmp/demo.md">https://example.com</a><script>const file="E:/test/data.json";</script>'
    const wrapper = mount(MarkdownRenderer, { props: { content: fence(raw), interactive: true } })
    await flushPromises()
    expect(wrapper.find('.code-source').text()).toBe(raw)
    wrapper.unmount()
  })

  it.each([false, true])('does not treat raw HTML as a generated interactive block (enabled=%s)', async interactive => {
    const content = '<div data-inline-visualization><span class="code-source" hidden>&lt;button&gt;Try&lt;/button&gt;</span></div>'
    const wrapper = mount(MarkdownRenderer, { props: { content, interactive } })
    await flushPromises()
    expect(wrapper.find('iframe').exists()).toBe(false)
    wrapper.unmount()
  })

  it('keeps formulas literal inside tilde-fenced interactive source', async () => {
    const raw = '<button data-formula="$x+y$">Calculate</button>'
    const wrapper = mount(MarkdownRenderer, { props: { content: `~~~interactive-html\n${raw}\n~~~`, interactive: true } })
    await flushPromises()
    expect(wrapper.find('.code-source').text()).toBe(raw)
    expect(wrapper.find('iframe').exists()).toBe(true)
    wrapper.unmount()
  })

  it('starts after streaming ends and restores cached replies', async () => {
    const wrapper = mount(MarkdownRenderer, { props: { content: fence(), interactive: true, streaming: true } })
    await wrapper.setProps({ streaming: false })
    await flushPromises()
    expect(wrapper.findAll('iframe')).toHaveLength(1)
    await wrapper.setProps({ content: 'plain reply' })
    await flushPromises()
    expect(wrapper.find('iframe').exists()).toBe(false)
    await wrapper.setProps({ content: fence() })
    await flushPromises()
    expect(wrapper.findAll('iframe')).toHaveLength(1)
    wrapper.unmount()
  })

  it('ignores messages from other frames and bounds frame height', async () => {
    const wrapper = mount(MarkdownRenderer, { props: { content: fence(), interactive: true }, attachTo: document.body })
    await flushPromises()
    const frame = wrapper.find('iframe').element as HTMLIFrameElement
    const initial = frame.style.height
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'sunday-visualization:resize', height: 700 }, source: window }))
    expect(frame.style.height).toBe(initial)
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'sunday-visualization:resize', height: 100000 }, source: frame.contentWindow }))
    await flushPromises()
    expect(frame.style.height).toBe('800px')
    wrapper.unmount()
    // Detached frames must no longer own a window listener.
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'sunday-visualization:resize', height: 300 }, source: frame.contentWindow }))
  })

  it('wires assistant replies explicitly without enabling every document', () => {
    const message = readFileSync('src/components/MessageView.vue', 'utf8')
    expect(message.match(/:interactive="true"/g)?.length).toBeGreaterThanOrEqual(3)
  })
})
