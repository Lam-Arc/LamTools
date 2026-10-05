import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import MemoryView from '../src/components/MemoryView.vue'
import type { CoreDurableRequest } from '../src/durable/api'
import type { CoreProjectClient } from '../src/projects/client'

/**
 * The 记忆 browser: the project tier opens on the project list — only projects
 * that actually hold memory are listed, and a project's files only appear once
 * one is entered — while the global tier is one flat directory. Both walk
 * level by level with the same toolbar / reader / editor the 资料库 uses.
 */

const entries = [
  { path: '偏好.md', is_dir: false, size: 12, modified: '2026-10-03 10:00', summary: '写代码时的习惯' },
  { path: '项目', is_dir: true, size: 0, modified: '', summary: '' },
  { path: '项目/部署.md', is_dir: false, size: 8, modified: '2026-10-03 11:00', summary: '部署注意什么' },
  { path: '项目/子层', is_dir: true, size: 0, modified: '', summary: '' },
  { path: '项目/子层/深.md', is_dir: false, size: 4, modified: '2026-10-03 12:00', summary: '更深一层' },
]

const projects = [
  { id: 'proj-1', name: '演示项目', workRoot: 'C:/work/demo', iconKey: 'folder', colorKey: 'blue' },
  { id: 'proj-2', name: '别的项目', workRoot: 'D:/other', iconKey: 'code', colorKey: 'green' },
]

function fakeRpc() {
  const calls: Array<{ method: string; params: Record<string, unknown> }> = []
  // 有状态的假后端：建 / 删之后树真的变了，界面才可能跟上。
  const tree = entries.map(entry => ({ ...entry }))
  const request = vi.fn(async (method: string, params: Record<string, unknown> = {}) => {
    calls.push({ method, params })
    const path = String(params.path ?? '')
    // 每次都给一份新的数组：真实的 RPC 反序列化也是新对象，
    // 复用同一个引用会让视图的 computed 不重算。
    if (method === 'memory.projects') {
      // 假后端：只有 demo 项目真的存了记忆，别的项目探测为空。
      const candidates = Array.isArray(params.projects) ? params.projects : []
      return {
        projects: candidates.filter(candidate => (candidate as { work_root?: string }).work_root === 'C:/work/demo'),
      }
    }
    if (method === 'memory.tree') return { entries: tree.map(entry => ({ ...entry })) }
    if (method === 'memory.read') return { path, content: '# 偏好\n\n正文一段。\n' }
    if (method === 'memory.write') {
      if (!tree.some(entry => entry.path === path)) {
        tree.push({ path, is_dir: false, size: 0, modified: '', summary: '' })
      }
      return { path }
    }
    if (method === 'memory.mkdir') {
      if (!tree.some(entry => entry.path === path)) {
        tree.push({ path, is_dir: true, size: 0, modified: '', summary: '' })
      }
      return { path }
    }
    if (method === 'memory.rename') {
      const found = tree.find(entry => entry.path === path)
      if (found) found.path = String(params.new_path ?? path)
      return { path: params.new_path }
    }
    if (method === 'memory.delete') {
      const index = tree.findIndex(entry => entry.path === path)
      if (index >= 0) tree.splice(index, 1)
      return { path }
    }
    return {}
  }) as unknown as CoreDurableRequest
  return { request, calls }
}

function fakeClient() {
  return {
    list: vi.fn(async () => projects.map(project => ({ ...project }))),
  } as unknown as CoreProjectClient
}

/** The view chains several awaited RPC calls before it re-renders. */
async function settled(rounds = 12): Promise<void> {
  for (let i = 0; i < rounds; i += 1) await Promise.resolve()
}

function mountView(overrides: Record<string, unknown> = {}) {
  const { request, calls } = fakeRpc()
  const client = fakeClient()
  const wrapper = mount(MemoryView, {
    props: { requestRpc: request, client, platform: 'desktop', ...overrides },
  })
  return { wrapper, calls, client }
}

describe('MemoryView', () => {
  it('opens the project tier on the project list, then walks a project level by level', async () => {
    const { wrapper, calls } = mountView()
    await settled()

    // 第一层是项目，且只列真正存有记忆的：探测不带出没记忆的项目。
    expect(calls[0]).toEqual({
      method: 'memory.projects',
      params: {
        projects: [
          { id: 'proj-1', name: '演示项目', work_root: 'C:/work/demo' },
          { id: 'proj-2', name: '别的项目', work_root: 'D:/other' },
        ],
      },
    })
    expect(calls.filter(call => call.method === 'memory.tree')).toHaveLength(0)
    expect(wrapper.findAll('[data-memory-project]').map(node => node.attributes('data-memory-project')))
      .toEqual(['proj-1'])
    expect(wrapper.get('[data-memory-project="proj-1"]').text()).toContain('演示项目')

    await wrapper.get('[data-memory-project="proj-1"]').trigger('click')
    await settled()
    // 进了项目才读它的记忆目录：项目根跟着项目走，不是当前会话的项目。
    const treeCalls = calls.filter(call => call.method === 'memory.tree')
    expect(treeCalls[0].params).toEqual({ scope: 'project', work_root: 'C:/work/demo' })
    // 根上的文件与文件夹分开呈现：文件夹能进去，文件直接读。
    expect(wrapper.findAll('[data-memory-entry]').map(node => node.attributes('data-memory-entry'))).toEqual(['偏好.md'])
    expect(wrapper.findAll('[data-memory-folder]').map(node => node.attributes('data-memory-folder'))).toEqual(['项目'])
    expect(wrapper.get('[data-memory-folder="项目"]').text()).toContain('2 个条目')

    await wrapper.get('[data-memory-folder="项目"]').trigger('click')
    await settled()
    // 进去之后只看到这一层：直属文件 + 下一层文件夹，不穿透到更深。
    expect(wrapper.findAll('[data-memory-entry]').map(node => node.attributes('data-memory-entry'))).toEqual(['项目/部署.md'])
    expect(wrapper.findAll('[data-memory-folder]').map(node => node.attributes('data-memory-folder'))).toEqual(['项目/子层'])
    expect(wrapper.get('[data-memory-crumb]').text()).toContain('项目')

    // 再深一层：层级判断必须跟着走，二级文件夹不能从所在层消失。
    await wrapper.get('[data-memory-folder="项目/子层"]').trigger('click')
    await settled()
    expect(wrapper.findAll('[data-memory-entry]').map(node => node.attributes('data-memory-entry'))).toEqual(['项目/子层/深.md'])
    expect(wrapper.findAll('[data-memory-folder]')).toHaveLength(0)
    wrapper.unmount()
  })

  it('goes back from a project to the project list, not out of the view', async () => {
    const { wrapper, client } = mountView()
    await settled()

    await wrapper.get('[data-memory-project="proj-1"]').trigger('click')
    await settled()
    expect(wrapper.find('[data-memory-projects]').exists()).toBe(false)

    expect((wrapper.vm as unknown as { handleBack: () => boolean }).handleBack()).toBe(true)
    await settled()
    // 回到项目清单：项目列表可再进入，宿主还不该被退出。
    expect(wrapper.find('[data-memory-projects]').exists()).toBe(true)
    expect(client.list).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('filters the project list by name before a project is entered', async () => {
    const { wrapper } = mountView()
    await settled()

    // 只列出了有记忆的项目，搜索在它们之中过滤。
    await wrapper.get('[data-memory-search]').setValue('演示')
    await settled()
    expect(wrapper.findAll('[data-memory-project]').map(node => node.attributes('data-memory-project')))
      .toEqual(['proj-1'])

    // 搜到没记忆的项目名：不是它漏网了，而是它本来就不在列表里。
    await wrapper.get('[data-memory-search]').setValue('别的')
    await settled()
    expect(wrapper.findAll('[data-memory-project]')).toHaveLength(0)
    expect(wrapper.get('[data-memory-no-projects]').text()).toContain('没有匹配的项目')
    wrapper.unmount()
  })

  it('switches to the global tier, which never needs a project', async () => {
    const { wrapper, calls } = mountView()
    await settled()

    await wrapper.get('[data-memory-tier="global"]').trigger('click')
    await settled()

    const tree = calls.filter(call => call.method === 'memory.tree')
    expect(tree[tree.length - 1].params).toEqual({ scope: 'global' })
    wrapper.unmount()
  })

  it('reads a markdown memory as a document and edits it in place', async () => {
    const { wrapper, calls } = mountView()
    await settled()

    await wrapper.get('[data-memory-project="proj-1"]').trigger('click')
    await settled()
    await wrapper.get('[data-memory-entry]').trigger('click')
    await settled()
    expect(wrapper.find('[data-memory-reader]').exists()).toBe(true)
    expect(wrapper.get('[data-memory-reader]').text()).toContain('正文一段')

    await wrapper.get('.full-area-actions button').trigger('click') // 编辑
    await settled(); await settled()
    expect(wrapper.find('[data-memory-editor]').exists()).toBe(true)
    const box = wrapper.get('[data-memory-editor-input]')
    expect((box.element as HTMLTextAreaElement).value).toContain('正文一段')
    expect(wrapper.get('[data-memory-editor-state]').text()).toBe('已保存')

    await box.setValue('# 偏好\n\n改过了。\n')
    await settled()
    expect(wrapper.get('[data-memory-editor-state]').text()).toBe('未保存')

    await wrapper.get('[data-memory-editor-save]').trigger('click')
    await settled(); await settled()
    const writes = calls.filter(call => call.method === 'memory.write')
    expect(writes[writes.length - 1].params).toEqual({
      scope: 'project',
      work_root: 'C:/work/demo',
      path: '偏好.md',
      content: '# 偏好\n\n改过了。\n',
    })
    expect(wrapper.find('[data-memory-reader]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('creates the next level inside the open folder and confirms before deleting', async () => {
    const { wrapper, calls } = mountView()
    await settled()
    await wrapper.get('[data-memory-project="proj-1"]').trigger('click')
    await settled()
    await wrapper.get('[data-memory-folder="项目"]').trigger('click')
    await settled()

    await wrapper.get('[data-memory-create-file]').trigger('click')
    await wrapper.get('[data-memory-dialog-input="create-file"]').setValue('规范')
    await wrapper.get('[data-memory-dialog-submit]').trigger('click')
    await settled(); await settled()
    expect(calls.filter(call => call.method === 'memory.write')[0].params).toMatchObject({ path: '项目/规范.md' })

    await wrapper.get('[data-memory-editor-cancel]').trigger('click')
    await settled()
    // 取消编辑回到阅读页，再退一步才是这一层的列表。
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await settled()
    await wrapper.get('[data-memory-entry]').trigger('click')
    await settled()
    // 两段式确认：第一击蓄势，第二击才真的删。
    const removeButton = wrapper.findAll('.full-area-actions button').find(button => button.text().includes('删除'))!
    await removeButton.trigger('click')
    await settled()
    expect(calls.some(call => call.method === 'memory.delete')).toBe(false)
    await removeButton.trigger('click')
    await settled()
    expect(calls.filter(call => call.method === 'memory.delete')[0].params).toMatchObject({ path: '项目/部署.md' })
    wrapper.unmount()
  })

  it('says why the project list is unavailable instead of failing silently', async () => {
    const { wrapper, calls } = mountView({ client: null })
    await settled()

    expect(wrapper.get('[data-memory-project-error]').text()).toContain('项目列表不可用')
    expect(calls).toHaveLength(0)

    await wrapper.get('[data-memory-tier="global"]').trigger('click')
    await settled()
    expect(wrapper.find('[data-memory-project-error]').exists()).toBe(false)
    expect(calls[calls.length - 1]).toEqual({ method: 'memory.tree', params: { scope: 'global' } })
    wrapper.unmount()
  })

  it('explains itself on a phone instead of showing a broken browser', async () => {
    const { wrapper, calls, client } = mountView({ platform: 'mobile' })
    await settled()

    expect(wrapper.get('[data-memory-note]').text()).toContain('手机端')
    expect(calls).toHaveLength(0)
    expect(client.list).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
