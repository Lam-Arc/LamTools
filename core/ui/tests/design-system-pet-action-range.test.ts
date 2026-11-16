import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PetActionPanel from '../src/components/PetActionPanel.vue'
import SundayRange from '../src/components/SundayRange.vue'
import { updatePetConfig } from '../src/pet/configFile'
vi.mock('../src/pet/configFile', () => ({ updatePetConfig: vi.fn() }))

describe('pet behavior shared ranges', () => {
  it('previews dragging and saves only on change, preserving each field', async () => {
    const record = { id: 'pet', actions: {}, hitboxes: [], behavior: { enabled: true, activity: .5, restChance: .2, mouseBias: .3, exploreRadius: 400 } }
    const updates: any[] = []
    vi.mocked(updatePetConfig).mockImplementation(async (fn: any) => { updates.push(fn({ pets: [record] })); return {} as any })
    const wrapper = mount(PetActionPanel, { props: { record: record as any } })
    const ranges = wrapper.findAllComponents(SundayRange)
    expect(ranges).toHaveLength(4)
    for (const [index, value] of ['0.7', '0.4', '0.6', '800'].entries()) {
      const input = ranges[index].get('input[type=range]')
      ;(input.element as HTMLInputElement).value = value
      await input.trigger('input')
      expect(updates).toHaveLength(index)
      expect(input.attributes('aria-valuetext')).toBe(['70%', '40%', '60%', '800px'][index])
      await input.trigger('change')
      await flushPromises()
    }
    expect(updates.map(update => update.pets[0].behavior)).toEqual([
      expect.objectContaining({ activity: .7 }), expect.objectContaining({ restChance: .4 }),
      expect.objectContaining({ mouseBias: .6 }), expect.objectContaining({ exploreRadius: 800 }),
    ])
    wrapper.unmount()
  })
})
