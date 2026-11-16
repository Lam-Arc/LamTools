import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CoreUpdateCard from '../src/components/CoreUpdateCard.vue'
describe('update modal control states', () => {
  it('disables controls that cannot dismiss during downloaded or installing states', async () => {
    const wrapper = mount(CoreUpdateCard, { props: { state: 'downloaded' }, global: { stubs: { Teleport: true } } })
    expect((wrapper.get('[data-update-dismiss]').element as HTMLButtonElement).disabled).toBe(true)
    expect((wrapper.get('[data-update-cancel]').element as HTMLButtonElement).disabled).toBe(true)
    await wrapper.setProps({ state: 'installing' })
    expect((wrapper.get('[data-update-dismiss]').element as HTMLButtonElement).disabled).toBe(true)
    expect((wrapper.get('[data-update-cancel]').element as HTMLButtonElement).disabled).toBe(true)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('closed')).toBeUndefined()
    await wrapper.setProps({ state: 'downloading' })
    expect((wrapper.get('[data-update-dismiss]').element as HTMLButtonElement).disabled).toBe(false)
    await wrapper.get('[data-update-cancel]').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    wrapper.unmount()
  })
})
