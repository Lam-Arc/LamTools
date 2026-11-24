import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import MaterialsView from '../src/components/MaterialsView.vue'

/**
 * user:“去找四个库中用户体验最差的点，处理掉”+
 * (资料库检索的验收：标签是主检索键，搜索必须匹配它；只出现一次的标签也要能点选；
 *  筛选没命中时说清楚“没有匹配”并给一键清除，不冒充空库、也不留白；
 *  在「文件夹」页签输入关键词时同样要给出文件结果。)
 */

function artifact(id: string, name: string, extra: Record<string, unknown> = {}) {
  return {
    artifact_id: id,
    name,
    path: `workspace://${extra.folder ? `${extra.folder}/` : ''}${name}`,
    uri: `workspace://${name}`,
    kind: 'file',
    role: 'deliverable',
    mime_type: 'text/plain',
    favorite: false,
    deleted: false,
    folder: '',
    updated_at: '2026-11-01T09:00:00',
    tags: [],
    rating: 0,
    ...extra,
  }
}

function makeRpc(rows: ReturnType<typeof artifact>[]) {
  return vi.fn(async (method: string) => {
    if (method === 'artifact.list') return { artifacts: rows }
    if (method === 'artifact.stats') return { count: rows.length, bytes: 1024 }
    return {}
  })
}

async function mountView(rows: ReturnType<typeof artifact>[]) {
  const wrapper = mount(MaterialsView, {
    props: {
      projectId: 'p1',
      workRoot: '/lab',
      requestRpc: makeRpc(rows) as never,
      transport: {} as never,
      uploadFiles: async () => {},
    },
  })
  await flushPromises()
  return wrapper
}

const names = (wrapper: ReturnType<typeof mount>) =>
  wrapper.findAll('[data-material]').map(node => node.attributes('data-material'))

describe('资料库 · 检索与无结果恢复', () => {
  it('搜索命中标签，而不只是文件名', async () => {
    const wrapper = await mountView([
      artifact('a1', 'one.css', { tags: ['button'] }),
      artifact('a2', 'two.md', { tags: ['logo'] }),
    ])

    await wrapper.get('[data-materials-search]').setValue('logo')
    await flushPromises()
    expect(names(wrapper)).toEqual(['a2'])

    await wrapper.get('[data-materials-search]').setValue('button')
    await flushPromises()
    expect(names(wrapper)).toEqual(['a1'])

    wrapper.unmount()
  })

  it('筛选条列出只出现一次的标签，点一下就只剩带它的条目', async () => {
    const wrapper = await mountView([
      artifact('a1', 'one.css', { tags: ['css'] }),
      artifact('a2', 'two.md', { tags: ['button'] }),
    ])

    const chip = wrapper.get('[data-materials-tag="button"]')
    expect(chip.text()).toBe('button')

    await chip.trigger('click')
    await flushPromises()
    expect(names(wrapper)).toEqual(['a2'])

    wrapper.unmount()
  })

  it('搜索没有结果时说“没有匹配的文件”并给一键清除，而不是“资料库还是空的”', async () => {
    const wrapper = await mountView([
      artifact('a1', 'one.css', { tags: ['css'] }),
      artifact('a2', 'two.md', { tags: ['logo'] }),
    ])

    await wrapper.get('[data-materials-search]').setValue('zzz')
    await flushPromises()

    expect(wrapper.find('[data-materials-empty]').exists()).toBe(false)
    const noResults = wrapper.get('[data-materials-no-results]')
    expect(noResults.text()).toContain('没有匹配的文件')

    await wrapper.get('[data-materials-clear-filters]').trigger('click')
    await flushPromises()
    expect((wrapper.get('[data-materials-search]').element as HTMLInputElement).value).toBe('')
    expect(names(wrapper)).toEqual(['a1', 'a2'])

    wrapper.unmount()
  })

  it('收藏页签为空、但库里有文件夹时，说明没有匹配而不是留白', async () => {
    const wrapper = await mountView([
      artifact('a1', 'one.css', { folder: '素材', tags: ['css'] }),
    ])

    await wrapper.get('[data-materials-tab="favorite"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-materials-no-results]').exists()).toBe(true)
    expect(wrapper.find('[data-materials-empty]').exists()).toBe(false)

    wrapper.unmount()
  })

  it('文件夹页签里输入关键词直接给文件结果（跨层）', async () => {
    const wrapper = await mountView([
      artifact('a1', 'root.md'),
      artifact('a2', 'logo.svg', { folder: '素材' }),
    ])

    await wrapper.get('[data-materials-tab="folders"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-materials-folder="素材"]').exists()).toBe(true)

    await wrapper.get('[data-materials-search]').setValue('logo')
    await flushPromises()
    expect(wrapper.find('[data-materials-folder="素材"]').exists()).toBe(false)
    expect(names(wrapper)).toEqual(['a2'])

    wrapper.unmount()
  })

  it('在文件夹里搜不到时，不再说“这一层还没有文件”', async () => {
    const wrapper = await mountView([
      artifact('a1', '甲.md', { folder: '项目A' }),
    ])

    await wrapper.get('[data-materials-tab="folders"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-materials-folder="项目A"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-materials-search]').setValue('zzz')
    await flushPromises()

    expect(wrapper.find('[data-materials-no-results]').exists()).toBe(true)
    expect(wrapper.find('[data-materials-empty]').exists()).toBe(false)

    wrapper.unmount()
  })
})
