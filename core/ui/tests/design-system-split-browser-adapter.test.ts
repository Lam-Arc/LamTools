import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import CoreSplitBrowser from '../src/components/CoreSplitBrowser.vue'

// user:“直接渲染项目真实组件…交互测试”+(浏览器可使用隔离服务测试导航，不打开真实网页)。
describe('split browser isolated service', () => {
  it('creates and navigates, reports updates, and closes the same view', async () => {
    let notify!: (event: { id: string; url: string; loading: boolean }) => void
    const unsubscribe = vi.fn()
    const services = { available: () => true, call: vi.fn(async () => {}), subscribe: vi.fn(async (callback) => { notify = callback; return unsubscribe }), openExternal: vi.fn(async () => {}) }
    const tab = { id: 'sample', kind: 'browser', resource: '', title: '浏览器' } as const
    const wrapper = mount(CoreSplitBrowser, { props: { tab: { ...tab }, visible: true, services } }); await flushPromises()
    const address = wrapper.get('input[aria-label="网页地址"]')
    await address.setValue('example.invalid'); await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(services.call).toHaveBeenCalledWith('sample', 'create', expect.objectContaining({ url: 'https://example.invalid/' }))
    notify({ id: 'sample', url: 'https://example.invalid/page', loading: false }); await flushPromises()
    expect((address.element as HTMLInputElement).value).toBe('https://example.invalid/page')
    await wrapper.get('button[aria-label="在默认浏览器打开"]').trigger('click'); await flushPromises()
    expect(services.openExternal).toHaveBeenCalledWith('https://example.invalid/page')
    wrapper.unmount(); await flushPromises()
    expect(unsubscribe).toHaveBeenCalledOnce()
    expect(services.call).toHaveBeenCalledWith('sample', 'close')
  })
  it('shows an asynchronous failure to open externally', async () => {
    const services = { available: () => false, call: vi.fn(async () => {}), subscribe: vi.fn(async () => () => {}), openExternal: vi.fn(async () => { throw Error('示例打开失败') }) }
    const wrapper = mount(CoreSplitBrowser, { props: { tab: { id: 'sample', kind: 'browser', resource: 'https://example.invalid', title: '示例' }, visible: true, services } })
    await wrapper.get('button[aria-label="在默认浏览器打开"]').trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('示例打开失败')
    wrapper.unmount()
  })
  it('reports failure to subscribe to desktop browser events', async () => {
    const services = { available: () => true, call: vi.fn(async () => {}), subscribe: vi.fn(async () => { throw Error('监听失败') }), openExternal: vi.fn(async () => {}) }
    const wrapper = mount(CoreSplitBrowser, { props: { tab: { id: 'sample', kind: 'browser', resource: '', title: '示例' }, visible: true, services } }); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('监听失败')
    await wrapper.get('input[aria-label="网页地址"]').setValue('example.invalid')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(services.call).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('waits for event subscription before creating a view', async () => {
    let ready!: (stop: () => void) => void
    const services = { available: () => true, call: vi.fn(async () => {}), subscribe: vi.fn(() => new Promise<() => void>(resolve => { ready = resolve })), openExternal: vi.fn(async () => {}) }
    const wrapper = mount(CoreSplitBrowser, { props: { tab: { id: 'sample', kind: 'browser', resource: '', title: '示例' }, visible: true, services } })
    await wrapper.get('input[aria-label="网页地址"]').setValue('example.invalid')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(services.call).not.toHaveBeenCalled()
    ready(() => {}); await flushPromises()
    expect(services.call).toHaveBeenCalledWith('sample', 'create', expect.objectContaining({ url: 'https://example.invalid/' }))
    wrapper.unmount()
  })
  it('does not create a view if closed before the listener is ready', async () => {
    let ready!: (stop: () => void) => void
    const stop = vi.fn()
    const services = { available: () => true, call: vi.fn(async () => {}), subscribe: vi.fn(() => new Promise<() => void>(resolve => { ready = resolve })), openExternal: vi.fn(async () => {}) }
    const wrapper = mount(CoreSplitBrowser, { props: { tab: { id: 'sample', kind: 'browser', resource: '', title: '示例' }, visible: true, services } })
    await wrapper.get('input[aria-label="网页地址"]').setValue('example.invalid'); await wrapper.get('form').trigger('submit')
    wrapper.unmount(); ready(stop); await flushPromises()
    expect(services.call).not.toHaveBeenCalled()
    expect(stop).toHaveBeenCalledOnce()
  })
  it('closes an existing view only once when navigation finishes after unmount', async () => {
    let finishNavigation!: () => void
    const call = vi.fn((_id: string, action: string) => action === 'navigate' ? new Promise<void>(resolve => { finishNavigation = resolve }) : Promise.resolve())
    const services = { available: () => true, call, subscribe: vi.fn(async () => () => {}), openExternal: vi.fn(async () => {}) }
    const wrapper = mount(CoreSplitBrowser, { props: { tab: { id: 'sample', kind: 'browser', resource: '', title: '示例' }, visible: true, services } }); await flushPromises()
    const address = wrapper.get('input[aria-label="网页地址"]')
    await address.setValue('one.invalid'); await wrapper.get('form').trigger('submit'); await flushPromises()
    await address.setValue('two.invalid'); await wrapper.get('form').trigger('submit'); await flushPromises()
    wrapper.unmount(); finishNavigation(); await flushPromises()
    expect(call.mock.calls.filter(([, action]) => action === 'close')).toHaveLength(1)
  })
  it('keeps a redirected address reported before the create request finishes', async () => {
    let notify!: (event: { id: string; url: string; loading: boolean }) => void
    let finish!: () => void
    const services = { available: () => true, call: vi.fn((_id: string, action: string) => action === 'create' ? new Promise<void>(resolve => { finish = resolve }) : Promise.resolve()), subscribe: vi.fn(async (callback) => { notify = callback; return () => {} }), openExternal: vi.fn(async () => {}) }
    const tab = { id: 'sample', kind: 'browser' as const, resource: '', title: '示例' }
    const wrapper = mount(CoreSplitBrowser, { props: { tab, visible: true, services } }); await flushPromises()
    const address = wrapper.get('input[aria-label="网页地址"]')
    await address.setValue('one.invalid'); await wrapper.get('form').trigger('submit'); await flushPromises()
    notify({ id: 'sample', url: 'https://redirect.invalid/final', loading: false }); finish(); await flushPromises()
    expect((address.element as HTMLInputElement).value).toBe('https://redirect.invalid/final')
    expect(tab.resource).toBe('https://redirect.invalid/final')
    wrapper.unmount()
  })
})
