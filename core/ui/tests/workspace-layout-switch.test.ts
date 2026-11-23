// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import { expect, it, vi } from 'vitest'
import CoreContentRoot from '@/components/CoreContentRoot.vue'
import CoreWorkspace from '@/components/CoreWorkspace.vue'
import { useWorkspace } from '@/workspace/useWorkspace'
import { parseWorkspace, serializeWorkspace } from '@/workspace'

const menu = vi.hoisted(() => vi.fn())
vi.mock('@/components/context-menu/context-menu', () => ({ openContextMenu: menu, contextMenuState: { open: false } }))

it('offers only Agent and Browser and keeps the layout name when a file tab is selected', async () => {
  const workspace = useWorkspace(ref('layout-pickers'), undefined, undefined, { persist: false })
  const wrapper = mount(CoreContentRoot, { props: { controller: workspace } })
  try {
    await wrapper.get('[data-content-root]').trigger('click')
    const actions = menu.mock.lastCall![0].items
    expect(actions.map((item: { label: string }) => item.label)).toEqual(['Agent', 'Browser'])
    actions[1].action()
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toBe('Browser')
    const file = workspace.add('files', '', 'Files', 'main')!
    await wrapper.vm.$nextTick()
    expect(workspace.state.mainTab?.id).toBe(file.id)
    expect(wrapper.text()).toBe('Browser')
    expect(parseWorkspace(serializeWorkspace(workspace.model.value), workspace.model.value).model.prefs.layout).toBe('browser')
    actions[0].action()
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toBe('Agent')
    expect(workspace.state.panes.main.tabs).toContainEqual(file)
  } finally { wrapper.unmount() }
})

it('leaves existing split and floating tabs in place and removes their promote buttons', async () => {
  const workspace = useWorkspace(ref('layout-positions'), undefined, undefined, { persist: false })
  workspace.setBounds({ x: 0, y: 0, width: 1100, height: 720 })
  const pane = workspace.split('main', 'right')!
  const browser = workspace.add('browser', 'https://example.test', 'Aux browser', pane)!
  const file = workspace.add('files', '', 'Floating files', 'main')!
  workspace.setSurfaceMode(file.id, 'float')
  const wrapper = mount(CoreWorkspace, { props: { controller: workspace, workRoot: '' } })
  try {
    workspace.setLayout('browser')
    await wrapper.vm.$nextTick()
    expect(workspace.placementOf(browser.id)).toMatchObject({ kind: 'area', areaId: pane })
    expect(workspace.placementOf(file.id)).toMatchObject({ kind: 'float' })
    expect(wrapper.find('[data-ws2-area-promote], [data-ws2-float-promote]').exists()).toBe(false)
  } finally { wrapper.unmount() }
})
