import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CoreWorkspaceMenu from '../src/components/CoreWorkspaceMenu.vue'

// user:“确保视觉、功能和交互不退化”+(工作环境变为不可选时关闭已展开的菜单)。
describe('workspace menu availability', () => {
  const options = [{ id: 'local', label: '本机', platform: 'windows', online: true }]
  it.each(['disabled', 'empty'] as const)('closes when %s', async reason => {
    const wrapper = mount(CoreWorkspaceMenu, { props: { activeId: 'local', options } })
    await wrapper.get('.core-workspace-menu__trigger').trigger('click')
    expect(wrapper.find('[data-workspace-option="local"]').exists()).toBe(true)
    await wrapper.setProps(reason === 'disabled' ? { disabled: true } : { options: [] })
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
    expect(wrapper.emitted('select')).toBeUndefined()
    wrapper.unmount()
  })
  it('supports arrow navigation, selection, and escape focus return', async () => {
    const entries = [...options, { id: 'remote', label: '远程', platform: 'windows', online: true }]
    const wrapper = mount(CoreWorkspaceMenu, { attachTo: document.body, props: { activeId: 'local', options: entries } })
    const trigger = wrapper.get('.core-workspace-menu__trigger')
    ;(trigger.element as HTMLElement).focus()
    await trigger.trigger('click'); await Promise.resolve()
    const first = wrapper.get('[data-workspace-option="local"]'), second = wrapper.get('[data-workspace-option="remote"]')
    expect(document.activeElement).toBe(first.element)
    await first.trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement).toBe(second.element)
    await second.trigger('click')
    expect(wrapper.emitted('select')).toEqual([['remote']])
    await trigger.trigger('click'); await Promise.resolve()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); await Promise.resolve()
    expect(document.activeElement).toBe(trigger.element)
    wrapper.unmount()
  })
})
