import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“直接渲染项目真实组件…交互测试”+(项目设置预览只更改本地项目)。
describe('project settings gallery', () => {
  it('edits project name and rules in isolated sample data', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreProjectSettings'); await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('[data-project-name-input]').exists()).toBe(true), { timeout: 10000 })
    const input = wrapper.get('[data-project-name-input]')
    await input.setValue('新示例'); await input.trigger('change'); await flushPromises()
    expect(wrapper.text()).toContain('本地项目：新示例')
    const rule = wrapper.get('textarea')
    await rule.setValue('本地规则')
    const save = wrapper.findAll('button').find(button => button.text() === '保存')!
    await save.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('本地规则已保存')
    wrapper.unmount()
  }, 15000)
  it('protects an unsaved rules draft when switching sections', async () => {
    const wrapper = mount(Gallery, { attachTo: document.body })
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreProjectSettings'); await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('textarea').exists()).toBe(true), { timeout: 10000 })
    await wrapper.get('textarea').setValue('未保存规则')
    await wrapper.get('[data-settings-section="subagent"]').trigger('click'); await flushPromises()
    expect(document.querySelector('[role="dialog"]')).toBeTruthy()
    ;(document.querySelector('.core-confirm__cancel') as HTMLButtonElement).click(); await flushPromises()
    expect(wrapper.get('textarea').element).toHaveProperty('value', '未保存规则')
    expect(wrapper.find('[data-settings-section="subagent"]').attributes('aria-current')).not.toBe('page')
    wrapper.unmount()
  }, 15000)

})
