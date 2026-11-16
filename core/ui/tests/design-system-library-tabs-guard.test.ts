import { defineComponent, h, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({ editing: false }))
vi.mock('../src/components/MaterialsView.vue', () => ({ default: defineComponent({ setup: () => () => h('div', '资料') }) }))
vi.mock('../src/components/MemoryView.vue', () => ({ default: defineComponent({ setup(_, { expose }) { expose({ isEditing: () => state.editing }); return () => h('div', '记忆') } }) }))
vi.mock('../src/components/PlanLibraryView.vue', () => ({ default: defineComponent({ setup: () => () => h('div', '方案') }) }))
vi.mock('../src/components/WikiView.vue', () => ({ default: defineComponent({ setup: () => () => h('div', 'Wiki') }) }))
import LibraryHomeView from '../src/components/LibraryHomeView.vue'

// user:“确保视觉、功能和交互不退化”+(手动激活标签时保留草稿保护)。
describe('library section keyboard navigation', () => {
  it('moves focus without switching and respects an open draft on activation', async () => {
    const wrapper = mount(LibraryHomeView, { attachTo: document.body, props: { client: {} as never, requestRpc: async () => ({}) } })
    const tabs = wrapper.findAll('[data-library-section]')
    expect(tabs[0].attributes('tabindex')).toBe('0')
    ;(tabs[0].element as HTMLElement).focus()
    await tabs[0].trigger('keydown', { key: 'ArrowRight' })
    expect(document.activeElement).toBe(tabs[1].element)
    expect(tabs[0].attributes('aria-selected')).toBe('true')
    await tabs[1].trigger('click'); await flushPromises()
    state.editing = true
    await tabs[1].trigger('keydown', { key: 'ArrowRight' })
    await tabs[2].trigger('click'); await flushPromises()
    expect(tabs[1].attributes('aria-selected')).toBe('true')
    state.editing = false
    await tabs[2].trigger('click'); await flushPromises()
    expect(tabs[2].attributes('aria-selected')).toBe('true')
    wrapper.unmount()
  })
})
