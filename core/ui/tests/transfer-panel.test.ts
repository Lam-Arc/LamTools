// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import TransferPanel from '../src/components/TransferPanel.vue'
import { usePreviewLightbox } from '../src/preview/usePreviewLightbox'

/**
 * user:“传输面板：在「远程连接」面板或文件屏里列出 transfers[]（方向、文件名、进度、状态），
 * 支持取消；失败可重试；完成后可「打开所在文件夹」”+
 * user:“接收列表：每条可「预览」与「打开所在文件夹」；新收到的文件要有可见提示”+
 * 面板只认宿主给的快照：取消是一次宿主命令，预览走统一灯箱链路。
 */
const SNAPSHOT = {
  transfers: [
    {
      id: 't-run',
      direction: 'send',
      name: '报告.pdf',
      total: 4096,
      transferred: 2048,
      percent: 50,
      state: 'transferring',
      code: '',
      message: '',
      path: '',
    },
    {
      id: 't-fail',
      direction: 'send',
      name: '图片.png',
      total: 100,
      transferred: 0,
      percent: 0,
      state: 'failed',
      code: 'file_disk_error',
      message: 'disk full',
      path: '',
    },
  ],
  received: [
    { transferId: 'r1', path: 'C:/lam/received/2026-01-01/说明.md', name: '说明.md', size: 2048, peer: '手机', from: '', at: 2000 },
    { transferId: 'r2', path: 'C:/lam/received/2026-01-01/合同.docx', name: '合同.docx', size: 1024, peer: '手机', from: '', at: 900 },
  ],
}

function mountPanel(overrides: { invoke?: ReturnType<typeof vi.fn>; sendSources?: Record<string, string> } = {}) {
  const invoke = overrides.invoke ?? vi.fn(async (command: string) => (command === 'p2p_status' ? SNAPSHOT : {}))
  const wrapper = mount(TransferPanel, {
    props: { invoke, sendSources: overrides.sendSources ?? {}, now: () => 1000 },
  })
  return { wrapper, invoke }
}

describe('transfer panel', () => {
  it('lists incoming and outgoing rows with direction, state and progress', async () => {
    const { wrapper } = mountPanel()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('报告.pdf')
    expect(text).toContain('发送')
    expect(text).toContain('传输中')
    expect(text).toContain('2.0 KB / 4.0 KB')
    expect(text).toContain('50%')
    // 失败原因走错误码映射，不显示原始码。
    expect(wrapper.text()).toContain('写盘失败')
    expect(wrapper.text()).not.toContain('file_disk_error')
  })

  it('cancels a running transfer through the host', async () => {
    const { wrapper, invoke } = mountPanel()
    await flushPromises()
    await wrapper.find('[data-transfer-cancel="t-run"]').trigger('click')
    await flushPromises()
    expect(invoke).toHaveBeenCalledWith('p2p_cancel_transfer', { id: 't-run' })
    // 取消之后重新对齐一次状态，界面不会停在旧进度上。
    expect(invoke).toHaveBeenCalledWith('p2p_status', undefined)
  })

  it('offers retry only for a failed send this window started', async () => {
    const { wrapper, invoke } = mountPanel({ sendSources: { 't-fail': 'C:/work/图片.png' } })
    await flushPromises()
    const retry = wrapper.find('[data-transfer-retry="t-fail"]')
    expect(retry.exists()).toBe(true)
    await retry.trigger('click')
    expect(wrapper.emitted('retry')?.[0]).toEqual([{ path: 'C:/work/图片.png', name: '图片.png' }])
    expect(invoke).not.toHaveBeenCalledWith('p2p_send_file', expect.anything())
  })

  it('previews a received file through the lightbox', async () => {
    const { wrapper } = mountPanel()
    await flushPromises()
    await wrapper.find('[data-received-preview="C:/lam/received/2026-01-01/说明.md"]').trigger('click')
    const lightbox = usePreviewLightbox()
    expect(lightbox.open.value).toBe(true)
    expect(lightbox.target.value?.kind).toBe('file')
  })

  it('disables preview where the lightbox cannot render, and says why', async () => {
    const { wrapper } = mountPanel()
    await flushPromises()
    const button = wrapper.find('[data-received-preview="C:/lam/received/2026-01-01/合同.docx"]')
    expect(button.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('分屏')
  })

  it('marks only files that arrived after the panel opened', async () => {
    const { wrapper } = mountPanel()
    await flushPromises()
    const rows = wrapper.findAll('[data-received-path]')
    expect(rows).toHaveLength(2)
    const fresh = wrapper.findAll('[data-received-fresh]')
    expect(fresh).toHaveLength(1)
  })

  it('opens the folder for a finished incoming transfer and a received file', async () => {
    // 只有「收进来的、且已完成」那一条才有本机路径可定位：发送侧的 path 是对方机器上的。
    const invoke = vi.fn(async (command: string) => (command === 'p2p_status'
      ? {
        ...SNAPSHOT,
        transfers: [{ ...SNAPSHOT.transfers[0], direction: 'receive', state: 'completed', path: 'C:/lam/received/x.pdf' }],
      }
      : {}))
    const { wrapper } = mountPanel({ invoke })
    await flushPromises()
    await wrapper.find('[data-transfer-reveal="t-run"]').trigger('click')
    await flushPromises()
    expect(invoke).toHaveBeenCalledWith('p2p_reveal_path', { path: 'C:/lam/received/x.pdf' })
  })

  it('never offers a folder button for an outgoing transfer', async () => {
    const invoke = vi.fn(async (command: string) => (command === 'p2p_status'
      ? { transfers: [{ ...SNAPSHOT.transfers[0], state: 'completed', path: '远端/x.pdf' }], received: [] }
      : {}))
    const { wrapper } = mountPanel({ invoke })
    await flushPromises()
    expect(wrapper.find('[data-transfer-reveal="t-run"]').exists()).toBe(false)
  })

  it('stops the progress animation when nothing is moving', async () => {
    const invoke = vi.fn(async (command: string) => (command === 'p2p_status'
      ? { transfers: [{ ...SNAPSHOT.transfers[0], state: 'completed' }], received: [] }
      : {}))
    const { wrapper } = mountPanel({ invoke })
    await flushPromises()
    expect(wrapper.find('.transfer-row.is-animating').exists()).toBe(false)
  })
})
