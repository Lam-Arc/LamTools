// @vitest-environment jsdom
/**
 * user:“分屏预览的能力应该要比灯箱更多，即灯箱有的，分屏也该有，多什么你自己设计，跟随第一性即可”+
 * (验收：① 灯箱那套图片查看器原样搬进分屏——缩放/拖动/双击/标注都在；
 *  ② 灯箱有的动作分屏一个不少：标注、复制、引用、在灯箱打开；
 *  ③ 分屏多出来的三件事：文档大纲可跳转、文档内查找带命中计数、选中文字能引用给 Agent)。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { strToU8, zipSync } from 'fflate'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { nextTick } from 'vue'
import CoreSplitPreview from '../src/components/CoreSplitPreview.vue'
import { PREVIEW_COMPOSER_KEY } from '../src/preview/composerBridge'
import type { SplitTab } from '../src/workspace/types'

vi.mock('../src/preview/imageClipboard', () => ({ copyImageBlob: vi.fn(async () => undefined) }))
vi.mock('../src/preview/usePreviewLightbox', async () => {
  const actual = await vi.importActual<typeof import('../src/preview/usePreviewLightbox')>('../src/preview/usePreviewLightbox')
  return { ...actual, previewLightboxAvailable: () => true, openInLightbox: vi.fn() }
})
import { copyImageBlob } from '../src/preview/imageClipboard'
import { openInLightbox } from '../src/preview/usePreviewLightbox'

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3, 4])

function stubTransport(body: Uint8Array = PNG) {
  return { request: vi.fn(async () => ({ status: 200, headers: {}, body })) } as never
}

const tab = (resource: string): SplitTab => ({ id: 'tab-1', kind: 'preview', title: resource, resource })

interface MountOptions {
  body?: Uint8Array
  attach?: ReturnType<typeof vi.fn>
  insert?: ReturnType<typeof vi.fn>
  stubViewer?: { hasAnnotations: boolean }
}

const wrappers: VueWrapper[] = []

function mountPreview(resource: string, options: MountOptions = {}) {
  const attach = options.attach ?? vi.fn(async () => undefined)
  const insert = options.insert ?? vi.fn()
  const viewer = defineComponent({
    name: 'PreviewImageViewerStub',
    setup(_props, { expose }) {
      expose({
        hasAnnotations: () => Boolean(options.stubViewer?.hasAnnotations),
        exportBlob: async () => new Blob([PNG], { type: 'image/png' }),
      })
      return () => h('div', { 'data-preview-image': 'stub' })
    },
  })
  const wrapper = mount(CoreSplitPreview, {
    props: { tab: tab(resource), root: 'E:/p', transport: stubTransport(options.body ?? PNG) },
    attachTo: document.body,
    global: {
      provide: { [PREVIEW_COMPOSER_KEY as unknown as string]: { attach, canAttach: () => true, insert } },
      stubs: { PreviewImageViewer: viewer },
    },
  })
  wrappers.push(wrapper)
  return { wrapper, attach, insert }
}

const button = (label: string) => document.querySelector(`[aria-label="${label}"]`) as HTMLElement | null

afterEach(() => {
  for (const wrapper of wrappers.splice(0)) wrapper.unmount()
  vi.mocked(copyImageBlob).mockClear()
  vi.mocked(openInLightbox).mockClear()
  document.body.innerHTML = ''
})

describe('split preview reaches lightbox parity', () => {
  it('图片用同一个共用查看器呈现，缩放/拖动/标注都在里面', async () => {
    mountPreview('E:/p/a.png')
    await flushPromises()
    await nextTick()
    expect(document.querySelector('.preview-image')?.getAttribute('data-preview-image')).not.toBeNull()
    // 图片的缩放由查看器自己的工具坞负责；工具条不再重复一套。
    expect(button('放大预览')).toBeNull()
    expect(button('标注')).not.toBeNull()
  })

  it('复制：图片走剪贴板，标注后复制的是合成图', async () => {
    const { wrapper } = mountPreview('E:/p/a.png')
    await flushPromises()
    await button('复制')!.click()
    await flushPromises()
    expect(copyImageBlob).toHaveBeenCalledTimes(1)
    expect((copyImageBlob as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][0]).toBeInstanceOf(Blob)
    wrapper.unmount()
  })

  it('引用：未标注交路径，标注后交合成图文件', async () => {
    const plain = mountPreview('E:/p/a.png')
    await flushPromises()
    await button('加入输入框')!.click()
    await flushPromises()
    expect(plain.attach).toHaveBeenCalledWith([{ path: 'E:/p/a.png', name: 'a.png' }])
    plain.wrapper.unmount()

    const annotated = mountPreview('E:/p/a.png', { stubViewer: { hasAnnotations: true } })
    await flushPromises()
    await button('加入输入框')!.click()
    await flushPromises()
    const items = annotated.attach.mock.calls[0][0] as File[]
    expect(items[0]).toBeInstanceOf(File)
    expect(items[0].name).toBe('a-标注.png')
    expect(items[0].type).toBe('image/png')
  })

  it('在灯箱中打开：媒体文件可以丢回灯箱', async () => {
    mountPreview('E:/p/a.png')
    await flushPromises()
    await button('在灯箱中打开')!.click()
    expect(openInLightbox).toHaveBeenCalledTimes(1)
  })
})

describe('split preview does things the lightbox cannot', () => {
  it('文档内查找：命中计数与逐个跳转', async () => {
    const body = new TextEncoder().encode('alpha beta alpha gamma alpha')
    const { wrapper } = mountPreview('E:/p/notes.txt', { body })
    await flushPromises()
    await nextTick()
    await button('在文档中查找')!.click()
    await nextTick()
    const input = document.querySelector('[data-split-find] input') as HTMLInputElement
    expect(input).not.toBeNull()
    input.value = 'alpha'
    input.dispatchEvent(new Event('input'))
    await nextTick()
    await flushPromises()
    const marks = document.querySelectorAll('mark.split-find-hit')
    expect(marks.length).toBe(3)
    expect((document.querySelector('.split-preview-find-count')?.textContent || '')).toContain('1 / 3')
    await wrapper.vm.$nextTick()
  })

  it('文档大纲：从标题跳章节', async () => {
    const body = new TextEncoder().encode('# 第一章\n\n正文\n\n## 小节\n\n更多正文')
    mountPreview('E:/p/readme.md', { body })
    await flushPromises()
    await nextTick()
    // Markdown 正文由 MarkdownRenderer 异步落地，大纲跟着出现。
    await expect.poll(() => document.querySelectorAll('.split-preview-outline-item').length, { timeout: 3000 }).toBe(2)
    const outline = document.querySelector('[data-split-outline]')
    expect(outline).not.toBeNull()
    const labels = [...document.querySelectorAll('.split-preview-outline-item')].map(item => item.textContent?.trim())
    expect(labels).toEqual(['第一章', '小节'])
    // user:“目录这种东西还是设成可折叠吧”+(收起后不占地方，状态记在本机)。
    const toggle = document.querySelector('[data-split-outline-toggle]') as HTMLElement
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    toggle.click()
    await nextTick()
    expect(document.querySelector('[data-split-outline]')).toBeNull()
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(localStorage.getItem('lamtools:split-preview-outline-open')).toBe('off')
    toggle.click()
    await nextTick()
    expect(document.querySelector('[data-split-outline]')).not.toBeNull()
    expect(localStorage.getItem('lamtools:split-preview-outline-open')).toBe('on')
    localStorage.removeItem('lamtools:split-preview-outline-open')
  })

  it('选中一段原文就能引用给 Agent', async () => {
    const body = new TextEncoder().encode('要引用的这一段原文')
    const { insert } = mountPreview('E:/p/notes.txt', { body })
    await flushPromises()
    await nextTick()
    const text = document.querySelector('.split-preview-text')?.firstChild
    expect(text).not.toBeNull()
    const range = document.createRange()
    range.selectNodeContents(text as Text)
    const selection = window.getSelection()!
    selection.removeAllRanges()
    selection.addRange(range)
    document.querySelector('.split-preview-main')!.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    await nextTick()
    const chip = document.querySelector('[data-split-quote]') as HTMLElement | null
    expect(chip).not.toBeNull()
    chip!.click()
    await nextTick()
    expect(insert).toHaveBeenCalledWith('要引用的这一段原文')
  })
})
describe('PowerPoint 按真实版式预览', () => {
  /** 一份最小演示文稿：一个文本形状，位置与幻灯片尺寸都是确定的。 */
  function minimalPptx(): Uint8Array {
    const ns = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
    return zipSync({
      'ppt/presentation.xml': strToU8(`<p:presentation ${ns}><p:sldSz cx="9144000" cy="6858000"/></p:presentation>`),
      'ppt/slides/slide1.xml': strToU8(`<p:sld ${ns}><p:cSld><p:spTree>`
        + '<p:sp><p:nvSpPr><p:cNvPr id="2" name="标题"/><p:cNvSpPr/></p:nvSpPr>'
        + '<p:spPr><a:xfrm><a:off x="914400" y="685800"/><a:ext cx="4572000" cy="915600"/></a:xfrm>'
        + '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="2B3A67"/></a:solidFill></p:spPr>'
        + '<p:txBody><a:bodyPr anchor="ctr"/><a:lstStyle/><a:p><a:r><a:rPr sz="3200"/><a:t>版式文本</a:t></a:r></a:p></p:txBody></p:sp>'
        + '</p:spTree></p:cSld></p:sld>'),
    })
  }

  it('演示文稿按文件里的版式画出来，不依赖本机 Office', async () => {
    const request = vi.fn(async () => ({ status: 200, headers: {}, body: minimalPptx() }))
    const wrapper = mount(CoreSplitPreview, {
      props: { tab: tab('E:/p/方案.pptx'), root: 'E:/p', transport: { request } as never },
      attachTo: document.body,
      global: { provide: { [PREVIEW_COMPOSER_KEY as unknown as string]: { attach: vi.fn(), canAttach: () => true, insert: vi.fn() } } },
    })
    wrappers.push(wrapper)
    await flushPromises()
    await nextTick()
    await flushPromises()
    expect(request.mock.calls.every(([input]) => input.path.startsWith('/files/read-reference'))).toBe(true)
    const slide = document.querySelector('[data-split-slides] .pptx-slide')
    expect(slide).not.toBeNull()
    expect(slide!.textContent || '').toContain('版式文本')
    const shape = slide!.querySelector('.pptx-shape') as HTMLElement
    expect(shape).not.toBeNull()
    // 位置按幻灯片尺寸换算成百分比：10% / 10%，宽 50%。
    expect(shape.style.left).toBe('10%')
    expect(shape.style.top).toBe('10%')
    expect(shape.style.width).toBe('50%')
  })
})
