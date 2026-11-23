import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import PreviewLightbox from '../src/preview/PreviewLightbox.vue'
import { filePreviewTarget, htmlPreviewTarget, previewTargetKey } from '../src/preview/target'
import {
  closePreviewLightbox,
  openInLightbox,
  previewLightboxAvailable,
  registerPreviewLightboxHost,
  resetPreviewLightbox,
  restorePreviewLightboxFocus,
  usePreviewLightbox,
} from '../src/preview/usePreviewLightbox'
import { registerPreviewBrowserHandoff } from '../src/preview/browserHandoff'
import type { LamToolsTransport } from '../src/transport'

// user:“灯箱：浮层盖在会话上，看完即关，不打断对话…ESC 关闭、Tab 焦点陷阱、打开时保存并恢复焦点”+
// (灯箱是单例；这里校验键盘与焦点契约，以及同一目标在两个宿主之间移交时不丢身份。
// 浮层 Teleport 到 body，所以断言要从 document 查，而不是组件的 wrapper)。
function fakeTransport(): LamToolsTransport {
  return {
    request: vi.fn(async () => ({ status: 200, headers: {}, body: new Uint8Array() })),
  } as unknown as LamToolsTransport
}

const wrappers: VueWrapper[] = []

function mountLightbox(transport = fakeTransport()) {
  const wrapper = mount(PreviewLightbox, { props: { transport }, attachTo: document.body })
  wrappers.push(wrapper)
  return wrapper
}

const dialogEl = () => document.querySelector('[role="dialog"]') as HTMLElement | null
const overlayEl = () => document.querySelector('[data-preview-lightbox]') as HTMLElement | null
const overlayText = () => overlayEl()?.textContent || ''

async function openAndSettle(target = filePreviewTarget('E:/p/a.png', { workRoot: 'E:/p' })) {
  openInLightbox(target)
  await flushPromises()
  await nextTick()
  await flushPromises()
}

afterEach(() => {
  for (const wrapper of wrappers.splice(0)) wrapper.unmount()
  resetPreviewLightbox()
  registerPreviewBrowserHandoff(null)
  document.body.innerHTML = ''
})

describe('preview lightbox: opening', () => {
  it('opens a dialog over the app with aria-modal', async () => {
    mountLightbox()
    await openAndSettle()
    const dialog = dialogEl()
    expect(dialog).not.toBeNull()
    expect(dialog!.getAttribute('aria-modal')).toBe('true')
    expect(overlayText()).toContain('a.png')
  })

  it('teleports the overlay out of the session container', async () => {
    // user:“灯箱必须能被遮罩正常盖住”+(会话里的滚动/transform 父级不能把浮层裁掉)。
    const host = document.createElement('div')
    host.style.transform = 'translateY(0)'
    document.body.appendChild(host)
    const wrapper = mount(PreviewLightbox, { props: { transport: fakeTransport() }, attachTo: host })
    wrappers.push(wrapper)
    await openAndSettle()
    expect(host.querySelector('[role="dialog"]')).toBeNull()
    expect(document.querySelector('[data-preview-lightbox]')).not.toBeNull()
  })

  it('reveals the target type in the header', async () => {
    mountLightbox()
    await openAndSettle(filePreviewTarget('E:/p/manual.pdf'))
    expect(overlayText()).toContain('manual.pdf')
    expect(overlayText()).toContain('PDF')
  })

  it('stays closed until a target is opened', () => {
    mountLightbox()
    expect(overlayEl()).toBeNull()
  })
})

describe('preview lightbox: keyboard', () => {
  it('closes on Escape', async () => {
    mountLightbox()
    await openAndSettle()
    const { open } = usePreviewLightbox()
    expect(open.value).toBe(true)
    overlayEl()!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    await flushPromises()
    expect(open.value).toBe(false)
  })

  it('keeps Tab inside the dialog', async () => {
    // user:“Tab 焦点陷阱”+(jsdom 量不到布局尺寸，trap 会兜底拦下默认行为；
    // 断言说明 Tab 不会把焦点交给遮罩后边的页面)。
    mountLightbox()
    await openAndSettle()
    const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    dialogEl()!.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
  })

  it('closes when the backdrop itself is clicked, not the content', async () => {
    // user:“点击遮罩可关”+(点内容区不算)。
    mountLightbox()
    await openAndSettle()
    const { open } = usePreviewLightbox()
    dialogEl()!.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    await flushPromises()
    expect(open.value).toBe(true)
    overlayEl()!.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    await flushPromises()
    expect(open.value).toBe(false)
  })
})

describe('preview lightbox: focus', () => {
  it('returns focus to whatever opened it', async () => {
    // user:“打开时保存并恢复焦点；关闭后焦点归位”。
    const opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    expect(document.activeElement).toBe(opener)

    mountLightbox()
    await openAndSettle()

    closePreviewLightbox()
    await flushPromises()
    restorePreviewLightboxFocus()
    expect(document.activeElement).toBe(opener)
  })

  it('does not hand focus to a detached opener', async () => {
    const opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    mountLightbox()
    await openAndSettle()
    opener.remove()
    closePreviewLightbox()
    restorePreviewLightboxFocus()
    expect(document.activeElement).not.toBe(opener)
  })
})

describe('preview lightbox: single target', () => {
  it('keeps the same identity when the same file is reopened', async () => {
    // user:“两种形态之间移交同一目标不丢失内容”+(身份只由目标内容决定)。
    mountLightbox()
    await openAndSettle(filePreviewTarget('E:\\p\\A.PNG', { workRoot: 'E:/p' }))
    const first = usePreviewLightbox().targetKey.value
    closePreviewLightbox()
    await openAndSettle(filePreviewTarget('e:/p/a.png', { workRoot: 'e:/p/' }))
    expect(usePreviewLightbox().targetKey.value).toBe(first)
  })

  it('switches target in place instead of stacking overlays', async () => {
    mountLightbox()
    await openAndSettle(filePreviewTarget('E:/p/a.png'))
    await openAndSettle(filePreviewTarget('E:/p/b.mp4'))
    expect(document.querySelectorAll('[data-preview-lightbox]')).toHaveLength(1)
    expect(overlayText()).toContain('b.mp4')
  })

  it('renders converted html targets inside the surface', async () => {
    mountLightbox()
    await openAndSettle(htmlPreviewTarget('<p>生成内容</p>', '生成内容'))
    const frame = document.querySelector('iframe') as HTMLIFrameElement | null
    expect(frame).not.toBeNull()
    expect(frame!.getAttribute('srcdoc')).toContain('生成内容')
  })
})

describe('preview lightbox: exits', () => {
  it('offers the default app for unsupported files', async () => {
    mountLightbox()
    await openAndSettle(filePreviewTarget('E:/p/report.docx', { workRoot: 'E:/p' }))
    expect(overlayText()).toContain('默认应用打开')
  })

  it('hides the browser exit until a browser module registers', async () => {
    // user:“现在没有浏览器模块，就留一个明确的注入点…不要在没有调用方时假装能用”。
    mountLightbox()
    await openAndSettle({ kind: 'url', url: 'https://example.com/a' })
    expect(overlayText()).toContain('浏览器')
    expect(overlayText()).not.toContain('用浏览器打开')
  })

  it('shows the browser exit once a hand-off is registered', async () => {
    const handoff = vi.fn()
    registerPreviewBrowserHandoff(handoff)
    mountLightbox()
    await openAndSettle({ kind: 'url', url: 'https://example.com/a' })
    const button = [...document.querySelectorAll('button')].find(item => item.textContent?.includes('用浏览器打开'))
    expect(button).toBeTruthy()
    button!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(handoff).toHaveBeenCalledWith('https://example.com/a')
  })
})

describe('preview lightbox: host registration', () => {
  it('reports availability only while a host is mounted', () => {
    // user:“至少接一个真实入口证明可用”+(没有宿主时点击要交回原通道，不能静默吞掉)。
    expect(previewLightboxAvailable()).toBe(false)
    const unregister = registerPreviewLightboxHost()
    expect(previewLightboxAvailable()).toBe(true)
    unregister()
    expect(previewLightboxAvailable()).toBe(false)
  })

  it('keeps availability stable across nested registrations', () => {
    const first = registerPreviewLightboxHost()
    const second = registerPreviewLightboxHost()
    first()
    expect(previewLightboxAvailable()).toBe(true)
    second()
    expect(previewLightboxAvailable()).toBe(false)
  })
})

describe('preview target identity', () => {
  it('keys html targets by title and url targets by address', () => {
    expect(previewTargetKey(htmlPreviewTarget('<p>x</p>', '标题'))).toBe('html\0标题')
    expect(previewTargetKey({ kind: 'url', url: 'http://127.0.0.1:1/a.pdf' })).toBe('url\0http://127.0.0.1:1/a.pdf')
    expect(previewTargetKey(null)).toBe('')
  })
})
