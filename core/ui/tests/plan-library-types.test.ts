import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import PlanLibraryView from '../src/components/PlanLibraryView.vue'
import type { CorePlanLibraryEntry, CoreProjectClient } from '../src/projects/client'

/**
 * 方案体系（PRD §3 / §6 / §7 / §8）：类型、专题、双状态、阅读页目录与关联、
 * 元数据写回、Agent 动作与按类型的创建。数据模型由后端 scan 提供，这里只
 * 验证界面确实把这些字段呈现出来、把用户动作带到对应的客户端调用与事件。
 */

const entry = (overrides: Partial<CorePlanLibraryEntry> = {}): CorePlanLibraryEntry => ({
  name: '记忆检索.md',
  path: '方案/记忆检索.md',
  folder: '',
  title: '记忆检索机制',
  status: 'ready',
  design_status: 'active',
  impl_status: 'none',
  type: 'SPEC',
  type_label: '技术规范',
  topic: 'Sunday Memory',
  related: [],
  summary: '检索协议与边界',
  favorite: false,
  size: 200,
  updated_at: 1759200000,
  ...overrides,
})

function fakeClient(entries: CorePlanLibraryEntry[], content = ''): CoreProjectClient {
  return {
    listPlanLibrary: vi.fn(async () => ({ dir: '方案', entries, folders: [] })),
    readFile: vi.fn(async (_projectId: string, path: string) => ({
      path,
      content: content || '# 记忆检索机制\n\n## 背景\n\n正文。\n\n## 机制\n\n正文。\n',
    })),
    writeFile: vi.fn(async (_projectId: string, path: string, body: string) => ({ path, content: body })),
    deletePlanLibraryFile: vi.fn(async (_projectId: string, path: string) => ({ deleted: path })),
    favoritePlanLibraryFile: vi.fn(async (_projectId: string, path: string, favorite: boolean) => ({
      entry: entry({ path, favorite }),
    })),
    createPlanLibraryFile: vi.fn(async (_projectId: string, name: string, folder = '', type = '', topic = '') => ({
      entry: entry({
        name: `${name}.md`,
        path: folder ? `方案/${folder}/${name}.md` : `方案/${name}.md`,
        folder,
        title: name,
        type: type as CorePlanLibraryEntry['type'],
        topic,
      }),
    })),
    createPlanLibraryFolder: vi.fn(async (_projectId: string, name: string) => ({
      folder: { name, path: `方案/${name}`, dir: name, parent: '', count: 0 },
    })),
    setPlanLibraryMeta: vi.fn(async (_projectId: string, path: string, patch: Record<string, unknown>) => ({
      entry: entry({ path, ...(patch as Partial<CorePlanLibraryEntry>) }),
    })),
    importPlanLibraryFile: vi.fn(async (_projectId: string, path: string) => ({ entry: entry({ name: path }) })),
  } as unknown as CoreProjectClient
}

async function settled(): Promise<void> {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

describe('方案体系界面', () => {
  it('shows the type badge and topic on cards, and filters by type / topic / impl status', async () => {
    const plans = [
      entry(),
      entry({
        name: '记忆实验.md',
        path: '方案/记忆实验.md',
        title: '记忆注入实验',
        type: 'EXP',
        type_label: '实验方案',
        topic: 'Sunday Memory',
        impl_status: 'doing',
        status: 'executing',
        design_status: 'active',
        updated_at: 1759300000,
      }),
      entry({
        name: '计费PRD.md',
        path: '方案/计费PRD.md',
        title: '计费 PRD',
        type: 'PRD',
        type_label: '产品需求文档',
        topic: '',
        design_status: 'draft',
        status: 'draft',
      }),
    ]
    const client = fakeClient(plans)
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()

    expect(wrapper.findAll('[data-library-entry]')).toHaveLength(3)
    expect(wrapper.get('[data-plan-type="SPEC"]').text()).toContain('技术规范')
    expect(wrapper.text()).toContain('Sunday Memory')

    await wrapper.get('[data-plan-filter-type]').setValue('EXP')
    await settled()
    expect(wrapper.findAll('[data-library-entry]').map(el => el.attributes('data-library-entry'))).toEqual(['记忆实验.md'])

    await wrapper.get('[data-plan-filter-type]').setValue('')
    await wrapper.get('[data-plan-filter-topic]').setValue('Sunday Memory')
    await settled()
    expect(wrapper.findAll('[data-library-entry]')).toHaveLength(2)

    await wrapper.get('[data-plan-filter-topic]').setValue('')
    await wrapper.get('[data-plan-filter-impl]').setValue('doing')
    await settled()
    expect(wrapper.findAll('[data-library-entry]').map(el => el.attributes('data-library-entry'))).toEqual(['记忆实验.md'])

    await wrapper.get('[data-plan-clear-filters]').trigger('click')
    await settled()
    expect(wrapper.findAll('[data-library-entry]')).toHaveLength(3)
    wrapper.unmount()
  })

  it('reads a plan with its design/impl status, a table of contents and related plans from the same topic', async () => {
    const plans = [
      entry({ related: ['会话:s-42'] }),
      entry({
        name: '记忆SPEC.md',
        path: '方案/记忆SPEC.md',
        title: '记忆检索规范',
        type: 'SPEC',
        type_label: '技术规范',
        topic: 'Sunday Memory',
        design_status: 'active',
        status: 'ready',
      }),
    ]
    const client = fakeClient(plans)
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()

    await wrapper.findAll('[data-library-entry]')[0].trigger('click')
    await settled(); await settled()

    const reader = wrapper.get('[data-library-reader]')
    expect(reader.get('[data-plan-type]').text()).toBe('技术规范')
    expect(reader.get('[data-plan-status]').text()).toBe('生效')
    // 未实施不占一行；已实施才出现第二个状态。
    expect(reader.find('[data-plan-impl]').exists()).toBe(false)
    expect(reader.get('[data-plan-topic]').text()).toContain('Sunday Memory')

    // 目录来自正文的二级标题。
    const toc = reader.findAll('[data-plan-toc-item]').map(item => item.text())
    expect(toc).toEqual(['背景', '机制'])

    // 同专题的其它方案 + 关联会话都列在「关联」里。
    expect(reader.get('[data-plan-relation="方案/记忆SPEC.md"]').text()).toContain('记忆检索规范')
    expect(reader.get('[data-plan-session="s-42"]').text()).toContain('s-42')

    // 点关联方案直接打开那一份。
    await reader.get('[data-plan-relation="方案/记忆SPEC.md"]').trigger('click')
    await settled(); await settled()
    expect(wrapper.get('.library-reader-title').text()).toBe('记忆检索规范')
    wrapper.unmount()
  })

  it('edits type / status / topic through the metadata panel without touching the body', async () => {
    const client = fakeClient([entry()])
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()
    await wrapper.findAll('[data-library-entry]')[0].trigger('click')
    await settled(); await settled()

    await wrapper.get('[data-plan-meta-toggle]').trigger('click')
    expect(wrapper.find('[data-plan-meta-panel]').exists()).toBe(true)
    await wrapper.get('[data-plan-meta-type]').setValue('PRD')
    await wrapper.get('[data-plan-meta-design]').setValue('archived')
    await wrapper.get('[data-plan-meta-impl]').setValue('review')
    await wrapper.get('[data-plan-meta-topic]').setValue('计费')
    await wrapper.get('[data-plan-meta-save]').trigger('click')
    await settled(); await settled()

    expect(client.setPlanLibraryMeta).toHaveBeenCalledWith('proj-1', '方案/记忆检索.md', {
      type: 'PRD',
      design_status: 'archived',
      impl_status: 'review',
      topic: '计费',
    })
    expect(wrapper.find('[data-plan-meta-panel]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('sends the five agent actions as one plan-action event with the entry', async () => {
    const client = fakeClient([entry()])
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()
    await wrapper.findAll('[data-library-entry]')[0].trigger('click')
    await settled(); await settled()

    const actions = wrapper.findAll('[data-plan-action]').map(button => button.attributes('data-plan-action'))
    expect(actions).toEqual(['discuss', 'review', 'revise', 'execute', 'check'])

    await wrapper.get('[data-plan-action="discuss"]').trigger('click')
    expect(wrapper.emitted('plan-action')?.[0]?.[0]).toMatchObject({
      entry: { path: '方案/记忆检索.md' },
      action: 'discuss',
    })
    wrapper.unmount()
  })

  it('creates a plan with the chosen type and keeps the type optional', async () => {
    const client = fakeClient([entry()])
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()

    await wrapper.get('[data-library-create]').trigger('click')
    expect(wrapper.find('[data-library-dialog-type]').exists()).toBe(true)
    await wrapper.get('[data-library-dialog-input="create-plan"]').setValue('计费重构')
    await wrapper.get('[data-library-dialog-type]').setValue('PRD')
    await wrapper.get('[data-library-dialog-submit]').trigger('click')
    await settled(); await settled()

    expect(client.createPlanLibraryFile).toHaveBeenCalledWith('proj-1', '计费重构', '', 'PRD', '')
    wrapper.unmount()
  })

  it('imports an existing markdown file instead of asking for a form', async () => {
    const client = fakeClient([entry()])
    const newline = String.fromCharCode(10)
    const imported = ['# 旧方案', '', '正文。', ''].join(newline)
    const importPlanFile = vi.fn(async () => ({ name: '旧方案.md', text: imported }))
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1', importPlanFile } })
    await settled()

    await wrapper.get('[data-library-import]').trigger('click')
    await settled(); await settled(); await settled()

    expect(client.createPlanLibraryFile).toHaveBeenCalledWith('proj-1', '旧方案', '', '', '')
    expect(client.writeFile).toHaveBeenCalledWith('proj-1', '方案/旧方案.md', imported)
    wrapper.unmount()
  })

  it('sorts by name when asked, newest first by default', async () => {
    const client = fakeClient([
      entry({ name: 'B方案.md', path: '方案/B方案.md', title: 'B 方案', updated_at: 1759100000 }),
      entry({ name: 'A方案.md', path: '方案/A方案.md', title: 'A 方案', updated_at: 1759200000 }),
    ])
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()

    expect(wrapper.findAll('[data-library-entry]').map(el => el.attributes('data-library-entry')))
      .toEqual(['A方案.md', 'B方案.md'])

    await wrapper.get('[data-plan-sort]').setValue('name')
    await settled()
    expect(wrapper.findAll('[data-library-entry]').map(el => el.attributes('data-library-entry')))
      .toEqual(['A方案.md', 'B方案.md'])

    await wrapper.get('[data-plan-sort]').setValue('type')
    await settled()
    // 同为 SPEC 时按修改时间新到旧。
    expect(wrapper.findAll('[data-library-entry]')).toHaveLength(2)
    wrapper.unmount()
  })
})
