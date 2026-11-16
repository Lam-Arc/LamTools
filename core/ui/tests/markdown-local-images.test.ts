import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import MarkdownRenderer from '../src/components/MarkdownRenderer.vue'

vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn().mockResolvedValue({ svg: '<svg></svg>' }),
  },
}))

vi.mock('@/plugins/assets', () => ({
  inlineVisualizationRuntimeUrl: () => 'about:blank',
}))

const TRANSPARENT = 'data:image/gif;base64,'

/**
 * user:“宫格式和 HTML img 就媒体全部加载失败”+(回复里直接写的 <img src="E:/…"> 以前不走
 * 取图通道，浏览器按相对地址去 404，宫格里的图全破。现在裸 HTML 的本地图也要被收编成
 * 同一个待加载标记，交给按字节取图的通道。)
 */
describe('MarkdownRenderer raw local images', () => {
  it('adopts a raw html img with an absolute local path', async () => {
    const wrapper = mount(MarkdownRenderer, {
      props: { content: '<img src="E:/pics/a.png" alt="实物图">' },
    })
    await wrapper.vm.$nextTick()

    const image = wrapper.find('img')
    expect(image.exists()).toBe(true)
    expect(image.attributes('data-local-image-path')).toBe('E:/pics/a.png')
    // 原地址被换成透明占位，避免浏览器先按相对地址 404 一次
    expect(image.attributes('src') || '').toContain(TRANSPARENT)
  })

  // 远程图在会话里本来就被挡住（避免被动加载外部资源），这条行为保持原样。
  it('keeps blocking remote images outside Study', async () => {
    const wrapper = mount(MarkdownRenderer, {
      props: { content: '<img src="https://example.com/a.png">' },
    })
    await wrapper.vm.$nextTick()

    const image = wrapper.find('img')
    expect(image.attributes('data-local-image-path')).toBeUndefined()
    expect(image.attributes('src')).toBeUndefined()
    expect(image.attributes('data-image-blocked')).toBe('remote-disabled')
  })

  it('keeps markdown image syntax on the same channel', async () => {
    const wrapper = mount(MarkdownRenderer, {
      props: { content: '![](E:/pics/b.png)' },
    })
    await wrapper.vm.$nextTick()

    const image = wrapper.find('img')
    expect(image.attributes('data-local-image-path')).toBe('E:/pics/b.png')
  })
})
