import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CommandPalette from '../src/components/CommandPalette.vue'

// user:“确保视觉、功能和交互不退化”+(多个输入区的补全菜单独立滚动，并准确标识上下文建议)。
describe('command palette isolation', () => {
  const originalScroll = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView')
  afterEach(() => { if (originalScroll) Object.defineProperty(Element.prototype, 'scrollIntoView', originalScroll); else delete (Element.prototype as any).scrollIntoView; vi.restoreAllMocks(); document.body.innerHTML = '' })
  it('scrolls the active option in its own instance', async () => {
    const scrolled: Element[] = []
    Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: function (this: Element) { scrolled.push(this) } })
    const commands = [{ name: 'one', title: 'One', source: 'core', action: 'insert_token', kind: 'skill' }, { name: 'two', title: 'Two', source: 'core', action: 'insert_token', kind: 'skill' }] as any
    const first = mount(CommandPalette, { attachTo: document.body, props: { commands, activeIndex: 0 } })
    const second = mount(CommandPalette, { attachTo: document.body, props: { commands, activeIndex: 0 } })
    await second.setProps({ activeIndex: 1 }); await Promise.resolve()
    expect(scrolled.at(-1)).toBe(second.get('[data-command-name="two"]').element)
    expect(scrolled).not.toContain(first.get('[data-command-name="one"]').element)
    first.unmount(); second.unmount()
  })
  it('labels context suggestions with their actual # trigger', () => {
    const commands = [{ name: '背景', title: '背景', source: 'core', action: 'insert_token', kind: 'skill', metadata: { reference_path: '/context', context: true } }] as any
    const wrapper = mount(CommandPalette, { props: { commands, activeIndex: 0 } })
    expect(wrapper.get('[role="option"]').attributes('aria-label')).toMatch(/^#背景/)
  })
})
