import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import MaterialsView from '../src/components/MaterialsView.vue'

/** user:“人只做观测和选用”+(选中的候选并排摆开；卡片上能看出被用过几次)。 */
function artifact(id: string, name: string, extra: Record<string, unknown> = {}) {
  return {
    artifact_id: id,
    name,
    path: `workspace://${name}`,
    uri: `workspace://${name}`,
    kind: 'file',
    role: 'deliverable',
    mime_type: 'text/css',
    favorite: false,
    deleted: false,
    folder: '',
    updated_at: new Date().toISOString(),
    tags: [],
    rating: 0,
    ...extra,
  }
}

function mountView(rows: ReturnType<typeof artifact>[]) {
  const requestRpc = vi.fn(async (method: string) => {
    if (method === 'artifact.list') return { artifacts: rows }
    if (method === 'artifact.stats') return { count: rows.length, bytes: 10 }
    return {}
  })
  const wrapper = mount(MaterialsView, {
    props: {
      projectId: 'p1',
      workRoot: '/lab',
      requestRpc: requestRpc as never,
      transport: {} as never,
      uploadFiles: async () => {},
    },
  })
  return { wrapper, requestRpc }
}

describe('资料库 · 取用痕迹与并排对比', () => {
  it('卡片上显示被用过几次', async () => {
    const { wrapper } = mountView([artifact('a1', 'glass.css', { usage_count: 3 })])
    await flushPromises()
    expect(wrapper.get('[data-material-used]').text()).toContain('3')
  })

  it('没被用过就不写次数，避免每张卡都挂一个 0', async () => {
    const { wrapper } = mountView([artifact('a1', 'glass.css')])
    await flushPromises()
    expect(wrapper.find('[data-material-used]').exists()).toBe(false)
  })

  it('选中两件才能并排对比，面板里带着星级与用法', async () => {
    const { wrapper } = mountView([
      artifact('a1', 'glass-high.css', {
        rating: 5,
        tags: ['material', 'glass'],
        usage: { entry: '.optical-glass', requires: '父级要有底色' },
        usage_count: 4,
      }),
      artifact('a2', 'glass-low.css', {
        rating: 4,
        tags: ['material', 'glass', 'low-trans'],
        usage: { entry: '.optical-glass--low-trans', requires: '父级要有底色' },
      }),
    ])
    await flushPromises()

    // 没选中任何东西时不出现批量栏，自然也没有对比入口
    expect(wrapper.find('[data-materials-compare-open]').exists()).toBe(false)

    await wrapper.get('[data-material-check="a1"]').trigger('click')
    expect(wrapper.get('[data-materials-compare-open]').attributes('disabled')).toBeDefined()

    await wrapper.get('[data-material-check="a2"]').trigger('click')
    expect(wrapper.get('[data-materials-compare-open]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-materials-compare-open]').trigger('click')
    await flushPromises()

    // 面板传送到 body（资料库整体带缩放，留在原地会被裁掉），所以从 document 上找
    const cells = document.body.querySelectorAll('[data-compare-item]')
    expect(cells).toHaveLength(2)
    const panelText = document.body.querySelector('[data-materials-compare]')?.textContent ?? ''
    expect(panelText).toContain('.optical-glass--low-trans')
    expect(panelText).toContain('用过 4 次')

    document.body.querySelector<HTMLElement>('[data-materials-compare-close]')?.click()
    await flushPromises()
    expect(document.body.querySelector('[data-materials-compare]')).toBeNull()
    wrapper.unmount()
  })

  it('只选一件时对比按钮不可用', async () => {
    const { wrapper } = mountView([artifact('a1', 'one.css'), artifact('a2', 'two.css')])
    await flushPromises()
    await wrapper.get('[data-material-check="a1"]').trigger('click')
    expect(wrapper.get('[data-materials-compare-open]').attributes('disabled')).toBeDefined()
  })
})
