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
    expect(wrapper.find('.composer-file-token').text()).toContain('@a.png')
    expect(wrapper.find('.composer-file-token').attributes('title')).toContain('C:/资料/a.png')
    const handle = wrapper.vm as unknown as { setSelectionRange(a: number, b: number): void; selectionStart: number; select(): void; selectionEnd: number }
    handle.setSelectionRange(0, 5)
    expect(handle.selectionStart).toBe(0)
    expect(handle.selectionEnd).toBe(5)
    handle.select()
    expect(handle.selectionEnd).toBe('check @"C:/资料/a.png" please'.length)
    await wrapper.setProps({ modelValue: 'check @"C:/资料/b.png" please' })
    expect(wrapper.find('.composer-file-token').text()).toContain('@b.png')
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
  it('does not refetch previews on each parent render and can read restored path-only icons', async () => {
    const request = vi.fn(async () => ({ status: 200, headers: {}, body: new TextEncoder().encode('{}') }))
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
    expect(request).toHaveBeenLastCalledWith(expect.objectContaining({ path: '/files/read-reference?path=C%3A%2Fnote.txt' }))
  })
  it('uses identical file menus in Markdown and outcomes, with a distinct link menu', async () => {
    const actions = useReferenceActions({ request: vi.fn() } as never, () => 'C:/project')
    actions.menu(new MouseEvent('contextmenu'), 'C:/project/report.md')
    expect(contextMenuState.items.map(i => 'label' in i ? i.label : '')).toEqual(['使用默认应用打开文件', '打开文件夹', '复制路径'])
    actions.menu(new MouseEvent('contextmenu'), 'example.com')
    expect(contextMenuState.items.map(i => 'label' in i ? i.label : '')).toEqual(['使用默认浏览器打开', '复制链接'])
    const host = document.createElement('div')
    host.innerHTML = '<p>@"C:/资料/a.png" and report.md</p><pre><code>report.md</code></pre>'
    renderFileReferenceNodes(host, 'C:/project')
    expect([...host.querySelectorAll('a')].map(a => a.textContent)).toEqual(['@a.png', '@report.md'])
    expect(host.querySelector('a')?.title).toBe('C:/资料/a.png')
    expect(host.querySelector('pre')?.textContent).toBe('report.md')
  })
})
