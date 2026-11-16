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
})
