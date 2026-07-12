import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
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

    expect(wrapper.findAll('button').every(button => button.attributes('disabled') !== undefined)).toBe(true)
  })
})
