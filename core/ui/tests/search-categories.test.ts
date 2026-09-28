import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import SearchShell from '../src/components/SearchShell.vue'
import type { CoreSessionListItem } from '../src/types'

/**
 * 用户共识：全局搜索分四类 —— 全部 / 任务 / 插件 / 文件，
 * 并且"现在能搜的"都要落进这几类里。这份契约锁住分类与归类：
 * 插件类收插件、技能、钩子；文件类收文件名/内容/文档；任务类收任务标题与消息命中。
 */
const SESSIONS = [
  {
    id: 'session-1',
    title: '玻璃样式优化去除上方高光',
    status: 'idle',
    updatedAt: '2026-09-28T10:00:00Z',
  },
  {
    id: 'session-2',
    title: '封禁移动端无效 skill 与 git 插件',
    status: 'idle',
    updatedAt: '2026-09-28T09:00:00Z',
  },
] as unknown as CoreSessionListItem[]

function requestRpc(table: Record<string, Record<string, unknown>>) {
  return vi.fn(async (method: string): Promise<Record<string, unknown>> => table[method] || {})
}

function mountSearch(
  table: Record<string, Record<string, unknown>>,
  extra: Record<string, unknown> = {},
) {
  return mount(SearchShell, {
    props: {
      requestRpc: requestRpc(table),
      sessions: SESSIONS,
      onJump: vi.fn(),
      commands: [
        { id: 'new-task', label: '新任务', group: '建议' as const, shortcut: 'Ctrl+N', run: vi.fn() },
        { id: 'toggle-sidebar', label: '切换侧栏', group: '面板' as const, shortcut: 'Ctrl+B', run: vi.fn() },
      ],
      ...extra,
    },
    global: { stubs: { Teleport: true } },
  })
}

const CATALOG = {
  'plugin.list': {
    plugins: [
      { name: 'imagegen', description: '生成图片', enabled: true },
      { name: 'study', description: '学习工作区', enabled: false },
    ],
  },
  'skill.list': {
    skills: [{ name: 'office-slides', description: '制作演示文稿', enabled: true }],
  },
  'hook.list': {
    hooks: [{ name: 'guard-shell', description: '拦截危险命令', trusted: true }],
  },
}

describe('global search categories', () => {
  it('offers 全部/任务/插件/文件 only', async () => {
    const wrapper = mountSearch(CATALOG)
    await flushPromises()

    const labels = wrapper.findAll('.search-tabs button').map((button) => button.text())
    expect(labels).toEqual(['全部', '任务', '插件', '文件'])
  })

  it('shows recent tasks and the host commands while the query is empty', async () => {
    const wrapper = mountSearch(CATALOG)
    await flushPromises()

    const groups = wrapper.findAll('.search-group-label').map((label) => label.text())
    expect(groups).toEqual(['最近任务', '建议', '面板'])
    expect(wrapper.text()).toContain('玻璃样式优化去除上方高光')
    expect(wrapper.text()).toContain('Ctrl+N')
  })

  it('classifies plugins, skills and hooks into 插件', async () => {
    const wrapper = mountSearch(CATALOG)
    await flushPromises()

    // 三类条目都归在“插件”分组下：插件按名字、技能按名字、钩子连信任状态一起被搜到
    for (const [needle, rowKey] of [
      ['imagegen', 'catalog-plugins-imagegen'],
      ['office', 'catalog-skills-office-slides'],
      ['已信任', 'catalog-hooks-guard-shell'],
    ] as const) {
      await wrapper.find('input').setValue(needle)
      await new Promise((resolve) => setTimeout(resolve, 350))
      await flushPromises()

      expect(wrapper.find(`[data-search-row="${rowKey}"]`).exists(), needle).toBe(true)
      const groups = wrapper.findAll('.search-group-label').map((label) => label.text())
      expect(groups, needle).toEqual(['插件'])
    }
  })

  it('keeps the category chips filtering what is listed', async () => {
    const wrapper = mountSearch(CATALOG)
    await flushPromises()

    await wrapper.find('input').setValue('o')
    await new Promise((resolve) => setTimeout(resolve, 350))
    await flushPromises()

    const taskChip = wrapper.findAll('.search-tabs button').find((button) => button.text() === '任务')
    await taskChip?.trigger('click')
    await flushPromises()

    // 只看任务时，插件条目不再出现
    expect(wrapper.find('[data-search-row="catalog-plugins-imagegen"]').exists()).toBe(false)
  })

  it('classifies file name, content and document hits into 文件', async () => {
    const wrapper = mountSearch({
      ...CATALOG,
      'workspace.search': {
        results: [{ path: 'src/app/main.ts', line: 12, content: 'const app = createApp()' }],
      },
    })
    await flushPromises()

    await wrapper.find('input').setValue('app')
    await new Promise((resolve) => setTimeout(resolve, 350))
    await flushPromises()

    // 文件名与内容两个来源都归到 文件 分组里
    const groups = wrapper.findAll('.search-group-label').map((label) => label.text())
    expect(groups).toContain('文件')
    expect(wrapper.text()).toContain('src/app/main.ts')
  })

  it('opens the plugins panel on the section a hit belongs to', async () => {
    const onOpenPlugins = vi.fn()
    const wrapper = mountSearch(CATALOG, { onOpenPlugins })
    await flushPromises()

    await wrapper.find('input').setValue('office')
    await new Promise((resolve) => setTimeout(resolve, 350))
    await flushPromises()

    const row = wrapper.find('[data-search-row="catalog-skills-office-slides"]')
    expect(row.exists()).toBe(true)
    await row.trigger('mousedown')

    expect(onOpenPlugins).toHaveBeenCalledWith({ section: 'skills', id: 'office-slides' })
  })

  it('opens a task hit through onOpenSession', async () => {
    const onOpenSession = vi.fn()
    const wrapper = mountSearch(CATALOG, { onOpenSession })
    await flushPromises()

    await wrapper.find('input').setValue('玻璃')
    await new Promise((resolve) => setTimeout(resolve, 350))
    await flushPromises()

    const row = wrapper.find('[data-search-row="session-session-1"]')
    expect(row.exists()).toBe(true)
    await row.trigger('mousedown')

    expect(onOpenSession).toHaveBeenCalledWith('session-1')
  })
})
