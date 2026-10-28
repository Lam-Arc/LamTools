import { mount, flushPromises } from '@vue/test-utils'
import { computed, defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import CoreSplitPane from '../src/components/CoreSplitPane.vue'
import CoreSplitWorkspace from '../src/components/CoreSplitWorkspace.vue'
import { useSplitWorkspace, type SplitWorkspaceController } from '../src/split/useSplitWorkspace'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); localStorage.clear(); vi.restoreAllMocks() })
const pane = () => ({ id: 'aux', activeTab: 'a', tabs: ['a', 'b'].map(id => ({ id, kind: 'editor' as const, resource: `${id}.md`, title: `${id}.md` })) })
// user:“样式优化：动画、交互体验、圆角策略等”+(验证常用标签操作和拖动撤回，避免精修破坏内容状态)。
describe('split pane interaction polish', () => {
  it('closes a tab with the middle button without selecting it', async () => {
    const value = pane(), wrapper = mount(CoreSplitPane, { props: { pane: value, active: true } }); wrappers.push(wrapper)
    await wrapper.findAll('.split-pane-tab')[1].trigger('auxclick', { button: 1 })
    expect(wrapper.emitted('close')).toEqual([[value.tabs[1]]])
    expect(wrapper.emitted('activate')).toBeUndefined()
  })
  it('activates the pane when its toolbar receives keyboard focus', async () => {
    const wrapper = mount(CoreSplitPane, { props: { pane: pane(), active: false } }); wrappers.push(wrapper)
    await wrapper.find('.split-icon-button').trigger('focusin')
    expect(wrapper.emitted('focus')).toHaveLength(1)
  })
  it('scrolls an overflowing tab strip while preserving page scrolling at its edge', async () => {
    const wrapper = mount(CoreSplitPane, { props: { pane: pane(), active: true } }); wrappers.push(wrapper)
    const strip = wrapper.find('.split-pane-tabs').element as HTMLElement
    Object.defineProperties(strip, { clientWidth: { value: 100 }, scrollWidth: { value: 300 } })
    const wheel = new WheelEvent('wheel', { deltaY: 48, cancelable: true, bubbles: true })
    strip.dispatchEvent(wheel)
    expect(strip.scrollLeft).toBe(48)
    expect(wheel.defaultPrevented).toBe(true)
    strip.scrollLeft = 200
    const edge = new WheelEvent('wheel', { deltaY: 48, cancelable: true, bubbles: true })
    strip.dispatchEvent(edge)
    expect(edge.defaultPrevented).toBe(false)
  })
  it('reveals a selected tab outside the visible strip', async () => {
    const value = pane(), wrapper = mount(CoreSplitPane, { props: { pane: value, active: true } }); wrappers.push(wrapper)
    const strip = wrapper.find('.split-pane-tabs').element as HTMLElement
    const tab = wrapper.findAll('.split-pane-tab')[1].element as HTMLElement
    Object.defineProperty(strip, 'clientWidth', { value: 100 })
    Object.defineProperties(tab, { offsetLeft: { value: 200 }, offsetWidth: { value: 70 } })
    strip.scrollTo = vi.fn()
    await wrapper.setProps({ pane: { ...value, activeTab: 'b' } })
    expect(strip.scrollTo).toHaveBeenCalledWith({ left: 170, behavior: 'smooth' })
  })
  it('restores the divider on Escape and cleans up an unfinished resize on unmount', async () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, width: 1440, height: 900, left: 0, top: 0, right: 1440, bottom: 900, toJSON() {} })
    let controller!: SplitWorkspaceController
    const Harness = defineComponent({ setup() { controller = useSplitWorkspace(computed(() => 'split-polish')); controller.split('main', 'right'); return () => h(CoreSplitWorkspace, { controller, workRoot: 'E:/project' }) } })
    const wrapper = mount(Harness, { attachTo: document.body }); wrappers.push(wrapper); await flushPromises()
    const divider = wrapper.find('[role=separator]'), initial = divider.attributes('aria-valuenow')
    divider.element.dispatchEvent(new MouseEvent('pointerdown', { button: 0, bubbles: true }))
    divider.element.dispatchEvent(new MouseEvent('pointermove', { clientX: 1000, clientY: 100, bubbles: true })); await flushPromises()
    expect(divider.attributes('aria-valuenow')).not.toBe(initial)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); await flushPromises()
    expect(divider.attributes('aria-valuenow')).toBe(initial)
    expect(document.body.classList.contains('split-is-resizing')).toBe(false)
    divider.element.dispatchEvent(new MouseEvent('pointerdown', { button: 0, bubbles: true }))
    wrapper.unmount(); wrappers.pop()
    expect(document.body.classList.contains('split-is-resizing')).toBe(false)
  })
  // user:“平时是隐藏的，只有当鼠标到了那个区域时才显示...不需要有背景 它只是一个图标”+(标题栏入口默认透明，悬停才显现)。
  it('keeps the header split entry transparent until hovered', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/styles/split-workspace.css'), 'utf8')
    const base = css.match(/\.split-entry \{[^}]*\}/)?.[0] || ''
    expect(base).toContain('opacity: 0')
    expect(base).toContain('background: transparent !important')
    expect(css).toContain('.split-entry:is(:hover, :focus-visible)')
    expect(css).toContain('.split-entry::before')
  })
  // user:“那个分屏的意思是打开分屏和折起分屏”+(标题栏入口只切换开关，不再向右/向下分屏)。
  it('wires the header split key to the open/collapse toggle', () => {
    const app = readFileSync(resolve(process.cwd(), 'src/app/LamToolsApp.vue'), 'utf8')
    expect(app).toContain('@click="splitWorkspace.toggle()"')
    expect(app).toContain("t('打开分屏')")
    expect(app).toContain("t('收起分屏')")
  })
  // user:“标签和角铁太难看，重新设计”+(标签改用主区文字与轻选中底色；角铁改为单层圆角 L 遮罩，不再出现白块和硬边 L)。
  it('uses main-area tab text, a quiet selected fill, and a single masked corner bracket', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/styles/split-workspace.css'), 'utf8')
    const tabRule = css.match(/\.split-pane-tab \{[^}]*\}/)?.[0] || ''
    const selectedRule = css.match(/\.split-pane-tab\.is-selected \{[^}]*\}/)?.[0] || ''
    const cornerRule = css.match(/\.split-corner-grip::before \{[^}]*\}/)?.[0] || ''
    const bottomRule = css.match(/\.split-corner-grip--bottom-left \{[^}]*\}/)?.[0] || ''
    expect(tabRule).toContain('--text: var(--theme-main-text)')
    expect(tabRule).not.toContain('--theme-control-text')
    expect(selectedRule).toContain('var(--alpha-active)')
    expect(selectedRule).not.toContain('theme-control-soft-background')
    expect(css).not.toContain('.split-pane-bar.is-active .split-pane-tab.is-selected::after')
    expect(css).not.toContain('.split-pane-bar .split-icon-button { background: var(--theme-control-soft-background); }')
    expect(cornerRule).toContain('mask: var(--split-corner-mask)')
    expect(bottomRule).toContain('--split-corner-rotation: -90deg')
  })
  // user:“分屏的右上角，只需要留一个加号...一个 x...从分屏的角进行拖拽”+(头部只保留加号与关闭，拆分入口改为角柄)。
  it('keeps only add/close controls and a corner split grip in the pane header', () => {
    const pane = readFileSync(resolve(process.cwd(), 'src/components/CoreSplitPane.vue'), 'utf8')
    const css = readFileSync(resolve(process.cwd(), 'src/styles/split-workspace.css'), 'utf8')
    expect(pane).not.toContain('split-split-handle')
    expect(pane).toContain('split-corner-grip')
    expect(pane).toContain("t('关闭分屏')")
    expect(pane).toContain("t('打开内容')")
    expect(css).toContain('.split-corner-grip')
    expect(css).toContain('.split-corner-grip--top-left')
    expect(css).toContain('.split-corner-grip--ghost')
    expect(css).toContain('.split-split-preview')
    expect(css).not.toContain('repeating-linear-gradient(-45deg, currentColor')
    expect(css).toContain('padding-inline: 22px var(--space-2)')
  })
})
