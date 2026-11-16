import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
vi.mock('read-excel-file/universal', () => ({ default: async () => [{ sheet: '第一张', data: [['甲']] }, { sheet: '第二张', data: [['乙']] }] }))
import CoreSplitPreview from '../src/components/CoreSplitPreview.vue'

// user:“确保视觉、功能和交互不退化”+(分屏工作表标签键盘切换实际表格)。
describe('spreadsheet preview tabs', () => {
  it('switches sheets with keyboard and preserves visible data', async () => {
    const wrapper = mount(CoreSplitPreview, { attachTo: document.body, props: {
      tab: { id: 'sheet', kind: 'preview', title: 'book.xlsx', resource: 'E:/p/book.xlsx', root: 'E:/p' }, root: 'E:/p',
      transport: { request: async () => ({ status: 200, headers: {}, body: new Uint8Array([1]) }) } as never,
    } })
    await flushPromises(); await flushPromises()
    const tabs = wrapper.findAll('.split-preview-sheet-tabs [role="tab"]')
    expect(tabs).toHaveLength(2)
    expect(tabs[0].attributes('tabindex')).toBe('0')
    ;(tabs[0].element as HTMLElement).focus()
    await tabs[0].trigger('keydown', { key: 'ArrowRight' })
    expect(tabs[1].attributes('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(tabs[1].element)
    expect(wrapper.findAll('.split-preview-sheet')[1].isVisible()).toBe(true)
    expect(wrapper.findAll('.split-preview-sheet')[1].text()).toContain('乙')
    wrapper.unmount()
  })
})
