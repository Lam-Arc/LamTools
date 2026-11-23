import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CoreMessageSurface from '../src/components/CoreMessageSurface.vue'

/**
 * user:“全部统一以这个为示例 可复用化，可调参数为胶囊/卡片,填充颜色,是否玻璃”
 * +(气泡外壳只有三个参数：形状、填充、玻璃；默认值与样例一致为玻璃卡片。
 *   组件只负责翻译参数，材质配方在 styles/message-surface.css)。
 */
describe('CoreMessageSurface', () => {
  it('defaults to the glass card surface with no inline fill', () => {
    const wrapper = mount(CoreMessageSurface, { slots: { default: '内容' } })
    const root = wrapper.get('.message-surface')
    expect(root.classes()).toContain('message-surface--card')
    expect(root.classes()).toContain('message-surface--glass')
    // 未布局时角度退回 45°，填充仍由角色色决定（没有内联 fill）
    expect(root.attributes('style')).toContain('--message-surface-edge-angle: 45.00deg')
    expect(root.attributes('style')).not.toContain('--message-surface-fill')
  })

  it('switches shape through the capsule parameter', () => {
    const wrapper = mount(CoreMessageSurface, { props: { shape: 'capsule' } })
    expect(wrapper.get('.message-surface').classes()).toContain('message-surface--capsule')
  })

  it('turns glass off into the solid surface', () => {
    const wrapper = mount(CoreMessageSurface, { props: { glass: false } })
    const classes = wrapper.get('.message-surface').classes()
    expect(classes).toContain('message-surface--solid')
    expect(classes).not.toContain('message-surface--glass')
  })

  it('passes a custom fill color or gradient through a CSS variable', () => {
    const wrapper = mount(CoreMessageSurface, {
      props: { fill: 'linear-gradient(150deg, #ffd76a66, #ff6f9a33)' },
    })
    expect(wrapper.get('.message-surface').attributes('style')).toContain('--message-surface-fill')
  })

  it('renders a plain container when the surface is off', () => {
    const wrapper = mount(CoreMessageSurface, {
      props: { surface: false },
      slots: { default: '纯文本' },
    })
    expect(wrapper.find('.message-surface').exists()).toBe(false)
    expect(wrapper.text()).toBe('纯文本')
  })
})
