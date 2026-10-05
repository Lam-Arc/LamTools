import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { describe, expect, it, vi } from 'vitest'

import PlanLibraryView from '../src/components/PlanLibraryView.vue'
import type { CorePlanLibraryEntry, CorePlanLibraryFolder, CoreProjectClient } from '../src/projects/client'

function read(relative: string): string {
  return readFileSync(relative, 'utf-8')
}

const entry = (overrides: Partial<CorePlanLibraryEntry> = {}): CorePlanLibraryEntry => ({
  name: '导出显示进度.md',
  path: '方案/导出显示进度.md',
  folder: '',
  title: '导出显示进度',
  status: 'draft',
  summary: '导出长报告时让用户看见进度',
  favorite: false,
  size: 120,
  updated_at: 1759200000,
  ...overrides,
})

const folder = (overrides: Partial<CorePlanLibraryFolder> = {}): CorePlanLibraryFolder => ({
  name: '归档',
  path: '方案/归档',
  dir: '归档',
  parent: '',
  count: 1,
  ...overrides,
})

function fakeClient(overrides: Partial<CoreProjectClient> = {}): CoreProjectClient {
  const client = {
    listPlanLibrary: vi.fn(async () => ({ dir: '方案', entries: [entry()], folders: [folder()] })),
    readFile: vi.fn(async () => ({ path: '方案/导出显示进度.md', content: '# 导出显示进度\n\n## 步骤\n1. 做点什么\n' })),
    writeFile: vi.fn(async (_projectId: string, path: string, content: string) => ({ path, content })),
    deletePlanLibraryFile: vi.fn(async (projectId: string, path: string) => ({ deleted: path })),
    favoritePlanLibraryFile: vi.fn(async (_projectId: string, path: string, favorite: boolean) => ({
      entry: entry({ path, favorite }),
    })),
    createPlanLibraryFile: vi.fn(async (_projectId: string, name: string, folderName = '') => ({
      entry: entry({
        name: `${name}.md`,
        path: folderName ? `${'方案'}/${folderName}/${name}.md` : `方案/${name}.md`,
        folder: folderName,
        title: name,
      }),
    })),
    createPlanLibraryFolder: vi.fn(async (_projectId: string, name: string) => ({
      folder: folder({ name, path: `方案/${name}`, count: 0 }),
    })),
    ...overrides,
  } as unknown as CoreProjectClient
  return client
}

async function settled(): Promise<void> {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

/** Escape 走文档级监听：资料库内部先回上一层，再退就是退出整版视图。 */
function pressEscape(): void {
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
}

function tabButton(wrapper: ReturnType<typeof mount>, id: string) {
  return wrapper.findAll('[data-library-tab]').find(button => button.attributes('data-library-tab') === id)!
}

describe('PlanLibraryView', () => {
  it('lists what the 方案 folder holds and opens one as a document', async () => {
    const client = fakeClient()
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()

    expect(client.listPlanLibrary).toHaveBeenCalledWith('proj-1')
    const cards = wrapper.findAll('[data-library-entry]')
    expect(cards).toHaveLength(1)
    expect(cards[0].text()).toContain('导出显示进度')
    expect(cards[0].text()).toContain('导出长报告时让用户看见进度')
    expect(cards[0].text()).toContain('草稿')

    await cards[0].trigger('click')
    await settled()
    expect(client.readFile).toHaveBeenCalledWith('proj-1', '方案/导出显示进度.md')
    expect(wrapper.get('.library-document').text()).toContain('做点什么')
    // 顶部条标题上报为面包屑。
    const headings = wrapper.emitted('heading') as Array<Array<{ title: string; subtitle: string }>>
    expect(headings[headings.length - 1][0].title).toContain('资料库 ›')

    // Esc 回列表，再 Esc 才退出整版视图。
    pressEscape()
    await settled()
    expect(wrapper.find('[data-library-reader]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('renders the cards inside the shared surface recipe', async () => {
    const client = fakeClient()
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()

    // 资料库与记忆共用 styles/library-surface.css：卡片必须落在这个根类里面，
    // 那份配方才够得着它（渲染到根之外的子树就只剩裸文字）。
    const root = wrapper.get('.library-surface')
    expect(root.classes()).toContain('full-area-view')
    expect(root.find('.plan-card').exists()).toBe(true)
    expect(wrapper.get('.plan-card .library-status').attributes('data-plan-status')).toBe('draft')
    expect(wrapper.get('.plan-card .card-menu-btn').attributes('aria-label')).toContain('导出显示进度')

    // 配方里每一条都挂在 .library-surface 下，不会漏到应用其它地方。
    const unrooted = read('src/styles/library-surface.css')
      .split('\n')
      .map(line => line.trim())
      .filter(line => line.endsWith('{') && !line.startsWith('@') && !line.startsWith('/*'))
      .filter(line => !line.startsWith('.library-surface'))
    expect(unrooted).toEqual([])

    await wrapper.findAll('[data-library-view-toggle] button')[1].trigger('click')
    expect(root.find('.library-row').exists()).toBe(true)
    expect(wrapper.get('.library-row .library-status').text()).toBe('草稿')

    wrapper.unmount()
  })

  it('guides an empty library towards the conversation', async () => {
    const client = fakeClient({ listPlanLibrary: vi.fn(async () => ({ dir: '方案', entries: [], folders: [] })) } as never)
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
        folders: [],
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

    pressEscape()
    await settled()
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

  it('edits the plan inside the library instead of leaving for the file workbench', async () => {
    const client = fakeClient()
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()
    await wrapper.get('[data-library-entry]').trigger('click')
    await settled()

    // 动作组的顺序：开工、编辑、删除。
    const editButton = () => wrapper.findAll('.full-area-actions button').find(button => button.text() === '编辑')!
    await editButton().trigger('click')
    await settled(); await settled()

    expect(wrapper.find('[data-library-editor]').exists()).toBe(true)
    expect(wrapper.emitted('edit-plan')).toBeUndefined()
    const headings = wrapper.emitted('heading') as Array<Array<{ title: string; subtitle: string }>>
    expect(headings[headings.length - 1][0].title).toBe('资料库 › 编辑 导出显示进度')

    const box = wrapper.get('[data-library-editor-input]')
    expect((box.element as HTMLTextAreaElement).value).toContain('# 导出显示进度')
    // 确认 = 保存并退出；没改过时确认只退出、不写盘。
    await wrapper.get('[data-library-editor-confirm]').trigger('click')
    await settled(); await settled(); await settled()
    expect(client.writeFile).not.toHaveBeenCalled()
    expect(wrapper.find('[data-library-reader]').exists()).toBe(true)

    // 再进编辑：改动后确认，写盘并直接回到阅读页。
    await editButton().trigger('click')
    await settled(); await settled()
    await wrapper.get('[data-library-editor-input]').setValue('# 导出显示进度\n\n## 步骤\n1. 改完了\n')
    await settled()
    expect(wrapper.get('[data-library-editor-state]').text()).toBe('未保存')

    await wrapper.get('[data-library-editor-confirm]').trigger('click')
    await settled(); await settled(); await settled()
    expect(client.writeFile).toHaveBeenCalledWith('proj-1', '方案/导出显示进度.md', '# 导出显示进度\n\n## 步骤\n1. 改完了\n')
    // 保存后回到阅读页看排版结果。
    expect(wrapper.find('[data-library-editor]').exists()).toBe(false)
    expect(wrapper.find('[data-library-reader]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('asks before dropping unsaved edits', async () => {
    const client = fakeClient()
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()
    await wrapper.get('[data-library-entry]').trigger('click')
    await settled()
    await wrapper.findAll('.full-area-actions button').find(button => button.text() === '编辑')!.trigger('click')
    await settled(); await settled()
    await wrapper.get('[data-library-editor-input]').setValue('改了一半')
    await settled()

    // 离开编辑页靠 Esc/返回：有未保存内容时先问一句。
    pressEscape()
    await settled()
    expect(wrapper.find('[data-library-discard]').exists()).toBe(true)

    // 继续编辑：留在原地，草稿还在。
    await wrapper.findAll('.dialog-actions button').find(button => button.text() === '继续编辑')!.trigger('click')
    await settled()
    expect(wrapper.find('[data-library-editor]').exists()).toBe(true)
    expect((wrapper.get('[data-library-editor-input]').element as HTMLTextAreaElement).value).toBe('改了一半')

    // 再来一次，这次放弃：回到阅读页，且从不写盘。
    pressEscape()
    await settled()
    await wrapper.get('[data-library-discard-confirm]').trigger('click')
    await settled()
    expect(wrapper.find('[data-library-editor]').exists()).toBe(false)
    expect(wrapper.find('[data-library-reader]').exists()).toBe(true)
    expect(client.writeFile).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('sends the refresh and create actions with the listing', async () => {
    const client = fakeClient()
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1', bandActions: false } })
    await settled()
    const refresh = wrapper.get('[data-library-refresh]')
    await refresh.trigger('click')
    await settled()
    expect(client.listPlanLibrary).toHaveBeenCalledTimes(2)

    // 新建方案：对话框提交后创建并直接打开。
    await wrapper.get('[data-library-create]').trigger('click')
    const input = wrapper.get('[data-library-dialog-input="create-plan"]')
    await input.setValue('新的迭代方案')
    await wrapper.get('[data-library-dialog-submit]').trigger('click')
    await settled()
    expect(client.createPlanLibraryFile).toHaveBeenCalledWith('proj-1', '新的迭代方案', '')
    expect(wrapper.find('[data-library-reader]').exists()).toBe(true)
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

  it('filters by search query and by the favorites tab through the client-backed star', async () => {
    const client = fakeClient({
      listPlanLibrary: vi.fn(async () => ({
        dir: '方案',
        entries: [
          entry(),
          entry({ name: '另一份.md', path: '方案/另一份.md', title: '另一份', summary: '完全不同的内容', favorite: true }),
        ],
        folders: [],
      })),
    } as never)
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()
    expect(wrapper.findAll('[data-library-entry]')).toHaveLength(2)

    await wrapper.get('[data-library-search]').setValue('另一份')
    expect(wrapper.findAll('[data-library-entry]')).toHaveLength(1)
    await wrapper.get('[data-library-search]').setValue('')

    await tabButton(wrapper, 'favorites').trigger('click')
    expect(wrapper.findAll('[data-library-entry]')).toHaveLength(1)
    expect(wrapper.findAll('[data-library-entry]')[0].text()).toContain('另一份')
    wrapper.unmount()
  })

  it('shows the folders tab with cards and an empty-state creator', async () => {
    const client = fakeClient({
      listPlanLibrary: vi.fn(async () => ({
        dir: '方案',
        entries: [entry({
          name: '夹内方案.md',
          path: '方案/归档/夹内方案.md',
          folder: '归档',
          title: '夹内方案',
        })],
        folders: [folder()],
      })),
    } as never)
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()

    await tabButton(wrapper, 'folders').trigger('click')
    expect(wrapper.find('[data-folders-empty]').exists()).toBe(false)
    const folderCard = wrapper.get('[data-library-folder="归档"]')
    expect(folderCard.text()).toContain('1 份方案')

    await folderCard.trigger('click')
    // 文件夹详情：面包屑 + 只显示该文件夹里的方案。
    expect(wrapper.get('[data-library-crumb]').text()).toContain('归档')
    expect(wrapper.findAll('[data-library-entry]')).toHaveLength(1)
    pressEscape()
    await settled()
    expect(wrapper.find('[data-library-crumb]').exists()).toBe(false)

    // 新建文件夹对话框（工具栏入口，任何时刻可用）。
    await wrapper.get('[data-library-create-folder]').trigger('click')
    await wrapper.get('[data-library-dialog-input="create-folder"]').setValue('迭代计划')
    await wrapper.get('[data-library-dialog-submit]').trigger('click')
    await settled()
    expect(client.createPlanLibraryFolder).toHaveBeenCalledWith('proj-1', '迭代计划')
    // 新文件夹建在当前层，界面跟着回到文件夹页，这次操作当场看得见。
    expect(wrapper.find('[data-library-crumb]').exists()).toBe(false)
    expect(tabButton(wrapper, 'folders').classes()).toContain('active')
    expect(wrapper.find('[data-library-folder="归档"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('walks nested folders and builds the next level inside the open one', async () => {
    const client = fakeClient({
      listPlanLibrary: vi.fn(async () => ({
        dir: '方案',
        entries: [entry({
          name: '深层方案.md',
          path: '方案/归档/这一期/深层方案.md',
          folder: '归档/这一期',
          title: '深层方案',
        })],
        folders: [
          folder({ name: '归档', path: '方案/归档', dir: '归档', parent: '', count: 1 }),
          folder({ name: '这一期', path: '方案/归档/这一期', dir: '归档/这一期', parent: '归档', count: 1 }),
        ],
      })),
    } as never)
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()
    await tabButton(wrapper, 'folders').trigger('click')

    const folderCards = () => wrapper.findAll('[data-library-folder]').map(card => card.attributes('data-library-folder'))
    // 根上只看到一级文件夹。
    expect(folderCards()).toEqual(['归档'])

    await wrapper.get('[data-library-folder="归档"]').trigger('click')
    await settled()
    // 进去看到的是下一层文件夹；更深处的方案不属于这一层。
    expect(folderCards()).toEqual(['归档/这一期'])
    expect(wrapper.findAll('[data-library-entry]')).toHaveLength(0)
    expect(wrapper.get('[data-library-crumb]').text()).toContain('归档')

    await wrapper.get('[data-library-folder="归档/这一期"]').trigger('click')
    await settled()
    expect(wrapper.findAll('[data-library-entry]').map(el => el.attributes('data-library-entry'))).toEqual(['深层方案.md'])
    // 面包屑逐层可点，最后一段是当前位置。
    expect(wrapper.findAll('[data-library-crumb-step]').map(el => el.attributes('data-library-crumb-step')))
      .toEqual(['归档', '归档/这一期'])
    expect(wrapper.get('[data-library-crumb-step="归档/这一期"]').classes()).toContain('crumb-link--current')

    // 点面包屑回到上一层。
    await wrapper.get('[data-library-crumb-step="归档"]').trigger('click')
    await settled()
    expect(folderCards()).toEqual(['归档/这一期'])

    // 在当前层新建文件夹：路径带上所在层，而不是又建到库根。
    await wrapper.get('[data-library-create-folder]').trigger('click')
    await wrapper.get('[data-library-dialog-input="create-folder"]').setValue('复盘')
    await wrapper.get('[data-library-dialog-submit]').trigger('click')
    await settled()
    expect(client.createPlanLibraryFolder).toHaveBeenCalledWith('proj-1', '归档/复盘')
    wrapper.unmount()
  })

  it('shows the create-folder empty state when the library has no folders', async () => {
    const client = fakeClient({ listPlanLibrary: vi.fn(async () => ({ dir: '方案', entries: [entry()], folders: [] })) } as never)
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'proj-1' } })
    await settled()
    await tabButton(wrapper, 'folders').trigger('click')

    const empty = wrapper.get('[data-folders-empty]')
    expect(empty.text()).toContain('创建你的第一个文件夹')
    expect(empty.text()).toContain('创建文件夹，整理资料库中的方案。')
    wrapper.unmount()
  })
})
