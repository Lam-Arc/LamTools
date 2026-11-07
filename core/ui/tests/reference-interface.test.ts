import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import InlineFileComposer from '../src/components/InlineFileComposer.vue'
import ReferenceItems from '../src/components/ReferenceItems.vue'
import { renderFileReferenceNodes } from '../src/helpers/fileReferenceRendering'
import { useReferenceActions } from '../src/helpers/referenceActions'
import { contextMenuState, closeContextMenu } from '../src/components/context-menu/context-menu'

const mounted: ReturnType<typeof mount>[] = []
afterEach(() => { mounted.splice(0).forEach(w => w.unmount()); closeContextMenu(); vi.restoreAllMocks() })
describe('file references in the real interface', () => {
  it('renders the full path as an atomic filename and keeps selection and undo available', async () => {
    const wrapper = mount(InlineFileComposer, { attachTo: document.body, props: { modelValue: 'check @"C:/资料/a.png" please' } })
    mounted.push(wrapper)
    expect(wrapper.find('.composer-file-token').text()).toContain('a.png')
    expect(wrapper.find('.composer-file-token').text()).not.toContain('@')
    expect(wrapper.find('.composer-file-token .composer-file-badge').exists()).toBe(true)
    expect(wrapper.find('.composer-file-token').attributes('title')).toContain('C:/资料/a.png')
    const handle = wrapper.vm as unknown as { setSelectionRange(a: number, b: number): void; selectionStart: number; select(): void; selectionEnd: number }
    handle.setSelectionRange(0, 5)
    expect(handle.selectionStart).toBe(0)
    expect(handle.selectionEnd).toBe(5)
    handle.select()
    expect(handle.selectionEnd).toBe('check @"C:/资料/a.png" please'.length)
    await wrapper.setProps({ modelValue: 'check @"C:/资料/b.png" please' })
    expect(wrapper.find('.composer-file-token').text()).toContain('b.png')
    expect(wrapper.find('.composer-file-token').text()).not.toContain('@')
  })
  it('confirms file completion without sending the message on Enter or its keyup', async () => {
    const wrapper = mount(InlineFileComposer, { attachTo: document.body, props: { modelValue: '@a', suggestions: [{ name: 'a.png', path: 'C:/a.png' }] } })
    mounted.push(wrapper)
    ;(wrapper.vm as unknown as { setSelectionRange(a: number, b: number): void }).setSelectionRange(2, 2)
    await nextTick()
    expect(wrapper.find('.command-palette').exists()).toBe(true)
    await wrapper.find('.cm-content').trigger('keydown', { key: 'Enter' })
    await wrapper.find('.cm-content').trigger('keyup', { key: 'Enter' })
    expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toBe('@"C:/a.png" ')
    expect(wrapper.emitted('keydown')).toBeUndefined()
    expect(wrapper.emitted('keyup')).toBeUndefined()
  })
  it('puts only small icons beneath a user bubble and exposes file missing clearly', async () => {
    const request = vi.fn(async () => ({ status: 200, headers: {}, body: new TextEncoder().encode(JSON.stringify({ path: 'C:/gone.png', error_code: 'file_missing' })) }))
    const wrapper = mount(ReferenceItems, { props: { compact: true, attachments: [{ id: 'a', filename: 'gone.png', mime_type: 'image/png', preview_type: 'image', size: 1 }], transport: { request } as never } })
    mounted.push(wrapper)
    await flushPromises()
    expect(wrapper.findAll('.reference-item')).toHaveLength(1)
    expect(wrapper.find('.reference-item').attributes('title')).toContain('原文件不存在')
    expect(wrapper.text()).not.toContain('gone.png')
  })
  it('does not refetch previews on each parent render and opens restored path-only icons with the default app', async () => {
    const request = vi.fn(async (input: { path: string }) => input.path.startsWith('/files/resolve-reference')
      ? { status: 200, headers: {}, body: new TextEncoder().encode(JSON.stringify({ path: 'C:/note.txt' })) }
      : { status: 200, headers: { 'content-type': 'text/plain' }, body: new TextEncoder().encode('note') })
    const file = { id: 'a', path: 'C:/note.txt', filename: 'note.txt', mime_type: 'text/plain', preview_type: 'text', size: 1 }
    const wrapper = mount(ReferenceItems, { props: { compact: true, attachments: [file], transport: { request } as never } })
    mounted.push(wrapper)
    await flushPromises()
    const count = request.mock.calls.length
    await wrapper.setProps({ attachments: [{ ...file }] })
    await flushPromises()
    expect(request).toHaveBeenCalledTimes(count)
    await wrapper.setProps({ attachments: [{ ...file, id: 'path:C:/note.txt' }] })
    await wrapper.find('.reference-item').trigger('click')
    await flushPromises()
    // user:“没有浮窗预览这一说，砍掉”+(没有分屏时直接交给默认应用，不再读取到居中浮层)。
    const openCall = request.mock.calls.find(([input]) => input.path === '/files/open-reference')?.[0]
    expect(openCall).toBeTruthy()
    expect(JSON.parse(new TextDecoder().decode((openCall as { body: Uint8Array }).body)).path).toBe('C:/note.txt')
  })
  it('uses identical file menus in Markdown and outcomes, with a distinct link menu', async () => {
    const actions = useReferenceActions({ request: vi.fn() } as never, () => 'C:/project')
    actions.menu(new MouseEvent('contextmenu'), 'C:/project/report.md')
    expect(contextMenuState.items.map(i => 'label' in i ? i.label : '')).toEqual(['使用默认应用打开文件', '打开文件夹', '复制路径'])
    actions.menu(new MouseEvent('contextmenu'), 'example.com')
    expect(contextMenuState.items.map(i => 'label' in i ? i.label : '')).toEqual(['使用默认浏览器打开', '复制链接'])
    const host = document.createElement('div')
    host.innerHTML = '<p>@"C:/资料/a.png" and docs/report.md</p><pre><code>report.md</code></pre>'
    renderFileReferenceNodes(host, 'C:/project')
    // user:“把那个@的符号去掉 换成对应的文件图标”+(引用文本只留文件名，
    // 文件类型徽标用 data-label 由 CSS 绘制，不进入复制的文本内容)。
    expect([...host.querySelectorAll('a')].map(a => a.textContent)).toEqual(['a.png', 'report.md'])
    const badges = [...host.querySelectorAll('a .file-reference-badge')] as HTMLElement[]
    expect(badges).toHaveLength(2)
    expect(badges[0]!.dataset.label).toBe('IMG')
    expect(badges[1]!.dataset.label).toBe('MD')
    expect(host.querySelector('a')?.title).toBe('C:/资料/a.png')
    expect(host.querySelector('pre')?.textContent).toBe('report.md')
  })
  it('only auto-links drive-absolute and project-relative paths, leaving ambiguous paths as text', () => {
    // user:“只渲染两种：从盘符开始的绝对路径且有文件，从项目路径开始的相对路径且有文件”+
    // (裸文件名、Unix 绝对路径、越过项目根的相对路径都不自动变成文件链接)。
    const host = document.createElement('div')
    host.innerHTML = '<p>report.md /tmp/photo.png ../outside.md foo/../../outside.md src/inside.ts</p>'
    renderFileReferenceNodes(host, 'C:/project')
    expect([...host.querySelectorAll('a')].map(a => a.textContent)).toEqual(['inside.ts'])
    expect(host.textContent).toContain('report.md')
    expect(host.textContent).toContain('/tmp/photo.png')
    expect(host.textContent).toContain('../outside.md')
    expect(host.textContent).toContain('foo/../../outside.md')
  })
})
