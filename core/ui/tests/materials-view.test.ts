import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import MaterialsView from '../src/components/MaterialsView.vue'
import type { LamToolsTransport, TransportHttpResponse } from '../src/transport'

/**
 * 资料区：对标 ChatGPT 资料库的版式。这里只验界面自己的事——筛选页签、
 * 排序、搜索、归档进层、收藏与移除的调用、占用那一行、空态与上传入口。
 * 取数与推导由 artifacts/model.ts 承担，和右栏成果库共用一份，不在这里重复。
 */

function artifact(overrides: Record<string, unknown> = {}) {
  return {
    artifact_id: overrides.artifact_id ?? 'a1',
    name: overrides.name ?? '提纲.md',
    kind: overrides.kind ?? 'document',
    mime_type: overrides.mime_type ?? 'text/markdown',
    path: overrides.path ?? 'workspace://资料/提纲.md',
    role: overrides.role ?? 'input',
    source: 'user_upload',
    availability: 'available',
    updated_at: overrides.updated_at ?? '2026-10-03T12:00:00',
    revision_count: 1,
    favorite: overrides.favorite ?? false,
    folder: overrides.folder ?? '',
    ...overrides,
  }
}

function fakeRpc(rows: unknown[]) {
  const calls: Array<{ method: string; params: Record<string, unknown> }> = []
  const requestRpc = vi.fn(async (method: string, params: Record<string, unknown> = {}) => {
    calls.push({ method, params })
    if (method === 'artifact.list') return { artifacts: rows }
    if (method === 'artifact.stats') return { count: rows.length, bytes: 2048 }
    if (method === 'artifact.favorite' || method === 'artifact.folder') {
      const target = rows.find(row => (row as { artifact_id: string }).artifact_id === params.artifact_id)
      return { artifact: { ...(target as object), ...params } }
    }
    return {}
  })
  return { requestRpc, calls }
}

const transport = {
  request: vi.fn(async (): Promise<TransportHttpResponse> => ({
    status: 404, headers: {}, body: new Uint8Array(),
  })),
} as unknown as LamToolsTransport

async function settle(rounds = 12): Promise<void> {
  for (let i = 0; i < rounds; i += 1) await Promise.resolve()
}

function mountView(rows: unknown[], extra: Record<string, unknown> = {}) {
  const { requestRpc, calls } = fakeRpc(rows)
  const wrapper = mount(MaterialsView, {
    props: { projectId: 'proj-1', transport, requestRpc, ...extra },
  })
  return { wrapper, requestRpc, calls }
}

const names = (wrapper: ReturnType<typeof mount>) =>
  wrapper.findAll('[data-material]').map(node => node.attributes('data-material'))

describe('MaterialsView', () => {
  it('shows the usage line, every pill tab and the cards', async () => {
    const { wrapper } = mountView([
      artifact({ artifact_id: 'a1', name: '提纲.md' }),
      artifact({ artifact_id: 'a2', name: '截图.png', kind: 'image', mime_type: 'image/png' }),
    ])
    await settle()

    expect(wrapper.get('[data-materials-usage]').text()).toBe('2 个文件 · 2.0 KB')
    expect(wrapper.findAll('[data-materials-tab]').map(node => node.attributes('data-materials-tab')))
      .toEqual(['all', 'image', 'document', 'spreadsheet', 'media', 'favorite', 'folders'])
    expect(names(wrapper)).toEqual(['a1', 'a2'])
    wrapper.unmount()
  })

  it('filters by type tab, by favourites and by search', async () => {
    const { wrapper } = mountView([
      artifact({ artifact_id: 'a1', name: '提纲.md', kind: 'document' }),
      artifact({ artifact_id: 'a2', name: '截图.png', kind: 'image', mime_type: 'image/png' }),
      artifact({ artifact_id: 'a3', name: '预算.xlsx', kind: 'spreadsheet', favorite: true }),
    ])
    await settle()

    await wrapper.get('[data-materials-tab="image"]').trigger('click')
    expect(names(wrapper)).toEqual(['a2'])

    await wrapper.get('[data-materials-tab="spreadsheet"]').trigger('click')
    expect(names(wrapper)).toEqual(['a3'])

    await wrapper.get('[data-materials-tab="favorite"]').trigger('click')
    expect(names(wrapper)).toEqual(['a3'])

    await wrapper.get('[data-materials-tab="all"]').trigger('click')
    await wrapper.get('[data-materials-search]').setValue('预算')
    await settle()
    expect(names(wrapper)).toEqual(['a3'])
    wrapper.unmount()
  })

  it('sorts by modification time by default and by name on demand', async () => {
    const { wrapper } = mountView([
      artifact({ artifact_id: 'old', name: 'a-旧.md', updated_at: '2026-01-01T09:00:00' }),
      artifact({ artifact_id: 'new', name: 'z-新.md', updated_at: '2026-10-01T09:00:00' }),
    ])
    await settle()
    expect(names(wrapper)).toEqual(['new', 'old'])

    await wrapper.get('[data-materials-sort]').trigger('click')
    await settle()
    expect(names(wrapper)).toEqual(['old', 'new'])
    wrapper.unmount()
  })

  it('walks into an archived folder one level at a time', async () => {
    const { wrapper } = mountView([
      artifact({ artifact_id: 'a1', name: '根.md', folder: '' }),
      artifact({ artifact_id: 'a2', name: '甲.md', folder: '项目A' }),
      artifact({ artifact_id: 'a3', name: '乙.md', folder: '项目A/这一期' }),
    ])
    await settle()

    await wrapper.get('[data-materials-tab="folders"]').trigger('click')
    await settle()
    expect(wrapper.findAll('[data-materials-folder]').map(node => node.attributes('data-materials-folder')))
      .toEqual(['项目A'])

    await wrapper.get('[data-materials-folder="项目A"]').trigger('click')
    await settle()
    // 只看这一层的直属文件：更深那件不属于这里。
    expect(names(wrapper)).toEqual(['a2'])
    expect(wrapper.get('[data-materials-crumb]').text()).toContain('项目A')

    await wrapper.get('[data-materials-crumb-step="项目A"]').trigger('click')
    await settle()
    expect(names(wrapper)).toEqual(['a2'])
    wrapper.unmount()
  })

  it('toggles the favourite through the batch bar and confirms before removing', async () => {
    const { wrapper, calls } = mountView([artifact({ artifact_id: 'a1', name: '提纲.md' })])
    await settle()

    await wrapper.get('[data-material-check="a1"]').trigger('click')
    await wrapper.get('[data-materials-favorite-selected]').trigger('click')
    await settle()
    expect(calls.filter(call => call.method === 'artifact.favorite')[0].params)
      .toMatchObject({ project_id: 'proj-1', artifact_id: 'a1', favorite: true })

    await wrapper.get('[data-material-check="a1"]').trigger('click')
    await wrapper.get('[data-materials-remove-selected]').trigger('click')
    await settle()
    // 移除要过一次确认，且口径是"只改资料库状态"。
    expect(wrapper.get('[data-materials-confirm]').text()).toContain('文件本身不会被删除')
    expect(calls.some(call => call.method === 'artifact.delete')).toBe(false)

    await wrapper.get('[data-materials-confirm-remove]').trigger('click')
    await settle()
    expect(calls.filter(call => call.method === 'artifact.delete')[0].params)
      .toMatchObject({ project_id: 'proj-1', artifact_ids: ['a1'] })
    wrapper.unmount()
  })

  it('uploads into the folder you are standing in', async () => {
    const uploadFiles = vi.fn(async () => {})
    const { wrapper } = mountView([artifact({ artifact_id: 'a1', folder: '项目A' })], { uploadFiles })
    await settle()
    await wrapper.get('[data-materials-tab="folders"]').trigger('click')
    await wrapper.get('[data-materials-folder="项目A"]').trigger('click')
    await settle()

    await wrapper.get('[data-materials-new]').trigger('click')
    await settle()
    expect(uploadFiles).toHaveBeenCalledWith('项目A')
    wrapper.unmount()
  })

  it('opens files with the system default app and surfaces the failure inline', async () => {
    const rows = [
      artifact({ artifact_id: 'a1', path: 'workspace://english-novels/webnovels/README.md', name: 'README.md' }),
      artifact({ artifact_id: 'att-1', path: 'attachment://att-1', name: '原件.png', kind: 'image', mime_type: 'image/png' }),
    ]
    const { wrapper, requestRpc, calls } = mountView(rows)
    await settle()

    // 工作区文件：打开交给系统，走 artifact.open。
    await wrapper.get('[data-material="a1"]').trigger('click')
    await settle()
    const openCall = calls.find(({ method, params }) => method === 'artifact.open' && params.artifact_id === 'a1')
    expect(openCall?.params).toMatchObject({ project_id: 'proj-1', path: 'workspace://english-novels/webnovels/README.md' })
    expect(wrapper.find('[data-materials-action-error]').exists()).toBe(false)

    // 上传原件走附件打开通道。
    await wrapper.get('[data-material="att-1"]').trigger('click')
    await settle()
    expect(transport.request).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'http', method: 'POST', path: '/attachments/att-1/open',
    }))

    // 打不开的文件：失败就近提示，卡片墙不消失。
    ;(requestRpc as ReturnType<typeof vi.fn>).mockImplementation(async (method: string) => {
      if (method === 'artifact.list') return { artifacts: rows }
      if (method === 'artifact.stats') return { count: rows.length, bytes: 2048 }
      throw new Error('Artifact file missing')
    })
    await wrapper.get('[data-material="a1"]').trigger('click')
    await settle()
    expect(wrapper.get('[data-materials-action-error]').text()).toContain('Artifact file missing')
    expect(wrapper.find('[data-material="a1"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('copies and shows the absolute disk path instead of the internal workspace reference', async () => {
    const { wrapper } = mountView(
      [artifact({ artifact_id: 'a1', path: 'workspace://english-novels/webnovels/README.md', name: 'README.md' })],
      { workRoot: 'E:\\novels\\english-novels' },
    )
    await settle()
    expect(wrapper.get('.material-name').attributes('title')).toBe('E:\\novels\\english-novels\\english-novels\\webnovels\\README.md')
    wrapper.unmount()
  })

  it('falls back to the type icon when a thumbnail cannot be fetched', async () => {
    const { wrapper } = mountView([
      artifact({ artifact_id: 'a1', name: '截图.png', kind: 'image', mime_type: 'image/png' }),
    ])
    await settle()

    // 取不到字节就退回类型图标，不让整面墙卡在破图上。
    expect(wrapper.find('.material-thumb img').exists()).toBe(false)
    expect(wrapper.find('[data-material="a1"] svg').exists()).toBe(true)
    expect(transport.request).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('explains an empty library and offers the upload', async () => {
    const uploadFiles = vi.fn(async () => {})
    const { wrapper } = mountView([], { uploadFiles })
    await settle()

    expect(wrapper.get('[data-materials-usage]').text()).toBe('资料库还是空的')
    expect(wrapper.get('[data-materials-empty]').text()).toContain('资料库还是空的')
    await wrapper.get('[data-materials-empty-upload]').trigger('click')
    expect(uploadFiles).toHaveBeenCalledWith('')
    wrapper.unmount()
  })
})
