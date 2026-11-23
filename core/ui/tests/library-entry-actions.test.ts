import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import MaterialsView from '../src/components/MaterialsView.vue'
import { ContextMenuHost } from '../src/components/context-menu/index.ts'
import { closeContextMenu } from '../src/components/context-menu/context-menu.ts'
import { registerPreviewLightboxHost, resetPreviewLightbox, usePreviewLightbox } from '../src/preview/usePreviewLightbox'
import type { LamToolsTransport, TransportHttpResponse } from '../src/transport'

// user:“在资料库条目上补：预览（走统一链路）、转换（复用 document_normalize → Markdown）、用默认应用打开”+
// (三个动作都要真的落到那个文件上：预览进灯箱、转换产出并登记、打开交系统；
// 失败必须落在就近的错误行上，不允许点了没反应。)

function artifact(overrides: Record<string, unknown> = {}) {
  return {
    artifact_id: overrides.artifact_id ?? 'a1',
    name: overrides.name ?? '季度报告.docx',
    kind: overrides.kind ?? 'document',
    mime_type: overrides.mime_type ?? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    path: overrides.path ?? 'workspace://资料/季度报告.docx',
    role: 'input',
    source: 'user_upload',
    availability: 'available',
    updated_at: '2026-10-03T12:00:00',
    revision_count: 1,
    favorite: false,
    folder: '',
    ...overrides,
  }
}

function fakeRpc(rows: unknown[]) {
  const requestRpc = vi.fn(async (method: string, params: Record<string, unknown> = {}) => {
    if (method === 'artifact.list') return { artifacts: rows }
    if (method === 'artifact.stats') return { count: rows.length, bytes: 1024 }
    return {}
  })
  return requestRpc
}

async function settle(rounds = 14): Promise<void> {
  for (let index = 0; index < rounds; index += 1) await Promise.resolve()
}

const SEP = String.fromCharCode(92)
/** 引用展开保留既有分隔符风格，校验时统一成 / 再比对。 */
const normalizePath = (value: string) => value.split(SEP).join('/')

const wrappers: ReturnType<typeof mount>[] = []

function mountView(rows: unknown[], transport: LamToolsTransport) {
  const requestRpc = fakeRpc(rows)
  // 菜单通过 Teleport 渲染到 body，要一起挂宿主才点得到。
  const host = mount(ContextMenuHost, { attachTo: document.body })
  wrappers.push(host)
  const wrapper = mount(MaterialsView, {
    props: { projectId: 'proj-1', transport, requestRpc, workRoot: 'E:/p' },
  })
  wrappers.push(wrapper)
  return { wrapper, requestRpc }
}

/** 打开某张卡的右键菜单，返回菜单面板（Teleport 到 body）。 */
async function openMenu(wrapper: ReturnType<typeof mount>) {
  await wrapper.get('[data-material="a1"]').trigger('contextmenu')
  await settle()
  return document.querySelector('[data-materials-menu="a1"]') as HTMLElement | null
}

function menuItem(panel: HTMLElement | null, label: string): HTMLButtonElement | null {
  if (!panel) return null
  const buttons = Array.from(panel.querySelectorAll<HTMLButtonElement>('button.context-menu-item'))
  return buttons.find(button => (button.textContent || '').includes(label)) || null
}

afterEach(() => {
  closeContextMenu({ restoreFocus: false })
  resetPreviewLightbox()
  for (const wrapper of wrappers.splice(0)) wrapper.unmount()
  document.body.innerHTML = ''
})

describe('library entry actions', () => {
  it('offers preview, convert and open-with-default-app on an entry menu', async () => {
    const transport = { request: vi.fn(async () => ({ status: 200, headers: {}, body: new Uint8Array() })) } as unknown as LamToolsTransport
    const { wrapper } = mountView([artifact()], transport)
    await settle()

    const panel = await openMenu(wrapper)
    expect(panel).not.toBeNull()
    expect(menuItem(panel, '预览')).not.toBeNull()
    expect(menuItem(panel, '转换成 Markdown')).not.toBeNull()
    expect(menuItem(panel, '使用默认应用打开')).not.toBeNull()
  })

  it('opens the entry in the lightbox — the same unified resolve chain', async () => {
    // user:“预览（走统一链路）”+(不是另开一套查看器：目标交给灯箱，由 resolve 三态决定)。
    const transport = { request: vi.fn(async () => ({ status: 200, headers: {}, body: new Uint8Array() })) } as unknown as LamToolsTransport
    // 灯箱宿主必须在场，否则入口会诚实地报「预览器还没就绪」而不是假装打开了。
    const unregister = registerPreviewLightboxHost()
    const { wrapper } = mountView([artifact()], transport)
    await settle()

    const panel = await openMenu(wrapper)
    menuItem(panel, '预览')!.click()
    await settle()

    // 灯箱是单例：点完菜单后它的目标就是这条资料。
    const target = usePreviewLightbox().target.value
    expect(target).toEqual(expect.objectContaining({ kind: 'file' }))
    if (target?.kind === 'file') {
      // 路径分隔符来自既有的引用展开（混合分隔符），只校验它指向那个文件。
      expect(normalizePath(target.path)).toBe('E:/p/资料/季度报告.docx')
      expect(target.workRoot).toBe('E:/p')
    }
    unregister()
  })

  it('asks the backend to convert and refreshes the wall afterwards', async () => {
    const request = vi.fn(async (input: { method: string; path: string }) => {
      if (input.path === '/files/convert') {
        return {
          status: 200,
          headers: {},
          body: new TextEncoder().encode(JSON.stringify({ artifact: { artifact_id: 'md1' } })),
        } as TransportHttpResponse
      }
      return { status: 404, headers: {}, body: new Uint8Array() } as TransportHttpResponse
    })
    const transport = { request } as unknown as LamToolsTransport
    const { wrapper, requestRpc } = mountView([artifact()], transport)
    await settle()
    const before = requestRpc.mock.calls.filter(([method]) => method === 'artifact.list').length

    const panel = await openMenu(wrapper)
    menuItem(panel, '转换成 Markdown')!.click()
    await settle()

    const convert = (request as unknown as { mock: { calls: Array<[{ path: string; method: string; body: Uint8Array }]> } }).mock.calls
      .find(([input]) => input.path === '/files/convert')
    expect(convert).toBeTruthy()
    const payload = JSON.parse(new TextDecoder().decode(convert![0].body))
    expect(payload).toEqual(expect.objectContaining({ work_root: 'E:/p', project_id: 'proj-1' }))
    // 引用展开保留既有分隔符风格；只校验它指向那个真实文件。
    expect(normalizePath(String(payload.path))).toBe('E:/p/资料/季度报告.docx')
    // 转换成功后就地刷新，新条目才会出现在这面墙上。
    expect(requestRpc.mock.calls.filter(([method]) => method === 'artifact.list').length).toBeGreaterThan(before)
  })

  it('shows the backend reason when a conversion is refused', async () => {
    // user:“失败要有明确错误，不允许点了没反应”。
    const request = vi.fn(async (input: { path: string }) => {
      if (input.path === '/files/convert') {
        return {
          status: 400,
          headers: {},
          body: new TextEncoder().encode(JSON.stringify({ detail: '这个文件没有可转换的文本（只支持 docx / pdf / xlsx）' })),
        } as TransportHttpResponse
      }
      return { status: 404, headers: {}, body: new Uint8Array() } as TransportHttpResponse
    })
    const transport = { request } as unknown as LamToolsTransport
    const { wrapper } = mountView([artifact()], transport)
    await settle()

    const panel = await openMenu(wrapper)
    menuItem(panel, '转换成 Markdown')!.click()
    await settle()

    expect(wrapper.get('[data-materials-action-error]').text()).toContain('docx / pdf / xlsx')
  })

  it('reports a clear error instead of doing nothing when the file path is unknown', async () => {
    const transport = { request: vi.fn(async () => ({ status: 200, headers: {}, body: new Uint8Array() })) } as unknown as LamToolsTransport
    const { wrapper } = mountView([artifact({ path: '' })], transport)
    await settle()

    const panel = await openMenu(wrapper)
    menuItem(panel, '转换成 Markdown')!.click()
    await settle()

    expect(wrapper.get('[data-materials-action-error]').text()).toContain('拿不到这个文件的真实路径')
  })
})
