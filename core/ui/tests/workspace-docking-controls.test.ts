// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { h, ref } from 'vue'
import { expect, it, vi } from 'vitest'
import CoreWorkspace from '@/components/CoreWorkspace.vue'
import CoreWorkspaceTabDrawer from '@/components/CoreWorkspaceTabDrawer.vue'
import WindowControls from '@/components/TitleBar.vue'
import { dismissAllToasts, showToast, useCoreToast } from '@/composables/useCoreToast'
import { parseWorkspace, serializeWorkspace } from '@/workspace'
import { keyboardIntent, useWorkspace } from '@/workspace/useWorkspace'

it('keeps each previously visible panel mounted and visible after docking a float', async () => {
  const controller = useWorkspace(ref('dock'), undefined, undefined, { persist: false })
  controller.setBounds({ x: 0, y: 0, width: 1100, height: 670 })
  const main = controller.add('browser', '', 'Browser', 'main')!
  const side = controller.split('main', 'right')!
  const files = controller.add('files', '', 'Files', side)!
  const editor = controller.add('editor', 'notes.md', 'Notes', side)!
  controller.setSurfaceMode(editor.id, 'float')
  const wrapper = mount(CoreWorkspace, {
    attachTo: document.body,
    props: { controller, workRoot: '' },
    slots: { default: ({ tab, visible }) => h('div', { 'data-test-tab': tab.id, 'data-visible': String(visible) }) },
  })
  const content = (id: string) => wrapper.get(`[data-test-tab="${id}"]`)
  try {
    const before = [content(main.id).element, content(files.id).element, content(editor.id).element]
    await wrapper.get('[data-ws2-float-pin]').trigger('click')
    const after = [content(main.id), content(files.id), content(editor.id)]
    expect(after.map(node => node.element)).toEqual(before)
    expect(after.map(node => node.attributes('data-visible'))).toEqual(['true', 'true', 'true'])
    expect(after.every(node => node.element.closest('[data-ws2-area]'))).toBe(true)
    expect(keyboardIntent({ key: 'Enter', ctrlKey: true, shiftKey: true })).toBeNull()
  } finally { wrapper.unmount() }
})

it('ignores the old exclusive focus flag when reading a layout', () => {
  const controller = useWorkspace(ref('old-focus'), undefined, undefined, { persist: false })
  const legacy = JSON.parse(serializeWorkspace(controller.model.value))
  legacy.focusAreaId = 'main'
  const read = parseWorkspace(JSON.stringify(legacy), controller.model.value)
  expect(read.model.tree).toEqual(controller.model.value.tree)
  expect(read.model).not.toHaveProperty('focusAreaId')
})

it('keeps small layouts silent until a genuinely too-small docking request fails', async () => {
  const onInsufficient = vi.fn(() => showToast('error', '当前窗口太小，无法分屏'))
  const controller = useWorkspace(ref('tiny-dock'), undefined, undefined, { persist: false, onInsufficient })
  controller.setBounds({ x: 0, y: 0, width: 140, height: 150 })
  const floating = controller.add('browser', '', 'Floating', 'main')!
  controller.setSurfaceMode(floating.id, 'float')
  const wrapper = mount(CoreWorkspace, { props: { controller, workRoot: '' } })
  try {
    expect(wrapper.find('[data-ws2-insufficient]').exists()).toBe(false)
    await wrapper.get('[data-ws2-float-pin]').trigger('mouseenter')
    expect(onInsufficient).not.toHaveBeenCalled()
    await wrapper.get('[data-ws2-float-pin]').trigger('click')
    expect(onInsufficient).toHaveBeenCalledOnce()
    expect(useCoreToast().toasts.value.some(item => item.kind === 'error')).toBe(true)
    expect(controller.placementOf(floating.id)?.kind).toBe('float')
    expect(wrapper.find('[data-ws2-insufficient]').exists()).toBe(false)
  } finally {
    wrapper.unmount()
    dismissAllToasts()
  }
})

it('places the tab drawer trigger before the native buttons in the same control group', async () => {
  const controller = useWorkspace(ref('window-actions'), undefined, undefined, { persist: false })
  const wrapper = mount(WindowControls, {
    props: { showInPreview: true, inline: true },
    slots: { default: () => h(CoreWorkspaceTabDrawer, { controller }) },
  })
  try {
    const buttons = wrapper.get('[data-window-controls]').findAll('button')
    expect(buttons.map(button => button.attributes('data-window-control'))).toEqual([undefined, 'minimize', 'maximize', 'close'])
    expect(buttons.every(button => button.classes().includes('window-control-button'))).toBe(true)
    await buttons[0].trigger('click')
    expect(wrapper.find('.ws2-tab-drawer').exists()).toBe(true)
  } finally { wrapper.unmount() }
})
