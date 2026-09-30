import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import PlanLibraryView from '../src/components/PlanLibraryView.vue'
import type { CorePlanLibraryEntry, CoreProjectClient } from '../src/projects/client'

const entry = (overrides: Partial<CorePlanLibraryEntry> = {}): CorePlanLibraryEntry => ({
  name: '导出显示进度.md',
  path: '方案/导出显示进度.md',
  title: '导出显示进度',
  status: 'draft',
  summary: '导出长报告时让用户看见进度',
  size: 120,
  updated_at: 1759200000,
  ...overrides,
})

function fakeClient(overrides: Partial<CoreProjectClient> = {}): CoreProjectClient {
  const client = {
    listPlanLibrary: vi.fn(async () => ({ dir: '方案', entries: [entry()] })),
    readFile: vi.fn(async () => ({ path: '方案/导出显示进度.md', content: '# 导出显示进度\n\n## 步骤\n1. 做点什么\n' })),
    deletePlanLibraryFile: vi.fn(async (projectId: string, path: string) => ({ deleted: path })),
    ...overrides,
  } as unknown as CoreProjectClient
  return client
}

async function settled(): Promise<void> {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

describe('PlanLibraryView', () => {
  it('lists what the 方案 folder holds and opens one as a document', async () => {
    const client = fakeClient()
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()

    expect(client.listPlanLibrary).toHaveBeenCalledWith('proj-1')
    const items = wrapper.findAll('[data-library-entry]')
    expect(items).toHaveLength(1)
    expect(items[0].text()).toContain('导出显示进度')
    expect(items[0].text()).toContain('导出长报告时让用户看见进度')
    expect(items[0].text()).toContain('草稿')

    await items[0].trigger('click')
    await settled()
    expect(client.readFile).toHaveBeenCalledWith('proj-1', '方案/导出显示进度.md')
    expect(wrapper.get('.library-document').text()).toContain('做点什么')
  })

  it('guides an empty library towards the conversation', async () => {
    const client = fakeClient({ listPlanLibrary: vi.fn(async () => ({ dir: '方案', entries: [] })) } as never)
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()

    const empty = wrapper.get('[data-library-empty]')
    expect(empty.text()).toContain('还没有方案')
    expect(empty.text()).toContain('在聊天里说出你的想法')
    expect(empty.text()).toContain('Markdown')
  })

  it('only lets a ready plan start, and says why when it cannot', async () => {
    const client = fakeClient({
      listPlanLibrary: vi.fn(async () => ({
        dir: '方案',
        entries: [
          entry({ status: 'ready' }),
          entry({ name: '草稿一份.md', path: '方案/草稿一份.md', title: '草稿一份', status: 'draft' }),
        ],
      })),
    } as never)
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()

    await wrapper.findAll('[data-library-entry]')[0].trigger('click')
    await settled()
    const start = wrapper.get('[data-library-start]')
    expect(start.attributes('disabled')).toBeUndefined()
    await start.trigger('click')
    expect(wrapper.emitted('start-plan')?.[0]?.[0]).toMatchObject({ path: '方案/导出显示进度.md' })

    await wrapper.findAll('[data-library-entry]')[1].trigger('click')
    await settled()
    const blocked = wrapper.get('[data-library-start]')
    expect(blocked.attributes('disabled')).toBeDefined()
    expect(blocked.attributes('title')).toContain('就绪')
  })

  it('deletes in two steps and reloads the list', async () => {
    const client = fakeClient()
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()
    await wrapper.get('[data-library-entry]').trigger('click')
    await settled()

    const remove = wrapper.get('[data-library-delete]')
    await remove.trigger('click')
    expect(remove.attributes('data-library-delete')).toBe('confirm')
    expect(client.deletePlanLibraryFile).not.toHaveBeenCalled()

    await remove.trigger('click')
    await settled()
    expect(client.deletePlanLibraryFile).toHaveBeenCalledWith('proj-1', '方案/导出显示进度.md')
    expect(client.listPlanLibrary).toHaveBeenCalledTimes(2)
  })

  it('edits through the host, and the desktop header band is the way back', async () => {
    const client = fakeClient()
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()
    await wrapper.get('[data-library-entry]').trigger('click')
    await settled()

    const buttons = wrapper.findAll('.library-reader-actions button')
    await buttons[1].trigger('click')
    expect(wrapper.emitted('edit-plan')?.[0]).toEqual(['方案/导出显示进度.md'])

    // 桌面没有界面内的返回键：返回键在顶部条上（宿主渲染）。
    expect(wrapper.find('.library-back').exists()).toBe(false)
    wrapper.unmount()
  })

  it('sends the refresh action to the header band on desktop', async () => {
    const client = fakeClient()
    const wrapper = mount(PlanLibraryView, {
      props: { client, projectId: 'proj-1', bandActions: false },
    })
    await settled()
    const refresh = wrapper.get('[data-library-refresh]')
    await refresh.trigger('click')
    await settled()
    expect(client.listPlanLibrary).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('rescans when the host bumps the refresh signal', async () => {
    const client = fakeClient()
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1', refreshSignal: 0 } })
    await settled()
    expect(client.listPlanLibrary).toHaveBeenCalledTimes(1)

    await wrapper.setProps({ refreshSignal: 1 })
    await settled()
    expect(client.listPlanLibrary).toHaveBeenCalledTimes(2)
  })
})
