import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createSplitDocuments } from '../src/split/documents'
import { splitNative } from '../src/split/native'

vi.mock('../src/split/native', () => ({ splitNative: vi.fn() }))
const stores: Array<ReturnType<typeof createSplitDocuments>> = []
const newDocuments = () => { const store = createSplitDocuments(); stores.push(store); return store }
afterEach(() => { stores.splice(0).forEach(store => store.dispose()); localStorage.clear() })
const source = (path: string) => readFileSync(resolve(process.cwd(), 'src', path), 'utf8')

describe('split pane paths and compact pages', () => {
  // user:“路径无法访问：文件名、目录名或卷标语法不正确”+(文件树返回的 Windows 路径可以直接读取、修改和保存)。
  it.each([
    ['\\\\?\\E:\\project\\notes.md', '//?/E:/project/notes.md'],
    ['\\\\server\\share\\notes.md', '//server/share/notes.md'],
    ['notes.md', 'E:/project/notes.md'],
  ])('round trips %s without adding the project root twice', async (input, expected) => {
    localStorage.clear()
    vi.mocked(splitNative).mockReset().mockResolvedValueOnce('before').mockResolvedValueOnce(undefined)
    const document = newDocuments().get('E:/project', input, 'editor')
    await document.load()
    expect(splitNative).toHaveBeenNthCalledWith(1, 'split_file_read', { root: 'E:/project', path: expected })
    document.doc.content = 'after'
    expect(await document.save()).toBe(true)
    expect(splitNative).toHaveBeenNthCalledWith(2, 'split_file_write', { root: 'E:/project', path: expected, content: 'after', original: 'before' })
  })

  // user:“专门对小屏或者说分屏状态做一下适配”+(布局依据页面容器宽度，与桌面窗口宽度无关)。
  it('provides a local sizing container for main and auxiliary pages', () => {
    expect(source('components/CoreAppPage.vue')).toContain('class="core-app-page"')
    expect(source('styles/app-page.css')).toMatch(/container:\s*app-page\s*\/\s*inline-size/)
  })

  it.each(['CoreSettings', 'CoreArrangeManager', 'SearchShell', 'AccountShell'])('%s adapts to its own pane', name => {
    const css = name === 'CoreSettings' ? source('styles/core-settings.css') : source(`components/${name}.vue`)
    expect(css).toContain('@container app-page')
    expect(css).not.toMatch(/@media\s*\((?:min|max)-width:/)
  })

  it('adapts shared navigation, library grids and plugin controls', () => {
    const css = source('styles/app-page.css')
    expect(css).toContain('.settings-nav')
    expect(css).toContain('.install-input')
    expect(css).toContain('.plan-grid')
    expect(source('styles/library-surface.css')).toContain('@container app-page')
  })
})
