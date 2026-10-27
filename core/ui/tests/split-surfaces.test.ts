import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, describe, it, expect, vi } from 'vitest'
import CoreSplitPane from '../src/components/CoreSplitPane.vue'
import { createSplitDocuments } from '../src/split/documents'
import { splitNative } from '../src/split/native'
vi.mock('../src/split/native', () => ({ splitNative: vi.fn(), hasSplitNative: () => true }))
const stores: Array<ReturnType<typeof createSplitDocuments>> = []
const newDocuments = () => { const store = createSplitDocuments(); stores.push(store); return store }
afterEach(() => { stores.splice(0).forEach(store => store.dispose()); localStorage.clear() })
describe('Split Pane content acceptance', () => {
  it('supports keyboard tab selection and keeps close separate from selection', async () => {
    const pane = { id: 'aux', activeTab: 'a', tabs: [{ id: 'a', kind: 'page' as const, resource: 'library', title: '资料库' }, { id: 'b', kind: 'page' as const, resource: 'settings', title: '设置' }] }
    const wrapper = mount(CoreSplitPane, { props: { pane, active: true }, attachTo: document.body })
    const tabs = wrapper.findAll('[role=tab]')
    ;(tabs[0].element as HTMLButtonElement).focus()
    await tabs[0].trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('activate')?.[0]).toEqual(['b'])
    await wrapper.findAll('.split-tab-close')[0].trigger('click')
    expect(wrapper.emitted('close')?.[0]).toEqual([pane.tabs[0]])
    expect(wrapper.emitted('activate')).toHaveLength(1)
    wrapper.unmount()
  })
  it('shares document edits and retains drafts after failed saves', async () => {
    localStorage.clear()
    vi.mocked(splitNative).mockResolvedValueOnce('original')
    const store = newDocuments(), first = store.get('E:/project', 'file.md', 'a'), second = store.get('E:/project', 'file.md', 'b')
    expect(first).toBe(second)
    await first.load(); first.doc.content = 'draft'
    vi.mocked(splitNative).mockRejectedValueOnce(Error('文件已被其他程序修改'))
    expect(await first.save()).toBe(false)
    expect(second.doc.content).toBe('draft')
    expect(second.dirty.value).toBe(true)
    expect(second.doc.baseline).toBe('original')
    vi.mocked(splitNative).mockResolvedValueOnce(undefined)
    expect(await first.save()).toBe(true)
    expect(second.dirty.value).toBe(false)
    await flushPromises()
  })
  it('recovers an unsaved draft without replacing it with newer disk content', async () => {
    localStorage.clear()
    vi.mocked(splitNative).mockResolvedValueOnce('old')
    const store = newDocuments(), previous = store.get('E:/project', 'a.md', 'previous')
    await previous.load(); previous.doc.content = 'my draft'; await flushPromises()
    // Draft writes are batched now; a real restart fires pagehide, tests flush explicitly.
    store.flush()
    vi.mocked(splitNative).mockResolvedValueOnce('external update')
    const document = newDocuments().get('E:/project', 'a.md', 'a')
    await document.load()
    expect(document.doc.content).toBe('my draft')
    expect(document.doc.baseline).toBe('old')
    expect(document.doc.error).toContain('发生变化')
  })
})
