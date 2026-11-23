// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { h, ref } from 'vue'
import { expect, it } from 'vitest'
import CoreWorkspace from '@/components/CoreWorkspace.vue'
import { useWorkspace } from '@/workspace/useWorkspace'
import type { SplitContent } from '@/workspace/types'

const contents: SplitContent[] = ['page', 'files', 'browser', 'editor', 'preview', 'plugin', 'conversation', 'agent']

it.each(contents)('keeps a close button above the content of a %s split', async kind => {
  const controller = useWorkspace(ref(`close-${kind}`), undefined, undefined, { persist: false })
  controller.setBounds({ x: 0, y: 0, width: 1000, height: 680 })
  const pane = controller.split('main', 'right')!
  controller.add(kind, kind === 'page' ? 'library' : '', 'Sample', pane)
  const wrapper = mount(CoreWorkspace, {
    props: { controller, workRoot: '' },
    slots: { default: () => h('div', 'sample') },
  })
  try {
    const region = wrapper.get(`[data-ws2-area="${pane}"]`)
    const header = region.get<HTMLElement>('.ws2-area__tabs')
    expect(parseFloat(header.element.style.height)).toBeGreaterThan(0)
    expect(region.find('.ws2-tab__close').exists()).toBe(true)
    expect(parseFloat(region.get<HTMLElement>('.ws2-area__content').element.style.top)).toBe(parseFloat(header.element.style.height))
    await region.get('[data-ws2-area-close]').trigger('click')
    expect(controller.state.panes[pane]).toBeUndefined()
    expect(controller.state.panes.main).toBeDefined()
  } finally { wrapper.unmount() }
})

it('closes an empty split and respects an unsaved guard before closing a populated split', async () => {
  const controller = useWorkspace(ref('close-guard'), undefined, undefined, { persist: false })
  controller.setBounds({ x: 0, y: 0, width: 1300, height: 680 })
  const files = controller.split('main', 'right')!
  const empty = controller.split('main', 'bottom')!
  const editor = controller.add('editor', 'notes.md', 'Notes', files)!
  let proceed: (() => void) | undefined
  controller.registerGuard(editor.id, confirm => { proceed = confirm })
  const wrapper = mount(CoreWorkspace, { props: { controller, workRoot: '' } })
  try {
    await wrapper.get(`[data-ws2-area="${empty}"] [data-ws2-area-close]`).trigger('click')
    expect(controller.state.panes[empty]).toBeUndefined()
    await wrapper.get(`[data-ws2-area="${files}"] [data-ws2-area-close]`).trigger('click')
    expect(controller.state.panes[files].tabs[0].id).toBe(editor.id)
    proceed!()
    expect(controller.state.panes[files]).toBeUndefined()
  } finally { wrapper.unmount() }
})
