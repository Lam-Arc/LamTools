import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PluginRegionBlocks from '../src/components/PluginRegionBlocks.vue'
import RightSidebarWidgetRenderer from '../src/components/RightSidebarWidgetRenderer.vue'
import CoreUpdateCard from '../src/components/CoreUpdateCard.vue'
describe('shared progress feedback', () => {
  it('clamps invalid plugin values for accessible progress while preserving displayed values', () => {
    const regions = [{ plugin: 'demo', region: 'main', order: 0, actions: [], blocks: [{ type: 'progress', label: '超出', value: 150, max: 100 }, { type: 'progress', label: '负数', value: -10, max: 0 }] }] as any
    const wrapper = mount(PluginRegionBlocks, { props: { regions, requestRpc: vi.fn(async () => ({})) } })
    const bars = wrapper.findAll('[role="progressbar"]')
    expect(bars[0].attributes('aria-valuenow')).toBe('100')
    expect(bars[0].attributes('aria-valuemax')).toBe('100')
    expect(bars[1].attributes('aria-valuenow')).toBe('0')
    expect(bars[1].attributes('aria-valuemax')).toBe('100')
    expect(wrapper.text()).toContain('150 / 100')
    wrapper.unmount()
  })
  it('uses the shared progress recipe in the sidebar and bounds the accessible value', () => {
    const entry = { pluginId: 'demo', id: 'widget', title: '示例', renderer: 'blocks' } as any
    const snapshot = { blocks: [{ type: 'progress', label: '任务进度', value: 150, max: 100 }] } as any
    const wrapper = mount(RightSidebarWidgetRenderer, { props: { entry, snapshot } })
    const bar = wrapper.get('[role="progressbar"]')
    expect(bar.classes()).toContain('sunday-progress')
    expect(bar.attributes('aria-label')).toBe('任务进度')
    expect(bar.attributes('aria-valuenow')).toBe('100')
    expect(bar.get('.sunday-progress__fill').attributes('style')).toContain('100%')
    wrapper.unmount()
  })
  it('reports unknown download totals as indeterminate and known totals accurately', async () => {
    const wrapper = mount(CoreUpdateCard, { props: { state: 'downloading', received: 20, total: 0 }, global: { stubs: { Teleport: true } } })
    const bar = wrapper.get('[role="progressbar"]')
    expect(bar.attributes('aria-label')).toBe('更新下载进度')
    expect(bar.attributes('aria-valuenow')).toBeUndefined()
    expect(bar.attributes('aria-valuetext')).toBe('下载中')
    await wrapper.setProps({ total: 100 })
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('20')
    await wrapper.setProps({ state: 'downloaded', total: 0 })
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('100')
    wrapper.unmount()
  })
})
