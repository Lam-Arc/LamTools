import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import MaterialsView from '../src/components/MaterialsView.vue'

/**
 * user:“库本身的全局与项目划分也仅是一个文件划分”+(资料库默认是全局库：
 * 从任何项目进来都先看到所有项目的资料；项目只作为筛选和归属标签，
 * 打开、改标签等操作要落在条目自己的项目上)。
 */

function artifact(id: string, name: string, projectId: string, extra: Record<string, unknown> = {}) {
  return {
    artifact_id: id,
    name,
    path: `workspace://${name}`,
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
    project_id: projectId,
    work_root: projectId === 'p1' ? 'C:/work/a' : 'C:/work/b',
    ...extra,
  }
}

function makeRpc(rows: ReturnType<typeof artifact>[]) {
  const calls: Array<{ method: string; params: Record<string, unknown> }> = []
  const rpc = vi.fn(async (method: string, params: Record<string, unknown> = {}) => {
    calls.push({ method, params })
    if (method === 'artifact.list') {
      const scoped = params.all_projects
        ? rows
        : rows.filter(row => row.project_id === params.project_id)
      return { artifacts: scoped }
    }
    if (method === 'artifact.stats') return { count: rows.length, bytes: 2048 }
    return {}
  })
  return { rpc, calls }
}

async function mountView(
  rows: ReturnType<typeof artifact>[],
  projects = [{ id: 'p1', name: '甲项目' }, { id: 'p2', name: '乙项目' }],
) {
  const { rpc, calls } = makeRpc(rows)
  const wrapper = mount(MaterialsView, {
    props: {
      projectId: 'p1',
      projects,
      workRoot: 'C:/work/a',
      requestRpc: rpc as never,
      transport: {} as never,
      uploadFiles: async () => {},
    },
  })
  await flushPromises()
  return { wrapper, calls }
}

describe('资料库 · 全局库', () => {
  it('默认列出所有项目的资料，并标出每条属于哪个项目', async () => {
    const { wrapper, calls } = await mountView([
      artifact('a1', '甲.md', 'p1'),
      artifact('a2', '乙.md', 'p2'),
    ])

    expect(calls.find(call => call.method === 'artifact.list')?.params).toMatchObject({ all_projects: true })
    expect(wrapper.findAll('[data-material]')).toHaveLength(2)
    expect(wrapper.findAll('[data-material-project]').map(node => node.text())).toEqual(['甲项目', '乙项目'])
    expect(wrapper.get('[data-materials-usage]').text()).toContain('全部项目')

    wrapper.unmount()
  })

  it('按项目筛选只取那个项目，清掉筛选回到全部', async () => {
    const { wrapper, calls } = await mountView([
      artifact('a1', '甲.md', 'p1'),
      artifact('a2', '乙.md', 'p2'),
    ])

    await wrapper.get('[data-materials-project-filter]').setValue('p2')
    await flushPromises()
    expect(calls.filter(call => call.method === 'artifact.list').pop()?.params).toMatchObject({ project_id: 'p2' })
    expect(wrapper.findAll('[data-material]')).toHaveLength(1)
    expect(wrapper.get('[data-materials-usage]').text()).toContain('乙项目')

    await wrapper.get('[data-materials-project-filter]').setValue('')
    await flushPromises()
    expect(calls.filter(call => call.method === 'artifact.list').pop()?.params).toMatchObject({ all_projects: true })
    expect(wrapper.findAll('[data-material]')).toHaveLength(2)

    wrapper.unmount()
  })

  it('打开与改标签都用条目自己的项目，不用当前项目', async () => {
    const { wrapper, calls } = await mountView([artifact('a2', '乙.md', 'p2')])

    await wrapper.get('[data-material="a2"]').trigger('click')
    await flushPromises()
    expect(calls.find(call => call.method === 'artifact.open')?.params).toMatchObject({ project_id: 'p2' })

    const tagInput = wrapper.get('[data-material-tag-input="a2"]')
    await tagInput.setValue('logo')
    await tagInput.trigger('keydown.enter')
    await flushPromises()
    expect(calls.find(call => call.method === 'artifact.tags')?.params)
      .toMatchObject({ project_id: 'p2', tags: ['logo'] })

    wrapper.unmount()
  })

  it('全局库里文件夹页签让位给项目筛选，选中项目后才出现', async () => {
    const { wrapper } = await mountView([artifact('a1', '甲.md', 'p1', { folder: '素材' })])

    expect(wrapper.find('[data-materials-tab="folders"]').exists()).toBe(false)
    await wrapper.get('[data-materials-project-filter]').setValue('p1')
    await flushPromises()
    expect(wrapper.find('[data-materials-tab="folders"]').exists()).toBe(true)

    wrapper.unmount()
  })
})

it('只有一个项目时仍可进入它的归档文件夹', async () => {
  const { wrapper } = await mountView(
    [artifact('a1', '甲.md', 'p1', { folder: '素材' })],
    [{ id: 'p1', name: '甲项目' }],
  )

  await wrapper.get('[data-materials-project-filter]').setValue('p1')
  await flushPromises()
  await wrapper.get('[data-materials-tab="folders"]').trigger('click')
  await wrapper.get('[data-materials-folder="素材"]').trigger('click')
  expect(wrapper.get('[data-material="a1"]').text()).toContain('甲.md')

  wrapper.unmount()
})
