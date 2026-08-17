import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageView from '../src/components/MessageView.vue'
import type { CoreMessage, MessagePart, ToolArtifact } from '../src/types'

/**
 * 「本轮产出」面板（message-artifacts）契约：
 * 1. 本轮（turn）运行期间隐藏——活跃轮内所有消息（含子代理 sub-line 段，经
 *    suppressArtifactsPanel 传播），轮次结束才出现；
 * 2. 面板内部去重：同一张图跨多个 part 只留一张（artifact_id → uri →
 *    image_data_url 归一化键），同一 uri 优先保留带 artifact_id 的条目。
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

describe('「本轮产出」面板：轮次结束才出现', () => {
  it('本轮运行中隐藏，轮次结束才出现', async () => {
    const m = msg('assistant:t1', [part('p1', [artifact('workspace://.lam/artifacts/a.png')])])
    const wrapper = mount(MessageView, { props: { msg: m, turnActive: true, activeTurnId: 't1' } })
    expect(wrapper.find('.message-artifacts').exists()).toBe(false)

    await wrapper.setProps({ turnActive: false })
    expect(wrapper.find('.message-artifacts').exists()).toBe(true)
  })

  it('同轮分段消息（assistant:<turn>#<n>）同样隐藏', () => {
    const m = msg('assistant:t1#2', [part('p1', [artifact('workspace://.lam/artifacts/a.png')])])
    const wrapper = mount(MessageView, { props: { msg: m, turnActive: true, activeTurnId: 't1' } })
    expect(wrapper.find('.message-artifacts').exists()).toBe(false)
  })

  it('历史消息（非活跃轮）直接显示', () => {
    const m = msg('assistant:t0', [part('p1', [artifact('workspace://.lam/artifacts/a.png')])])
    const wrapper = mount(MessageView, { props: { msg: m } })
    expect(wrapper.find('.message-artifacts').exists()).toBe(true)
  })

  it('live 标记的消息同样隐藏（turn 状态边界兜底）', () => {
    const m = msg('assistant:t9', [part('p1', [artifact('workspace://.lam/artifacts/a.png')])])
    const wrapper = mount(MessageView, {
      props: { msg: { ...m, metadata: { live: true } }, turnActive: false },
    })
    expect(wrapper.find('.message-artifacts').exists()).toBe(false)
  })

  it('sub-line 子消息经 suppressArtifactsPanel 传播隐藏', async () => {
    const m = msg('sub-line-1:assistant', [part('p1', [artifact('workspace://.lam/artifacts/a.png')])])
    const wrapper = mount(MessageView, { props: { msg: m, suppressArtifactsPanel: true } })
    expect(wrapper.find('.message-artifacts').exists()).toBe(false)

    await wrapper.setProps({ suppressArtifactsPanel: false })
    expect(wrapper.find('.message-artifacts').exists()).toBe(true)
  })
})

describe('「本轮产出」面板：内部去重', () => {
  it('同一 uri 跨 part 只保留一张，优先保留带 artifact_id 的条目', () => {
    const m = msg('assistant:t2', [
      part('p1', [artifact('workspace://.lam/artifacts/x.png')]),
      part('p2', [artifact('workspace://.lam/artifacts/x.png', { artifact_id: 'art-x' })]),
    ])
    const wrapper = mount(MessageView, { props: { msg: m, projectId: 'proj-1' } })
    expect(wrapper.findAll('.message-artifacts figure')).toHaveLength(1)
    // 保留的是带 id 的条目：src 走 artifact 端点而非 files/raw
    expect(wrapper.get('.message-artifacts img').attributes('src')).toContain('/projects/proj-1/artifacts/art-x/file')
  })

  it('read_file base64 图（无 id/uri）按内容去重', () => {
    const m = msg('assistant:t3', [
      part('p1', [artifact(undefined, { dataUrl: 'data:image/png;base64,AAAA' })]),
      part('p2', [artifact(undefined, { dataUrl: 'data:image/png;base64,AAAA' })]),
    ])
    const wrapper = mount(MessageView, { props: { msg: m } })
    expect(wrapper.findAll('.message-artifacts figure')).toHaveLength(1)
  })

  it('不同图正常保留', () => {
    const m = msg('assistant:t4', [
      part('p1', [artifact('workspace://.lam/artifacts/a.png')]),
      part('p2', [artifact('workspace://.lam/artifacts/b.png')]),
    ])
    const wrapper = mount(MessageView, { props: { msg: m } })
    expect(wrapper.findAll('.message-artifacts figure')).toHaveLength(2)
  })
})

describe('决策答复 GSAP Transition（jsdom 降级）', () => {
  it('决策答复在 jsdom 下正常渲染不报错', () => {
    const m = msg('assistant:t5', [
      {
        id: 'd1',
        partType: 'decision',
        status: 'completed',
        metadata: { waitingResponse: { action: 'approve', response: 'ok' } },
      },
    ])
    const wrapper = mount(MessageView, { props: { msg: m } })
    expect(wrapper.find('.decision-card-decision').exists()).toBe(true)
    expect(wrapper.find('.decision-card-decision').text()).toContain('批准')
  })
})
