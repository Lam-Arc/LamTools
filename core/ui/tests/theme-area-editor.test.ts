import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ThemeAreaEditor from '../src/components/ThemeAreaEditor.vue'

function mountEditor(overrides: Record<string, unknown> = {}) {
  return mount(ThemeAreaEditor, {
    props: {
      label: '主界面',
      stops: [{ color: '#1b1d22', position: 0 }],
      angle: 180,
      opacity: 1,
      textColor: '#fbf7f0',
      showOpacity: true,
      fillMode: 'solid',
      glassLevel: 'off',
      image: '',
      imageFit: 'cover',
      ...overrides,
    },
  })
}

describe('主题区域编辑器', () => {
  // user:“色彩渐变图像作为一个 mark 节点，然后玻璃应该单独作为一个 preference 节点”
  it('填充节点只有纯色/渐变/图片，纯色只呈现一个颜色', () => {
    const wrapper = mountEditor()
    expect(wrapper.findAll('[data-theme-fill-mode]').map((node) => node.attributes('data-theme-fill-mode')))
      .toEqual(['solid', 'gradient', 'image'])
    expect(wrapper.get('[data-theme-fill-mode="solid"]').attributes('aria-checked')).toBe('true')
    expect(wrapper.find('[data-theme-solid-color]').exists()).toBe(true)
    expect(wrapper.find('.gradient-stop-list').exists()).toBe(false)
    expect(wrapper.find('[data-theme-pick-image]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('选中渐变才显示颜色节点与角度', () => {
    const wrapper = mountEditor({ fillMode: 'gradient' })
    expect(wrapper.find('.gradient-stop-list').exists()).toBe(true)
    expect(wrapper.find('[data-theme-solid-color]').exists()).toBe(false)
    expect(wrapper.text()).toContain('渐变角度')
    wrapper.unmount()
  })

  it('玻璃偏好独立常驻：关闭/高透/低透三档并回传选择', async () => {
    const wrapper = mountEditor()
    const levels = wrapper.findAll('[data-theme-glass-level]')
    expect(levels.map((node) => node.attributes('data-theme-glass-level'))).toEqual(['off', 'high', 'low'])
    expect(levels[0].attributes('aria-checked')).toBe('true')

    await levels[1].trigger('click')
    expect(wrapper.emitted('update:glass-level')?.[0]).toEqual(['high'])
    wrapper.unmount()
  })

  it('玻璃开启时填充仍可调，颜色就是玻璃的着色', async () => {
    const wrapper = mountEditor({ fillMode: 'solid', glassLevel: 'high' })
    expect(wrapper.find('[data-theme-solid-color]').exists()).toBe(true)

    await wrapper.get('[data-theme-solid-color]').setValue('#334455')
    expect(wrapper.emitted('update:stops')?.at(-1)?.[0]).toEqual([{ color: '#334455', position: 0 }])
    wrapper.unmount()
  })

  it('玻璃关闭时才显示透明度，开启后由材质决定浓度', () => {
    const off = mountEditor({ glassLevel: 'off' })
    expect(off.findAll('.theme-area-card input[type="range"]')).toHaveLength(1)
    off.unmount()

    const on = mountEditor({ glassLevel: 'high' })
    expect(on.findAll('.theme-area-card input[type="range"]')).toHaveLength(0)
    on.unmount()
  })

  it('切换填充时把选择回传给主题', async () => {
    const wrapper = mountEditor()
    await wrapper.get('[data-theme-fill-mode="gradient"]').trigger('click')
    expect(wrapper.emitted('update:fill-mode')?.[0]).toEqual(['gradient'])
    await wrapper.get('[data-theme-fill-mode="image"]').trigger('click')
    expect(wrapper.emitted('update:fill-mode')?.[1]).toEqual(['image'])
    wrapper.unmount()
  })

  it('纯色改颜色只改第一个节点，保留原有其余节点', async () => {
    const wrapper = mountEditor({
      fillMode: 'solid',
      stops: [{ color: '#111111', position: 0 }, { color: '#222222', position: 100 }],
    })
    await wrapper.get('[data-theme-solid-color]').setValue('#334455')
    expect(wrapper.emitted('update:stops')?.at(-1)?.[0]).toEqual([
      { color: '#334455', position: 0 },
      { color: '#222222', position: 100 },
    ])
    wrapper.unmount()
  })

  it('图片样式提供选择、清除与适应方式，未选图时不显示清除', async () => {
    const withImage = mountEditor({
      fillMode: 'image',
      image: 'data:image/gif;base64,R0lGODlhAQABAAAAACw=',
    })
    expect(withImage.find('[data-theme-pick-image]').exists()).toBe(true)
    expect(withImage.find('[data-theme-clear-image]').exists()).toBe(true)
    expect(withImage.find('[data-theme-image-fit]').exists()).toBe(true)
    // 图片也能垫底色：透明图会透出它，玻璃开启时它就是玻璃的着色。
    await withImage.get('[data-theme-image-base-color]').setValue('#334455')
    expect(withImage.emitted('update:stops')?.at(-1)?.[0]).toEqual([{ color: '#334455', position: 0 }])
    await withImage.get('[data-theme-clear-image]').trigger('click')
    expect(withImage.emitted('update:image')?.[0]).toEqual([''])
    withImage.unmount()

    const withoutImage = mountEditor({ fillMode: 'image', image: '' })
    expect(withoutImage.find('[data-theme-clear-image]').exists()).toBe(false)
    withoutImage.unmount()
  })
})
