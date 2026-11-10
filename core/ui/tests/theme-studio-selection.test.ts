import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ThemeStudio from '../src/components/ThemeStudio.vue'
import { STUDIO_STYLE_ID } from '../src/themeStudio/runtime.ts'

/**
 * user:“框选、复制粘贴、独显”“三级间距标注”“发布前检查”“发布历史”+
 * (编辑器新补的五块交互：每块至少一条能证明行为真的发生的断言。)
 */

const publishedStyle = () => document.querySelector<HTMLStyleElement>(`style[data-ui-theme-studio="${STUDIO_STYLE_ID}"]`)
const editorStyle = () => document.querySelector<HTMLStyleElement>('style[data-studio-editor-state]')

function pointerEvent(type: string, x: number, y: number, init: PointerEventInit = {}): PointerEvent {
  return new PointerEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, pointerId: 1, ...init })
}

function stubRect(element: HTMLElement, rect: { left: number; top: number; width: number; height: number }): void {
  element.getBoundingClientRect = () => ({
    ...rect,
    right: rect.left + rect.width,
    bottom: rect.top + rect.height,
    x: rect.left,
    y: rect.top,
    toJSON: () => ({}),
  }) as DOMRect
}

describe('编辑器：选择与组织', () => {
  beforeEach(() => {
    localStorage.clear()
    document.querySelectorAll('style[data-ui-theme-studio]').forEach((node) => node.remove())
    document.querySelectorAll('style[data-studio-editor-state]').forEach((node) => node.remove())
  })

  it('在空白处拖出矩形可以框选多个元素', async () => {
    const first = document.createElement('div')
    first.dataset.uiId = 'shell.app-rail'
    stubRect(first, { left: 10, top: 10, width: 40, height: 40 })
    const second = document.createElement('div')
    second.dataset.uiId = 'shell.sidebar'
    stubRect(second, { left: 60, top: 10, width: 40, height: 40 })
    document.body.append(first, second)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()

    document.body.dispatchEvent(pointerEvent('pointerdown', 0, 0))
    document.dispatchEvent(pointerEvent('pointermove', 200, 200))
    await flushPromises()
    expect(wrapper.find('[data-studio-marquee]').exists()).toBe(true)
    document.dispatchEvent(pointerEvent('pointerup', 200, 200))
    await flushPromises()

    // 两个都进多选：对齐条出现，主选中的带选中态，另一个画额外选框。
    expect(wrapper.find('[data-studio-align="left"]').exists()).toBe(true)
    expect(wrapper.find('[data-studio-node="shell.app-rail"]').classes()).toContain('is-selected')
    expect(wrapper.findAll('.studio-outline--extra')).toHaveLength(1)
    wrapper.unmount()
    first.remove()
    second.remove()
  })

  it('复制一个元素的样式，粘贴到另一个元素', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()

    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#112233')
    await flushPromises()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'c', ctrlKey: true, bubbles: true }))
    await flushPromises()
    expect(wrapper.find('[data-studio-notice]').text()).toContain('已复制样式')

    await wrapper.get('[data-studio-node="shell.app-rail"]').trigger('click')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'v', ctrlKey: true, bubbles: true }))
    await flushPromises()

    const css = document.querySelector<HTMLStyleElement>('style[data-ui-theme-studio="ui-theme-studio-preview"]')?.textContent || ''
    expect(css).toContain('[data-ui-id="shell.app-rail"][data-ui-id]')
    expect(css).toContain('color: #112233')
    wrapper.unmount()
  })

  it('独显只留当前图层与必要祖先，退出即恢复', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-view="layers"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-studio-solo="shell.sidebar"]').trigger('click')
    await flushPromises()
    const css = editorStyle()?.textContent || ''
    expect(css).toContain('[data-ui-id="shell.app-rail"] { visibility: hidden }')
    expect(css).not.toContain('[data-ui-id="shell.sidebar"] { visibility: hidden }')
    expect(css).not.toContain('[data-ui-id="shell.left-drawer"] { visibility: hidden }')

    await wrapper.get('[data-studio-solo="shell.sidebar"]').trigger('click')
    await flushPromises()
    expect(editorStyle()?.textContent || '').toBe('')
    wrapper.unmount()
  })

  it('同级间距画成三级标注，标签显示可见间距', async () => {
    const parent = document.createElement('div')
    parent.dataset.uiId = 'shell.sidebar'
    stubRect(parent, { left: 0, top: 0, width: 400, height: 300 })
    const previous = document.createElement('div')
    previous.dataset.uiId = 'shell.app-rail'
    stubRect(previous, { left: 20, top: 20, width: 120, height: 40 })
    const current = document.createElement('div')
    current.dataset.uiId = 'chat.thread'
    stubRect(current, { left: 20, top: 80, width: 120, height: 40 })
    parent.append(previous, current)
    document.body.append(parent)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="chat.thread"]').trigger('click')
    await flushPromises()

    const label = wrapper.get('[data-studio-gap-label]')
    expect(label.attributes('data-studio-gap-label')).toBe('brace')
    expect(label.text()).toBe('20')
    expect(wrapper.find('[data-studio-gap-pill]').exists()).toBe(true)
    wrapper.unmount()
    parent.remove()
  })
})

describe('编辑器：发布前检查与历史', () => {
  beforeEach(() => {
    localStorage.clear()
    document.querySelectorAll('style[data-ui-theme-studio]').forEach((node) => node.remove())
    document.querySelectorAll('style[data-studio-editor-state]').forEach((node) => node.remove())
  })

  it('元素超出外壳时挡住发布并指出方向', async () => {
    const shell = document.createElement('div')
    shell.dataset.uiId = 'shell.root'
    stubRect(shell, { left: 0, top: 0, width: 320, height: 800 })
    const sidebar = document.createElement('div')
    sidebar.dataset.uiId = 'shell.sidebar'
    stubRect(sidebar, { left: 0, top: 0, width: 500, height: 100 })
    document.body.append(shell, sidebar)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#123456')
    await flushPromises()

    await wrapper.get('[data-studio-publish]').trigger('click')
    await flushPromises()

    const panel = wrapper.get('[data-studio-preflight]')
    expect(panel.text()).toContain('超出界面')
    expect(panel.text()).toContain('右 180px')
    expect(publishedStyle()).toBeNull()
    wrapper.unmount()
    shell.remove()
    sidebar.remove()
  })

  it('滚动内容与刻意隐藏的入口不算布局溢出', async () => {
    const shell = document.createElement('div')
    shell.dataset.uiId = 'shell.root'
    stubRect(shell, { left: 0, top: 0, width: 320, height: 800 })
    // 消息是滚动内容，超出视口是正常的。
    const message = document.createElement('div')
    message.dataset.uiTemplate = 'template.message'
    stubRect(message, { left: 0, top: 900, width: 500, height: 100 })
    // 明确 display:none 的入口是刻意的界面状态。
    const hidden = document.createElement('div')
    hidden.dataset.uiId = 'shell.titlebar'
    hidden.style.display = 'none'
    stubRect(hidden, { left: 0, top: 0, width: 900, height: 100 })
    document.body.append(shell, message, hidden)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#123456')
    await flushPromises()
    await wrapper.get('[data-studio-publish]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-studio-preflight]').exists()).toBe(false)
    expect(publishedStyle()).not.toBeNull()
    wrapper.unmount()
    shell.remove()
    message.remove()
    hidden.remove()
  })

  it('历史面板能列出版本并回到那一版', async () => {
    // 历史由发布时写入；这里直接预置一版，验证面板与回滚动作。
    localStorage.setItem('sunday.themeStudio.history.v1', JSON.stringify([{
      at: new Date().toISOString(),
      document: {
        schemaVersion: 1,
        themeId: 'studio',
        nodes: { 'shell.sidebar': { color: '#112233' } },
        templates: {},
        instances: {},
        breakpoints: [],
        assets: [],
        updatedAt: new Date().toISOString(),
      },
    }]))
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()

    await wrapper.get('[data-studio-history]').trigger('click')
    await flushPromises()
    const panel = wrapper.get('[data-studio-history-panel]')
    expect(panel.text()).toContain('元素 1')

    await wrapper.get('[data-studio-history-restore="0"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-studio-notice]').text()).toContain('已回到这一版')
    wrapper.unmount()
  })
})
