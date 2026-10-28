import { mount, flushPromises } from '@vue/test-utils'
import { computed, defineComponent, h, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CoreSplitWorkspace from '../src/components/CoreSplitWorkspace.vue'
import CoreAppPage from '../src/components/CoreAppPage.vue'
import AppRail from '../src/components/AppRail.vue'
import { useSplitWorkspace, type SplitWorkspaceController } from '../src/split/useSplitWorkspace'
import { moveTab, layoutRects } from '../src/split/layout'
import { closeContextMenu, contextMenuState } from '../src/components/context-menu/context-menu'

vi.mock('../src/components/CoreSettings.vue', () => ({ __esModule: true, default: defineComponent({ name: 'TestSettings', props: ['hideNav', 'activeSection'], setup: (props, { expose }) => { expose({ requestNavigation: (proceed: () => void) => proceed() }); return () => h('div', { 'data-local-nav': !props.hideNav }, 'settings') } }) }))
vi.mock('../src/components/LibraryHomeView.vue', () => ({ __esModule: true, default: defineComponent({ name: 'TestLibrary', setup(_, { expose }) { const dirty = ref(true); expose({ hasUnsavedChanges: () => dirty.value, savePendingChanges: async () => { dirty.value = false; return true }, discardPendingChanges: () => { dirty.value = false } }); return () => h('div', 'library') } }) }))
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.restoreAllMocks(); localStorage.clear(); closeContextMenu() })
function workspace() {
  let controller!: SplitWorkspaceController
  const Child = defineComponent({ setup() { const draft = ref('draft stays here'); return () => h('textarea', { value: draft.value }) } })
  const Harness = defineComponent({ setup() { controller = useSplitWorkspace(computed(() => 'split-acceptance')); const a = controller.split('main', 'right')!; controller.add('editor', '/a.md', 'a.md', a); return () => h(CoreSplitWorkspace, { controller, workRoot: 'E:/project' }, { default: () => h(Child) }) } })
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(() => ({ x: 0, y: 0, width: 1440, height: 900, left: 0, top: 0, right: 1440, bottom: 900, toJSON() {} }))
  const wrapper = mount(Harness, { attachTo: document.body }); wrappers.push(wrapper)
  return { wrapper, controller }
}
describe('Split Pane integrated interaction', () => {
  it('never adds a main tab and preserves the mounted editor when moved between screens', async () => {
    const { wrapper, controller } = workspace(); await flushPromises()
    expect(wrapper.findAll('[role=tab]')).toHaveLength(1)
    const source = Object.keys(controller.state.panes)[0], tab = controller.state.panes[source].tabs[0]
    const editor = wrapper.find('textarea').element
    const target = controller.split(source, 'bottom')!
    moveTab(controller.state, source, target, tab.id)
    await flushPromises()
    expect(wrapper.find('textarea').element).toBe(editor)
    expect(wrapper.findAll('[role=tab]')).toHaveLength(1)
    controller.toggle(); await flushPromises()
    expect(wrapper.find('textarea').element).toBe(editor)
    controller.toggle(); await flushPromises()
    expect(wrapper.find('textarea').element).toBe(editor)
  })
  it('keeps auxiliary settings navigation local instead of mutating primary section state', async () => {
    const onSectionChange = vi.fn()
    const wrapper = mount(CoreAppPage, { props: { page: 'settings', auxiliary: true, bindings: { settings: { hideNav: true, activeSection: 'models', onSectionChange } } } })
    wrappers.push(wrapper); await flushPromises()
    expect(wrapper.find('[data-local-nav]').attributes('data-local-nav')).toBe('true')
    expect(wrapper.findComponent({ name: 'TestSettings' }).props('activeSection')).toBeUndefined()
    expect(onSectionChange).not.toHaveBeenCalled()
  })
  it('guards unsaved library content before a pane can close', async () => {
    const wrapper = mount(CoreAppPage, { attachTo: document.body, props: { page: 'library', auxiliary: true, bindings: { library: {} } } })
    wrappers.push(wrapper); await flushPromises()
    const proceed = vi.fn()
    ;(wrapper.vm as unknown as { requestNavigation: (proceed: () => void) => void }).requestNavigation(proceed)
    await flushPromises()
    expect(proceed).not.toHaveBeenCalled()
    const confirm = document.querySelector<HTMLButtonElement>('.core-confirm__submit')!
    expect(confirm).not.toBeNull(); confirm.click(); await flushPromises()
    expect(proceed).toHaveBeenCalledTimes(1)
  })
  it('opens App Rail content in a split without navigating the primary view', async () => {
    const wrapper = mount(AppRail, { props: { active: 'chat' } }); wrappers.push(wrapper)
    await wrapper.find('[data-rail-entry=library]').trigger('contextmenu')
    const action = contextMenuState.items[0]
    if (!('action' in action)) throw Error('missing split action')
    action.action()
    expect(wrapper.emitted('open-split')?.[0]).toEqual(['library', 'right'])
    expect(wrapper.emitted('open')).toBeUndefined()
  })
  // user:“审查分屏代码，并优化”+(没有分屏时菜单不能提供“收起分屏”，否则点击反而新建一块空屏)。
  it('does not offer to collapse a workspace without auxiliary panes', async () => {
    let controller!: SplitWorkspaceController
    const Harness = defineComponent({ setup() { controller = useSplitWorkspace(computed(() => 'split-menu')); return () => h(CoreSplitWorkspace, { controller, workRoot: 'E:/project' }) } })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(() => ({ x: 0, y: 0, width: 1440, height: 900, left: 0, top: 0, right: 1440, bottom: 900, toJSON() {} }))
    const wrapper = mount(Harness, { attachTo: document.body }); wrappers.push(wrapper); await flushPromises()
    const workspace = wrapper.findComponent(CoreSplitWorkspace)
    ;(workspace.vm as unknown as { operations: (event: MouseEvent, pane: string) => void }).operations(new MouseEvent('contextmenu', { clientX: 10, clientY: 10 }), 'main')
    const labels = contextMenuState.items.map(item => ('label' in item ? item.label : ''))
    expect(labels).toContain('向右分屏')
    expect(labels).not.toContain('收起分屏')
  })
  // user:“分屏的右上角，只需要留一个加号来新增标签页即可，一个 x 来关闭此分屏，不需要再有一个分屏键了”+(头部只保留加号、关闭和右下角拖拽角柄)。
  it('keeps only add-tab and close-pane controls plus a corner grip', async () => {
    const { wrapper } = workspace(); await flushPromises()
    expect(wrapper.find('.split-split-handle').exists()).toBe(false)
    expect(wrapper.find('.split-corner-grip').exists()).toBe(true)
    expect(wrapper.find('[aria-label="打开内容"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="关闭分屏"]').exists()).toBe(true)
  })
  it('closes the whole pane from the header X', async () => {
    const { wrapper, controller } = workspace(); await flushPromises()
    await wrapper.find('[aria-label="关闭分屏"]').trigger('click')
    await flushPromises()
    expect(Object.keys(controller.state.panes)).toHaveLength(0)
  })
  // user:“从分屏的角进行拖拽，来起一个新的分屏”+(按住角柄拖出方向，松手直接落屏，不再弹菜单)。
  it('pulls out a new pane by dragging the corner grip', async () => {
    const { wrapper, controller } = workspace(); await flushPromises()
    const grip = wrapper.find('.split-corner-grip').element
    grip.dispatchEvent(new MouseEvent('pointerdown', { button: 0, clientX: 900, clientY: 100, bubbles: true }))
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 1000, clientY: 100, bubbles: true }))
    await flushPromises()
    expect(document.body.classList.contains('split-is-pulling')).toBe(true)
    window.dispatchEvent(new MouseEvent('pointerup', { clientX: 1000, clientY: 100, bubbles: true }))
    await flushPromises()
    expect(Object.keys(controller.state.panes)).toHaveLength(2)
    expect(contextMenuState.open).toBe(false)
    expect(document.body.classList.contains('split-is-pulling')).toBe(false)
  })
  // user:“分割线位置跟着鼠标...起始角决定新区域落在哪一侧”+(左上角起拖向右拉，新屏落在左侧，原屏右移)。
  it('places the new pane at the pointer on the starting corner side', async () => {
    const { wrapper, controller } = workspace(); await flushPromises()
    const source = Object.keys(controller.state.panes)[0]
    const before = layoutRects(controller.state.tree, { x: 0, y: 0, width: 1440, height: 900 }).panes[source]
    const grip = wrapper.find('.split-corner-grip').element
    grip.dispatchEvent(new MouseEvent('pointerdown', { button: 0, clientX: 900, clientY: 100, bubbles: true }))
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 1000, clientY: 100, bubbles: true }))
    window.dispatchEvent(new MouseEvent('pointerup', { clientX: 1000, clientY: 100, bubbles: true }))
    await flushPromises()
    const after = layoutRects(controller.state.tree, { x: 0, y: 0, width: 1440, height: 900 }).panes
    expect(Object.keys(after)).toHaveLength(3)
    expect(after[source].x).toBeGreaterThan(before.x)
    const created = Object.entries(after).find(([id]) => id !== source && id !== 'main')?.[1]
    expect(created?.x).toBeLessThan(after[source].x)
    expect((created?.x || 0) + (created?.width || 0)).toBeLessThanOrEqual(after[source].x)
  })
  // user:“为什么左下角那个角铁是不可拖动的”+(左下角铁与左上使用同一套拖拽判定，能直接拉出下方分屏)。
  it('pulls out a new pane from the bottom-left corner grip', async () => {
    const { wrapper, controller } = workspace(); await flushPromises()
    const grip = wrapper.find('.split-corner-grip--bottom-left').element
    grip.dispatchEvent(new MouseEvent('pointerdown', { button: 0, clientX: 900, clientY: 800, bubbles: true }))
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 900, clientY: 600, bubbles: true }))
    window.dispatchEvent(new MouseEvent('pointerup', { clientX: 900, clientY: 600, bubbles: true }))
    await flushPromises()
    expect(Object.keys(controller.state.panes)).toHaveLength(2)
    expect(document.querySelectorAll('.split-corner-grip--bottom-left').length).toBe(2)
  })
  // user:“该对齐的就全部都去对齐”“我要体验一致化”+(角柄拖到相邻分屏上直接合并，两块区域同时描边)。
  it('joins a pane by dragging its corner grip onto a sibling pane', async () => {
    let controller!: SplitWorkspaceController
    const Child = defineComponent({ setup() { return () => h('div') } })
    const Harness = defineComponent({ setup() {
      controller = useSplitWorkspace(computed(() => 'split-join'))
      const first = controller.split('main', 'right')!, second = controller.split(first, 'bottom')!
      controller.add('page', 'res-a', 'A', first); controller.add('page', 'res-b', 'B', second)
      return () => h(CoreSplitWorkspace, { controller, workRoot: 'E:/project' }, { default: () => h(Child) })
    } })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, width: 1440, height: 900, left: 0, top: 0, right: 1440, bottom: 900, toJSON() {} })
    const wrapper = mount(Harness, { attachTo: document.body }); wrappers.push(wrapper); await flushPromises()
    const [first, second] = Object.keys(controller.state.panes)
    const grip = wrapper.findAll('.split-pane-frame')[0].find('.split-corner-grip').element
    grip.dispatchEvent(new MouseEvent('pointerdown', { button: 0, clientX: 900, clientY: 100, bubbles: true }))
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 1000, clientY: 700, bubbles: true }))
    await flushPromises()
    expect(wrapper.find('.split-split-preview--join').exists()).toBe(true)
    expect(wrapper.findAll('.split-split-preview--join .split-split-preview-area')).toHaveLength(2)
    window.dispatchEvent(new MouseEvent('pointerup', { clientX: 1000, clientY: 700, bubbles: true }))
    await flushPromises()
    expect(controller.state.panes[first]).toBeUndefined()
    expect(controller.state.panes[second].tabs.map(tab => tab.resource)).toEqual(['res-b', 'res-a'])
    expect(layoutRects(controller.state.tree, { x: 0, y: 0, width: 1440, height: 900 }).panes[second].height).toBeGreaterThan(450)
  })
  // user:“边框右键合并/交换”+(分隔线右键提供与 Blender Area Options 对应的非拖拽入口)。
  it('offers merge and swap actions on a pane border', async () => {
    let controller!: SplitWorkspaceController
    const Child = defineComponent({ setup() { return () => h('div') } })
    const Harness = defineComponent({ setup() {
      controller = useSplitWorkspace(computed(() => 'split-border'))
      const first = controller.split('main', 'right')!, second = controller.split(first, 'bottom')!
      controller.add('page', 'res-a', 'A', first); controller.add('page', 'res-b', 'B', second)
      return () => h(CoreSplitWorkspace, { controller, workRoot: 'E:/project' }, { default: () => h(Child) })
    } })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, width: 1440, height: 900, left: 0, top: 0, right: 1440, bottom: 900, toJSON() {} })
    const wrapper = mount(Harness, { attachTo: document.body }); wrappers.push(wrapper); await flushPromises()
    const [first, second] = Object.keys(controller.state.panes)
    const rows = wrapper.findAll('[role=separator]').find(element => element.classes('split-divider--rows'))
    if (!rows) throw Error('missing row divider')
    rows.element.dispatchEvent(new MouseEvent('contextmenu', { clientX: 1000, clientY: 455, bubbles: true, cancelable: true }))
    await flushPromises()
    const labels = contextMenuState.items.map(item => 'label' in item ? item.label : '')
    expect(labels).toContain('合并这两块分屏')
    expect(labels).toContain('交换这两块分屏')
    const swap = contextMenuState.items.find(item => 'label' in item && item.label === '交换这两块分屏')
    if (!swap || !('action' in swap) || !swap.action) throw Error('missing swap action')
    swap.action(); await flushPromises()
    expect(controller.state.panes[first].tabs.map(tab => tab.resource)).toEqual(['res-b'])
    expect(controller.state.panes[second].tabs.map(tab => tab.resource)).toEqual(['res-a'])
  })
  // user:“分屏键...那个分屏的意思是打开分屏和折起分屏”+(标题栏开关循环打开、收起与恢复)。
  it('opens, collapses and restores the split from the header toggle', async () => {
    let controller!: SplitWorkspaceController
    const Harness = defineComponent({ setup() { controller = useSplitWorkspace(computed(() => 'split-header')); return () => h('div') } })
    const wrapper = mount(Harness); wrappers.push(wrapper); await flushPromises()
    controller.toggle()
    expect(Object.keys(controller.state.panes)).toHaveLength(1)
    controller.toggle()
    expect(controller.state.hidden).toBe(true)
    controller.toggle()
    expect(controller.state.hidden).toBe(false)
    expect(Object.keys(controller.state.panes)).toHaveLength(1)
  })
})
