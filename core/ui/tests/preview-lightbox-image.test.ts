import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import PreviewLightbox, { type PreviewResolver } from '../src/preview/PreviewLightbox.vue'
import { PREVIEW_COMPOSER_KEY } from '../src/preview/composerBridge'
import { openInLightbox, resetPreviewLightbox, usePreviewLightbox } from '../src/preview/usePreviewLightbox'
import { filePreviewTarget } from '../src/preview/target'
import type { LamToolsTransport } from '../src/transport'

// user:“提供复制/外部打开键…『引用』，直接将已标注/未标注则为原图直接加入输入框”+
// (灯箱只负责取出这张图：未标注取原始字节，标注后请求查看器合成 PNG；
//  「引用」把文件交给宿主提供的通道并关闭灯箱。截图/标注的像素效果由展厅交互测试负责。)
vi.mock('../src/preview/imageClipboard', () => ({ copyImageBlob: vi.fn(async () => undefined) }))
import { copyImageBlob } from '../src/preview/imageClipboard'

const PNG_BYTES = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])

function fakeTransport(): LamToolsTransport {
  return {
    request: vi.fn(async () => ({ status: 200, headers: {}, body: PNG_BYTES })),
  } as unknown as LamToolsTransport
}

/** 图片解析：直接给一张本机地址的图，不碰真实文件。 */
const resolveImage: PreviewResolver = async () => ({
  mode: 'native',
  url: 'http://127.0.0.1:9/read-reference?path=a.png',
  mime: 'image/png',
  title: 'a.png',
})

const wrappers: VueWrapper[] = []

function mountLightbox(options: { transport?: LamToolsTransport; provide?: boolean } = {}) {
  const attach = vi.fn(async () => undefined)
  const provide = options.provide === false
    ? {}
    : { [PREVIEW_COMPOSER_KEY as unknown as string]: { attach, canAttach: () => true } }
  const wrapper = mount(PreviewLightbox, {
    props: { transport: options.transport ?? fakeTransport(), resolver: resolveImage },
    attachTo: document.body,
    global: { provide },
  })
  wrappers.push(wrapper)
  return { wrapper, attach }
}

const overlayEl = () => document.querySelector('[data-preview-lightbox]') as HTMLElement | null
const overlayText = () => overlayEl()?.textContent || ''
const click = (selector: string) => (document.querySelector(selector) as HTMLElement | null)?.click()

async function openAndSettle(path = 'E:/p/a.png') {
  openInLightbox(filePreviewTarget(path, { workRoot: 'E:/p' }))
  await flushPromises()
  await nextTick()
  await flushPromises()
}

afterEach(() => {
  for (const wrapper of wrappers.splice(0)) wrapper.unmount()
  resetPreviewLightbox()
  vi.mocked(copyImageBlob).mockClear()
  document.body.innerHTML = ''
})

describe('lightbox image presentation', () => {
  it('图片用原生查看器呈现，不再是浏览器图片文档', async () => {
    mountLightbox()
    await openAndSettle()
    expect(document.querySelector('[data-preview-image]')).not.toBeNull()
    expect(document.querySelector('iframe')).toBeNull()
    expect(overlayText()).toContain('图片')
    expect(document.querySelector('[data-preview-zoom-percent]')?.textContent).toContain('%')
  })

  it('复制取原图字节，并保持文件格式', async () => {
    const transport = fakeTransport()
    mountLightbox({ transport })
    await openAndSettle()
    click('[data-preview-copy]')
    await flushPromises()
    expect(copyImageBlob).toHaveBeenCalledTimes(1)
    const blob = vi.mocked(copyImageBlob).mock.calls[0][0] as Blob
    expect(blob.type).toBe('image/png')
    expect(await blob.arrayBuffer()).toEqual(PNG_BYTES.buffer)
    // 打开时还会去列同目录的邻居，这里只数「读这张图」的那一次。
    const reads = vi.mocked(transport.request).mock.calls.filter(([request]) => (
      String((request as { path?: string })?.path || '').includes('/files/read-reference')
    ))
    expect(reads).toHaveLength(1)
    expect(overlayText()).toContain('已复制原图')
  })

  it('引用把图片交给输入框通道，并关闭灯箱', async () => {
    const { attach } = mountLightbox()
    await openAndSettle()
    click('[data-preview-reference]')
    await flushPromises()
    expect(attach).toHaveBeenCalledTimes(1)
    // user:“现在本身就是存路径，可以直接把路径上传上去，走路径那条链路”+
    // (未标注的原图只交绝对路径，输入框按路径登记，不读字节也不复制文件)。
    const items = attach.mock.calls[0][0] as unknown as { path: string; name: string }[]
    expect(items).toEqual([{ path: 'E:/p/a.png', name: 'a.png' }])
    expect(usePreviewLightbox().open.value).toBe(false)
  })

  it('没有输入框通道时不渲染引用按钮', async () => {
    mountLightbox({ provide: false })
    await openAndSettle()
    expect(document.querySelector('[data-preview-reference]')).toBeNull()
    expect(document.querySelector('[data-preview-copy]')).not.toBeNull()
    expect(document.querySelector('[data-preview-open]')).not.toBeNull()
  })

  it('标注开关打开共用工具条（与 Ping 同一份）', async () => {
    mountLightbox()
    await openAndSettle()
    click('[data-preview-annotate]')
    await nextTick()
    const tools = document.querySelector('[data-preview-annotate-tools]')
    expect(tools).not.toBeNull()
    const toolbar = tools!.querySelector('[role="toolbar"]')
    expect(toolbar).not.toBeNull()
    expect(toolbar!.getAttribute('aria-label')).toBe('标注工具')
    const labels = Array.from(toolbar!.querySelectorAll('button')).map(button => button.getAttribute('aria-label'))
    expect(labels).toEqual(expect.arrayContaining(['箭头', '问号', '叹号', '文字块', '画笔', '颜色', '撤销', '重做', '清空', '退出标注']))
  })
})
