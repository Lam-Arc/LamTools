import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import CoreProjectCreate from '../src/components/CoreProjectCreate.vue'
describe('project creation local preview', () => {
  it('uses the supplied in-app directory browser without invoking the desktop picker', async () => {
    const nativePicker = vi.fn(async () => 'E:\\actual')
    ;(window as any).__LAMTOOLS_PICK_DIRECTORY = nativePicker
    const transport = { request: vi.fn(async () => ({ status: 200, headers: {}, body: new TextEncoder().encode('{"entries":[]}') })) } as any
    const wrapper = mount(CoreProjectCreate, { props: { transport, useNativePicker: false }, global: { stubs: { Teleport: true } } })
    await wrapper.get('[data-project-browse]').trigger('click')
    expect(nativePicker).not.toHaveBeenCalled()
    expect(wrapper.find('.fb-dialog').exists()).toBe(true)
    wrapper.unmount()
    delete (window as any).__LAMTOOLS_PICK_DIRECTORY
  })
})
