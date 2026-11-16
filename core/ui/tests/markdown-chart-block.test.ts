import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { flushPromises } from '@vue/test-utils'

import MarkdownRenderer from '@/components/MarkdownRenderer.vue'

/**
 * user:“图表落地，柱状，折线，饼图都支持”+(```chart 围栏要真的走到渲染器：
 * 先出占位，静态渲染后挂上 CoreChart；坏规格退化成一句错误提示而不是空框。)
 */

const BAR = [
  '```chart',
  '{"type":"bar","title":"会话量","categories":["-2w","-1w"],"series":[{"name":"会话量","data":[12,18]}]}',
  '```',
].join('\n')

const BROKEN = [
  '```chart',
  '{"type":"bar","series":[{"data":[1]}]}',
  '```',
].join('\n')

async function settle(): Promise<void> {
  await flushPromises()
  await new Promise(resolve => setTimeout(resolve, 0))
  await flushPromises()
}

describe('MarkdownRenderer chart fence', () => {
  it('mounts the chart component for a chart fence', async () => {
    const wrapper = mount(MarkdownRenderer, {
      props: { content: BAR, interactive: true },
      global: { stubs: { teleport: true } },
    })
    await settle()

    expect(wrapper.find('[data-chart-block]').exists()).toBe(true)
    const chart = wrapper.find('.core-chart')
    expect(chart.exists()).toBe(true)
    expect(chart.attributes('data-chart-type')).toBe('bar')
    expect(chart.text()).toContain('会话量')
    // 源码仍可复制：JSON 原样留在隐藏节点里
    expect(wrapper.find('.code-source').text()).toContain('"type":"bar"')
  })

  it('shows an actionable error instead of an empty frame', async () => {
    const wrapper = mount(MarkdownRenderer, {
      props: { content: BROKEN, interactive: true },
      global: { stubs: { teleport: true } },
    })
    await settle()

    const chart = wrapper.find('.core-chart')
    expect(chart.exists()).toBe(true)
    expect(chart.attributes('data-chart-type')).toBe('invalid')
    expect(chart.find('.core-chart__error').text()).toContain('categories')
  })

  it('leaves an ordinary code block alone', async () => {
    const wrapper = mount(MarkdownRenderer, {
      props: { content: '```ts\nconst a = 1\n```', interactive: true },
      global: { stubs: { teleport: true } },
    })
    await settle()

    expect(wrapper.find('[data-chart-block]').exists()).toBe(false)
    expect(wrapper.find('.core-chart').exists()).toBe(false)
    expect(wrapper.find('code').text()).toContain('const a = 1')
  })

  /**
   * user:“每个图表 SVG 或多媒体都要单独一行吗？不能自适应或者并列展示吗？”
   * +(围栏上带 half 标记的两块并排；不带标记的仍然独占一行。)
   */
  it('puts two half-marked charts side by side', async () => {
    const content = [
      '```chart half',
      '{"type":"bar","categories":["A"],"series":[{"name":"左","data":[1]}]}',
      '```',
      '',
      '```chart half',
      '{"type":"bar","categories":["B"],"series":[{"name":"右","data":[2]}]}',
      '```',
    ].join('\n')

    const wrapper = mount(MarkdownRenderer, {
      props: { content, interactive: true },
      global: { stubs: { teleport: true } },
    })
    await settle()

    expect(wrapper.findAll('.code-block--half')).toHaveLength(2)
    // 两个都还是图表，没有被当成普通代码块
    expect(wrapper.find('code.language-chart').exists()).toBe(false)
  })

  it('keeps a chart full width when the flag is absent', async () => {
    const wrapper = mount(MarkdownRenderer, {
      props: { content: BAR, interactive: true },
      global: { stubs: { teleport: true } },
    })
    await settle()
    expect(wrapper.find('.code-block--half').exists()).toBe(false)
  })

  /**
   * user:“右侧空了一块，并没有铺满”+(half 只有凑成一对时才占一半；落单的保持整宽，
   * 否则右边会空出一条。)
   */
  it('only shrinks half blocks that are actually paired', async () => {
    const pair = [
      '```chart half',
      '{"type":"bar","categories":["A"],"series":[{"name":"左","data":[1]}]}',
      '```',
      '',
      '```chart half',
      '{"type":"bar","categories":["B"],"series":[{"name":"右","data":[2]}]}',
      '```',
    ].join('\n')
    const single = [
      '```chart half',
      '{"type":"bar","categories":["A"],"series":[{"name":"单","data":[1]}]}',
      '```',
    ].join('\n')

    const paired = mount(MarkdownRenderer, {
      props: { content: pair, interactive: true },
      global: { stubs: { teleport: true } },
    })
    await settle()
    expect(paired.findAll('[data-half].is-paired')).toHaveLength(2)
    // 成对的两块被包进一个 flex 行，行内空白和边距不会再把第二块挤下去
    expect(paired.findAll('.half-row')).toHaveLength(1)
    expect(paired.find('.half-row').element.children).toHaveLength(2)

    const lone = mount(MarkdownRenderer, {
      props: { content: single, interactive: true },
      global: { stubs: { teleport: true } },
    })
    await settle()
    expect(lone.findAll('[data-half]')).toHaveLength(1)
    expect(lone.findAll('[data-half].is-paired')).toHaveLength(0)
    expect(lone.findAll('.half-row')).toHaveLength(0)
  })

  /**
   * user:“如果在同一组内又满足大于这个最小尺寸，那就把它们合成一排”+(一排几个由宽度决定，
   * 不写死两列：三块连排也进同一行。)
   */
  it('puts a run of three halves into one responsive row', async () => {
    const fence = (name: string) => [
      '```chart half',
      `{"type":"bar","categories":["A"],"series":[{"name":"${name}","data":[1]}]}`,
      '```',
    ].join('\n')
    const content = [fence('一'), fence('二'), fence('三')].join('\n\n')

    const wrapper = mount(MarkdownRenderer, {
      props: { content, interactive: true },
      global: { stubs: { teleport: true } },
    })
    await settle()

    expect(wrapper.findAll('.half-row')).toHaveLength(1)
    expect(wrapper.find('.half-row').element.children).toHaveLength(3)
  })
})
