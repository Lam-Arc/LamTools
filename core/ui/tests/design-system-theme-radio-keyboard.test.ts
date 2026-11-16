import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ThemeAreaEditor from '../src/components/ThemeAreaEditor.vue'
import ThemeEditor from '../src/components/ThemeEditor.vue'

describe('theme radio keyboard navigation', () => {
  it('navigates fill and glass options while preserving controlled updates', async () => {
    const wrapper = mount(ThemeAreaEditor, { attachTo: document.body, props: { label: '主界面', stops: [{ color: '#111111', position: 0 }], angle: 180, opacity: 1, textColor: '#ffffff', showOpacity: true, fillMode: 'solid', glassLevel: 'off', image: '', imageFit: 'cover' } })
    const fill = wrapper.get('[data-theme-fill-mode="solid"]')
    expect(fill.attributes('tabindex')).toBe('0')
    expect(wrapper.get('[data-theme-fill-mode="gradient"]').attributes('tabindex')).toBe('-1')
    fill.element.focus(); await fill.trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('update:fill-mode')?.[0]).toEqual(['gradient'])
    expect(document.activeElement).toBe(wrapper.get('[data-theme-fill-mode="gradient"]').element)
    const glass = wrapper.get('[data-theme-glass-level="off"]')
    glass.element.focus(); await glass.trigger('keydown', { key: 'End' })
    expect(wrapper.emitted('update:glass-level')?.[0]).toEqual(['low'])
    expect(document.activeElement).toBe(wrapper.get('[data-theme-glass-level="low"]').element)
    wrapper.unmount()
  })
  it('navigates appearance modes by arrow and wraps at the ends', async () => {
    const props = { density: 'standard', densityOptions: [], themeMode: 'system' as const, getStops: () => [{ color: '#111111', position: 0 }], getAngle: () => 0, getOpacity: () => 1, getTextColor: () => '#fff', getFillMode: () => 'solid' as const, getGlassLevel: () => 'off' as const, getImage: () => '', getImageFit: () => 'cover' as const, presets: [], themePreviewStyle: {}, themePreviewMainStyle: {}, themePreviewComposerStyle: {}, themePreviewControlStyle: {} }
    const wrapper = mount(ThemeEditor, { attachTo: document.body, props })
    const first = wrapper.get('[data-theme-mode="system"]')
    expect(first.attributes('tabindex')).toBe('0')
    first.element.focus(); await first.trigger('keydown', { key: 'ArrowLeft' })
    expect(wrapper.emitted('update:theme-mode')?.[0]).toEqual(['scheduled'])
    expect(document.activeElement).toBe(wrapper.get('[data-theme-mode="scheduled"]').element)
    wrapper.unmount()
  })
})
