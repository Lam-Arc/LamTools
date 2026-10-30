import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CoreSplitPreview from '../src/components/CoreSplitPreview.vue'
import { createSplitState, openTab, splitPane, restoreSplitState } from '../src/split/layout'
import { openFileInSplit } from '../src/split/openFile'
import { isTextPath, previewKindFor, splitContentFor } from '../src/split/preview'
import { useSplitPreviewPreference } from '../src/split/previewPreference'

// user:“分屏预览器不支持图片吗？改一下图片，视频 office，什么东西都尽可能支持一下”+
// (验收富媒体/文档进预览器、文本仍进编辑器，默认打开走同一条分屏入口)。
describe('split file preview routing', () => {
  it.each([
    ['cover.PNG', 'image'],
    ['photo.jpeg', 'image'],
    ['icon.svg', 'image'],
    ['clip.mp4', 'video'],
    ['sound.mp3', 'audio'],
    ['manual.pdf', 'pdf'],
    ['report.docx', 'docx'],
    ['budget.xlsx', 'xlsx'],
    ['macro.xlsm', 'xlsx'],
    ['deck.pptx', 'pptx'],
    ['README.md', 'markdown'],
    ['guide.markdown', 'markdown'],
  ])('previews %s as %s', (path, kind) => {
    expect(previewKindFor(path)).toBe(kind)
    expect(splitContentFor(path)).toBe('preview')
  })

  it.each(['main.rs', 'config.yaml', 'Dockerfile', '.gitignore', 'data.json', 'page.html'])(
    'keeps %s in the text editor', path => {
      expect(isTextPath(path)).toBe(true)
      expect(previewKindFor(path)).toBeNull()
      expect(splitContentFor(path)).toBe('editor')
    })

  it('sends files it cannot classify to the previewer instead of showing binary garbage', () => {
    expect(splitContentFor('archive.zip')).toBe('preview')
    expect(splitContentFor('legacy.doc')).toBe('preview')
    expect(splitContentFor('')).toBe('editor')
  })

  it('restores a persisted preview tab and still drops an unknown kind', () => {
    const state = createSplitState(), right = splitPane(state, 'main', 'right')!
    openTab(state, right, { id: 'preview-1', kind: 'preview', title: 'a.png', resource: 'E:/p/a.png', root: 'E:/p' })
    const restored = restoreSplitState(JSON.stringify(state))
    expect(restored.panes[right]?.tabs[0]?.kind).toBe('preview')
    openTab(state, right, { id: 'bad', kind: 'video' as never, title: 'a.mp4', resource: 'E:/p/a.mp4' })
    expect(restoreSplitState(JSON.stringify(state)).panes[right]).toBeUndefined()
  })

  it('opens through the same entry as text: previews reuse a preview pane, text reuses an editor pane', () => {
    const add = vi.fn((...args: unknown[]) => args)
    const controller: any = { tabs: { value: [] }, state: { activePane: 'main' }, split: () => null, add }
    openFileInSplit(controller, 'E:/p/photo.png', { workRoot: 'E:/p' })
    expect(add).toHaveBeenLastCalledWith('preview', 'E:/p/photo.png', 'photo.png', undefined, undefined, 'E:/p', undefined)
    controller.tabs.value = [{ pane: 'right', tab: { id: 'p', kind: 'preview', title: '', resource: '' } }]
    openFileInSplit(controller, 'E:/p/b.pdf', { workRoot: 'E:/p' })
    expect(add).toHaveBeenLastCalledWith('preview', 'E:/p/b.pdf', 'b.pdf', 'right', undefined, 'E:/p', undefined)
    controller.tabs.value = [{ pane: 'left', tab: { id: 'e', kind: 'editor', title: '', resource: '' } }]
    openFileInSplit(controller, 'E:/p/main.rs', { workRoot: 'E:/p' })
    expect(add).toHaveBeenLastCalledWith('editor', 'E:/p/main.rs', 'main.rs', 'left', undefined, 'E:/p', undefined)
  })

  it('stops taking over preview files when the experimental switch is off', () => {
    const preference = useSplitPreviewPreference()
    const add = vi.fn((...args: unknown[]) => args)
    const controller: any = { tabs: { value: [] }, state: { activePane: 'main' }, split: () => null, add }
    preference.setEnabled(false)
    expect(openFileInSplit(controller, 'E:/p/photo.png', { workRoot: 'E:/p' })).toBeNull()
    expect(openFileInSplit(controller, 'E:/p/main.rs', { workRoot: 'E:/p' })).not.toBeNull()
    // 用户主动选“在分屏中打开”时不看默认开关。
    expect(openFileInSplit(controller, 'E:/p/photo.png', { workRoot: 'E:/p', force: true })).not.toBeNull()
    preference.setEnabled(true)
    expect(openFileInSplit(controller, 'E:/p/photo.png', { workRoot: 'E:/p' })).not.toBeNull()
  })

  it('renders an image read through the backend instead of the text editor', async () => {
    const createObjectURL = vi.fn(() => 'blob:preview'), revokeObjectURL = vi.fn()
    Object.assign(URL, { createObjectURL, revokeObjectURL })
    const request = vi.fn().mockResolvedValue({ status: 200, headers: { 'content-type': 'image/png' }, body: new Uint8Array([137, 80, 78, 71]) })
    const wrapper = mount(CoreSplitPreview, {
      props: {
        tab: { id: 'p', kind: 'preview', title: 'a.png', resource: 'E:/p/a.png', root: 'E:/p' },
        root: 'E:/p',
        transport: { request } as never,
      },
    })
    await flushPromises()
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ kind: 'http', method: 'GET', path: expect.stringContaining('/files/read-reference') }))
    expect(wrapper.find('img').attributes('src')).toBe('blob:preview')
    wrapper.unmount()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:preview')
  })

  it('renders Markdown in the preview pane and keeps an edit entry', async () => {
    const request = vi.fn().mockResolvedValue({
      status: 200, headers: { 'content-type': 'text/markdown' },
      body: new TextEncoder().encode('# 标题\n\n正文段落'),
    })
    const add = vi.fn(() => ({}))
    const wrapper = mount(CoreSplitPreview, {
      props: {
        tab: { id: 'md', kind: 'preview', title: 'README.md', resource: 'E:/p/README.md', root: 'E:/p' },
        root: 'E:/p', pane: 'right',
        controller: { add } as never,
        transport: { request } as never,
      },
    })
    await flushPromises()
    await flushPromises()
    expect(wrapper.html()).toContain('标题')
    await wrapper.get('[aria-label="在文本编辑器中编辑"]').trigger('click')
    expect(add).toHaveBeenCalledWith('editor', 'E:/p/README.md', 'README.md', 'right', undefined, 'E:/p', undefined)
  })
})
