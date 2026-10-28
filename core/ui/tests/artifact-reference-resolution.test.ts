import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import MarkdownRenderer from '../src/components/MarkdownRenderer.vue'
import ReferenceItems from '../src/components/ReferenceItems.vue'
import { contextMenuState, closeContextMenu } from '../src/components/context-menu/context-menu'

const root = 'E:/LamTools/MyProject'
const wrong = `${root}/krea_ref01_00001_.png`
const actual = `${root}/.lam/artifacts/images/krea_ref01_00001_.png`
const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value))
const mounted: ReturnType<typeof mount>[] = []
afterEach(() => { mounted.splice(0).forEach(w => w.unmount()); closeContextMenu(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

// user:“引用的地址可能不对”+(链接、图片、成果预览均使用后台核实的成果路径)。
describe('artifact-backed file references', () => {
  it('corrects link targets before clicking and opens the resolved path', async () => {
    const request = vi.fn(async input => ({ status: 200, headers: {}, body: bytes(input.path.startsWith('/files/resolve-reference') ? { path: actual } : { status: 'opened' }) }))
    const wrapper = mount(MarkdownRenderer, { props: { content: `[图片](${wrong})` }, global: { provide: { 'lamtools-reference-transport': { request }, 'lamtools-reference-root': () => root } } })
    mounted.push(wrapper)
    await flushPromises()
    expect(wrapper.find('a').attributes('title')).toBe(actual)
    expect(wrapper.find('a').attributes('data-file-path')).toBe(actual)
    await wrapper.find('a').trigger('click')
    await flushPromises()
    const call = request.mock.calls.find(([input]) => input.path === '/files/open-reference')![0]
    expect(JSON.parse(new TextDecoder().decode(call.body)).path).toBe(actual)
  })

  it('loads local Markdown images through the authenticated reference reader', async () => {
    vi.stubGlobal('URL', URL)
    URL.createObjectURL = vi.fn(() => 'blob:reference-test')
    URL.revokeObjectURL = vi.fn()
    const request = vi.fn(async input => ({ status: 200, headers: { 'content-type': 'image/png' }, body: input.path.startsWith('/files/resolve-reference') ? bytes({ path: actual }) : new Uint8Array([137, 80, 78, 71]) }))
    const wrapper = mount(MarkdownRenderer, { props: { content: `![图片](${wrong})` }, global: { provide: { 'lamtools-reference-transport': { request }, 'lamtools-reference-root': () => root } } })
    mounted.push(wrapper)
    await flushPromises()
    expect(wrapper.find('img').attributes('src')).toBe('blob:reference-test')
    expect(request.mock.calls.some(([input]) => input.path.startsWith('/files/read-reference?') && decodeURIComponent(input.path).includes(actual))).toBe(true)
  })

  it('reads unregistered outcome images as file paths rather than fabricated artifact IDs', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:reference-test')
    URL.revokeObjectURL = vi.fn()
    const request = vi.fn(async input => ({ status: 200, headers: { 'content-type': 'image/png' }, body: input.path.startsWith('/files/resolve-reference') ? bytes({ path: actual }) : new Uint8Array([137, 80, 78, 71]) }))
    const wrapper = mount(ReferenceItems, { props: { artifacts: [{ kind: 'image', uri: wrong }], transport: { request } as never, projectId: 'p', workRoot: root } })
    mounted.push(wrapper)
    await flushPromises()
    expect(wrapper.find('button.reference-item').attributes('title')).toContain(actual)
    expect(request.mock.calls.some(([input]) => input.path.startsWith('/files/read-reference?'))).toBe(true)
    expect(request.mock.calls.some(([input]) => input.path.includes('/artifacts/'))).toBe(false)
  })

  it('copies the verified path and refuses an ambiguous reference without opening anything', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    const notice = vi.fn()
    const request = vi.fn(async (_input: { path: string }) => ({ status: 200, headers: {}, body: bytes({ path: actual }) }))
    const wrapper = mount(MarkdownRenderer, { props: { content: `[图片](${wrong})` }, global: { provide: { 'lamtools-reference-transport': { request }, 'lamtools-reference-root': () => root, 'lamtools-reference-notice': notice } } })
    mounted.push(wrapper)
    await flushPromises()
    await wrapper.find('a').trigger('contextmenu')
    const item = contextMenuState.items.find(item => 'id' in item && item.id === 'copy-path')
    if (item && 'action' in item) await item.action()
    expect(writeText).toHaveBeenCalledWith(actual)
    request.mockResolvedValue({ status: 409, headers: {}, body: bytes({ detail: '存在多个同名成果，请使用完整路径' }) })
    await wrapper.find('a').trigger('click')
    await flushPromises()
    expect(notice).toHaveBeenCalledWith('存在多个同名成果，请使用完整路径')
    expect(request.mock.calls.some(args => (args[0] as { path?: string } | undefined)?.path === '/files/open-reference')).toBe(false)
    delete (navigator as { clipboard?: unknown }).clipboard
  })

  it('also resolves paths when opening a preview without visible outcome icons', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:reference-test')
    URL.revokeObjectURL = vi.fn()
    const request = vi.fn(async input => ({ status: 200, headers: { 'content-type': 'image/png' }, body: input.path.startsWith('/files/resolve-reference') ? bytes({ path: actual }) : new Uint8Array([137, 80, 78, 71]) }))
    const wrapper = mount(ReferenceItems, { props: { previewOnly: true, artifacts: [{ kind: 'image', uri: wrong }], transport: { request } as never, workRoot: root } })
    mounted.push(wrapper)
    ;(wrapper.vm as unknown as { previewPath(path: string): void }).previewPath(wrong)
    await flushPromises()
    expect(document.querySelector('.reference-preview header span')?.getAttribute('title')).toBe(actual)
    expect(document.querySelector('.reference-preview img')?.getAttribute('src')).toBe('blob:reference-test')
  })
})
