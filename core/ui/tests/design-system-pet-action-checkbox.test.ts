import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PetActionPanel from '../src/components/PetActionPanel.vue'
import { updatePetConfig } from '../src/pet/configFile'

vi.mock('../src/pet/configFile', () => ({ updatePetConfig: vi.fn() }))

describe('pet action shared checkboxes', () => {
  it('preserves each configuration update while using the shared control', async () => {
    const record = { id: 'pet', actions: { idle: { type: 'frames', sources: ['idle.png'], fps: 8, loop: true } }, hitboxes: [{ id: 'body', name: '身体', x: 0, y: 0, width: 1, height: 1, action: 'idle', enabled: true }], behavior: { enabled: true } }
    const updates: any[] = []
    vi.mocked(updatePetConfig).mockImplementation(async (fn: any) => { updates.push(fn({ pets: [record] })); return {} as any })
    const wrapper = mount(PetActionPanel, { props: { record: record as any } })
    const inputs = wrapper.findAll('input[type=checkbox]')
    expect(inputs).toHaveLength(3)
    for (const input of inputs) {
      expect(input.classes()).toContain('sunday-checkbox')
      await input.setValue(false)
      await flushPromises()
    }
    expect(updates[0].pets[0].actions.idle.loop).toBe(false)
    expect(updates[1].pets[0].hitboxes[0].enabled).toBe(false)
    expect(updates[2].pets[0].behavior.enabled).toBe(false)
    expect(wrapper.emitted('changed')).toHaveLength(3)
    wrapper.unmount()
  })
})
