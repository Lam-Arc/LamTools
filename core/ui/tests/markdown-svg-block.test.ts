import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import MarkdownRenderer from '@/components/MarkdownRenderer.vue'

/**
 * user:“1:矢量渲染失败”+(svg 围栏在普通聊天里也要渲染成图形：它以前被 autoPlotMath
 * 这个 Study 开关挡住，聊天里退化成一段代码。)
 */

const SVG = [
  '```svg',
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 60">',
  '  <rect x="4" y="4" width="112" height="52" rx="8" fill="none" stroke="#888"/>',
  '</svg>',
  '```',
].join('\n')

describe('MarkdownRenderer svg fence', () => {
  it('renders an inline svg figure without the study switch', () => {
    const wrapper = mount(MarkdownRenderer, {
      props: { content: SVG },
      global: { stubs: { teleport: true } },
    })

    const figure = wrapper.find('figure.study-inline-svg')
    expect(figure.exists()).toBe(true)
    expect(figure.attributes('class')).toContain('md-inline-svg')
    expect(figure.find('svg').exists()).toBe(true)
    // 不再退化成一段代码
    expect(wrapper.find('.code-block pre').exists()).toBe(false)
  })

  it('keeps a malformed svg out of the document', () => {
    const wrapper = mount(MarkdownRenderer, {
      props: { content: '```svg\n<svg><rect></svg>\n```' },
      global: { stubs: { teleport: true } },
    })
    expect(wrapper.find('figure.study-inline-svg').exists()).toBe(false)
  })

  it('honours the half flag for side-by-side svg', () => {
    const content = SVG.replace('```svg', '```svg half')
    const wrapper = mount(MarkdownRenderer, {
      props: { content },
      global: { stubs: { teleport: true } },
    })
    const figure = wrapper.find('figure.md-inline-svg')
    expect(figure.exists()).toBe(true)
    expect(figure.classes()).toContain('md-inline-svg--half')
  })

  /**
   * user:“矢量乌漆麻黑一大坨，什么什么都看不清”+(模型把样式写在 style 属性里，
   * 属性被清洗掉后形状退回默认黑色填充。样式必须先转成表现属性。)
   */
  it('keeps inline style declarations as paint attributes', () => {
    const content = [
      '```svg',
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 60">',
      '  <rect x="4" y="4" width="112" height="52" rx="8" style="fill:none;stroke:#888;stroke-width:2"/>',
      '  <text x="20" y="34" style="fill:#0f0;font-size:12">A</text>',
      '</svg>',
      '```',
    ].join('\n')

    const wrapper = mount(MarkdownRenderer, {
      props: { content },
      global: { stubs: { teleport: true } },
    })

    const rect = wrapper.find('figure.md-inline-svg rect')
    expect(rect.exists()).toBe(true)
    expect(rect.attributes('fill')).toBe('none')
    expect(rect.attributes('stroke')).toBe('#888')
    expect(rect.attributes('stroke-width')).toBe('2')
    // style 属性本身不再留在文档里
    expect(rect.attributes('style')).toBeUndefined()

    const text = wrapper.find('figure.md-inline-svg text')
    expect(text.attributes('font-size')).toBe('12')
    expect(text.attributes('fill')).toBe('#0f0')
  })
})
