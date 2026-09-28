import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageView from '../src/components/MessageView.vue'
import type { CoreMessage, MessagePart, ToolArtifact } from '../src/types'
import { createFakeTransport } from './fake-transport'

const testTransport = createFakeTransport()

function mountMessageView(options: any = {}) {
  return mount(MessageView, {
    ...options,
    props: { transport: testTransport, ...(options.props ?? {}) },
  })
}

afterEach(() => {
  vi.restoreAllMocks()
})

/**
 * 「本轮产出」面板（message-artifacts）契约：
 * 1. 产出一旦到达就显示——live/history 使用同一位置；子代理 sub-line 段仍经
 *    suppressArtifactsPanel 显式抑制，避免嵌套面板重复；
 * 2. 面板接纳生成图片与 file_change，排除 file_read；同一产物跨多个 part 去重。
 */

function artifact(uri?: string, extra?: { artifact_id?: string; dataUrl?: string }): ToolArtifact & { artifact_id?: string } {
  return {
    kind: 'image',
    ...(uri !== undefined ? { uri } : {}),
    ...(extra?.artifact_id ? { artifact_id: extra.artifact_id } : {}),
    ...(extra?.dataUrl ? { metadata: { image_data_url: extra.dataUrl } } : {}),
  }
}

function part(id: string, artifacts: Array<ToolArtifact & { artifact_id?: string }>): MessagePart {
  return { id, partType: 'tool_result', status: 'completed', label: 'tool', artifacts }
}

function msg(id: string, parts: MessagePart[]): CoreMessage {
  return { id, role: 'assistant', content: '', timestamp: '', parts }
}

describe('「本轮产出」面板：实时与历史同位置显示', () => {
  it('本轮运行中即可显示，轮次结束后保持显示', async () => {
    const m = msg('assistant:t1', [part('p1', [artifact('workspace://.lam/artifacts/a.png')])])
    const wrapper = mountMessageView( { props: { msg: m, turnActive: true, activeTurnId: 't1' } })
    const livePanel = wrapper.find('.message-artifacts')
    expect(livePanel.exists()).toBe(true)

    await wrapper.setProps({ turnActive: false })
    expect(wrapper.find('.message-artifacts').exists()).toBe(true)
    expect(wrapper.find('.message-artifacts').element).toBe(livePanel.element)
  })

  it('同轮分段消息（assistant:<turn>#<n>）同样显示', () => {
    const m = msg('assistant:t1#2', [part('p1', [artifact('workspace://.lam/artifacts/a.png')])])
    const wrapper = mountMessageView( { props: { msg: m, turnActive: true, activeTurnId: 't1' } })
    expect(wrapper.find('.message-artifacts').exists()).toBe(true)
  })

  it('历史消息（非活跃轮）直接显示', () => {
    const m = msg('assistant:t0', [part('p1', [artifact('workspace://.lam/artifacts/a.png')])])
    const wrapper = mountMessageView( { props: { msg: m } })
    expect(wrapper.find('.message-artifacts').exists()).toBe(true)
  })

  it('live 标记的消息同样显示（turn 状态边界不改变位置）', () => {
    const m = msg('assistant:t9', [part('p1', [artifact('workspace://.lam/artifacts/a.png')])])
    const wrapper = mountMessageView( {
      props: { msg: { ...m, metadata: { live: true } }, turnActive: false },
    })
    expect(wrapper.find('.message-artifacts').exists()).toBe(true)
  })

  it('sub-line 子消息经 suppressArtifactsPanel 传播隐藏', async () => {
    const m = msg('sub-line-1:assistant', [part('p1', [artifact('workspace://.lam/artifacts/a.png')])])
    const wrapper = mountMessageView( { props: { msg: m, suppressArtifactsPanel: true } })
    expect(wrapper.find('.message-artifacts').exists()).toBe(false)

    await wrapper.setProps({ suppressArtifactsPanel: false })
    expect(wrapper.find('.message-artifacts').exists()).toBe(true)
  })
})

describe('「本轮产出」面板：内部去重', () => {
  it('同一 uri 跨 part 只保留一张，优先保留带 artifact_id 的条目', async () => {
    const m = msg('assistant:t2', [
      part('p1', [artifact('workspace://.lam/artifacts/x.png')]),
      part('p2', [artifact('workspace://.lam/artifacts/x.png', { artifact_id: 'art-x' })]),
    ])
    const createObjectURL = vi.fn(() => 'blob:artifact-preview')
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: createObjectURL,
    })
    const wrapper = mountMessageView( {
      props: {
        msg: m,
        projectId: 'proj-1',
        transport: createFakeTransport({
          status: 200,
          headers: { 'content-type': 'image/png' },
          body: new Uint8Array([137, 80, 78, 71]),
        }),
      },
    })
    expect(wrapper.findAll('.message-artifacts .message-attachment-deck__card')).toHaveLength(1)
    // 保留的是带 id 的条目：src 走 artifact 端点而非 files/raw
    await vi.waitFor(() => {
      expect(createObjectURL).toHaveBeenCalled()
      expect(wrapper.get('.message-artifacts img').attributes('src')).toBe('blob:artifact-preview')
    })
  })

  it('read_file base64 图（无 id/uri）按内容去重', () => {
    const m = msg('assistant:t3', [
      part('p1', [artifact(undefined, { dataUrl: 'data:image/png;base64,AAAA' })]),
      part('p2', [artifact(undefined, { dataUrl: 'data:image/png;base64,AAAA' })]),
    ])
    const wrapper = mountMessageView( { props: { msg: m } })
    expect(wrapper.findAll('.message-artifacts .message-attachment-deck__card')).toHaveLength(1)
  })

  it('不同图正常保留', () => {
    const m = msg('assistant:t4', [
      part('p1', [artifact('workspace://.lam/artifacts/a.png')]),
      part('p2', [artifact('workspace://.lam/artifacts/b.png')]),
    ])
    const wrapper = mountMessageView( { props: { msg: m } })
    expect(wrapper.findAll('.message-artifacts .message-attachment-deck__card')).toHaveLength(2)
  })

  it('展示代码/配置/文档 file_change，并排除 command/file-read 证据', () => {
    const m = msg('assistant:t5', [part('p1', [
      { kind: 'file_change', uri: 'src/app.ts', content: '+export const ready = true' },
      { kind: 'file_change', uri: 'settings.jsonc', content: '+{"ready": true}' },
      { kind: 'file_change', uri: 'README.md', content: '+# Ready' },
      {
        kind: 'file_read',
        uri: '.lam/preview/legacy.png',
        metadata: { image_data_url: 'data:image/png;base64,AAAA' },
      },
      { kind: 'file_read', uri: 'notes.txt', content: 'read only' },
    ])])
    const wrapper = mountMessageView({ props: { msg: m } })
    const cards = wrapper.findAll('.message-artifacts .message-attachment-deck__card')
    expect(cards).toHaveLength(3)
    expect(wrapper.text()).toContain('本轮产出')
    expect(wrapper.text()).not.toContain('legacy.png')
    expect(wrapper.text()).not.toContain('notes.txt')
  })
})

describe('已答复的审批卡撤出对话', () => {
  it('答复落定后整卡不再渲染，也不留下答复回显', () => {
    const m = msg('assistant:t5', [
      {
        id: 'd1',
        partType: 'decision',
        status: 'completed',
        metadata: { waitingResponse: { action: 'approve', response: 'ok' } },
      },
    ])
    const wrapper = mountMessageView( { props: { msg: m, processExpandedIds: new Set([m.id]) } })
    expect(wrapper.find('.decision-card').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('已选择')
  })

  it('待答复的审批卡仍然渲染，等待选择', () => {
    const m = msg('assistant:t6', [
      {
        id: 'd2',
        partType: 'decision',
        status: 'pending',
        label: '等待授权',
      },
    ])
    const wrapper = mountMessageView( { props: { msg: m, processExpandedIds: new Set([m.id]) } })
    const card = wrapper.find('.decision-card')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain('等待选择')
  })
})
