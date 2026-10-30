import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ThemeStudio from '../src/components/ThemeStudio.vue'
import { UI_REGISTRY } from '../src/uiRegistry/registry.ts'
import { STUDIO_PREVIEW_STYLE_ID, STUDIO_STYLE_ID } from '../src/themeStudio/runtime.ts'
import { applyStoredPublishedTheme } from '../src/themeStudio/bootstrap.ts'

/**
 * user:“可视化主题与布局编辑器”+
 * (工作台要能列出全部可编辑元素、选中后改属性立即预览、发布后落到正式样式并持久化。)
 */
const previewStyle = () => document.querySelector<HTMLStyleElement>(`style[data-ui-theme-studio="${STUDIO_PREVIEW_STYLE_ID}"]`)
const publishedStyle = () => document.querySelector<HTMLStyleElement>(`style[data-ui-theme-studio="${STUDIO_STYLE_ID}"]`)

describe('可视化编辑器工作台', () => {
  beforeEach(() => {
    localStorage.clear()
    document.querySelectorAll('style[data-ui-theme-studio]').forEach((node) => node.remove())
  })

  it('列出全部可编辑元素，默认不选中', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    expect(wrapper.findAll('[data-studio-node]')).toHaveLength(UI_REGISTRY.length)
    // 独立审查可用性项：打开不再自动全选主区域（避免开屏整屏暗化、无引导的观感）。
    expect(wrapper.find('.is-selected').exists()).toBe(false)
    expect(wrapper.text()).toContain('先选择一个组件')
    wrapper.unmount()
  })

  it('改颜色立即进入预览通道，不写正式样式', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#112233')
    await flushPromises()

    expect(previewStyle()?.textContent).toContain('color: #112233')
    expect(publishedStyle()).toBeNull()
    wrapper.unmount()
    expect(previewStyle()).toBeNull()
  })

  it('选中模板时写进模板通道', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="template.conversation"]').trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#556677')
    await flushPromises()
    const css = previewStyle()?.textContent || ''
    expect(css).toContain('[data-ui-template="template.conversation"][data-ui-template]')
    expect(css).toContain('color: #556677')
    wrapper.unmount()
  })

  it('多选后左对齐会写位移', async () => {
    const first = document.createElement('div')
    first.dataset.uiId = 'shell.app-rail'
    first.getBoundingClientRect = () => ({ left: 100, top: 100, width: 40, height: 40, right: 140, bottom: 140, x: 100, y: 100, toJSON: () => ({}) }) as DOMRect
    const second = document.createElement('div')
    second.dataset.uiId = 'shell.sidebar'
    second.getBoundingClientRect = () => ({ left: 200, top: 120, width: 40, height: 40, right: 240, bottom: 160, x: 200, y: 120, toJSON: () => ({}) }) as DOMRect
    document.body.append(first, second)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.app-rail"]').trigger('click')
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click', { ctrlKey: true })
    await flushPromises()

    const alignLeft = wrapper.get('[data-studio-align="left"]')
    await alignLeft.trigger('click')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('translate: -100px 0px')
    wrapper.unmount()
    first.remove()
    second.remove()
  })

  it('发布后写正式样式与本地存储', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#224466')
    await flushPromises()

    const publish = wrapper.get('[data-studio-publish]')
    expect(publish).toBeTruthy()
    await publish.trigger('click')
    await flushPromises()

    expect(publishedStyle()?.textContent).toContain('color: #224466')
    expect(previewStyle()).toBeNull()
    expect(localStorage.getItem('sunday.themeStudio.published.v1')).toContain('#224466')
    wrapper.unmount()
  })

  it('恢复默认会清空覆盖', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#335577')
    await flushPromises()

    const reset = wrapper.get('[data-studio-reset]')
    await reset.trigger('click')
    await flushPromises()
    // 恢复默认需要确认（独立审查可用性项）。
    expect(previewStyle()?.textContent).toContain('#335577')
    await wrapper.get('.core-confirm__submit').trigger('click')
    await flushPromises()
    expect(previewStyle()?.textContent || '').not.toContain('#335577')
    expect(wrapper.find('.core-confirm').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('编辑器界面控制', () => {
  beforeEach(() => {
    localStorage.clear()
    document.querySelectorAll('style[data-ui-theme-studio]').forEach((node) => node.remove())
  })

  // user:“图层和元素按钮应当为图层和属性按钮”“点图层按钮不要同时把图层和属性调出来，点属性按钮也一样”+
  // (图层键只开左侧图层卡；属性键只开右侧属性卡；两张卡各自开关，互不联动)
  it('图层卡与属性卡各自开关，互不联动', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    expect(wrapper.get('[data-studio-panel="tree"]').classes()).not.toContain('is-open')
    expect(wrapper.get('[data-studio-panel="props"]').classes()).not.toContain('is-open')

    await wrapper.get('[data-studio-open-layers]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-studio-panel="tree"]').classes()).toContain('is-open')
    expect(wrapper.get('[data-studio-panel="props"]').classes()).not.toContain('is-open')
    expect(wrapper.find('[data-studio-layers]').exists()).toBe(true)

    await wrapper.get('[data-studio-open-props]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-studio-panel="props"]').classes()).toContain('is-open')
    expect(wrapper.get('[data-studio-panel="tree"]').classes()).toContain('is-open')

    await wrapper.get('[data-studio-open-layers]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-studio-panel="tree"]').classes()).not.toContain('is-open')
    expect(wrapper.get('[data-studio-panel="props"]').classes()).toContain('is-open')

    await wrapper.get('[data-studio-open-props]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-studio-panel="props"]').classes()).not.toContain('is-open')
    wrapper.unmount()
  })

  // user:“编辑器状态下，若编辑模式未打开则保持正常交互”+
  // (编辑模式开着才接管画布点击；关掉后界面点击穿透，业务动作照常、选中态不再变化。)
  it('编辑模式默认开启，关闭后界面恢复正常交互', async () => {
    const target = document.createElement('button')
    target.dataset.uiId = 'shell.app-rail'
    let clicks = 0
    target.addEventListener('click', () => { clicks += 1 })
    document.body.append(target)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    const switchInput = () => wrapper.get('[data-studio-edit-mode] input[type="checkbox"]')
    expect((switchInput().element as HTMLInputElement).checked).toBe(true)

    await target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    await flushPromises()
    expect(clicks).toBe(0)
    expect(wrapper.get('[data-studio-node="shell.app-rail"]').classes()).toContain('is-selected')

    await switchInput().setValue(false)
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.main"]').trigger('click')
    await target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    await flushPromises()
    expect(clicks).toBe(1)
    expect(wrapper.get('[data-studio-node="shell.app-rail"]').classes()).not.toContain('is-selected')
    wrapper.unmount()
    target.remove()
  })

  // user:“并加一个编辑模式的开关和一个取消（不保存退出）”+
  // (取消=不保存退出：丢弃未发布草稿、清掉预览并关闭编辑器，不写任何存储。)
  it('取消不保存退出：丢弃未发布修改并关闭编辑器', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#112233')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('#112233')

    await wrapper.get('[data-studio-cancel]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('close')).toBeTruthy()
    expect(previewStyle()).toBeNull()
    expect(localStorage.getItem('sunday.themeStudio.published.v1')).toBeNull()
    wrapper.unmount()
  })

  // user:“工具条精简，按钮：开关键|图层卡 元素卡| 撤销 重做|磁铁 辅助线|取消 确认，
  //  每一个都是单独的键，不写文字，用图标表示”+
  // (工具条只剩图标键，按竖线分组；导入/导出/恢复默认移到图层卡底部。)
  it('工具条精简为分组图标键，不写文字', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    const toolbar = wrapper.get('[data-studio-toolbar]')
    for (const selector of [
      '[data-studio-edit-mode]',
      '[data-studio-open-layers]',
      '[data-studio-open-props]',
      '[data-studio-undo]',
      '[data-studio-redo]',
      '[data-studio-snap-toggle]',
      '[data-studio-overlay-toggle]',
      '[data-studio-cancel]',
      '[data-studio-publish]',
    ]) {
      expect(toolbar.find(selector).exists(), selector).toBe(true)
    }
    // 每个动作都是单独的图标键，不带文字。
    for (const selector of ['[data-studio-open-layers]', '[data-studio-open-props]', '[data-studio-undo]', '[data-studio-redo]', '[data-studio-snap-toggle]', '[data-studio-overlay-toggle]', '[data-studio-cancel]', '[data-studio-publish]']) {
      expect(toolbar.get(selector).text(), selector).toBe('')
    }
    // 4 条竖向分隔：开关|图层/属性|撤销/重做|磁铁/辅助线|取消/确认
    expect(toolbar.findAll('.studio-toolbar-divider')).toHaveLength(4)
    // 导入/导出/恢复默认已经收进元素卡底部，不再占工具条。
    expect(toolbar.find('[data-studio-reset]').exists()).toBe(false)
    expect(wrapper.find('[data-studio-secondary] [data-studio-reset]').exists()).toBe(true)
    // 不再残留任何单独悬浮的控件。
    expect(wrapper.findAll('[data-studio-float]')).toHaveLength(0)
    wrapper.unmount()
  })

  // user:“那个正在预览真实界面那个话，用一个小胶囊，下边不圆角，贴住控件 bar 的上沿，低透玻璃样式”+
  // (胶囊是工具条外层的第一个子节点，跟着 bar 一起移动，低透玻璃底)
  it('预览提示是贴在工具条上沿的低透玻璃胶囊', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    const hint = wrapper.get('.studio-canvas-hint')
    expect(hint.text()).toContain('正在预览真实界面')
    expect(hint.classes()).toContain('optical-glass')
    expect(hint.classes()).toContain('optical-glass--low-trans')
    expect(wrapper.get('[data-studio-toolbar-float]').element.firstElementChild).toBe(hint.element)
    wrapper.unmount()
  })

  // user:“我希望左侧的元素卡和右侧的图层卡，以及底下的工具条，全部都可以被拖动”+
  // (标题栏/工具条空白处是拖拽手柄；拖拽后写入 left/top，按按钮不会误触发整卡拖动)
  it('图层卡、属性卡和工具条都能拖动，按按钮不误拖', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-open-layers]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-studio-open-props]').trigger('click')
    await flushPromises()

    const dragBy = async (selector: string, fromX: number, fromY: number, toX: number, toY: number) => {
      const handle = wrapper.get(selector)
      handle.element.dispatchEvent(pointerEvent('pointerdown', fromX, fromY))
      window.dispatchEvent(pointerEvent('pointermove', toX, toY))
      window.dispatchEvent(pointerEvent('pointerup', toX, toY))
      await flushPromises()
    }

    await dragBy('[data-studio-panel="tree"] [data-studio-drag-handle]', 100, 100, 140, 130)
    const tree = wrapper.get('[data-studio-panel="tree"]')
    expect(tree.attributes('style')).toContain('left: 40px')
    expect(tree.attributes('style')).toContain('top: 30px')

    await dragBy('[data-studio-panel="props"] [data-studio-drag-handle]', 200, 200, 170, 240)
    const props = wrapper.get('[data-studio-panel="props"]')
    // 向左越界会被夹到 0，不会把卡片拖出屏幕。
    expect(props.attributes('style')).toContain('left: 0px')
    expect(props.attributes('style')).toContain('top: 40px')

    await dragBy('[data-studio-toolbar-float] [data-studio-drag-grip]', 10, 10, 60, 25)
    const bar = wrapper.get('[data-studio-toolbar-float]')
    expect(bar.attributes('style')).toContain('left: 50px')
    expect(bar.attributes('style')).toContain('top: 15px')

    // 按工具条按钮不会把整条拖走。
    const before = bar.attributes('style')
    wrapper.get('[data-studio-snap-toggle]').element.dispatchEvent(pointerEvent('pointerdown', 60, 25))
    window.dispatchEvent(pointerEvent('pointermove', 200, 200))
    window.dispatchEvent(pointerEvent('pointerup', 200, 200))
    await flushPromises()
    expect(wrapper.get('[data-studio-toolbar-float]').attributes('style')).toBe(before)
    wrapper.unmount()
  })

  // user:“确认带反馈动画”+(点确认立即发布，按钮打勾脉冲，动画结束才关闭编辑器)
  it('确认发布先落地并播放反馈动画，再关闭编辑器', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#123456')
    await flushPromises()

    await wrapper.get('[data-studio-publish]').trigger('click')
    await flushPromises()
    expect(publishedStyle()?.textContent).toContain('#123456')
    expect(wrapper.get('[data-studio-publish]').classes()).toContain('is-confirmed')
    await vi.waitFor(() => expect(wrapper.emitted('close')).toBeTruthy(), { timeout: 2000 })
    wrapper.unmount()
  })

  // user:“下方的 bar ，均用低透玻璃样式”+(编辑器的左右栏、底部工具条和浮动控件全部
  //  复用 .optical-glass--low-trans 低透玻璃底座，不再用实心面板。)
  it('左右栏、底部工具条与浮动控件都挂在低透玻璃上', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    const glassSelectors = [
      '[data-studio-panel="tree"]',
      '[data-studio-panel="props"]',
      '[data-studio-toolbar]',
    ]
    for (const selector of glassSelectors) {
      const classes = wrapper.get(selector).classes()
      expect(classes, selector).toContain('optical-glass')
      expect(classes, selector).toContain('optical-glass--low-trans')
    }
    wrapper.unmount()
  })

  // user:“而且为什么这个点了发布之后 它的修改不生效啊”+
  // (发布后关闭编辑器样式必须还在；重启后由启动逻辑从本地存储恢复。)
  it('发布后关闭编辑器样式仍在，重启可由启动逻辑恢复', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#224466')
    await flushPromises()
    const publish = wrapper.get('[data-studio-publish]')
    await publish.trigger('click')
    await flushPromises()

    wrapper.unmount()
    expect(publishedStyle()?.textContent).toContain('#224466')

    document.querySelectorAll('style[data-ui-theme-studio]').forEach((node) => node.remove())
    expect(applyStoredPublishedTheme()).toBe(true)
    expect(publishedStyle()?.textContent).toContain('#224466')
  })
})

// jsdom 的指针事件属性是只读 getter，手动构造普通事件带上坐标（供多个用例共用）。
function pointerEvent(type: string, x: number, y: number): Event {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'clientX', { value: x })
  Object.defineProperty(event, 'clientY', { value: y })
  Object.defineProperty(event, 'button', { value: 0 })
  return event
}

describe('编辑器交互补齐', () => {
  beforeEach(() => {
    localStorage.clear()
    document.querySelectorAll('style[data-ui-theme-studio]').forEach((node) => node.remove())
  })

  // user:“按这个设计方案审…补齐”+(方案 §3.3/§3.5：Esc 先清多选再取消选中)

  it('Esc 先退出多选，再取消选中', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.app-rail"]').trigger('click')
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click', { ctrlKey: true })
    await flushPromises()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(wrapper.get('[data-studio-node="shell.app-rail"]').classes()).toContain('is-selected')
    expect(wrapper.get('[data-studio-node="shell.sidebar"]').classes()).not.toContain('is-selected')

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(wrapper.get('[data-studio-node="shell.app-rail"]').classes()).not.toContain('is-selected')
    expect(wrapper.text()).toContain('先选择一个组件')
    wrapper.unmount()
  })

  // user:“按这个设计方案审…补齐”+(方案 §3.1 吸附开关：关闭时拖动不吸附、不保存吸附关系)
  it('吸附开关控制拖动吸附', async () => {
    const target = document.createElement('div')
    target.dataset.uiId = 'shell.app-rail'
    target.getBoundingClientRect = () => ({ left: 2, top: 100, width: 40, height: 40, right: 42, bottom: 140, x: 2, y: 100, toJSON: () => ({}) }) as DOMRect
    document.body.append(target)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.app-rail"]').trigger('click')

    // 默认开吸附：元素左缘 2px + 拖 4px = 6px，被吸附回 0。
    target.dispatchEvent(pointerEvent('pointerdown', 100, 100))
    document.dispatchEvent(pointerEvent('pointermove', 104, 100))
    document.dispatchEvent(pointerEvent('pointerup', 104, 100))
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('translate: -2px 0px')

    await wrapper.get('[data-studio-snap-toggle]').trigger('click')
    target.dispatchEvent(pointerEvent('pointerdown', 100, 100))
    document.dispatchEvent(pointerEvent('pointermove', 104, 100))
    document.dispatchEvent(pointerEvent('pointerup', 104, 100))
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('translate: 2px 0px')
    wrapper.unmount()
    target.remove()
  })

  // user:“按这个设计方案审…补齐”+(方案 §3.3 悬停细框提示，不改选中)
  it('悬停画细框提示，离开即消失', async () => {
    const target = document.createElement('div')
    target.dataset.uiId = 'shell.app-rail'
    document.body.append(target)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    target.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }))
    await flushPromises()
    expect(wrapper.get('.studio-hover-box').exists()).toBe(true)

    document.body.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }))
    await flushPromises()
    expect(wrapper.find('.studio-hover-box').exists()).toBe(false)
    wrapper.unmount()
    target.remove()
  })

  // user:“按这个设计方案审…补齐”+(方案 §3.4：子中心到直接父中心细虚线，父容器青绿轮廓)
  it('选中时画父容器轮廓与父子中心虚线', async () => {
    const parent = document.createElement('div')
    parent.dataset.uiId = 'shell.root'
    parent.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 400, right: 400, bottom: 400, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect
    const child = document.createElement('div')
    child.dataset.uiId = 'shell.app-rail'
    child.getBoundingClientRect = () => ({ left: 50, top: 50, width: 40, height: 40, right: 90, bottom: 90, x: 50, y: 50, toJSON: () => ({}) }) as DOMRect
    parent.append(child)
    document.body.append(parent)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.app-rail"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('.studio-parent-box').exists()).toBe(true)
    const line = wrapper.get('.studio-parent-link')
    expect(line.attributes('x1')).toBeTruthy()
    expect(wrapper.get('[data-studio-parent-hint]').text()).toContain('shell.root')
    wrapper.unmount()
    parent.remove()
  })

  // user:“按这个设计方案审…补齐”+(方案 §3.3：模板编辑紫色样本实线+同模板实例虚线)
  it('选中模板时样本画紫框，其余实例画虚线', async () => {
    const samples: HTMLElement[] = []
    for (const index of [0, 1, 2]) {
      const node = document.createElement('div')
      node.dataset.uiTemplate = 'template.conversation'
      node.getBoundingClientRect = () => ({ left: 10 + index * 60, top: 10, width: 50, height: 20, right: 60 + index * 60, bottom: 30, x: 10 + index * 60, y: 10, toJSON: () => ({}) }) as DOMRect
      document.body.append(node)
      samples.push(node)
    }

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="template.conversation"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('.studio-template-sample').exists()).toBe(true)
    expect(wrapper.findAll('.studio-template-sibling')).toHaveLength(2)
    wrapper.unmount()
    samples.forEach((node) => node.remove())
  })

  // user:“按这个设计方案审…补齐”+(方案 §3.1 图层树搜索与折叠)
  it('图层树支持搜索过滤与分组折叠', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    expect(wrapper.findAll('[data-studio-node]')).toHaveLength(UI_REGISTRY.length)

    await wrapper.get('[data-studio-tree-search]').setValue('消息')
    await flushPromises()
    const matched = wrapper.findAll('[data-studio-node]')
    expect(matched.length).toBeGreaterThan(0)
    expect(matched.length).toBeLessThan(UI_REGISTRY.length)

    await wrapper.get('[data-studio-tree-search]').setValue('')
    await wrapper.get('[data-studio-tree-caret="shell.root"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-studio-node]').length).toBeLessThan(UI_REGISTRY.length)

    await wrapper.get('[data-studio-tree-caret="shell.root"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-studio-node]')).toHaveLength(UI_REGISTRY.length)
    wrapper.unmount()
  })

  // user:“按这个设计方案审…补齐”+(方案 §9.4 辅助标注层独立显示开关)
  it('辅助线开关隐藏全部画布覆盖层', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-overlay-toggle]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-studio-canvas]').classes()).toContain('is-overlay-hidden')
    wrapper.unmount()
  })
})

describe('编辑器补齐：属性面板与流程', () => {
  beforeEach(() => {
    localStorage.clear()
    document.querySelectorAll('style[data-ui-theme-studio]').forEach((node) => node.remove())
  })

  // user:“按这个设计方案审…补齐”+(方案 §4.3：宽高各自有模式，fill/hug/固定，可配 min/max)
  it('尺寸面板：模式与数值编译进样式', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.app-rail"]').trigger('click')

    await wrapper.get('[data-studio-size-mode="width"]').setValue('fill')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('width: 100%')

    await wrapper.get('[data-studio-size-mode="width"]').setValue('fixed')
    await wrapper.get('[data-studio-size-value="width"]').setValue('240')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('width: 240px')

    await wrapper.get('[data-studio-size-min="width"]').setValue('120')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('min-width: 120px')

    await wrapper.get('[data-studio-size-mode="width"]').setValue('')
    await flushPromises()
    expect(previewStyle()?.textContent || '').not.toContain('width: 240px')
    wrapper.unmount()
  })

  // user:“按这个设计方案审…补齐”+(方案 §8.1：背景透明度与组件整体透明度分离)
  it('背景透明度独立编译，不混入组件透明度', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.main"]').trigger('click')
    await wrapper.get('[data-studio-field="background-opacity"]').setValue('0.5')
    await flushPromises()
    const css = previewStyle()?.textContent || ''
    expect(css).toContain('--ui-bg-opacity: 0.5')
    // 组件整体透明度不被牵连（--ui-bg-opacity 里的子串不算）。
    expect(css).not.toMatch(/(^|[^-])opacity: 0\.5/)
    wrapper.unmount()
  })

  // user:“按这个设计方案审…补齐”+(方案 §8.2：fit 六种齐全，fixed 也要可选)
  it('适配方式选项包含 fixed', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.main"]').trigger('click')
    await flushPromises()
    const values = wrapper.get('[data-studio-asset-fit]').findAll('option').map((option) => option.element.value)
    expect(values).toEqual(['fixed', 'contain', 'cover', 'stretch', 'tile', 'nineSlice'])
    wrapper.unmount()
  })

  // user:“按这个设计方案审…补齐”+(方案 §10.1 自动保存草稿：重开恢复，取消/发布清除)
  it('草稿自动保存：重开编辑器恢复，取消后清除', async () => {
    let wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#123456')
    await flushPromises()
    await vi.waitFor(() => expect(localStorage.getItem('sunday.themeStudio.draft.v1')).toContain('#123456'))
    wrapper.unmount()

    wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    expect((wrapper.get('[data-studio-field="color"]').element as HTMLInputElement).value).toBe('#123456')

    await wrapper.get('[data-studio-cancel]').trigger('click')
    await flushPromises()
    expect(localStorage.getItem('sunday.themeStudio.draft.v1')).toBeNull()
    wrapper.unmount()
  })

  it('发布成功后草稿自动保存被清除', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#223344')
    await flushPromises()
    await vi.waitFor(() => expect(localStorage.getItem('sunday.themeStudio.draft.v1')).toBeTruthy())

    const publish = wrapper.get('[data-studio-publish]')
    await publish.trigger('click')
    await flushPromises()
    expect(localStorage.getItem('sunday.themeStudio.draft.v1')).toBeNull()
    wrapper.unmount()
  })

  // user:“按这个设计方案审…补齐”+(独立审查 P0 回归守卫：消息/会话实例常因虚拟列表或
  //  未打开的页面而不在 DOM 里，发布不得按 DOM 判孤立误删合法覆盖。)
  it('发布不删除界面上暂不存在的实例覆盖', async () => {
    const node = document.createElement('div')
    node.dataset.uiTemplate = 'template.message'
    node.dataset.uiInstance = 'message:m1'
    document.body.append(node)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    await flushPromises()
    // 默认是模板作用域；显式切到“此实例”才写这一条。
    await wrapper.get('[data-studio-scope]').setValue('instance')
    await wrapper.get('[data-studio-field="color"]').setValue('#0a0b0c')
    await flushPromises()

    node.remove()
    await flushPromises()
    const publish = wrapper.get('[data-studio-publish]')
    await publish.trigger('click')
    await flushPromises()
    expect(publishedStyle()?.textContent).toContain('[data-ui-instance="message:m1"]')
    wrapper.unmount()
  })

  // user:“按这个设计方案审…补齐”+(独立审查 P1：导入失败必须给提示，非法文档不进草稿)
  it('导入非法主题文件给出明确错误', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    const input = wrapper.get('input[accept="application/json,.json"]').element as HTMLInputElement

    const broken = new File(['{"schemaVersion":99}'], 'broken.json', { type: 'application/json' })
    Object.defineProperty(input, 'files', { value: [broken] })
    input.dispatchEvent(new Event('change'))
    // 版本超前的文档在迁移阶段就被拒绝，且错误信息直接可见。
    await vi.waitFor(() => expect(wrapper.text()).toContain('主题版本 99 高于当前支持的'))
    expect(previewStyle()?.textContent || '').toBe('')
    wrapper.unmount()
  })

  // user:“按这个设计方案审…补齐”+(独立审查 P2：拖拽中 Esc 废弃本次拖拽，不提交位移)
  it('拖拽中按 Esc 废弃本次拖拽', async () => {
    const target = document.createElement('div')
    target.dataset.uiId = 'shell.app-rail'
    target.getBoundingClientRect = () => ({ left: 100, top: 100, width: 40, height: 40, right: 140, bottom: 140, x: 100, y: 100, toJSON: () => ({}) }) as DOMRect
    document.body.append(target)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.app-rail"]').trigger('click')

    target.dispatchEvent(pointerEvent('pointerdown', 100, 100))
    document.dispatchEvent(pointerEvent('pointermove', 140, 100))
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    document.dispatchEvent(pointerEvent('pointerup', 140, 100))
    await flushPromises()
    expect(previewStyle()?.textContent || '').not.toContain('translate')
    expect(target.style.translate).toBe('')
    wrapper.unmount()
    target.remove()
  })

  // user:“按这个设计方案审…补齐”+(独立审查 P2：恢复默认不可回退，需要确认)
  it('恢复默认需确认后才清空', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#335577')
    await flushPromises()

    await wrapper.get('[data-studio-reset]').trigger('click')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('#335577')

    await wrapper.get('.core-confirm__submit').trigger('click')
    await flushPromises()
    expect(previewStyle()?.textContent || '').not.toContain('#335577')
    // 独立审查 P2：确认后对话框要自动收起。
    expect(wrapper.find('.core-confirm').exists()).toBe(false)
    wrapper.unmount()
  })

  // user:“按这个设计方案审…补齐”+(独立审查 P1：浏览态辅助覆盖层全部消失)
  it('关闭编辑模式后父容器与模板标注消失', async () => {
    const parent = document.createElement('div')
    parent.dataset.uiId = 'shell.root'
    const child = document.createElement('div')
    child.dataset.uiId = 'shell.app-rail'
    parent.append(child)
    document.body.append(parent)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.app-rail"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('.studio-parent-box').exists()).toBe(true)

    await wrapper.get('[data-studio-edit-mode] input[type="checkbox"]').setValue(false)
    await flushPromises()
    expect(wrapper.find('.studio-parent-box').exists()).toBe(false)
    expect(wrapper.find('.studio-links line').exists()).toBe(false)
    wrapper.unmount()
    parent.remove()
  })

  // user:“按这个设计方案审…补齐”+(独立审查可用性项：关闭但保留草稿的入口)
  it('关闭保留草稿：草稿留在本地，重开还在', async () => {
    let wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#445566')
    await flushPromises()

    await wrapper.get('[data-studio-close]').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('close')).toBeTruthy()
    await vi.waitFor(() => expect(localStorage.getItem('sunday.themeStudio.draft.v1')).toContain('#445566'))
    wrapper.unmount()

    wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    expect((wrapper.get('[data-studio-field="color"]').element as HTMLInputElement).value).toBe('#445566')
    wrapper.unmount()
  })

  // user:“在聊天区，如果我想拖动东西，会直接变成选中文字。在编辑台应该禁用选中文字，专注组件的交互”+
  // (编辑模式开启时给 html 挂 studio-editing，全局禁用文本选择；关闭或退出编辑器立即恢复。)
  it('编辑模式开启时禁用文本选择，关闭与退出后恢复', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    expect(document.documentElement.classList.contains('studio-editing')).toBe(true)

    await wrapper.get('[data-studio-edit-mode] input[type="checkbox"]').setValue(false)
    await flushPromises()
    expect(document.documentElement.classList.contains('studio-editing')).toBe(false)

    await wrapper.get('[data-studio-edit-mode] input[type="checkbox"]').setValue(true)
    await flushPromises()
    expect(document.documentElement.classList.contains('studio-editing')).toBe(true)

    wrapper.unmount()
    expect(document.documentElement.classList.contains('studio-editing')).toBe(false)
  })

  // user:“添加图片应该是一个按钮。如果成功添加图片之后，该按钮应换成图片的小号预览，点击即可更换图片”+
  // (无素材时显示「选择图片」按钮；有素材后按钮换成缩略图，点缩略图直接打开文件选择换图。)
  it('素材按钮：无图显示文案，有图换成小号预览且点击可更换', async () => {
    localStorage.setItem('sunday.themeStudio.draft.v1', JSON.stringify({
      schemaVersion: 1,
      themeId: 'studio',
      nodes: {
        'shell.sidebar': { background: { type: 'asset', assetRef: 'asset-abc123', fit: 'cover', overflow: 'clipped' } },
      },
      templates: {},
      instances: {},
      breakpoints: [],
      assets: [{
        id: 'asset-abc123',
        sha256: 'a'.repeat(64),
        mime: 'image/png',
        width: 4,
        height: 4,
        url: 'data:image/png;base64,QQ==',
      }],
      updatedAt: new Date().toISOString(),
    }))

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()

    // 无素材的元素：按钮显示「选择图片」。
    await wrapper.get('[data-studio-node="shell.main"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-studio-pick-asset]').text()).toContain('选择图片')
    expect(wrapper.find('[data-studio-asset-preview]').exists()).toBe(false)

    // 有素材的元素：按钮换成小号预览。
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await flushPromises()
    const chip = wrapper.get('[data-studio-pick-asset]')
    const preview = chip.get('[data-studio-asset-preview]')
    expect(preview.attributes('src')).toBe('data:image/png;base64,QQ==')

    // 点击预览 = 更换图片：打开文件选择（隐藏 input 收到 click）。
    const fileInput = wrapper.get('input[accept="image/*"]').element as HTMLInputElement
    let pickerOpened = 0
    fileInput.addEventListener('click', () => { pickerOpened += 1 })
    await chip.trigger('click')
    expect(pickerOpened).toBe(1)
    wrapper.unmount()
  })

  // user:“图片和颜色应该有优先级，即内部层级关系：图片应该在颜色的上面，但又在文字的下面”+
  // (颜色铺底、图片覆盖其上、文字属于内容层永远最上；图片背景同时保留底色。)
  it('图片背景保留底色：颜色在下、图片在上', async () => {
    localStorage.setItem('sunday.themeStudio.draft.v1', JSON.stringify({
      schemaVersion: 1,
      themeId: 'studio',
      nodes: {
        'shell.sidebar': { background: { type: 'asset', assetRef: 'asset-abc123', color: '#112233', fit: 'cover', overflow: 'clipped' } },
      },
      templates: {},
      instances: {},
      breakpoints: [],
      assets: [{
        id: 'asset-abc123',
        sha256: 'a'.repeat(64),
        mime: 'image/png',
        width: 4,
        height: 4,
        url: 'data:image/png;base64,QQ==',
      }],
      updatedAt: new Date().toISOString(),
    }))

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await flushPromises()

    const css = previewStyle()?.textContent || ''
    // 底色与图片同一条规则：CSS 绘制顺序保证颜色在下、图片在上、文字在两者之上。
    expect(css).toContain('background-color: #112233')
    expect(css).toContain('background-image: var(--ui-asset-asset-abc123)')

    // 有图片时改背景颜色只换底色，不会把图片弄丢（缩略图仍在）。
    await wrapper.get('[data-studio-field="background"]').setValue('#445566')
    await flushPromises()
    const updated = previewStyle()?.textContent || ''
    expect(updated).toContain('background-color: #445566')
    expect(updated).toContain('background-image: var(--ui-asset-asset-abc123)')
    expect(wrapper.find('[data-studio-asset-preview]').exists()).toBe(true)
    wrapper.unmount()
  })

  // user:“有一些样式，它的背景颜色不是纯色而是透明，而且那个背景色除了可直接选色，也应该和主题 token 关联上吧”+
  // (背景颜色支持：自定义色 / 透明 / 主题令牌（跟随主题预设自动变化），并保留与图片的分层。)
  it('背景颜色支持主题令牌与透明', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-studio-color-token]').setValue('main-background')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('background-color: var(--theme-main-background)')
    // 选令牌时自定义色盘停用，避免两套颜色同时生效的歧义。
    expect((wrapper.get('[data-studio-field="background"]').element as HTMLInputElement).disabled).toBe(true)

    await wrapper.get('[data-studio-color-token]').setValue('transparent')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('background-color: transparent')

    // 切回自定义颜色后色盘可用，取色立即生效。
    await wrapper.get('[data-studio-color-token]').setValue('')
    await flushPromises()
    expect((wrapper.get('[data-studio-field="background"]').element as HTMLInputElement).disabled).toBe(false)
    await wrapper.get('[data-studio-field="background"]').setValue('#123123')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('background-color: #123123')
    wrapper.unmount()
  })

  // user:“图片和颜色应该有优先级……”+(令牌底色同样铺在图片下面)
  it('图片背景可以搭配主题令牌底色', async () => {
    localStorage.setItem('sunday.themeStudio.draft.v1', JSON.stringify({
      schemaVersion: 1,
      themeId: 'studio',
      nodes: {
        'shell.sidebar': {
          background: { type: 'asset', assetRef: 'asset-abc123', colorToken: 'backdrop-background', fit: 'cover', overflow: 'clipped' },
        },
      },
      templates: {},
      instances: {},
      breakpoints: [],
      assets: [{
        id: 'asset-abc123',
        sha256: 'a'.repeat(64),
        mime: 'image/png',
        width: 4,
        height: 4,
        url: 'data:image/png;base64,QQ==',
      }],
      updatedAt: new Date().toISOString(),
    }))

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await flushPromises()

    const css = previewStyle()?.textContent || ''
    expect(css).toContain('background-color: var(--theme-backdrop-background)')
    expect(css).toContain('background-image: var(--ui-asset-asset-abc123)')
    wrapper.unmount()
  })

  // 安全：颜色令牌只接受白名单，导入的主题不能借令牌字段注入任意 CSS。
  it('非法颜色令牌在导入时被拒绝', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    const input = wrapper.get('input[accept="application/json,.json"]').element as HTMLInputElement
    const evilDoc = {
      schemaVersion: 1,
      themeId: 'evil',
      nodes: { 'shell.sidebar': { background: { type: 'solid', colorToken: 'main-background); body{display:none' } } },
      templates: {},
      instances: {},
      breakpoints: [],
      assets: [],
      updatedAt: new Date().toISOString(),
    }
    const file = new File([JSON.stringify(evilDoc)], 'evil.json', { type: 'application/json' })
    Object.defineProperty(input, 'files', { value: [file] })
    input.dispatchEvent(new Event('change'))
    await vi.waitFor(() => expect(wrapper.text()).toContain('背景颜色令牌无效'))
    wrapper.unmount()
  })

  // user:“一个样式最开始是什么颜色，就应该让它显示为什么颜色。除非我单独去设置，
  //  不然我上完图再把图撤了，就会发生突变”+
  // (撤图不能留下任何伪造的底色规则：没设过底色→完全回到原样；设过→原样保留。)
  it('撤掉图片后：没设过底色就恢复原始外观，不留残留规则', async () => {
    localStorage.setItem('sunday.themeStudio.draft.v1', JSON.stringify({
      schemaVersion: 1,
      themeId: 'studio',
      nodes: {
        'shell.sidebar': { background: { type: 'asset', assetRef: 'asset-abc123', fit: 'cover', overflow: 'clipped' } },
      },
      templates: {},
      instances: {},
      breakpoints: [],
      assets: [{
        id: 'asset-abc123',
        sha256: 'a'.repeat(64),
        mime: 'image/png',
        width: 4,
        height: 4,
        url: 'data:image/png;base64,QQ==',
      }],
      updatedAt: new Date().toISOString(),
    }))

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('background-image: var(--ui-asset-asset-abc123)')

    await wrapper.get('[data-studio-clear-asset]').trigger('click')
    await flushPromises()
    const css = previewStyle()?.textContent || ''
    // 没有单独的底色设置 → 背景覆盖整条消失，组件自己的样式原样显示。
    expect(css).not.toContain('background-color')
    expect(css).not.toContain('background-image')
    wrapper.unmount()
  })

  // user:“除非我单独去设置”+(设过底色：撤图后保留那个底色，图片层拿掉)
  it('撤掉图片后：设过的底色原样保留', async () => {
    localStorage.setItem('sunday.themeStudio.draft.v1', JSON.stringify({
      schemaVersion: 1,
      themeId: 'studio',
      nodes: {
        'shell.sidebar': { background: { type: 'asset', assetRef: 'asset-abc123', color: '#112233', fit: 'cover', overflow: 'clipped' } },
      },
      templates: {},
      instances: {},
      breakpoints: [],
      assets: [{
        id: 'asset-abc123',
        sha256: 'a'.repeat(64),
        mime: 'image/png',
        width: 4,
        height: 4,
        url: 'data:image/png;base64,QQ==',
      }],
      updatedAt: new Date().toISOString(),
    }))

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-studio-clear-asset]').trigger('click')
    await flushPromises()
    const css = previewStyle()?.textContent || ''
    expect(css).toContain('background-color: #112233')
    expect(css).not.toContain('var(--ui-asset-asset-abc123)')
    wrapper.unmount()
  })

  // user:“一个样式最开始是什么颜色，就应该让它显示为什么颜色”+(导入主题里带的渐变底，上图再撤图要原样回来)
  it('撤掉图片后：原有渐变背景原样恢复', async () => {
    localStorage.setItem('sunday.themeStudio.draft.v1', JSON.stringify({
      schemaVersion: 1,
      themeId: 'studio',
      nodes: {
        'shell.sidebar': {
          background: {
            type: 'asset',
            assetRef: 'asset-abc123',
            fit: 'cover',
            overflow: 'clipped',
            angle: 90,
            stops: [{ color: '#111111', position: 0 }, { color: '#222222', position: 100 }],
          },
        },
      },
      templates: {},
      instances: {},
      breakpoints: [],
      assets: [{
        id: 'asset-abc123',
        sha256: 'a'.repeat(64),
        mime: 'image/png',
        width: 4,
        height: 4,
        url: 'data:image/png;base64,QQ==',
      }],
      updatedAt: new Date().toISOString(),
    }))

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-studio-clear-asset]').trigger('click')
    await flushPromises()
    const css = previewStyle()?.textContent || ''
    expect(css).toContain('linear-gradient(90deg, #111111 0%, #222222 100%)')
    expect(css).not.toContain('var(--ui-asset-asset-abc123)')
    wrapper.unmount()
  })

  // user:“那个间距是干啥的？为什么我调了半天也没有反应呢？”+
  // (gap 只对 flex/grid 生效；块级容器改用子项外边距，保证间距一定看得见效果。)
  it('间距：flex 容器走 gap，块级容器走子项外边距', async () => {
    const flexTarget = document.createElement('div')
    flexTarget.dataset.uiId = 'shell.app-rail'
    flexTarget.style.display = 'flex'
    document.body.append(flexTarget)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.app-rail"]').trigger('click')
    await wrapper.get('[data-studio-field="gap"]').setValue('10')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('gap: 10px')
    expect(previewStyle()?.textContent || '').not.toContain('margin-block-start')
    wrapper.unmount()
    flexTarget.remove()

    const blockTarget = document.createElement('div')
    blockTarget.dataset.uiId = 'shell.app-rail'
    document.body.append(blockTarget)

    const second = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await second.get('[data-studio-node="shell.app-rail"]').trigger('click')
    await second.get('[data-studio-field="gap"]').setValue('12')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('> * + * { margin-block-start: 12px }')
    expect(previewStyle()?.textContent || '').not.toContain('gap: 12px')
    second.unmount()
    blockTarget.remove()
  })

  // user:“我不是说过图像不被容器裁切吗”+
  // (允许溢出组件=图片按原始尺寸居中绘制、超出组件边界的部分可见，文字仍在最上层。)
  it('允许溢出组件：图片按原始尺寸外绘，不再被裁切', async () => {
    localStorage.setItem('sunday.themeStudio.draft.v1', JSON.stringify({
      schemaVersion: 1,
      themeId: 'studio',
      nodes: {
        'shell.sidebar': {
          background: {
            type: 'asset',
            assetRef: 'asset-abc123',
            fit: 'cover',
            overflow: 'local-visible',
            overflowHost: 'relative',
          },
        },
      },
      templates: {},
      instances: {},
      breakpoints: [],
      assets: [{
        id: 'asset-abc123',
        sha256: 'a'.repeat(64),
        mime: 'image/png',
        width: 200,
        height: 100,
        url: 'data:image/png;base64,QQ==',
      }],
      updatedAt: new Date().toISOString(),
    }))

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await flushPromises()

    const css = previewStyle()?.textContent || ''
    // 组件本体不再裁切，并成为定位宿主；图片层按原始尺寸居中，可越过组件边界。
    expect(css).toContain('overflow: visible')
    expect(css).toContain('position: relative')
    expect(css).toContain('::before')
    expect(css).toContain('width: 200px')
    expect(css).toContain('height: 100px')
    expect(css).toContain('background-image: var(--ui-asset-asset-abc123)')
    expect(css).toContain('pointer-events: none')
    wrapper.unmount()
  })

  // user:“我编辑了一个会话名称，那么所有的会话名称最好都与它一致，同时一起改变”+
  // (内部同类元素登记为模板：会话名称/项目名称/项目行，改一处全部同步。)
  it('会话名称、项目名称、项目行都是可共享编辑的模板', async () => {
    const sessionTitle = document.createElement('span')
    sessionTitle.dataset.uiTemplate = 'template.session-title'
    document.body.append(sessionTitle)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="template.session-title"]').trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#778899')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('[data-ui-template="template.session-title"][data-ui-template]')
    expect(previewStyle()?.textContent).toContain('color: #778899')

    const labels = wrapper.findAll('[data-studio-node]').map((node) => node.text())
    expect(labels.some((text) => text.includes('会话名称'))).toBe(true)
    expect(labels.some((text) => text.includes('项目名称'))).toBe(true)
    expect(labels.some((text) => text.includes('项目行'))).toBe(true)
    wrapper.unmount()
    sessionTitle.remove()
  })

  // user:“按理说我编辑了一个会话行，所有的会话行都会被应用成一样的东西”+
  // (点实例默认写模板，所有同类一起变；要改单条时从作用域下拉显式切“此实例”。)
  it('点击实例默认编辑模板，同类一起变；切到此实例才只改一条', async () => {
    const first = document.createElement('div')
    first.dataset.uiTemplate = 'template.conversation'
    first.dataset.uiInstance = 'session:s1'
    const second = document.createElement('div')
    second.dataset.uiTemplate = 'template.conversation'
    second.dataset.uiInstance = 'session:s2'
    document.body.append(first, second)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    first.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    await flushPromises()

    // 默认就是模板作用域：改颜色所有会话行一起变。
    await wrapper.get('[data-studio-field="color"]').setValue('#667788')
    await flushPromises()
    const css = previewStyle()?.textContent || ''
    expect(css).toContain('[data-ui-template="template.conversation"][data-ui-template]')
    expect(css).not.toContain('[data-ui-instance="session:s1"]')

    // 显式切到“此实例”后，才只写这一条。
    await wrapper.get('[data-studio-scope]').setValue('instance')
    await wrapper.get('[data-studio-field="color"]').setValue('#111213')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('[data-ui-instance="session:s1"]')
    wrapper.unmount()
    first.remove()
    second.remove()
  })

  // user:“为什么没有拉伸拖拽功能，比如……会话列表中的某一项有点太大了，我想把它缩小一下”+
  // (选中可调尺寸的元素出现边线手柄：拖动手柄实时改尺寸，松手写进当前作用域。)
  it('边界手柄拖拽改尺寸，松手写入样式', async () => {
    const target = document.createElement('div')
    target.dataset.uiId = 'shell.app-rail'
    target.getBoundingClientRect = () => ({ left: 100, top: 100, width: 100, height: 40, right: 200, bottom: 140, x: 100, y: 100, toJSON: () => ({}) }) as DOMRect
    document.body.append(target)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.app-rail"]').trigger('click')
    await flushPromises()
    const handle = wrapper.get('[data-studio-resize="e"]')
    expect(handle.exists()).toBe(true)

    handle.element.dispatchEvent(pointerEvent('pointerdown', 200, 120))
    document.dispatchEvent(pointerEvent('pointermove', 240, 120))
    document.dispatchEvent(pointerEvent('pointerup', 240, 120))
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('width: 140px')
    wrapper.unmount()
    target.remove()
  })

  // 仅外观元素（没有 size 权限）不显示缩放手柄，避免假手柄。
  it('没有尺寸权限的元素不显示缩放手柄', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.main"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-studio-resize]').exists()).toBe(false)
    wrapper.unmount()
  })

  // user:“添加的图像应该可以裁切、位移、缩放等等”+(适配方式=裁切；这里补位置与缩放)
  it('背景图片支持位置与缩放', async () => {
    localStorage.setItem('sunday.themeStudio.draft.v1', JSON.stringify({
      schemaVersion: 1,
      themeId: 'studio',
      nodes: {
        'shell.sidebar': { background: { type: 'asset', assetRef: 'asset-abc123', fit: 'cover', overflow: 'clipped' } },
      },
      templates: {},
      instances: {},
      breakpoints: [],
      assets: [{
        id: 'asset-abc123',
        sha256: 'a'.repeat(64),
        mime: 'image/png',
        width: 200,
        height: 100,
        url: 'data:image/png;base64,QQ==',
      }],
      updatedAt: new Date().toISOString(),
    }))

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-studio-bg-pos="x"]').setValue('20')
    await wrapper.get('[data-studio-bg-pos="y"]').setValue('80')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('background-position: 20% 80%')

    await wrapper.get('[data-studio-bg-scale]').setValue('2')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('background-size: 400px auto')
    wrapper.unmount()
  })

  // user:“把图片的编辑器给做成九宫格裁切，九宫格可拖动，九宫格就代表了这个图片实际显示进去的是什么部分”+
  // (面板里显示整图预览+三等分参考线；整块九宫格=组件实际显示区域，拖动它平移取景。
  //  帧 220×150、素材 200×100、cover、1×：横向溢出 80px，右移 40px = 位置从 50% 挪到 0%。)
  it('九宫格裁切器：跟随组件真实比例，拖动改变图片实际显示的部分', async () => {
    const stage = document.createElement('div')
    stage.dataset.uiId = 'shell.sidebar'
    stage.getBoundingClientRect = () => ({ left: 0, top: 0, width: 300, height: 120, right: 300, bottom: 120, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect
    document.body.append(stage)
    localStorage.setItem('sunday.themeStudio.draft.v1', JSON.stringify({
      schemaVersion: 1,
      themeId: 'studio',
      nodes: {
        'shell.sidebar': { background: { type: 'asset', assetRef: 'asset-abc123', fit: 'cover', overflow: 'clipped' } },
      },
      templates: {},
      instances: {},
      breakpoints: [],
      assets: [{
        id: 'asset-abc123',
        sha256: 'a'.repeat(64),
        mime: 'image/png',
        width: 200,
        height: 100,
        url: 'data:image/png;base64,QQ==',
      }],
      updatedAt: new Date().toISOString(),
    }))

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await flushPromises()

    const crop = wrapper.get('[data-studio-crop]')
    expect(crop.find('.studio-crop-grid').exists()).toBe(true)
    // 九宫格取景框与组件实际显示范围同比例（300×120 → 2.5）。
    expect(crop.attributes('style')).toContain('aspect-ratio: 2.5')

    crop.element.dispatchEvent(pointerEvent('pointerdown', 100, 100))
    document.dispatchEvent(pointerEvent('pointermove', 140, 100))
    document.dispatchEvent(pointerEvent('pointerup', 140, 100))
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('background-position: 0% 50%')
    wrapper.unmount()
    stage.remove()
  })

  // user:“不点击双栏键时，右键点击任何一个组件，会在它的旁边找一个位置展开小版右栏，就是不能遮挡那个组件”+
  // (小版右栏出现在元素右侧；点双栏键展开完整双栏时小版收起。)
  it('右键组件展开不遮挡的小版右栏', async () => {
    const target = document.createElement('div')
    target.dataset.uiId = 'shell.sidebar'
    target.getBoundingClientRect = () => ({ left: 100, top: 100, width: 80, height: 40, right: 180, bottom: 140, x: 100, y: 100, toJSON: () => ({}) }) as DOMRect
    document.body.append(target)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    target.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }))
    await flushPromises()

    const props = wrapper.get('[data-studio-panel="props"]')
    expect(props.classes()).toContain('is-mini')
    expect(props.attributes('data-studio-mini-inspector')).toBe('true')
    expect(props.text()).toContain('会话列表')
    // 位于目标右侧（180 + 12），不遮挡元素。
    expect(props.attributes('style')).toContain('left: 192px')

    // 点卡片键展开完整双栏 → 小版右栏收起。
    await wrapper.get('[data-studio-open-props]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-studio-panel="props"]').classes()).not.toContain('is-mini')
    expect(wrapper.get('[data-studio-panel="props"]').classes()).toContain('is-open')
    wrapper.unmount()
    target.remove()
  })

  // user:“在编辑状态下，应该禁用掉原有的交互，比如说拖动会话栏排序”+
  // (mousedown/dragstart 在捕获层被拦，组件自身的拖拽排序不会启动；关闭编辑模式即恢复。)
  it('编辑模式屏蔽组件自身的拖拽排序交互', async () => {
    const target = document.createElement('div')
    target.dataset.uiId = 'shell.sidebar'
    document.body.append(target)
    let mousedowns = 0
    target.addEventListener('mousedown', () => { mousedowns += 1 })

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()

    target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
    const dragEvent = new Event('dragstart', { bubbles: true, cancelable: true })
    target.dispatchEvent(dragEvent)
    expect(mousedowns).toBe(0)
    expect(dragEvent.defaultPrevented).toBe(true)

    await wrapper.get('[data-studio-edit-mode] input[type="checkbox"]').setValue(false)
    await flushPromises()
    target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
    expect(mousedowns).toBe(1)
    wrapper.unmount()
    target.remove()
  })

  // user:“把布局规则变量给统一……不要再有写死的值和无法被改变的值”+
  // (会话抽屉改宽度=写 --layout-sidebar-width 变量，主区域等派生位置自动跟随)
  it('外壳容器改尺寸写入布局变量，而不是写死元素宽度', async () => {
    const target = document.createElement('div')
    target.dataset.uiId = 'shell.left-drawer'
    target.getBoundingClientRect = () => ({ left: 100, top: 60, width: 200, height: 400, right: 300, bottom: 460, x: 100, y: 60, toJSON: () => ({}) }) as DOMRect
    document.body.append(target)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.left-drawer"]').trigger('click')
    await flushPromises()

    const handle = wrapper.get('[data-studio-resize="e"]')
    handle.element.dispatchEvent(pointerEvent('pointerdown', 300, 200))
    document.dispatchEvent(pointerEvent('pointermove', 340, 200))
    document.dispatchEvent(pointerEvent('pointerup', 340, 200))
    await flushPromises()

    const css = previewStyle()?.textContent || ''
    expect(css).toContain('--layout-sidebar-width: 240px')
    expect(css).not.toContain('[data-ui-id="shell.left-drawer"][data-ui-id] { width')
    wrapper.unmount()
    target.remove()
  })

  // user:“装文字它本身就是一个容器，它是可以被拖动拉伸的，就像 PPT 里面一样”+
  // (文字容器同样有把柄：拉伸写模板宽度，所有同类文字一起变)
  it('文字容器可调尺寸，写的是文字节点本身的尺寸', async () => {
    const target = document.createElement('div')
    target.dataset.uiTemplate = 'template.project-name'
    target.getBoundingClientRect = () => ({ left: 100, top: 100, width: 120, height: 20, right: 220, bottom: 120, x: 100, y: 100, toJSON: () => ({}) }) as DOMRect
    document.body.append(target)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="template.project-name"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-studio-resize="e"]').exists()).toBe(true)

    wrapper.get('[data-studio-resize="e"]').element.dispatchEvent(pointerEvent('pointerdown', 220, 110))
    document.dispatchEvent(pointerEvent('pointermove', 260, 110))
    document.dispatchEvent(pointerEvent('pointerup', 260, 110))
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('[data-ui-template="template.project-name"][data-ui-template]')
    expect(previewStyle()?.textContent).toContain('width: 160px')
    wrapper.unmount()
    target.remove()
  })

  // user:“我认为主区和分屏本质是一个容器”+
  // (拖分屏主面板宽度=写内容区变量，主区/输入栏一起跟随)
  it('分屏主面板改尺寸写入内容区布局变量', async () => {
    const target = document.createElement('div')
    target.dataset.uiId = 'shell.split'
    target.getBoundingClientRect = () => ({ left: 0, top: 0, width: 600, height: 400, right: 600, bottom: 400, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect
    document.body.append(target)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.split"]').trigger('click')
    await flushPromises()

    wrapper.get('[data-studio-resize="e"]').element.dispatchEvent(pointerEvent('pointerdown', 600, 200))
    document.dispatchEvent(pointerEvent('pointermove', 680, 200))
    document.dispatchEvent(pointerEvent('pointerup', 680, 200))
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('--layout-split-primary-width: 680px')
    wrapper.unmount()
    target.remove()
  })

  // user:“它应该是相对原版做了什么调整……比如 X+1 Y-2”+
  // (消息行高度改的是“在自身实际高度后叠加的增量”，不写绝对高度、不压平内容)
  it('消息流子项调高度存增量，不写绝对高度', async () => {
    const target = document.createElement('div')
    target.dataset.uiTemplate = 'template.message'
    target.getBoundingClientRect = () => ({ left: 100, top: 100, width: 400, height: 80, right: 500, bottom: 180, x: 100, y: 100, toJSON: () => ({}) }) as DOMRect
    document.body.append(target)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="template.message"]').trigger('click')
    await flushPromises()

    wrapper.get('[data-studio-resize="s"]').element.dispatchEvent(pointerEvent('pointerdown', 300, 180))
    document.dispatchEvent(pointerEvent('pointermove', 300, 200))
    document.dispatchEvent(pointerEvent('pointerup', 300, 200))
    await flushPromises()
    const css = previewStyle()?.textContent || ''
    // 拖了 +20px：只记增量，绝不出现 height 覆盖。
    expect(css).toContain('margin-block-end: 20px')
    expect(css).not.toMatch(/(^|[^-])height: 20px/)
    wrapper.unmount()
    target.remove()
  })

  // user:“如果它超出了父节点的位置，那要把父节点也自动撑大”+
  // (子级放大越界 → 父级最小尺寸按溢出量增加)
  it('子节点越界时父节点自动撑大', async () => {
    const parent = document.createElement('div')
    parent.dataset.uiId = 'shell.sidebar'
    parent.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100, right: 100, bottom: 100, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect
    const child = document.createElement('div')
    child.dataset.uiId = 'chat.thread'
    child.getBoundingClientRect = () => ({ left: 10, top: 10, width: 200, height: 50, right: 210, bottom: 60, x: 10, y: 10, toJSON: () => ({}) }) as DOMRect
    parent.append(child)
    document.body.append(parent)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="chat.thread"]').trigger('click')
    await flushPromises()

    // 提交一次尺寸（拖右边线 0px 也走同步）：父级宽度 100 → 最小宽度撑到 100+110。
    wrapper.get('[data-studio-resize="e"]').element.dispatchEvent(pointerEvent('pointerdown', 210, 30))
    document.dispatchEvent(pointerEvent('pointermove', 210, 30))
    document.dispatchEvent(pointerEvent('pointerup', 210, 30))
    await flushPromises()

    const css = previewStyle()?.textContent || ''
    expect(css).toContain('[data-ui-id="shell.sidebar"][data-ui-id]')
    expect(css).toContain('min-width: 210px')
    wrapper.unmount()
    parent.remove()
  })

  // user:“在父节点缩小的时候，也要把子节点自动缩回去”+
  // (父级缩小后，子级的位移被夹回父级范围内)
  it('父节点缩小后子节点位移自动回缩', async () => {
    localStorage.setItem('sunday.themeStudio.draft.v1', JSON.stringify({
      schemaVersion: 1,
      themeId: 'studio',
      nodes: { 'shell.main': { offset: { x: 40, y: 0 } } },
      templates: {},
      instances: {},
      breakpoints: [],
      assets: [],
      updatedAt: new Date().toISOString(),
    }))

    const parent = document.createElement('div')
    parent.dataset.uiId = 'shell.sidebar'
    parent.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100, right: 100, bottom: 100, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect
    const child = document.createElement('div')
    child.dataset.uiId = 'shell.main'
    // 自然位置 20，宽 90：右缘 110 已超出父级 100；translate 40 使其更远。
    child.getBoundingClientRect = () => ({ left: 60, top: 10, width: 90, height: 30, right: 150, bottom: 40, x: 60, y: 10, toJSON: () => ({}) }) as DOMRect
    parent.append(child)
    document.body.append(parent)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await flushPromises()

    // 提交一次父级尺寸（拖 0px ），触发子级回缩：x 从 40 夹到 -10。
    wrapper.get('[data-studio-resize="e"]').element.dispatchEvent(pointerEvent('pointerdown', 100, 50))
    document.dispatchEvent(pointerEvent('pointermove', 100, 50))
    document.dispatchEvent(pointerEvent('pointerup', 100, 50))
    await flushPromises()

    expect(previewStyle()?.textContent).toContain('translate: -10px 0px')
    wrapper.unmount()
    parent.remove()
  })

  // user:“桌面壳作为底层容器 不应该有任何容器能够超出它”+
  // (拖动和拉尺寸都以 shell.root 的矩形为最终边界，越界会被夹回来)
  it('拖动与拉尺寸都不能超出桌面壳', async () => {
    const shell = document.createElement('div')
    shell.dataset.uiId = 'shell.root'
    shell.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 800, right: 1000, bottom: 800, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect
    const main = document.createElement('div')
    main.dataset.uiId = 'shell.main'
    const base = { left: 100, top: 100, width: 400, height: 300 }
    // 让矩形跟随拖动时的 translate，才能验证“拖到壳外会被夹回来”。
    main.getBoundingClientRect = () => {
      const parts = (main.style.translate || '0px 0px').split(' ').map((value) => Number.parseFloat(value) || 0)
      const left = base.left + (parts[0] || 0)
      const top = base.top + (parts[1] || 0)
      return { left, top, width: base.width, height: base.height, right: left + base.width, bottom: top + base.height, x: left, y: top, toJSON: () => ({}) } as DOMRect
    }
    shell.append(main)
    document.body.append(shell)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    // 关掉吸附，避免贴边自动转成锚点；这里只验证外壳边界。
    await wrapper.get('[data-studio-snap-toggle]').trigger('click')
    await wrapper.get('[data-studio-node="shell.main"]').trigger('click')
    await flushPromises()

    // 往右下拖 600/500：壳只到 1000×800，位移从 600/500 夹到 500/400。
    main.dispatchEvent(pointerEvent('pointerdown', 100, 100))
    document.dispatchEvent(pointerEvent('pointermove', 700, 600))
    document.dispatchEvent(pointerEvent('pointerup', 700, 600))
    await flushPromises()
    expect(previewStyle()?.textContent ?? '').toContain('translate: 500px 400px')

    // 往左上拖出壳：位移夹回 -100/-100，元素左/上边贴住外壳。
    main.dispatchEvent(pointerEvent('pointerdown', 700, 600))
    document.dispatchEvent(pointerEvent('pointermove', -300, -400))
    document.dispatchEvent(pointerEvent('pointerup', -300, -400))
    await flushPromises()
    expect(previewStyle()?.textContent ?? '').toContain('translate: -100px -100px')

    // 拉右边线 2000px：宽度最多到外壳右缘（1000 - 100 = 900）。
    wrapper.get('[data-studio-resize="e"]').element.dispatchEvent(pointerEvent('pointerdown', 500, 250))
    document.dispatchEvent(pointerEvent('pointermove', 2500, 250))
    document.dispatchEvent(pointerEvent('pointerup', 2500, 250))
    await flushPromises()
    expect(previewStyle()?.textContent ?? '').toContain('width: 900px')
    wrapper.unmount()
    shell.remove()
  })

  // user:“我开分屏的时候是不是会导致界面缩小？缩小之后，如果消息流写了一个绝对数值，那肯定就超出了”+
  // (消息流宽度写成“填满所在屏 + 上限”，分屏变窄自动跟随，不写死绝对宽度)
  it('消息流宽度写成填满加上限，分屏变窄不溢出', async () => {
    const target = document.createElement('div')
    target.dataset.uiId = 'chat.thread'
    target.getBoundingClientRect = () => ({ left: 0, top: 0, width: 900, height: 600, right: 900, bottom: 600, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect
    document.body.append(target)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="chat.thread"]').trigger('click')
    await flushPromises()

    wrapper.get('[data-studio-resize="e"]').element.dispatchEvent(pointerEvent('pointerdown', 900, 300))
    document.dispatchEvent(pointerEvent('pointermove', 940, 300))
    document.dispatchEvent(pointerEvent('pointerup', 940, 300))
    await flushPromises()

    const css = previewStyle()?.textContent || ''
    expect(css).toContain('width: 100%')
    expect(css).toContain('max-width: 940px')
    expect(css).not.toMatch(/(^|[^-])width: 940px/)
    wrapper.unmount()
    target.remove()
  })

  // user:“在使用时，如果是由于响应式变化导致的收缩，这个是不要永久存的”+
  // (运行期窗口变化只更新覆盖层，不往草稿/存储写任何值)
  it('运行期响应式变化不回写主题', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await wrapper.get('[data-studio-field="color"]').setValue('#123456')
    await flushPromises()
    await vi.waitFor(() => expect(localStorage.getItem('sunday.themeStudio.draft.v1')).toContain('#123456'))
    const before = localStorage.getItem('sunday.themeStudio.draft.v1')

    window.dispatchEvent(new Event('resize'))
    await flushPromises()
    window.dispatchEvent(new Event('scroll'))
    await flushPromises()
    // 等一个防抖周期，确认没有任何新写入。
    await new Promise((resolve) => setTimeout(resolve, 350))
    expect(localStorage.getItem('sunday.themeStudio.draft.v1')).toBe(before)
    wrapper.unmount()
  })

  // user:“子容器应当是相对于父容器的某一个边……在兜底呢，就是距离不得小于 0”+
  // (左/上越界：父级不向左上生长，回夹子级位移，与父边距离归 0)
  it('子节点从左侧越界时回夹到位移距离为 0', async () => {
    localStorage.setItem('sunday.themeStudio.draft.v1', JSON.stringify({
      schemaVersion: 1,
      themeId: 'studio',
      nodes: { 'chat.thread': { offset: { x: 0, y: 0 } } },
      templates: {},
      instances: {},
      breakpoints: [],
      assets: [],
      updatedAt: new Date().toISOString(),
    }))

    const parent = document.createElement('div')
    parent.dataset.uiId = 'shell.sidebar'
    parent.getBoundingClientRect = () => ({ left: 100, top: 100, width: 200, height: 100, right: 300, bottom: 200, x: 100, y: 100, toJSON: () => ({}) }) as DOMRect
    const child = document.createElement('div')
    child.dataset.uiId = 'chat.thread'
    // 子级左缘 60，比父级左缘 100 少 40：距离为负，兜底应回夹 40。
    child.getBoundingClientRect = () => ({ left: 60, top: 110, width: 100, height: 30, right: 160, bottom: 140, x: 60, y: 110, toJSON: () => ({}) }) as DOMRect
    parent.append(child)
    document.body.append(parent)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="chat.thread"]').trigger('click')
    await flushPromises()

    // 提交一次尺寸（拖 0px），触发越界兜底。
    wrapper.get('[data-studio-resize="e"]').element.dispatchEvent(pointerEvent('pointerdown', 160, 130))
    document.dispatchEvent(pointerEvent('pointermove', 160, 130))
    document.dispatchEvent(pointerEvent('pointerup', 160, 130))
    await flushPromises()

    expect(previewStyle()?.textContent).toContain('translate: 40px 0px')
    wrapper.unmount()
    parent.remove()
  })

  // user:“子容器应当是相对于父容器的某一个边或者某几个边，设定距离，而兜底就是距离不得小于 0”+
  // (方案 §4.4：锚点编译成相对父边的绝对边距；父容器自动成为定位宿主)
  it('锚点：相对父容器边设定距离，父容器成为定位宿主', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="template.message"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-studio-anchor-edge="h"]').setValue('left')
    await wrapper.get('[data-studio-anchor-offset="h"]').setValue('12')
    await wrapper.get('[data-studio-anchor-edge="v"]').setValue('top')
    await wrapper.get('[data-studio-anchor-offset="v"]').setValue('8')
    await flushPromises()

    const css = previewStyle()?.textContent || ''
    expect(css).toContain('[data-ui-template="template.message"][data-ui-template]')
    expect(css).toContain('position: absolute')
    expect(css).toContain('left: 12px')
    expect(css).toContain('top: 8px')
    // 父容器（会话内容）自动成为定位宿主。
    expect(css).toContain('[data-ui-id="chat.thread"][data-ui-id] { position: relative }')
    wrapper.unmount()
  })

  // user:“贴近父级边界 → 预览边界锚点；释放后保留该边距”+(方案 §4.5 拖拽推断)
  it('拖动贴住父边松手后保存为边锚点', async () => {
    const parent = document.createElement('div')
    parent.dataset.uiId = 'shell.sidebar'
    parent.style.display = 'grid'
    parent.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 300, right: 400, bottom: 300, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect
    const child = document.createElement('div')
    child.dataset.uiId = 'chat.thread'
    // 左缘距父边 2px（吸附阈值内），纵向不在任何边/中心线附近。
    child.getBoundingClientRect = () => ({ left: 2, top: 50, width: 100, height: 40, right: 102, bottom: 90, x: 2, y: 50, toJSON: () => ({}) }) as DOMRect
    parent.append(child)
    document.body.append(parent)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="chat.thread"]').trigger('click')
    await flushPromises()

    child.dispatchEvent(pointerEvent('pointerdown', 50, 60))
    document.dispatchEvent(pointerEvent('pointermove', 54, 60))
    document.dispatchEvent(pointerEvent('pointerup', 54, 60))
    await flushPromises()

    const css = previewStyle()?.textContent || ''
    expect(css).toContain('position: absolute')
    expect(css).toContain('left: 2px')
    wrapper.unmount()
    parent.remove()
  })

  // user:“只经过吸附线不松手、或用户禁用吸附时 → 不保存关系”+(禁吸附时只存位移)
  it('禁用吸附时不生成锚点，只保存位移', async () => {
    const parent = document.createElement('div')
    parent.dataset.uiId = 'shell.sidebar'
    parent.style.display = 'grid'
    parent.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 300, right: 400, bottom: 300, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect
    const child = document.createElement('div')
    child.dataset.uiId = 'chat.thread'
    child.getBoundingClientRect = () => ({ left: 2, top: 50, width: 100, height: 40, right: 102, bottom: 90, x: 2, y: 50, toJSON: () => ({}) }) as DOMRect
    parent.append(child)
    document.body.append(parent)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="chat.thread"]').trigger('click')
    await wrapper.get('[data-studio-snap-toggle]').trigger('click')
    await flushPromises()

    child.dispatchEvent(pointerEvent('pointerdown', 50, 60))
    document.dispatchEvent(pointerEvent('pointermove', 54, 60))
    document.dispatchEvent(pointerEvent('pointerup', 54, 60))
    await flushPromises()

    const css = previewStyle()?.textContent || ''
    expect(css).toContain('translate: 4px 0px')
    expect(css).not.toContain('position: absolute')
    wrapper.unmount()
    parent.remove()
  })

  // user:“滚轮每格 ±1px，按 Shift 每格 ±8px；双击标记直接输入数值”+(方案 §5.2 间距胶囊)
  it('间距胶囊：滚轮微调父级行距，Shift 加速，双击可直接输入', async () => {
    const parent = document.createElement('div')
    parent.dataset.uiId = 'shell.sidebar'
    parent.style.display = 'grid'
    parent.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 300, right: 400, bottom: 300, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect
    const child = document.createElement('div')
    child.dataset.uiId = 'chat.thread'
    child.getBoundingClientRect = () => ({ left: 20, top: 40, width: 100, height: 40, right: 120, bottom: 80, x: 20, y: 40, toJSON: () => ({}) }) as DOMRect
    parent.append(child)
    document.body.append(parent)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="chat.thread"]').trigger('click')
    await flushPromises()

    const pill = wrapper.get('[data-studio-gap-pill]')
    expect(pill.text()).toContain('间距 0')

    // jsdom 的 shiftKey 是只读 getter，手动构造 WheelEvent。
    pill.element.dispatchEvent(new WheelEvent('wheel', { deltaY: -1, bubbles: true, cancelable: true }))
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('gap: 1px')

    pill.element.dispatchEvent(new WheelEvent('wheel', { deltaY: -1, shiftKey: true, bubbles: true, cancelable: true }))
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('gap: 9px')

    await pill.trigger('dblclick')
    await flushPromises()
    const input = wrapper.get('[data-studio-gap-input]')
    await input.setValue('20')
    await input.trigger('blur')
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('gap: 20px')
    wrapper.unmount()
    parent.remove()
  })

  // user:“Z-index 从 1~9999 一直分层，100 个 z 为一层”+
  // (层级写进真实的 z-index；未自带定位的元素自动补 position: relative，堆叠才生效)
  it('层级写真实 z-index，未定位元素自动成为定位元素', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="template.message"]').trigger('click')
    await wrapper.get('[data-studio-field="layer"]').setValue('250')
    await flushPromises()

    const css = previewStyle()?.textContent || ''
    expect(css).toContain('z-index: 250')
    expect(css).toContain('position: relative')
    // 自带定位的外壳不补 relative，避免覆盖 fixed/absolute。
    expect(css).not.toMatch(/\[data-ui-id="shell\.main"\]\[data-ui-id\]\s*\{[^}]*position: relative/)
    wrapper.unmount()
  })

  // user:“这个图层应该像 PS 一样可单独编辑，显隐/锁定等”+
  // (eye=只在编辑器隐藏；lock=画布上不响应点选/拖动)
  it('图层显隐与锁定只影响编辑器', async () => {
    const target = document.createElement('div')
    target.dataset.uiId = 'shell.sidebar'
    document.body.append(target)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    // 图层（z）与父子结构分开：眼/锁只在「图层」视图里。
    await wrapper.get('[data-studio-view="layers"]').trigger('click')
    await flushPromises()
    // 先选中另一个元素，验证锁定后点画布不会切到被锁的层。
    await wrapper.get('[data-studio-layer-row="shell.main"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-studio-lock="shell.sidebar"]').trigger('click')
    await flushPromises()
    target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    await flushPromises()
    expect(wrapper.get('[data-studio-layer-row="shell.sidebar"]').classes()).not.toContain('is-selected')
    expect(wrapper.get('[data-studio-layer-row="shell.main"]').classes()).toContain('is-selected')

    // 隐藏只写编辑器会话样式节点，不进主题草稿。
    await wrapper.get('[data-studio-eye="shell.sidebar"]').trigger('click')
    await flushPromises()
    const editorStyle = document.querySelector<HTMLStyleElement>('style[data-studio-editor-state]')
    expect(editorStyle?.textContent).toContain('[data-ui-id="shell.sidebar"] { visibility: hidden }')
    expect(localStorage.getItem('sunday.themeStudio.draft.v1') || '').not.toContain('visibility: hidden')

    wrapper.unmount()
    expect(document.querySelector('style[data-studio-editor-state]')).toBeNull()
    target.remove()
  })

  // user:“父子是父子，层级是层级，不要混为一谈”+
  // (图层视图按 z 从高到低排序、按 100 一层分组；拖拽重排就是改 z)
  it('图层视图按 z 排序分带，拖拽重排直接改 z', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="template.message"]').trigger('click')
    await wrapper.get('[data-studio-field="layer"]').setValue('250')
    await flushPromises()
    await wrapper.get('[data-studio-node="template.conversation"]').trigger('click')
    await wrapper.get('[data-studio-field="layer"]').setValue('350')
    await flushPromises()

    await wrapper.get('[data-studio-view="layers"]').trigger('click')
    await flushPromises()

    const rows = wrapper.findAll('[data-studio-layer-row]')
    expect((rows[0].element as HTMLElement).dataset.studioLayerRow).toBe('template.conversation')
    expect((rows[1].element as HTMLElement).dataset.studioLayerRow).toBe('template.message')
    const bands = wrapper.findAll('.studio-layer-band').map((node) => node.text())
    expect(bands[0]).toContain('第 4 层')
    expect(bands[1]).toContain('第 3 层')
    // user:“auto不要单开，挂在对应的图层内”+(没有真实 z 的元素归入第 1 层，不再单独成组)
    expect(bands.at(-1)).toContain('第 1 层')

    // 把消息行拖到会话行之上：z = 目标 z + 1，重新排序后它排最前。
    const messageRow = wrapper.get('[data-studio-layer-row="template.message"]')
    const conversationRow = wrapper.get('[data-studio-layer-row="template.conversation"]')
    messageRow.element.dispatchEvent(new Event('dragstart', { bubbles: true }))
    conversationRow.element.dispatchEvent(new Event('drop', { bubbles: true, cancelable: true }))
    await flushPromises()
    expect(previewStyle()?.textContent).toContain('z-index: 351')
    expect((wrapper.findAll('[data-studio-layer-row]')[0].element as HTMLElement).dataset.studioLayerRow).toBe('template.message')
    wrapper.unmount()
  })

  // user:“怎么全是未分层？我们前端不可能全是 0 层”+
  // (未覆盖时图层列表读取页面里元素的真实计算 z，按真实值分带排序)
  it('图层视图显示元素真实的计算 z，而不是一律 0', async () => {
    const main = document.createElement('div')
    main.dataset.uiId = 'shell.main'
    main.style.zIndex = '20'
    const rail = document.createElement('div')
    rail.dataset.uiId = 'shell.app-rail'
    rail.style.zIndex = '35'
    document.body.append(main, rail)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-view="layers"]').trigger('click')
    await flushPromises()

    expect((wrapper.get('[data-studio-layer-input="shell.main"]').element as HTMLInputElement).value).toBe('20')
    expect((wrapper.get('[data-studio-layer-input="shell.app-rail"]').element as HTMLInputElement).value).toBe('35')
    // 真实 z 参与排序与分带（35 在 20 上面，同属第 1 层）。
    const ids = wrapper.findAll('[data-studio-layer-row]').map((row) => (row.element as HTMLElement).dataset.studioLayerRow)
    expect(ids.indexOf('shell.app-rail')).toBeLessThan(ids.indexOf('shell.main'))
    expect(wrapper.findAll('.studio-layer-band').map((node) => node.text()).some((text) => text.includes('第 1 层'))).toBe(true)
    wrapper.unmount()
    main.remove()
    rail.remove()
  })

  // user:“怎么可能有一个东西它是没有层级的呢”+
  // (z:auto 是相对分层：按文档顺序绘制，面板显示“自动 · #序号”，后绘制的排在前面)
  it('auto 层按文档顺序显示相对层级', async () => {
    const first = document.createElement('div')
    first.dataset.uiId = 'shell.sidebar'
    const second = document.createElement('div')
    second.dataset.uiId = 'shell.right-rail'
    document.body.append(first, second)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-view="layers"]').trigger('click')
    await flushPromises()

    const sidebarRow = wrapper.get('[data-studio-layer-row="shell.sidebar"]')
    const railRow = wrapper.get('[data-studio-layer-row="shell.right-rail"]')
    // user:“层级写为 auto12345 层”+(auto 子层的层级列直接写 auto+顺序号)
    expect((sidebarRow.get('[data-studio-layer-input]').element as HTMLInputElement).value).toMatch(/^auto\d+$/)
    expect((railRow.get('[data-studio-layer-input]').element as HTMLInputElement).value).toMatch(/^auto\d+$/)
    // 后出现在文档里的元素绘制在上 → 相对层级更高、排在更前。
    const ids = wrapper.findAll('[data-studio-layer-row]').map((row) => (row.element as HTMLElement).dataset.studioLayerRow)
    expect(ids.indexOf('shell.right-rail')).toBeLessThan(ids.indexOf('shell.sidebar'))
    wrapper.unmount()
    first.remove()
    second.remove()
  })

  // user:“那这个 auto 元素我知道它是分在哪一块儿了吗？”+
  // (自动层的“块”=最近的已登记父容器：行内标注它在哪个容器里、排第几位)
  it('auto 层标注所属容器与顺序', async () => {
    const parent = document.createElement('div')
    parent.dataset.uiId = 'shell.sidebar'
    parent.style.zIndex = '20'
    const child = document.createElement('div')
    child.dataset.uiId = 'shell.sidebar-items'
    parent.append(child)
    document.body.append(parent)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-view="layers"]').trigger('click')
    await flushPromises()

    const row = wrapper.get('[data-studio-layer-row="shell.sidebar-items"]')
    expect((row.get('[data-studio-layer-input]').element as HTMLInputElement).value).toMatch(/^auto\d+$/)
    expect(row.text()).toContain('在「会话列表」内')
    // user:“有没有可能它的父层级是固定的？”+(父层固定 z 时一并标出，子元素被约束在这一块内)
    expect(row.text()).toContain('父层 z=20')
    wrapper.unmount()
    parent.remove()
  })

  // user:“auto不要单开，挂在对应的图层内，层级写为 auto12345 层”+
  // (auto 子层归入父层所在的层带，带内排在显式层之后；层级列写 auto+序号)
  it('auto 子层归入父层所在层带', async () => {
    const parent = document.createElement('div')
    parent.dataset.uiId = 'shell.sidebar'
    parent.style.zIndex = '250'
    const child = document.createElement('div')
    child.dataset.uiId = 'shell.sidebar-items'
    parent.append(child)
    document.body.append(parent)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-view="layers"]').trigger('click')
    await flushPromises()

    const headers = wrapper.findAll('.studio-layer-band').map((node) => node.text())
    // 父层 z=250 属第 3 层，auto 子层跟着进第 3 层；其余无 z 元素在第 1 层。
    expect(headers[0]).toContain('第 3 层')
    expect(headers[1]).toContain('第 1 层')
    const ids = wrapper.findAll('[data-studio-layer-row]').map((row) => (row.element as HTMLElement).dataset.studioLayerRow)
    expect(ids.indexOf('shell.sidebar')).toBeLessThan(ids.indexOf('shell.sidebar-items'))
    expect(ids.indexOf('shell.sidebar-items')).toBeLessThan(ids.indexOf('shell.main'))
    wrapper.unmount()
    parent.remove()
  })

  // user:“图层可折叠”+(每个层带都能收起/展开，收起后只留层带标题)
  it('图层带可折叠', async () => {
    const parent = document.createElement('div')
    parent.dataset.uiId = 'shell.sidebar'
    parent.style.zIndex = '250'
    document.body.append(parent)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-view="layers"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-studio-layer-band="3"]').attributes('aria-expanded')).toBe('true')
    await wrapper.get('[data-studio-layer-band="3"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-studio-layer-band="3"]').attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('[data-studio-layer-row="shell.sidebar"]').exists()).toBe(false)
    await wrapper.get('[data-studio-layer-band="3"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-studio-layer-row="shell.sidebar"]').exists()).toBe(true)
    wrapper.unmount()
    parent.remove()
  })

  // user:“比如说会话行和消息行……它是 auto 在哪儿的？……那就再细分一层，把它挂在那个会话抽屉底下”+
  // (同一层带里 auto 行按最近的已登记父容器逐级缩进：会话抽屉 → 会话列表 → 项组 → 会话行 → 会话名称)
  it('auto 行挂在父容器行下面，形成缩进层级', async () => {
    const drawer = document.createElement('div')
    drawer.dataset.uiId = 'shell.sidebar'
    drawer.style.zIndex = '100'
    const items = document.createElement('div')
    items.dataset.uiId = 'shell.sidebar-items'
    const row = document.createElement('div')
    row.dataset.uiTemplate = 'template.conversation'
    const title = document.createElement('strong')
    title.dataset.uiTemplate = 'template.session-title'
    row.append(title)
    items.append(row)
    drawer.append(items)
    document.body.append(drawer)

    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-view="layers"]').trigger('click')
    await flushPromises()

    const depthOf = (id: string) =>
      (wrapper.get(`[data-studio-layer-row="${id}"]`).element as HTMLElement).dataset.studioLayerDepth
    expect(depthOf('shell.sidebar')).toBe('0')
    expect(depthOf('shell.sidebar-items')).toBe('1')
    expect(depthOf('template.conversation')).toBe('2')
    expect(depthOf('template.session-title')).toBe('3')

    // 父子在列表里紧挨着，先父后子。
    const ids = wrapper.findAll('[data-studio-layer-row]').map((node) => (node.element as HTMLElement).dataset.studioLayerRow)
    expect(ids.indexOf('shell.sidebar-items')).toBe(ids.indexOf('shell.sidebar') + 1)
    expect(ids.indexOf('template.conversation')).toBe(ids.indexOf('shell.sidebar-items') + 1)
    expect(wrapper.find('[data-studio-auto-caret="shell.sidebar"]').exists()).toBe(true)

    // 收起这一块自动子层：子行全部隐藏，父行保留；再点恢复。
    await wrapper.get('[data-studio-auto-caret="shell.sidebar"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-studio-layer-row="shell.sidebar"]').exists()).toBe(true)
    expect(wrapper.find('[data-studio-layer-row="shell.sidebar-items"]').exists()).toBe(false)
    await wrapper.get('[data-studio-auto-caret="shell.sidebar"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-studio-layer-row="shell.sidebar-items"]').exists()).toBe(true)
    wrapper.unmount()
    drawer.remove()
  })

  // user:“输入层级数值的时候 不要让它直接变，摁回车，或者说是点其他地方保存了再变”+
  // (层级输入只在回车/失焦时提交，边打字不会边跳层)
  it('层级输入在打字时不生效，回车或失焦才提交', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')

    const panelInput = wrapper.get('[data-studio-field="layer"]')
    const panelEl = panelInput.element as HTMLInputElement
    panelEl.value = '250'
    await panelInput.trigger('input')
    expect(previewStyle()?.textContent ?? '').not.toContain('z-index: 250')
    await panelInput.trigger('change')
    expect(previewStyle()?.textContent ?? '').toContain('z-index: 250')

    await wrapper.get('[data-studio-view="layers"]').trigger('click')
    await flushPromises()
    const layerInput = wrapper.get('[data-studio-layer-input="shell.main"]')
    const layerEl = layerInput.element as HTMLInputElement
    layerEl.value = '320'
    await layerInput.trigger('input')
    expect(previewStyle()?.textContent ?? '').not.toContain('z-index: 320')
    await layerInput.trigger('change')
    expect(previewStyle()?.textContent ?? '').toContain('z-index: 320')
    wrapper.unmount()
  })

  // user:“按这个设计方案审…补齐”+(方案 §8.5：按内容嗅探校验格式，SVG 拒绝脚本)
  it('导入素材拒绝未知格式与带脚本的 SVG', async () => {
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()
    await wrapper.get('[data-studio-node="shell.main"]').trigger('click')
    const input = () => wrapper.get('input[accept="image/*"]').element as HTMLInputElement

    const garbage = new File(['definitely-not-an-image'], 'x.png', { type: 'image/png' })
    Object.defineProperty(input(), 'files', { value: [garbage] })
    input().dispatchEvent(new Event('change'))
    await vi.waitFor(() => expect(wrapper.text()).toContain('图片格式无法识别'))

    const evil = new File(['<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'], 'evil.svg', { type: 'image/svg+xml' })
    Object.defineProperty(input(), 'files', { value: [evil] })
    input().dispatchEvent(new Event('change'))
    await vi.waitFor(() => expect(wrapper.text()).toContain('SVG 不允许包含脚本'))
    wrapper.unmount()
  })
})
