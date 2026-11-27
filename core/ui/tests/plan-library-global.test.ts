import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import PlanLibraryView from '../src/components/PlanLibraryView.vue'
import type { CorePlanLibraryEntry, CoreProjectClient } from '../src/projects/client'

/**
 * user:“库本身的全局与项目划分也仅是一个文件划分”+(方案库先列所有项目的位置；
 * 进哪个项目才读哪个项目的「方案/」，返回回到项目清单，而不是被当前项目锁住)。
 */

const entry = (project: string): CorePlanLibraryEntry => ({
  name: `${project}-方案.md`,
  path: `方案/${project}-方案.md`,
  folder: '',
  title: `${project} 的方案`,
  status: 'ready',
  summary: '一个可开工的方案',
  favorite: false,
  size: 120,
  updated_at: 1759200000,
})

function fakeClient() {
  const listPlanLibrary = vi.fn(async (projectId: string) => ({
    dir: '方案',
    entries: projectId === 'p2' ? [entry('p2')] : [],
    folders: [],
  }))
  return {
    listPlanLibrary,
    readFile: vi.fn(async (_projectId: string, path: string) => ({ path, content: '# 方案\n' })),
    writeFile: vi.fn(async (_projectId: string, path: string, content: string) => ({ path, content })),
    deletePlanLibraryFile: vi.fn(async (_projectId: string, path: string) => ({ deleted: path })),
    favoritePlanLibraryFile: vi.fn(async (_projectId: string, path: string, favorite: boolean) => ({
      entry: { ...entry('p2'), path, favorite },
    })),
    createPlanLibraryFile: vi.fn(),
    createPlanLibraryFolder: vi.fn(),
    renamePlanLibraryFile: vi.fn(),
    movePlanLibraryFile: vi.fn(),
    deletePlanLibraryFolder: vi.fn(),
  } as unknown as CoreProjectClient
}

async function settled(rounds = 10): Promise<void> {
  for (let index = 0; index < rounds; index += 1) await Promise.resolve()
}

describe('方案库 · 全局库', () => {
  it('库根列出所有项目，进入项目才读它的方案，返回回到项目清单', async () => {
    const client = fakeClient()
    const wrapper = mount(PlanLibraryView, {
      props: {
        client,
        projectId: 'p1',
        projects: [{ id: 'p1', name: '甲项目' }, { id: 'p2', name: '乙项目' }],
      },
    })
    await settled()

    // 库根不读任何单个项目；先摆出所有项目的位置，并标出当前项目。
    expect(client.listPlanLibrary).not.toHaveBeenCalled()
    expect(wrapper.findAll('[data-plan-project]').map(node => node.attributes('data-plan-project')))
      .toEqual(['p1', 'p2'])
    expect(wrapper.get('[data-plan-project="p1"]').text()).toContain('当前项目')

    await wrapper.get('[data-plan-project="p2"]').trigger('click')
    await settled()
    expect(client.listPlanLibrary).toHaveBeenCalledWith('p2')
    expect(wrapper.findAll('[data-library-entry]')).toHaveLength(1)
    expect(wrapper.text()).toContain('乙项目')

    await wrapper.get('[data-library-entry]').trigger('click')
    await settled()
    await wrapper.get('[data-library-start]').trigger('click')
    await wrapper.get('[data-plan-action="discuss"]').trigger('click')
    expect(wrapper.emitted('start-plan')?.[0]?.[0]).toMatchObject({
      entry: { path: entry('p2').path }, sourceProjectId: 'p2',
    })
    expect(wrapper.emitted('plan-action')?.[0]?.[0]).toMatchObject({
      entry: { path: entry('p2').path }, sourceProjectId: 'p2', action: 'discuss',
    })
    expect((wrapper.vm as unknown as { handleBack: () => boolean }).handleBack()).toBe(true)
    await settled()

    // 从项目里退一步回到项目清单，而不是退出整个资料库。
    expect((wrapper.vm as unknown as { handleBack: () => boolean }).handleBack()).toBe(true)
    await settled()
    expect(wrapper.findAll('[data-plan-project]')).toHaveLength(2)

    wrapper.unmount()
  })

  it('没有项目时说明下一步，而不是显示一个空库', async () => {
    const client = fakeClient()
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: null, projects: [] } })
    await settled()

    expect(wrapper.text()).toContain('还没有项目')
    expect(wrapper.find('[data-plan-projects]').exists()).toBe(false)
    wrapper.unmount()
  })
})
