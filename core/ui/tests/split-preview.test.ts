import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CoreSplitPreview from '../src/components/CoreSplitPreview.vue'
import ReferenceItems from '../src/components/ReferenceItems.vue'
import UserReferenceText from '../src/components/UserReferenceText.vue'
import { WorkspaceKey } from '../src/workspace/context'
import { createWorkspace, parseWorkspace, serializeWorkspace } from '../src/workspace'
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

  it('restores a persisted preview tab', () => {
    const model = createWorkspace([{ id: 'preview-1', kind: 'preview', title: 'a.png', resource: 'E:/p/a.png' }], 'preview-1')
    const restored = parseWorkspace(serializeWorkspace(model), createWorkspace([], ''))
    expect(restored.model.surfaces['preview-1']?.kind).toBe('preview')
    expect(restored.dropped).toBe(0)
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

  // user:“与灯箱共用同一条解析与呈现链路”+(分屏不再把整段字节搬进 blob，
  // 直接用解析层给出的本机地址；图片走 native 三态，和灯箱是同一个地址)。
  it('renders an image through the same resolved native address the lightbox uses', async () => {
    const request = vi.fn().mockResolvedValue({ status: 200, headers: {}, body: new Uint8Array() })
    const wrapper = mount(CoreSplitPreview, {
      props: {
        tab: { id: 'p', kind: 'preview', title: 'a.png', resource: 'E:/p/a.png', root: 'E:/p' },
        root: 'E:/p',
        transport: { request } as never,
      },
    })
    await flushPromises()
    const src = wrapper.find('img').attributes('src') || ''
    expect(src).toContain('/api/core/files/read-reference')
    expect(src).toContain('inline=1')
    expect(new URL(src, 'http://127.0.0.1:1').searchParams.get('path')).toBe('E:/p/a.png')
    // 图片是浏览器原生能显示的类型：解析层不读字节，也就没有第二份拷贝。
    expect(request).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('shows the same reason and exit for a file neither surface can display', async () => {
    // user:“不能看的，给的原因和动作与灯箱一致”+(原因取自同一解析层，不是分屏自己写的一句)。
    const request = vi.fn().mockResolvedValue({ status: 200, headers: {}, body: new Uint8Array() })
    const wrapper = mount(CoreSplitPreview, {
      props: {
        tab: { id: 'zip', kind: 'preview', title: 'a.zip', resource: 'E:/p/a.zip', root: 'E:/p' },
        root: 'E:/p',
        transport: { request } as never,
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('浏览器无法直接显示这种文件类型')
    expect(wrapper.text()).toContain('使用默认应用打开')
    expect(request).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('routes Markdown artifact chips to the split preview without a floating preview', async () => {
    const add = vi.fn(() => 'tab-1')
    const request = vi.fn(async () => ({ status: 200, headers: {}, body: new TextEncoder().encode(JSON.stringify({ path: 'E:/p/README.md' })) }))
    const wrapper = mount(ReferenceItems, {
      attachTo: document.body,
      props: {
        artifacts: [{ kind: 'memory', uri: 'E:/p/README.md', name: 'README.md', metadata: { path: 'E:/p/README.md' } } as never],
        transport: { request } as never,
        workRoot: 'E:/p',
      },
      global: { provide: { [WorkspaceKey as unknown as string]: { tabs: { value: [] }, state: { activePane: 'main' }, split: () => null, add } } },
    })
    await flushPromises()
    await wrapper.get('button.reference-item').trigger('click')
    await flushPromises()
    expect(add).toHaveBeenCalledWith('preview', 'E:/p/README.md', 'README.md', undefined, undefined, 'E:/p', undefined)
    expect(document.querySelector('.reference-preview')).toBeNull()
    wrapper.unmount()
  })

  it('opens a message file link in the split preview instead of the system app', async () => {
    // user:“把附件预览给做好”+(点击正文里的文件链接先走内置预览；
    // 只有预览器不可用或实验开关关闭时才交给系统默认应用)。
    const add = vi.fn(() => 'tab-1')
    const request = vi.fn(async (input: { path: string }) => input.path.startsWith('/files/resolve-reference')
      ? { status: 200, headers: {}, body: new TextEncoder().encode(JSON.stringify({ path: 'E:/p/photo.png' })) }
      : { status: 200, headers: {}, body: new Uint8Array() })
    const wrapper = mount(UserReferenceText, {
      props: { text: '@"E:/p/photo.png"' },
      global: {
        provide: {
          'lamtools-reference-transport': { request },
          [WorkspaceKey as unknown as string]: { tabs: { value: [] }, state: { activePane: 'main' }, split: () => null, add },
        },
      },
    })
    await flushPromises()
    await wrapper.get('.user-file-reference').trigger('click')
    await flushPromises()
    expect(add).toHaveBeenCalledWith('preview', 'E:/p/photo.png', 'photo.png', undefined, undefined, '', undefined)
    expect(request.mock.calls.some(([input]) => input.path === '/files/open-reference')).toBe(false)
    wrapper.unmount()
  })

  it('keeps project text in the editor but previews attachment text outside the project read-only', () => {
    // user:“把附件预览给做好”+(受管附件副本在项目目录外，编辑器会因权限拒绝；
    // 这类文本改为只读预览，项目内文本仍进编辑器)。
    const add = vi.fn((...args: unknown[]) => args)
    const controller: any = { tabs: { value: [] }, state: { activePane: 'main' }, split: () => null, add }
    openFileInSplit(controller, 'E:/project/notes.txt', { workRoot: 'E:/project' })
    expect(add).toHaveBeenLastCalledWith('editor', 'E:/project/notes.txt', 'notes.txt', undefined, undefined, 'E:/project', undefined)
    openFileInSplit(controller, 'E:/managed/attachments/notes.txt', { workRoot: 'E:/project' })
    expect(add).toHaveBeenLastCalledWith('preview', 'E:/managed/attachments/notes.txt', 'notes.txt', undefined, undefined, 'E:/project', undefined)
  })

  it('renders an outside-root text attachment as a read-only text preview', async () => {
    const request = vi.fn().mockResolvedValue({
      status: 200, headers: { 'content-type': 'text/plain' },
      body: new TextEncoder().encode('附件正文\n第二行'),
    })
    const wrapper = mount(CoreSplitPreview, {
      props: {
        tab: { id: 'txt', kind: 'preview', title: 'notes.txt', resource: 'E:/managed/notes.txt', root: 'E:/project' },
        root: 'E:/project',
        transport: { request } as never,
      },
    })
    await flushPromises()
    expect(wrapper.get('.split-preview-text').text()).toContain('附件正文')
    expect(wrapper.get('.split-preview-kind').text()).toBe('文本')
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
