import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { useThemeStudio } from '../src/composables/useThemeStudio.ts'
import CoreSettings from '../src/components/CoreSettings.vue'
import ThemeStudio from '../src/components/ThemeStudio.vue'
import { DEFAULT_THEME } from '../src/helpers/theme'

/**
 * user:“我只要切换界面，编辑就自动取消了，那它不是永远不可能编辑到主界面吗”+
 * (编辑器挂在应用层而不是设置页：打开状态是全局单例，切到任何界面编辑都不中断；
 *  设置页只留一个入口按钮，不再承载编辑器本身。)
 */

const PageA = defineComponent({ setup: () => () => h('div', { 'data-page': 'a' }, useThemeStudio().studioOpen.value ? 'open-a' : 'closed-a') })
const PageB = defineComponent({ setup: () => () => h('div', { 'data-page': 'b' }, useThemeStudio().studioOpen.value ? 'open-b' : 'closed-b') })

describe('界面编辑器打开状态', () => {
  beforeEach(() => {
    useThemeStudio().studioOpen.value = false
    localStorage.clear()
    document.querySelectorAll('style[data-ui-theme-studio]').forEach((node) => node.remove())
  })

  it('打开状态是全局单例，页面卸载重建后依然保持', async () => {
    const { studioOpen } = useThemeStudio()
    const pageA = mount(PageA)
    expect(pageA.text()).toBe('closed-a')

    studioOpen.value = true
    await flushPromises()
    expect(pageA.text()).toBe('open-a')
    pageA.unmount()

    // 模拟切到另一个界面：新页面读到的是同一个状态，编辑不中断。
    const pageB = mount(PageB)
    expect(pageB.text()).toBe('open-b')
    pageB.unmount()
  })

  it('设置页入口按钮打开全局编辑器，但编辑器不在设置页内渲染', async () => {
    const { studioOpen } = useThemeStudio()
    const wrapper = mount(CoreSettings, {
      attachTo: document.body,
      props: {
        models: [],
        providers: [],
        density: 'standard',
        theme: structuredClone(DEFAULT_THEME),
        section: 'appearance',
      },
      global: { stubs: { Teleport: true } },
    })
    await flushPromises()
    await wrapper.get('[data-open-theme-studio]').trigger('click')
    await flushPromises()

    expect(studioOpen.value).toBe(true)
    // 编辑器由应用层挂载，设置页子树里不再出现它。
    expect(document.querySelector('[data-theme-studio]')).toBeNull()
    wrapper.unmount()
  })

  it('编辑器内取消关闭时同步全局打开状态', async () => {
    const { studioOpen } = useThemeStudio()
    studioOpen.value = true
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()

    await wrapper.get('[data-studio-cancel]').trigger('click')
    await flushPromises()

    expect(studioOpen.value).toBe(false)
    expect(wrapper.emitted('close')).toBeTruthy()
    wrapper.unmount()
  })
})
