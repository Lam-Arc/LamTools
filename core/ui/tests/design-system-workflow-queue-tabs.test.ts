import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SundaySegmented from '../src/components/SundaySegmented.vue'
import WorkflowQueuePanel from '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowQueuePanel.vue'

// user:“确保视觉、功能和交互不退化”+(队列标签支持键盘切换且只保留一个 Tab 入口)。
describe('workflow queue tabs', () => {
  it('switches, focuses and wraps with arrow and boundary keys', async () => {
    const wrapper = mount(WorkflowQueuePanel, { attachTo: document.body })
    const tabs = wrapper.findAll('[role="tab"]')
    expect(tabs.map(tab => tab.attributes('tabindex'))).toEqual(['0', '-1'])
    ;(tabs[0].element as HTMLElement).focus()
    await tabs[0].trigger('keydown', { key: 'ArrowRight' })
    expect(tabs[1].attributes('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(tabs[1].element)
    expect(tabs.map(tab => tab.attributes('tabindex'))).toEqual(['-1', '0'])
    expect(wrapper.text()).toContain('还没有运行历史')
    await tabs[1].trigger('keydown', { key: 'Home' })
    expect(tabs[0].attributes('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(tabs[0].element)
    await tabs[0].trigger('keydown', { key: 'ArrowLeft' })
    expect(tabs[1].attributes('aria-selected')).toBe('true')
    wrapper.unmount()
  })
})

// user:“确保视觉、功能和交互不退化”+(扩展共享导航后原有分段单选仍可操作)。
it('preserves radio group keyboard selection', async () => {
  const wrapper = mount(SundaySegmented, { attachTo: document.body, props: { modelValue: 'a', label: '选项', options: [{ value: 'a', label: '甲' }, { value: 'b', label: '乙' }] } })
  const buttons = wrapper.findAll('[role="radio"]')
  ;(buttons[0].element as HTMLElement).focus()
  await buttons[0].trigger('keydown', { key: 'ArrowRight' })
  expect(wrapper.emitted('update:modelValue')).toEqual([['b']])
  expect(document.activeElement).toBe(buttons[1].element)
  wrapper.unmount()
})
