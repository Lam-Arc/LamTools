import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ReferenceItems from '../src/components/ReferenceItems.vue'

function artifact(index: number, path = '') {
  return {
    artifact_id: `result-${index}`,
    name: `result-${index}.ts`,
    kind: 'file',
    path,
    metadata: {},
  }
}

describe('outcome files collapse', () => {
  it('shows six outcome files by default and folds the rest behind a toggle', async () => {
    // user:“把底下跟的那一堆成果文件默认折叠一下，正常显示 6 个，多余 6 个的就折叠进去”
    const wrapper = mount(ReferenceItems, {
      props: {
        artifacts: Array.from({ length: 8 }, (_, index) => artifact(index)) as never,
        transport: { request: vi.fn() } as never,
      },
    })
    await flushPromises()

    expect(wrapper.findAll('.reference-item:not(.reference-item--more)')).toHaveLength(6)
    const toggle = wrapper.get('[data-reference-toggle]')
    expect(toggle.text()).toContain('展开其余 2 项')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(wrapper.findAll('.file-type-badge')).toHaveLength(6)
    expect(wrapper.text()).not.toContain('@')

    await toggle.trigger('click')
    expect(wrapper.findAll('.reference-item:not(.reference-item--more)')).toHaveLength(8)
    expect(wrapper.get('[data-reference-toggle]').text()).toContain('收起')

    await wrapper.get('[data-reference-toggle]').trigger('click')
    expect(wrapper.findAll('.reference-item:not(.reference-item--more)')).toHaveLength(6)
  })

  it('marks the folded toggle when a hidden outcome file is missing', async () => {
    // 缺失文件仍在原位置显示红色状态；折叠时由“展开其余”按钮带红色 ! 提醒。
    const request = vi.fn(async () => ({
      status: 404,
      headers: {},
      body: new TextEncoder().encode(JSON.stringify({ detail: '原文件不存在' })),
    }))
    const artifacts = Array.from({ length: 7 }, (_, index) => artifact(index))
    artifacts.push(artifact(7, 'C:/missing.ts'))

    const wrapper = mount(ReferenceItems, {
      props: { artifacts: artifacts as never, transport: { request } as never, workRoot: 'C:/' },
    })
    await flushPromises()

    await vi.waitFor(() => {
      expect(wrapper.get('[data-reference-toggle] .reference-item-error').exists()).toBe(true)
    })

    await wrapper.get('[data-reference-toggle]').trigger('click')
    const items = wrapper.findAll('.reference-item:not(.reference-item--more)')
    expect(items).toHaveLength(8)
    expect(items[7]!.classes()).toContain('reference-item--failed')
    expect(items[7]!.find('.file-type-badge').exists()).toBe(true)
  })
})
