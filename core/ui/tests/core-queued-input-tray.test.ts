import { mount } from '@vue/test-utils'
import { vi } from 'vitest'
import { describe, expect, it, afterEach } from 'vitest'
import CoreQueuedInputTray from '../src/components/CoreQueuedInputTray.vue'

describe('CoreQueuedInputTray', () => {
  it('renders queued input actions and emits edit, guide, delete', async () => {
    const wrapper = mount(CoreQueuedInputTray, {
      props: {
        items: [{ id: 'q1', text: 'next task', status: 'queued', position: 1 }],
        canGuide: true,
      },
    })

    expect(wrapper.text()).toContain('next task')

    await wrapper.find('[aria-label="编辑待发送内容"]').trigger('click')
    await wrapper.find('[aria-label="作为引导发送"]').trigger('click')
    await wrapper.find('[aria-label="删除待发送内容"]').trigger('click')

    expect(wrapper.emitted('edit')?.[0]).toEqual([{ id: 'q1', text: 'next task', status: 'queued', position: 1 }])
    expect(wrapper.emitted('guide')?.[0]).toEqual([{ id: 'q1', text: 'next task', status: 'queued', position: 1 }])
    expect(wrapper.emitted('delete')?.[0]).toEqual([{ id: 'q1', text: 'next task', status: 'queued', position: 1 }])
  })

  it('emits save and draft updates while editing', async () => {
    const wrapper = mount(CoreQueuedInputTray, {
      props: {
        items: [{ id: 'q1', text: 'old', status: 'queued', position: 1 }],
        editingId: 'q1',
        draft: 'old',
      },
    })

    await wrapper.find('input').setValue('new')
    await wrapper.find('input').trigger('keydown.enter')

    expect(wrapper.emitted('update:draft')?.[0]).toEqual(['new'])
    expect(wrapper.emitted('save')?.[0]).toEqual([{ id: 'q1', text: 'old', status: 'queued', position: 1 }])
  })

  it('disables every mutation while a queued item is being guided', () => {
    const wrapper = mount(CoreQueuedInputTray, {
      props: {
        items: [{ id: 'q1', text: 'pending', status: 'queued', position: 1 }],
        canGuide: true,
        submittingIds: new Set(['q1']),
      },
    })

    // Every mutating action button is disabled while the item is guided; the
    // decorative ellipsis (aria-hidden, tabindex=-1) intentionally stays enabled
    expect(wrapper.findAll('button.core-queued-input-action').every(button => button.attributes('disabled') !== undefined)).toBe(true)
  })

  // user:“排队项可拖拽上下移动重新排序”+(按住行拖到目标行松手：按落点在目标行的
  //   上/下半区决定插到它之前还是之后，提交一份完整新顺序；拖回原位不提交)。
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('reorders rows by drag and drop and skips no-op drags', async () => {
    const items = [
      { id: 'q1', text: 'one', status: 'queued', position: 1 },
      { id: 'q2', text: 'two', status: 'queued', position: 2 },
      { id: 'q3', text: 'three', status: 'queued', position: 3 },
    ]
    const wrapper = mount(CoreQueuedInputTray, { props: { items } })
    const rows = () => wrapper.findAll('.core-queued-input-row')
    expect(rows().length).toBe(3)

    // 把 q1 拖到 q3 的下半区（clientY 落在行高下半段）：新顺序 [q2, q3, q1]。
    await rows()[0].trigger('dragstart', { dataTransfer: { setData: () => undefined, effectAllowed: '' } })
    vi.spyOn(rows()[2].element, 'getBoundingClientRect').mockReturnValue(
      { top: 0, height: 100, bottom: 100, left: 0, right: 0, width: 0, x: 0, y: 0, toJSON: () => undefined } as DOMRect,
    )
    await rows()[2].trigger('dragover', { clientY: 80, dataTransfer: { dropEffect: '' } })
    await rows()[2].trigger('drop', { clientY: 80, dataTransfer: { getData: () => 'q1' }, preventDefault: () => undefined })
    await rows()[2].trigger('dragend')

    expect(wrapper.emitted('reorder')?.[0]).toEqual([
      [{ id: 'q2', text: 'two', status: 'queued', position: 2 }, { id: 'q3', text: 'three', status: 'queued', position: 3 }, { id: 'q1', text: 'one', status: 'queued', position: 1 }],
    ])
  })

  it('does not emit a reorder when the row drops back onto itself', async () => {
    const items = [
      { id: 'q1', text: 'one', status: 'queued', position: 1 },
      { id: 'q2', text: 'two', status: 'queued', position: 2 },
    ]
    const wrapper = mount(CoreQueuedInputTray, { props: { items } })
    const rows = () => wrapper.findAll('.core-queued-input-row')

    await rows()[0].trigger('dragstart', { dataTransfer: { setData: () => undefined, effectAllowed: '' } })
    // 悬停在自己身上不产生插入提示；落回自己不提交任何顺序。
    await rows()[0].trigger('dragover', { clientY: 10, dataTransfer: { dropEffect: '' } })
    await rows()[0].trigger('drop', { clientY: 10, dataTransfer: { getData: () => 'q1' }, preventDefault: () => undefined })
    await rows()[0].trigger('dragend')

    expect(wrapper.emitted('reorder')).toBeUndefined()
  })
})
