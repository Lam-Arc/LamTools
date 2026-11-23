import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import PreviewSurface from '../src/preview/PreviewSurface.vue'
import type { PreviewDocument } from '../src/preview/resolve'

// user:“除了Office类，别的都把它修好”+
// (表面按类型分派：图片/音视频/PDF/文本各自有原生查看器，只有「转换出来的 HTML」还用 iframe；
//  三态判定仍然只有一份，unsupported 仍是说明 + 出口)。
const URL_BASE = 'http://127.0.0.1:52341/api/core/files/read-reference?path=a&inline=1'
const image: PreviewDocument = { mode: 'native', url: URL_BASE, mime: 'image/png', title: 'a.png' }
const video: PreviewDocument = { mode: 'native', url: URL_BASE, mime: 'video/mp4', title: 'a.mp4' }
const audio: PreviewDocument = { mode: 'native', url: URL_BASE, mime: 'audio/mpeg', title: 'a.mp3' }
const pdf: PreviewDocument = { mode: 'native', url: URL_BASE, mime: 'application/pdf', title: 'a.pdf' }
const text: PreviewDocument = { mode: 'native', url: URL_BASE, mime: 'text/plain; charset=utf-8', title: 'a.txt' }
const rendered: PreviewDocument = { mode: 'rendered', html: '<p>正文</p>', title: 'a.md' }
const unsupported: PreviewDocument = { mode: 'unsupported', reason: '浏览器不能直接显示这种文件类型；可以用默认应用打开', title: 'a.docx' }

function mountSurface(document: PreviewDocument | null, props: Record<string, unknown> = {}) {
  return mount(PreviewSurface, { props: { document, loadTimeoutMs: 0, ...props } })
}

afterEach(() => { vi.useRealTimers() })

describe('preview surface: images', () => {
  it('uses the native viewer, never a browser image document', () => {
    const wrapper = mountSurface(image)
    expect(wrapper.find('[data-preview-image]').exists()).toBe(true)
    expect(wrapper.find('iframe').exists()).toBe(false)
  })

  it('forwards the annotation mode to the viewer', () => {
    const wrapper = mountSurface(image, { annotating: true })
    expect(wrapper.find('[data-preview-annotate-tools]').exists()).toBe(true)
  })
})

describe('preview surface: media', () => {
  it('plays video through a native element', () => {
    const wrapper = mountSurface(video)
    const element = wrapper.get('[data-preview-media] video')
    expect(element.attributes('src')).toContain('/files/read-reference')
    expect(element.attributes('controls')).toBeDefined()
    expect(wrapper.find('iframe').exists()).toBe(false)
  })

  it('plays audio through a native element', () => {
    const wrapper = mountSurface(audio)
    expect(wrapper.get('[data-preview-media] audio').attributes('src')).toContain('/files/read-reference')
    expect(wrapper.find('iframe').exists()).toBe(false)
  })
})

describe('preview surface: pdf', () => {
  it('renders through pdfjs, not the sandboxed built-in viewer', () => {
    const wrapper = mountSurface(pdf, { loadBytes: async () => new Uint8Array() })
    expect(wrapper.find('[data-preview-pdf]').exists()).toBe(true)
    expect(wrapper.find('iframe').exists()).toBe(false)
  })
})

describe('preview surface: text', () => {
  it('decodes text itself so csv/json do not depend on the iframe', async () => {
    const wrapper = mountSurface(text, {
      loadBytes: async () => new TextEncoder().encode('姓名,角色\n阿图,owner'),
    })
    await flushPromises()
    await flushPromises()
    expect(wrapper.get('.preview-text__body').text()).toContain('阿图,owner')
    expect(wrapper.find('iframe').exists()).toBe(false)
  })
})

describe('preview surface: rendered html', () => {
  it('uses srcdoc with a sandbox and no url', () => {
    const wrapper = mountSurface(rendered)
    const frame = wrapper.get('iframe')
    expect(frame.attributes('srcdoc')).toBe('<p>正文</p>')
    expect(frame.attributes('src')).toBeUndefined()
    expect(frame.attributes('sandbox')).toBe('')
  })
})

describe('preview surface: states', () => {
  it('explains unsupported types and offers the default app', async () => {
    const wrapper = mountSurface(unsupported, { canOpenWithDefaultApp: true })
    expect(wrapper.get('[role="alert"]').text()).toContain('默认应用打开')
    expect(wrapper.find('iframe').exists()).toBe(false)
    const button = wrapper.findAll('button').find(item => item.text().includes('用默认应用打开'))!
    await button.trigger('click')
    expect(wrapper.emitted('open-default')).toHaveLength(1)
  })

  it('offers the browser hand-off only when the caller allows it', async () => {
    const without = mountSurface(unsupported, { canOpenWithDefaultApp: true })
    expect(without.text()).not.toContain('用浏览器打开')
    const withHandoff = mountSurface(unsupported, { canOpenWithDefaultApp: true, canHandOff: true })
    const button = withHandoff.findAll('button').find(item => item.text().includes('用浏览器打开'))!
    await button.trigger('click')
    expect(withHandoff.emitted('open-browser')).toHaveLength(1)
  })

  it('shows an empty state before any target is chosen', () => {
    const wrapper = mountSurface(null)
    expect(wrapper.text()).toContain('选择一个文件')
    expect(wrapper.find('iframe').exists()).toBe(false)
  })

  it('drops interaction for embedded cards', () => {
    const wrapper = mountSurface(rendered, { interactive: false })
    expect(wrapper.get('iframe').attributes('sandbox')).toBe('')
    expect(wrapper.classes()).toContain('preview-surface--inert')
  })
})
