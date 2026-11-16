import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import CoreUpdateCard from '../src/components/CoreUpdateCard.vue'
const animation = vi.hoisted(() => ({ leave: vi.fn(() => new Promise<void>(() => {})) }))
vi.mock('../src/motion/presets.ts', () => ({ shouldSkipMotion: () => false, enterFade: vi.fn(), enterMorph: vi.fn(), enterScrim: vi.fn(), leaveMorph: animation.leave, leaveScrim: vi.fn() }))
describe('update cancellation', () => {
  it('sends cancellation only once while the close animation is in progress', async () => {
    const origin = document.createElement('button')
    const wrapper = mount(CoreUpdateCard, { props: { origin, state: 'downloading' }, global: { stubs: { Teleport: true } } })
    await wrapper.get('[data-update-cancel]').trigger('click')
    await wrapper.get('[data-update-dismiss]').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    expect(animation.leave).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
