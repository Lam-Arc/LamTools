import { mount, flushPromises } from '@vue/test-utils'
import { computed, defineComponent, h, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CoreSplitWorkspace from '../src/components/CoreSplitWorkspace.vue'
import CoreAppPage from '../src/components/CoreAppPage.vue'
import AppRail from '../src/components/AppRail.vue'
import { useSplitWorkspace, type SplitWorkspaceController } from '../src/split/useSplitWorkspace'
import { moveTab } from '../src/split/layout'
import { closeContextMenu, contextMenuState } from '../src/components/context-menu/context-menu'
import { t } from '../src/i18n'

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
  // user:“在分屏内选择分屏类型和标签页”+(点击手柄先选方向，再从同一菜单选内容)。
  it('offers split directions and tab content from the pane handle', async () => {
    const { wrapper, controller } = workspace(); await flushPromises()
    const handle = wrapper.find('.split-split-handle')
    expect(handle.exists()).toBe(true)
    handle.element.dispatchEvent(new MouseEvent('pointerdown', { button: 0, clientX: 900, clientY: 100, bubbles: true }))
    window.dispatchEvent(new MouseEvent('pointerup', { button: 0, clientX: 900, clientY: 100, bubbles: true }))
    await flushPromises()
    const right = contextMenuState.items.find(item => item.type === 'submenu' && item.label === t('向右分屏'))
    if (!right || right.type !== 'submenu') throw Error('missing right direction')
    const settings = right.children.find(item => 'label' in item && item.label === t('设置'))
    if (!settings || !('action' in settings) || !settings.action) throw Error('missing settings content')
    settings.action(); await flushPromises()
    expect(Object.keys(controller.state.panes)).toHaveLength(2)
    expect(controller.tabs.value.some(({ tab }) => tab.kind === 'page' && tab.resource === 'settings')).toBe(true)
  })
  // user:“通过拖动拉起，而不是点击按钮。就类似 blender”+(按住手柄横向拖动直接落下一块新屏，不再弹菜单)。
  it('pulls out a new pane by dragging the split handle', async () => {
    const { wrapper, controller } = workspace(); await flushPromises()
    const handle = wrapper.find('.split-split-handle').element
    handle.dispatchEvent(new MouseEvent('pointerdown', { button: 0, clientX: 900, clientY: 100, bubbles: true }))
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 400, clientY: 100, bubbles: true }))
    await flushPromises()
    expect(document.body.classList.contains('split-is-pulling')).toBe(true)
    window.dispatchEvent(new MouseEvent('pointerup', { clientX: 400, clientY: 100, bubbles: true }))
    await flushPromises()
    expect(Object.keys(controller.state.panes)).toHaveLength(2)
    expect(contextMenuState.open).toBe(false)
    expect(document.body.classList.contains('split-is-pulling')).toBe(false)
  })
  // user:“点一下这个分屏键，自动在右边起一个分屏...分屏键里面不需要有任何东西”+(标题栏动作只分屏；已收起时恢复)。
  it('splits the active pane right from the header action and restores a collapsed split', async () => {
    let controller!: SplitWorkspaceController
    const Harness = defineComponent({ setup() { controller = useSplitWorkspace(computed(() => 'split-header')); return () => h('div') } })
    const wrapper = mount(Harness); wrappers.push(wrapper); await flushPromises()
    const first = controller.splitRight()
    expect(first).toBeTruthy()
    expect(Object.keys(controller.state.panes)).toHaveLength(1)
    expect(controller.splitRight()).toBeTruthy()
    expect(Object.keys(controller.state.panes)).toHaveLength(2)
    controller.state.activePane = first!
    controller.state.hidden = true
    expect(controller.splitRight()).toBeNull()
    expect(controller.state.hidden).toBe(false)
    expect(Object.keys(controller.state.panes)).toHaveLength(2)
    controller.setBounds(1600, 1000)
    controller.state.activePane = 'main'
    expect(controller.splitRight()).toBeTruthy()
    expect(Object.keys(controller.state.panes)).toHaveLength(3)
  })
})
