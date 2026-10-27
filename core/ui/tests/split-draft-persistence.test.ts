import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createSplitDocuments } from '../src/split/documents'
import { splitNative } from '../src/split/native'

vi.mock('../src/split/native', () => ({ splitNative: vi.fn() }))
const draftKey = 'lamtools:split-draft:E:/project:E:/project/a.md'

// user:“审查分屏代码，并优化”+(连续输入时不再每个按键同步写一次本机存储；暂停、退出或测试刷新时一次性落盘)。
describe('split draft persistence', () => {
  beforeEach(() => { localStorage.clear(); vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers(); localStorage.clear() })

  it('batches keystrokes and writes the latest draft after the pause', async () => {
    vi.mocked(splitNative).mockResolvedValueOnce('before')
    const store = createSplitDocuments(), document = store.get('E:/project', 'a.md', 'editor')
    await document.load()
    document.doc.content = 'first'
    await nextTick()
    document.doc.content = 'second'
    await nextTick()
    expect(localStorage.getItem(draftKey)).toBeNull()
    vi.advanceTimersByTime(299)
    expect(localStorage.getItem(draftKey)).toBeNull()
    vi.advanceTimersByTime(1)
    expect(JSON.parse(localStorage.getItem(draftKey) || 'null')).toEqual({ content: 'second', baseline: 'before' })
    store.dispose()
  })

  it('flushes a pending draft before the page is hidden and forgets it after a successful save', async () => {
    vi.mocked(splitNative).mockResolvedValueOnce('before')
    const store = createSplitDocuments(), document = store.get('E:/project', 'a.md', 'editor')
    await document.load()
    document.doc.content = 'pending'
    await nextTick()
    expect(localStorage.getItem(draftKey)).toBeNull()
    window.dispatchEvent(new Event('pagehide'))
    expect(JSON.parse(localStorage.getItem(draftKey) || 'null')?.content).toBe('pending')
    vi.mocked(splitNative).mockResolvedValueOnce(undefined)
    expect(await document.save()).toBe(true)
    expect(localStorage.getItem(draftKey)).toBeNull()
    store.dispose()
  })

  // user:“审查分屏代码，并优化”+(最后一个编辑器标签关闭后释放正文和监听；再次打开从本机草稿恢复)。
  it('releases the file content after the last view closes and recovers the draft on reopen', async () => {
    vi.mocked(splitNative).mockResolvedValueOnce('before')
    const store = createSplitDocuments(), first = store.get('E:/project', 'a.md', 'a')
    await first.load()
    first.doc.content = 'draft'
    await nextTick()
    first.release()
    const reopened = store.get('E:/project', 'a.md', 'b')
    expect(reopened).not.toBe(first)
    expect(reopened.doc.content).toBe('draft')
    expect(reopened.doc.baseline).toBe('before')
    reopened.release()
    store.dispose()
  })
})
