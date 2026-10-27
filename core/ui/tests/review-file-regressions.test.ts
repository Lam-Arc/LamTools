import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createSplitDocuments } from '../src/split/documents'
import { splitNative } from '../src/split/native'
import { createDesktopFilePicker } from '../src/app/desktopFilePicker'
import { flushPromises, mount } from '@vue/test-utils'
import CoreSplitTextEditor from '../src/components/CoreSplitTextEditor.vue'
import type { SplitWorkspaceController } from '../src/split/useSplitWorkspace'

vi.mock('../src/split/native', () => ({ splitNative: vi.fn() }))
const stores: Array<ReturnType<typeof createSplitDocuments>> = []
const newDocuments = () => { const store = createSplitDocuments(); stores.push(store); return store }
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear()
  // jsdom does not implement the text geometry CodeMirror measures after mounting.
  vi.stubGlobal('Range', class extends Range {
    getClientRects() { return document.createElement('span').getClientRects() }
    getBoundingClientRect() { return new DOMRect() }
  })
})
afterEach(() => {
  // Draft writes are batched; dispose tracked stores so pending timers cannot reach a later test.
  stores.splice(0).forEach(store => store.dispose())
  document.body.innerHTML = ''; vi.unstubAllGlobals(); localStorage.clear()
})

// user:“修”+(复现审查中的桌面上传失效、另存为映射错配和重开旧内容，保护未保存草稿)。
describe('reviewed file regressions', () => {
  it('returns selected file bytes for desktop library uploads', async () => {
    const pending = createDesktopFilePicker(vi.fn()).pick({ multiple: true, source: 'file' })
    const input = document.querySelector<HTMLInputElement>('input[type=file]')!
    expect(input).not.toBeNull()
    const file = new File(['library input'], 'note.txt', { type: 'text/plain' })
    Object.defineProperty(input, 'files', { value: [file] })
    input.dispatchEvent(new Event('change'))
    expect(await pending).toEqual([file])
    expect(document.querySelector('input[type=file]')).toBeNull()
  })

  it('keeps native path selection for chat attachments and handles cancellation', async () => {
    const pickPaths = vi.fn().mockResolvedValueOnce(['E:/project/a.md'])
    expect(await createDesktopFilePicker(pickPaths).pickPaths!()).toEqual(['E:/project/a.md'])
    expect(pickPaths).toHaveBeenCalledTimes(1)
    const pending = createDesktopFilePicker(pickPaths).pick()
    document.querySelector('input')!.dispatchEvent(new Event('cancel'))
    expect(await pending).toBeNull()
  })

  it('opens the original file independently after saving a copy', async () => {
    vi.mocked(splitNative).mockResolvedValueOnce('original A')
    const store = newDocuments(), original = store.get('E:/project', 'a.md', 'a')
    await original.load()
    original.doc.content = 'copy B'
    vi.mocked(splitNative).mockResolvedValueOnce(undefined)
    expect(await original.save('b.md')).toBe(true)
    expect(store.get('E:/project', 'b.md', 'b')).toBe(original)
    const reopened = store.get('E:/project', 'a.md', 'reopened')
    expect(reopened).not.toBe(original)
    vi.mocked(splitNative).mockResolvedValueOnce('original A')
    await reopened.load()
    expect(reopened.doc.path).toBe('E:/project/a.md')
    expect(reopened.doc.content).toBe('original A')
  })

  it('refreshes a clean file on reopen and uses the new baseline when saving', async () => {
    const store = newDocuments(), original = store.get('E:/project', 'a.md', 'a')
    vi.mocked(splitNative).mockResolvedValueOnce('old')
    await original.load()
    vi.mocked(splitNative).mockResolvedValueOnce('external update')
    const reopened = store.get('E:/project', 'a.md', 'reopened')
    await reopened.load()
    expect(reopened.doc.content).toBe('external update')
    expect(reopened.doc.baseline).toBe('external update')
    reopened.doc.content = 'new edit'
    vi.mocked(splitNative).mockResolvedValueOnce(undefined)
    expect(await reopened.save()).toBe(true)
    expect(splitNative).toHaveBeenLastCalledWith('split_file_write', expect.objectContaining({ original: 'external update', content: 'new edit' }))
  })

  it('preserves an unsaved shared draft when another view opens the file', async () => {
    const store = newDocuments(), original = store.get('E:/project', 'a.md', 'a')
    vi.mocked(splitNative).mockResolvedValueOnce('old')
    await original.load()
    original.doc.content = 'unsaved draft'
    const reopened = store.get('E:/project', 'a.md', 'reopened')
    await reopened.load()
    expect(reopened.doc.content).toBe('unsaved draft')
    expect(reopened.doc.baseline).toBe('old')
    expect(splitNative).toHaveBeenCalledTimes(1)
  })

  it('keeps the original mapping and draft after a failed save as', async () => {
    const store = newDocuments(), original = store.get('E:/project', 'a.md', 'a')
    vi.mocked(splitNative).mockResolvedValueOnce('original')
    await original.load()
    original.doc.content = 'draft'
    vi.mocked(splitNative).mockRejectedValueOnce(Error('target already exists'))
    expect(await original.save('b.md')).toBe(false)
    expect(store.get('E:/project', 'a.md', 'again')).toBe(original)
    expect(store.get('E:/project', 'b.md', 'new')).not.toBe(original)
    expect(original.doc.content).toBe('draft')
    expect(original.dirty.value).toBe(true)
  })

  it('retains edits made in a shared view while a refresh is pending', async () => {
    const original = newDocuments().get('E:/project', 'a.md', 'a')
    vi.mocked(splitNative).mockResolvedValueOnce('old')
    await original.load()
    let finish!: (text: string) => void
    vi.mocked(splitNative).mockImplementationOnce(() => new Promise<string>(resolve => { finish = resolve }))
    const refresh = original.load()
    original.doc.content = 'new draft'
    finish('external update')
    await refresh
    expect(original.doc.content).toBe('new draft')
    expect(original.doc.baseline).toBe('old')
    expect(original.doc.error).toContain('发生变化')
  })

  it('blocks saving stale clean content when a file disappears, then allows retry', async () => {
    const original = newDocuments().get('E:/project', 'a.md', 'a')
    vi.mocked(splitNative).mockResolvedValueOnce('old')
    await original.load()
    vi.mocked(splitNative).mockRejectedValueOnce(Error('file missing'))
    await original.load()
    expect(original.doc.loaded).toBe(false)
    expect(await original.save()).toBe(false)
    vi.mocked(splitNative).mockResolvedValueOnce('restored')
    await original.load()
    expect(original.doc.loaded).toBe(true)
    expect(original.doc.content).toBe('restored')
  })

  it('refuses to save over a file that another open tab owns', async () => {
    vi.mocked(splitNative).mockResolvedValueOnce('A').mockResolvedValueOnce('B')
    const store = newDocuments(), first = store.get('E:/project', 'a.md', 'a'), second = store.get('E:/project', 'b.md', 'b')
    await first.load(); await second.load()
    first.doc.content = 'changed A'
    expect(await first.save('b.md')).toBe(false)
    expect(first.doc.error).toContain('另一个标签')
    expect(store.get('E:/project', 'b.md', 'other')).toBe(second)
    expect(second.doc.content).toBe('B')
    expect(splitNative).toHaveBeenCalledTimes(2)
  })

  it('applies content changed by another view while keeping the shared document', async () => {
    vi.mocked(splitNative).mockResolvedValue('original A')
    const documents = newDocuments()
    const controller = { registerGuard: () => () => {} } as unknown as SplitWorkspaceController
    const firstTab = { id: 'a', kind: 'editor' as const, title: 'a.md', resource: 'a.md' }
    const first = mount(CoreSplitTextEditor, { props: { tab: firstTab, root: 'E:/project', controller, documents } })
    const second = mount(CoreSplitTextEditor, { props: { tab: { ...firstTab, id: 'second-view' }, root: 'E:/project', controller, documents } })
    try {
      await flushPromises()
      const shared = documents.get('E:/project', 'a.md', 'a')
      shared.doc.content = 'from another view'
      await flushPromises()
      expect(first.find('.cm-content').text()).toContain('from another view')
      expect(second.find('.cm-content').text()).toContain('from another view')
    } finally { first.unmount(); second.unmount() }
  })

  it('updates every shared editor target after saving a copy', async () => {
    vi.mocked(splitNative).mockResolvedValue('original A')
    const documents = newDocuments()
    const controller = { registerGuard: () => () => {} } as unknown as SplitWorkspaceController
    const firstTab = { id: 'a', kind: 'editor' as const, title: 'a.md', resource: 'a.md' }
    const secondTab = { ...firstTab, id: 'second-view' }
    const first = mount(CoreSplitTextEditor, { props: { tab: firstTab, root: 'E:/project', controller, documents } })
    const second = mount(CoreSplitTextEditor, { props: { tab: secondTab, root: 'E:/project', controller, documents } })
    try {
      await flushPromises()
      await first.find('input').setValue('b.md')
      await first.find('button[aria-label="保存文件"]').trigger('click')
      await flushPromises()
      expect(firstTab.resource).toBe('E:/project/b.md')
      expect(secondTab.resource).toBe('E:/project/b.md')
      expect((second.find('input').element as HTMLInputElement).value).toBe('E:/project/b.md')
    } finally { first.unmount(); second.unmount() }
  })
})
