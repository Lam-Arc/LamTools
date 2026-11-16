import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import CoreSkillsEditor from '../src/components/CoreSkillsEditor.vue'
import SundaySwitch from '../src/components/SundaySwitch.vue'
describe('skill shared switch', () => {
  it('holds the current state while saving, applies success and restores on failure', async () => {
    let resolveSave!: () => void
    const rpc = vi.fn((method: string) => {
      if (method === 'skill.list') return Promise.resolve({ skills: [{ name: 'alpha', description: '', source: 'user', enabled: true, deletable: false, group: '' }], groups: [] })
      if (method === 'skill.disable') return new Promise<Record<string, unknown>>(resolve => { resolveSave = () => resolve({}) })
      return Promise.reject(new Error('启用失败'))
    })
    const wrapper = mount(CoreSkillsEditor, { props: { requestRpc: rpc } }); await flushPromises()
    const card = wrapper.get('[data-skill-card="alpha"]')
    const control = card.findComponent(SundaySwitch)
    expect(control.exists()).toBe(true)
    const input = control.get('input')
    await input.setValue(false)
    expect((input.element as HTMLInputElement).disabled).toBe(true)
    resolveSave(); await flushPromises()
    expect((input.element as HTMLInputElement).checked).toBe(false)
    await input.setValue(true); await flushPromises()
    expect((input.element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.text()).toContain('启用失败')
    expect(rpc).toHaveBeenCalledWith('skill.enable', { name: 'alpha' })
    wrapper.unmount()
  })
})
