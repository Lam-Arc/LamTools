import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CoreSplitPane from '../src/components/CoreSplitPane.vue'

// user:“统一与去重…确保视觉、功能和交互不退化”+(分屏标签共享导航并保留关闭操作)。
describe('split tabs shared navigation', () => {
  it('navigates actual tabs without treating the close button as a tab', async () => {
    const pane = { id: 'p', activeTab: 'a', tabs: [
      { id: 'a', kind: 'page' as const, title: '甲', resource: 'a' },
      { id: 'b', kind: 'page' as const, title: '乙', resource: 'b' },
    ] }
    const wrapper = mount(CoreSplitPane, { attachTo: document.body, props: { pane, active: true } })
    const tabs = wrapper.findAll('[role="tab"]')
    ;(tabs[0].element as HTMLElement).focus()
    await tabs[0].trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('activate')).toEqual([['b']])
    expect(document.activeElement).toBe(tabs[1].element)
    await wrapper.findAll('.split-tab-close')[0].trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('activate')).toHaveLength(1)
    await wrapper.findAll('.split-tab-close')[0].trigger('click')
    expect(wrapper.emitted('close')?.[0]).toEqual([pane.tabs[0]])
    wrapper.unmount()
  })
})
