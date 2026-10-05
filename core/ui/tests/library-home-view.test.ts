import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import LibraryHomeView from '../src/components/LibraryHomeView.vue'
import type { CoreProjectClient } from '../src/projects/client'

/**
 * 资料库的壳：一个入口三个分区（资料 / 记忆 / 方案），都是同一套版面。
 *
 * 这里只验壳自己的事——分区切换、标题合成、内层草稿保护；三个分区内部的
 * 行为由各自的测试文件覆盖。
 */

function fakeClient() {
  return {
    list: vi.fn(async () => []),
    listPlanLibrary: vi.fn(async () => ({
      dir: '方案',
      entries: [{
        name: '导出显示进度.md',
        path: '方案/导出显示进度.md',
        folder: '',
        title: '导出显示进度',
        status: 'ready',
        summary: '',
        favorite: false,
        size: 10,
        updated_at: 1759200000,
      }],
      folders: [],
    })),
    readFile: vi.fn(async () => ({ path: '方案/导出显示进度.md', content: '# 导出显示进度' })),
    writeFile: vi.fn(async (_project: string, path: string, content: string) => ({ path, content })),
  } as unknown as CoreProjectClient
}

function fakeRpc() {
  return vi.fn(async (method: string) => {
    if (method === 'artifact.list') return { artifacts: [] }
    if (method === 'memory.tree') return { entries: [] }
    return {}
  })
}

async function settle(rounds = 12): Promise<void> {
  for (let i = 0; i < rounds; i += 1) await Promise.resolve()
}

const settled = settle

function mountHome() {
  const client = fakeClient()
  const requestRpc = fakeRpc()
  const wrapper = mount(LibraryHomeView, {
    props: { client, requestRpc, projectId: 'proj-1', workRoot: 'C:/work/demo', platform: 'desktop' },
  })
  return { wrapper, client, requestRpc }
}

describe('LibraryHomeView', () => {
  it('opens on 资料 and offers all three sections', async () => {
    const { wrapper } = mountHome()
    await settle()

    expect(wrapper.findAll('[data-library-section]').map(node => node.attributes('data-library-section')))
      .toEqual(['materials', 'memory', 'plans'])
    expect(wrapper.get('[data-library-section="materials"]').attributes('aria-selected')).toBe('true')

    // 资料 = 资料库版式的资料区（成果数据同一份，版式按资料库来）。
    expect(wrapper.find('[data-materials-view]').exists()).toBe(true)
    expect(wrapper.emitted('heading')?.[0]).toEqual([{ title: '资料库 › 资料', subtitle: '项目里进出的文件 — 用户上传、中间产物与最终产物。' }])
    wrapper.unmount()
  })

  it('switches sections and hands each one its own heading under 资料库', async () => {
    const { wrapper, client } = mountHome()
    await settle()

    await wrapper.get('[data-library-section="memory"]').trigger('click')
    await settle()
    expect(wrapper.find('.memory-view').exists()).toBe(true)
    expect(wrapper.find('[data-materials-view]').exists()).toBe(false)

    await wrapper.get('[data-library-section="plans"]').trigger('click')
    await settle()
    expect(wrapper.find('.plan-library-view').exists()).toBe(true)
    expect(client.listPlanLibrary).toHaveBeenCalledWith('proj-1')

    const headings = (wrapper.emitted('heading') as Array<Array<{ title: string }>>).map(entry => entry[0].title)
    expect(headings).toContain('资料库 › 记忆')
    expect(headings[headings.length - 1].startsWith('资料库 › 方案')).toBe(true)
    wrapper.unmount()
  })

  it('keeps the section tabs from swallowing an open draft', async () => {
    const { wrapper } = mountHome()
    await settle()
    await wrapper.get('[data-library-section="plans"]').trigger('click')
    await settle()
    await settled()

    // 进方案 → 打开一篇 → 编辑：写了一半的正文不该被一次分区切换吞掉。
    await wrapper.get('[data-library-entry]').trigger('click')
    await settled()
    await wrapper.findAll('.full-area-actions button').find(button => button.text() === '编辑')!.trigger('click')
    await settled(); await settled()
    expect(wrapper.find('[data-library-editor-input]').exists()).toBe(true)

    await wrapper.get('[data-library-section="memory"]').trigger('click')
    await settled()
    expect(wrapper.find('[data-library-editor-input]').exists()).toBe(true)
    expect(wrapper.find('.memory-view').exists()).toBe(false)

    // 退出编辑后再切，照常生效——守门只挡"正在写"这一种情况。
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await settled()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await settled()
    await wrapper.get('[data-library-section="memory"]').trigger('click')
    await settled()
    expect(wrapper.find('.memory-view').exists()).toBe(true)
    wrapper.unmount()
  })

  it('lets the host exit when no section can go back further', async () => {
    const { wrapper } = mountHome()
    await settle()

    expect((wrapper.vm as unknown as { handleBack: () => boolean }).handleBack()).toBe(false)
    wrapper.unmount()
  })
})
