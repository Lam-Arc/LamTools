import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import CoreSubAgentPane from '../src/components/CoreSubAgentPane.vue'
import ChatThread from '../src/components/ChatThread.vue'
import { findCoreSubAgentRun, selectCoreSubAgentRuns } from '../src/agents/subAgentProjection'
import { formatSubAgentElapsed, normalizeSubAgentType, subAgentRunIdentity, subAgentStatusLabel } from '../src/agents/subAgentDisplay'
import type { CoreMessage, CoreSubAgentRun } from '../src/types'
import { createFakeTransport } from './fake-transport'

const testTransport = createFakeTransport()

afterEach(() => {
  document.body.querySelectorAll('[data-sub-agent-pane]').forEach(element => element.remove())
})

function paneRun(overrides: Partial<CoreSubAgentRun> = {}): CoreSubAgentRun {
  return {
    id: 'thread-1:sub:renderer_dev',
    subSessionId: 'thread-1:sub:renderer_dev',
    name: 'renderer_dev',
    task: '做《林溪小镇》的渲染器，交付 render.js 与冒烟脚本。',
    status: 'running',
    modelId: 'deepseek/deepseek-v4.1-flash',
    model: 'deepseek/deepseek-v4.1-flash',
    reasoningLevel: 'high',
    type: 'execute',
    startedAt: '2026-10-04T21:20:11.789Z',
    updatedAt: '2026-10-04T21:22:11.789Z',
    elapsedMs: 120_000,
    timeline: [
      { id: 'sub-task', role: 'user', content: '做《林溪小镇》的渲染器，交付 render.js 与冒烟脚本。', timestamp: '', parts: [] },
      {
        id: 'sub-answer',
        role: 'assistant',
        content: '渲染器已完成，两个交付文件都在。',
        timestamp: '',
        parts: [{
          id: 'sub-text',
          partType: 'model_text',
          status: 'completed',
          content: '渲染器已完成，两个交付文件都在。',
        }],
      },
    ],
    sourcePartIds: [],
    ...overrides,
  }
}

function paneElement(): HTMLElement {
  const element = document.body.querySelector<HTMLElement>('[data-sub-agent-pane]')
  if (!element) throw new Error('sub-agent pane not mounted')
  return element
}

describe('CoreSubAgentPane', () => {
  it('shows only context calls and cache as small footer text', async () => {
    const run = paneRun({ timeline: [{ id: 'child', role: 'assistant', content: '', timestamp: '', parts: [], metadata: {
      contextMetrics: { estimated_prompt_tokens: 2000, context_window_tokens: 10000 },
      resourceCalls: [{ id: 'child-call', usage: { llm_calls: 1, input_tokens: 100, output_tokens: 10, cached_tokens: 80 } }],
    } }] })
    const wrapper = mount(CoreSubAgentPane, { props: { run, transport: testTransport, teleportTo: 'body' } })
    await nextTick()
    const footer = paneElement().querySelector('footer')!
    expect(footer.textContent).toContain('2k / 10k')
    expect(footer.textContent).toContain('调用 1')
    expect(footer.textContent).toContain('80%')
    expect(footer.textContent).not.toContain('输入')
    expect(footer.textContent).not.toContain('输出')
    expect(footer.querySelector('svg')).toBeNull()
    wrapper.unmount()
  })

  it('renders identity, timing and the child timeline without any composer', async () => {
    const run = paneRun({ status: 'completed', elapsedMs: 120_000 })
    const wrapper = mount(CoreSubAgentPane, {
      props: { run, transport: testTransport, teleportTo: 'body' },
    })
    await nextTick()

    const pane = paneElement()
    expect(pane.textContent).toContain('renderer_dev')
    expect(pane.textContent).toContain('已完成')
    expect(pane.textContent).toContain('execute')
    expect(pane.textContent).toContain('deepseek/deepseek-v4.1-flash')
    expect(pane.textContent).toContain('high')
    expect(pane.textContent).toContain('2m 00s')
    expect(pane.textContent).toContain('交付 render.js 与冒烟脚本')
    expect(pane.textContent).toContain('渲染器已完成，两个交付文件都在。')

    // 只读：这一屏没有任何输入控件。
    expect(pane.querySelector('textarea')).toBeNull()
    expect(pane.querySelector('input')).toBeNull()
    expect(pane.querySelector('.sub-agent-pane-composer')).toBeNull()

    wrapper.unmount()
  })

  it('shows the task once, from the process stream, with no separate task box', async () => {
    // 顶部不再有独立任务格：任务文本由过程流第一条用户消息承担（用户 2026-10-12 口径）。
    // 监督者记录的 summary 是结论，不能拿来当任务。
    const run = paneRun({
      task: '',
      timeline: [
        { id: 'sub-task', role: 'user', content: '把渲染器补齐并给出冒烟结果', timestamp: '', parts: [] },
        {
          id: 'sub-answer',
          role: 'assistant',
          content: '渲染器已完成，两个交付文件都在。',
          timestamp: '',
          parts: [{ id: 'sub-text', partType: 'model_text', status: 'completed', content: '渲染器已完成，两个交付文件都在。' }],
        },
      ],
    })
    const wrapper = mount(CoreSubAgentPane, {
      props: {
        run,
        transport: testTransport,
        teleportTo: 'body',
        durableRecord: { name: 'renderer_dev', status: 'completed', summary: '渲染器已完成，两个交付文件都在。' },
      },
    })
    await nextTick()

    const pane = paneElement()
    expect(pane.querySelector('.sub-agent-pane-task')).toBeNull()
    const text = pane.textContent || ''
    // 任务只出现一次（过程流的第一条用户消息），结论也只出现一次（结论在其后的回答里）。
    expect(text.split('把渲染器补齐并给出冒烟结果').length - 1).toBe(1)
    expect(text.split('渲染器已完成').length - 1).toBe(1)
    wrapper.unmount()
  })

  it('resizes the pane from the gap handle, within limits, and with arrow keys', async () => {
    const firePointer = (target: Element, type: string, clientX: number): void => {
      const event = new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, clientX })
      Object.defineProperty(event, 'pointerId', { value: 1 })
      Object.defineProperty(event, 'isPrimary', { value: true })
      target.dispatchEvent(event)
    }
    const fireKey = (target: Element, key: string, shiftKey = false): void => {
      target.dispatchEvent(new KeyboardEvent('keydown', { key, shiftKey, bubbles: true, cancelable: true }))
    }
    // 拖动按帧合并：pointermove 只登记，帧到才 emit。
    const nextFrame = (): Promise<void> => new Promise((resolve) => requestAnimationFrame(() => resolve()))
    const wrapper = mount(CoreSubAgentPane, {
      props: { run: paneRun(), transport: testTransport, teleportTo: 'body', width: 360 },
    })
    await nextTick()

    const handle = paneElement().querySelector('[data-sub-agent-pane-resize]')
    expect(handle).toBeTruthy()
    expect(handle?.getAttribute('role')).toBe('separator')
    expect(handle?.getAttribute('aria-label')).toBe('调整子代理面板宽度')
    expect(handle?.getAttribute('aria-valuenow')).toBe('360')

    // 向左拖 = 加宽（面板贴右缘，与右侧栏那条把手同向）。
    firePointer(handle!, 'pointerdown', 500)
    firePointer(handle!, 'pointermove', 420)
    await nextFrame()
    expect(wrapper.emitted('resize')!.at(-1)).toEqual([440])
    firePointer(handle!, 'pointerup', 420)

    // 限宽：拖到极端也不越界，聊天区不会被挤没。
    firePointer(handle!, 'pointerdown', 900)
    firePointer(handle!, 'pointermove', -3000)
    await nextFrame()
    const widened = wrapper.emitted('resize')!.at(-1)?.[0] as number
    expect(widened).toBeLessThanOrEqual(720)
    firePointer(handle!, 'pointermove', 5000)
    await nextFrame()
    const narrowed = wrapper.emitted('resize')!.at(-1)?.[0] as number
    expect(narrowed).toBeGreaterThanOrEqual(320)
    firePointer(handle!, 'pointerup', 5000)

    // 方向键与鼠标同向；Shift 步进更大；其他键不动。
    fireKey(handle!, 'ArrowLeft')
    expect(wrapper.emitted('resize')!.at(-1)).toEqual([372])
    fireKey(handle!, 'ArrowRight', true)
    expect(wrapper.emitted('resize')!.at(-1)).toEqual([328])
    fireKey(handle!, 'ArrowDown')
    expect(wrapper.emitted('resize')!.at(-1)).toEqual([328])
    wrapper.unmount()
  })

  it('coalesces a drag to at most one resize per frame and keeps the final width', async () => {
    const firePointer = (target: Element, type: string, clientX: number): void => {
      const event = new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, clientX })
      Object.defineProperty(event, 'pointerId', { value: 1 })
      Object.defineProperty(event, 'isPrimary', { value: true })
      target.dispatchEvent(event)
    }
    const wrapper = mount(CoreSubAgentPane, {
      props: { run: paneRun(), transport: testTransport, teleportTo: 'body', width: 400 },
    })
    await nextTick()
    const handle = paneElement().querySelector('[data-sub-agent-pane-resize]')!

    // 一次帧内连发多条 move：只有一帧一次的 emit，且取最后一条。
    firePointer(handle, 'pointerdown', 600)
    firePointer(handle, 'pointermove', 560)
    firePointer(handle, 'pointermove', 540)
    firePointer(handle, 'pointermove', 520)
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
    const emits = wrapper.emitted('resize')!
    expect(emits).toHaveLength(1)
    expect(emits.at(-1)).toEqual([480])

    // 松手时最后一帧还没跑完：宽度不能丢。
    firePointer(handle, 'pointermove', 500)
    firePointer(handle, 'pointerup', 500)
    expect(wrapper.emitted('resize')!.at(-1)).toEqual([500])
    wrapper.unmount()
  })

  it('makes nested sub-agent rows inside the pane explicitly non-interactive', async () => {
    // 面板不消费"打开子代理"事件：里面的子代理行必须明确不可点（没有指针/悬停反馈、
    // 点击不抛事件、无障碍标注不可交互），否则用户点了会以为坏掉了。
    const run = paneRun({
      timeline: [{
        id: 'sub-inner',
        role: 'assistant',
        content: '',
        timestamp: '',
        parts: [{
          id: 'inner-agent-row',
          partType: 'agent_summary',
          status: 'completed',
          label: 'Agent completed',
          toolName: 'sub_agent_receive',
          toolArgs: { type: 'execute', name: 'inner_dev' },
          content: '内部子代理结论',
          metadata: { agent_name: 'inner_dev', sub_session_id: 'sub-inner-1' },
        }],
      }],
    })
    const wrapper = mount(CoreSubAgentPane, {
      props: { run, transport: testTransport, teleportTo: 'body' },
    })
    await nextTick()

    const heading = paneElement().querySelector('.sub-line-heading') as HTMLButtonElement | null
    expect(heading).toBeTruthy()
    // 原生 disabled：浏览器不再派发用户点击，无障碍也报不可用。
    expect(heading!.disabled).toBe(true)
    // 文案也不再承诺"打开"。
    expect(heading!.getAttribute('title')).toBeTruthy()
    expect(heading!.getAttribute('title')).not.toContain('打开')
    // 面板自身不冒泡任何"打开子代理"事件。
    expect(Object.keys(wrapper.emitted() ?? {})).not.toContain('open-sub-agent')
    wrapper.unmount()
  })

  it('reuses the main thread surface so process cards keep their layout', async () => {
    // 过程卡片/思考卡片的排版规则全部挂在 `.thread` 作用域上：容器少这个类，
    // 过程组标题的网格就会失效（文字被挤到右边、状态图标压到文字上）。
    const wrapper = mount(CoreSubAgentPane, {
      props: { run: paneRun(), transport: testTransport, teleportTo: 'body' },
    })
    await nextTick()
    const scroll = paneElement().querySelector('.sub-agent-pane-scroll')
    expect(scroll?.classList.contains('thread')).toBe(true)
    expect(scroll?.querySelector('.thread')).toBeNull()
    wrapper.unmount()
  })

  it('leaves the elapsed label out when the run carries no usable timing', async () => {
    const wrapper = mount(CoreSubAgentPane, {
      props: {
        run: paneRun({ status: 'error', elapsedMs: 0, startedAt: '2026-10-05T20:30:48.460939', completedAt: '2026-10-05T20:30:48.460939' }),
        transport: testTransport,
        teleportTo: 'body',
      },
    })
    await nextTick()
    const meta = paneElement().querySelector('.sub-agent-pane-meta')?.textContent ?? ''
    expect(meta).not.toContain('0ms')
    expect(meta).toContain('deepseek/deepseek-v4.1-flash')
    wrapper.unmount()
  })

  it('keeps the elapsed label live while the run is active and freezes it afterwards', async () => {
    const wrapper = mount(CoreSubAgentPane, {
      props: { run: paneRun({ status: 'running', elapsedMs: undefined }), transport: testTransport, teleportTo: 'body' },
    })
    await nextTick()
    expect(paneElement().textContent).toMatch(/\d/)

    await wrapper.setProps({ run: paneRun({ status: 'completed', elapsedMs: 162_000 }) })
    await nextTick()
    expect(paneElement().textContent).toContain('2m 42s')

    wrapper.unmount()
  })

  it('prefers the durable supervisor record for status and timing of resumed runs', async () => {
    // 续跑过的子代理：投影只能看到「运行中」的委派行，真实状态在监督者记录里。
    const wrapper = mount(CoreSubAgentPane, {
      props: {
        run: paneRun({ status: 'running' }),
        transport: testTransport,
        teleportTo: 'body',
        durableRecord: {
          name: 'renderer_dev',
          status: 'idle',
          elapsed_ms: 1_068_569,
          started_at: Date.now() / 1000 - 4000,
          completed_at: Date.now() / 1000 - 2300,
        },
      },
    })
    await nextTick()
    const head = paneElement().querySelector('.sub-agent-pane-head')?.textContent ?? ''
    expect(head).toContain('空闲')
    expect(head).not.toContain('运行中')
    expect(paneElement().textContent).toContain('17m 48s')
    wrapper.unmount()
  })

  it('keeps the live tick when the durable record says the run is active', async () => {
    const wrapper = mount(CoreSubAgentPane, {
      props: {
        run: paneRun({ status: 'running' }),
        transport: testTransport,
        teleportTo: 'body',
        durableRecord: { name: 'renderer_dev', status: 'running', started_at: Date.now() / 1000 - 65 },
      },
    })
    await nextTick()
    expect(paneElement().querySelector('.sub-agent-pane-head')?.textContent).toContain('运行中')
    expect(paneElement().textContent).toContain('1m 05s')
    wrapper.unmount()
  })

  it('closes from the back affordance', async () => {
    const wrapper = mount(CoreSubAgentPane, {
      props: { run: paneRun(), transport: testTransport, teleportTo: 'body' },
    })
    await nextTick()
    paneElement().querySelector<HTMLElement>('.sub-agent-pane-back')!.click()
    expect(wrapper.findComponent(CoreSubAgentPane).emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })
})

describe('sub-agent display helpers', () => {
  it('labels durable run statuses for every surface', () => {
    expect(subAgentStatusLabel('running')).toBe('运行中')
    // 等待回答 = 成员停在提问这个人类边界；已暂停 = 用户暂停了整个会话。
    expect(subAgentStatusLabel('paused')).toBe('等待回答')
    expect(subAgentStatusLabel('suspended')).toBe('已暂停')
    expect(subAgentStatusLabel('interrupted')).toBe('已中断')
    expect(subAgentStatusLabel('closed')).toBe('已关闭')
    expect(subAgentStatusLabel('idle')).toBe('空闲')
    expect(subAgentStatusLabel('error')).toBe('失败')
    expect(subAgentStatusLabel('completed')).toBe('已完成')
  })

  it('normalizes the delegation kind to the shared two-token vocabulary', () => {
    expect(normalizeSubAgentType('consider')).toBe('consider')
    expect(normalizeSubAgentType('thinking')).toBe('consider')
    expect(normalizeSubAgentType('execute')).toBe('execute')
    expect(normalizeSubAgentType(undefined)).toBe('execute')
  })

  it('formats durations on one scale', () => {
    expect(formatSubAgentElapsed(840)).toBe('840ms')
    expect(formatSubAgentElapsed(12_400)).toBe('12s')
    expect(formatSubAgentElapsed(1_629_849)).toBe('27m 09s')
  })

  it('keys a run by durable identity, stable across per-frame rebuilds', () => {
    // 面板开着时 openSubAgentRun 每条消息都会重建一个新运行对象；持久记录的拉取/
    // 刷新必须按身份去重，否则就成了每帧一次 RPC（面板一开整机卡顿的根因）。
    const run = paneRun()
    const rebuiltRun: CoreSubAgentRun = { ...run, timeline: [], status: 'completed' }
    expect(subAgentRunIdentity(run)).toBe('thread-1:sub:renderer_dev')
    expect(subAgentRunIdentity(rebuiltRun)).toBe(subAgentRunIdentity(run))
    expect(subAgentRunIdentity({ subSessionId: '', id: '' })).toBe('')
    expect(subAgentRunIdentity(null)).toBe('')

    const messages: CoreMessage[] = [{
      id: 'm-1',
      role: 'assistant',
      content: '',
      timestamp: '',
      parts: [{
        id: 'p-1',
        partType: 'agent_summary',
        status: 'running',
        content: '',
        toolName: 'sub_agent',
        metadata: { agent_name: 'renderer_dev', sub_session_id: 'thread-1:sub:renderer_dev' },
      }],
    }]
    const first = selectCoreSubAgentRuns(messages)[0]
    const rebuilt = selectCoreSubAgentRuns(messages.map(message => ({ ...message })))[0]
    expect(rebuilt).not.toBe(first)
    expect(subAgentRunIdentity(rebuilt)).toBe(subAgentRunIdentity(first))
  })
})

describe('findCoreSubAgentRun', () => {
  it('resolves a transcript part to its run by sub-session id, then by name', () => {
    const messages: CoreMessage[] = [
      {
        id: 'm-1',
        role: 'assistant',
        content: '',
        timestamp: '',
        parts: [{
          id: 'p-1',
          partType: 'agent_summary',
          status: 'completed',
          content: '完成。',
          toolName: 'sub_agent',
          metadata: { agent_name: 'renderer_dev', sub_session_id: 'thread-1:sub:renderer_dev' },
        }],
      },
    ]
    const runs = selectCoreSubAgentRuns(messages)
    expect(findCoreSubAgentRun(runs, 'thread-1:sub:renderer_dev')?.name).toBe('renderer_dev')
    expect(findCoreSubAgentRun(runs, { subSessionId: '', name: 'renderer_dev' })?.name).toBe('renderer_dev')
    expect(findCoreSubAgentRun(runs, { subSessionId: '', name: 'missing' })).toBeUndefined()
  })
})

describe('CoreSubAgentPane timeline cost', () => {
  function longTimeline(count: number): CoreSubAgentRun['timeline'] {
    return Array.from({ length: count }, (_, index) => ({
      id: `sub-msg-${index}`,
      role: 'assistant' as const,
      content: `过程 ${index}`,
      timestamp: '',
      parts: [{
        id: `sub-part-${index}`,
        partType: 'model_text' as const,
        status: 'completed' as const,
        content: `过程 ${index}`,
      }],
    }))
  }

  it('mounts only a bounded window of a long timeline, and can reveal earlier process', async () => {
    const wrapper = mount(CoreSubAgentPane, {
      props: { run: paneRun({ timeline: longTimeline(200) }), transport: testTransport, teleportTo: 'body' },
    })
    await nextTick()

    const pane = paneElement()
    const mounted = pane.querySelectorAll('.message-view').length
    // 200 条过程不再全部挂载：窗口有上限。
    expect(mounted).toBe(30)
    expect(mounted).toBeLessThan(200)

    const reveal = pane.querySelector<HTMLElement>('[data-sub-agent-pane-earlier]')
    expect(reveal).toBeTruthy()
    reveal!.click()
    await nextTick()
    expect(paneElement().querySelectorAll('.message-view').length).toBe(60)
    wrapper.unmount()
  })

  it('does not mount an earlier action affordance when the whole timeline fits', async () => {
    const wrapper = mount(CoreSubAgentPane, {
      props: { run: paneRun(), transport: testTransport, teleportTo: 'body' },
    })
    await nextTick()
    expect(paneElement().querySelector('[data-sub-agent-pane-earlier]')).toBeNull()
    wrapper.unmount()
  })

  it('keeps a settled run out of the live path when its parts still read running', async () => {
    // 成员已完成，但过程条目还挂着 running（续跑/唤醒后的残留）：分屏不能继续按
    // 流式渲染它，否则完成的内容会永远留在实时路径上逐帧重投影。
    const wrapper = mount(CoreSubAgentPane, {
      props: {
        run: paneRun({
          status: 'running',
          timeline: [{
            id: 'sub-live',
            role: 'assistant',
            content: '结论',
            timestamp: '',
            metadata: { live: true, timeline: true },
            parts: [{ id: 'sub-live-part', partType: 'model_text', status: 'running', content: '结论' }],
          }],
        }),
        transport: testTransport,
        teleportTo: 'body',
        durableRecord: { name: 'renderer_dev', status: 'completed' },
      },
    })
    await nextTick()

    const passed = wrapper.findComponent(ChatThread).props('messages') as CoreMessage[]
    expect(passed).toHaveLength(1)
    expect(passed[0].metadata?.live).toBeFalsy()
    wrapper.unmount()
  })

  it('settles on the run status when there is no durable record', async () => {
    const wrapper = mount(CoreSubAgentPane, {
      props: {
        run: paneRun({
          status: 'completed',
          timeline: [{
            id: 'sub-live-2',
            role: 'assistant',
            content: '结论',
            timestamp: '',
            metadata: { live: true },
            parts: [{ id: 'sub-live-2-part', partType: 'model_text', status: 'running', content: '结论' }],
          }],
        }),
        transport: testTransport,
        teleportTo: 'body',
      },
    })
    await nextTick()
    const passed = wrapper.findComponent(ChatThread).props('messages') as CoreMessage[]
    expect(passed[0].metadata?.live).toBeFalsy()
    wrapper.unmount()
  })

  it('keeps a genuinely running member live', async () => {
    const wrapper = mount(CoreSubAgentPane, {
      props: {
        run: paneRun({
          status: 'running',
          timeline: [{
            id: 'sub-running',
            role: 'assistant',
            content: '进行中',
            timestamp: '',
            metadata: { live: true },
            parts: [{ id: 'sub-running-part', partType: 'model_text', status: 'running', content: '进行中' }],
          }],
        }),
        transport: testTransport,
        teleportTo: 'body',
      },
    })
    await nextTick()
    const passed = wrapper.findComponent(ChatThread).props('messages') as CoreMessage[]
    expect(passed[0].metadata?.live).toBe(true)
    wrapper.unmount()
  })
})

describe('CoreSubAgentPane member-wait settling', () => {
  /** 父条目与子过程都还写着 running 的残留运行。 */
  function residueRun(): CoreSubAgentRun {
    return paneRun({
      status: 'running',
      timeline: [{
        id: 'sub-residue',
        role: 'assistant',
        content: '结论',
        timestamp: '',
        metadata: { live: true },
        parts: [{ id: 'sub-residue-part', partType: 'model_text', status: 'running', content: '结论' }],
      }],
    })
  }

  function mountedLiveOf(props: Record<string, unknown>): unknown {
    const wrapper = mount(CoreSubAgentPane, {
      props: { run: residueRun(), transport: testTransport, teleportTo: 'body', ...props },
    })
    const passed = wrapper.findComponent(ChatThread).props('messages') as CoreMessage[]
    const live = passed[0]?.metadata?.live
    wrapper.unmount()
    return live
  }

  it('settles a member the wait list no longer names, without a durable record', () => {
    // 名单里没有它 => 运行时不再报告它在跑：残留状态据此收敛。
    expect(mountedLiveOf({
      memberWaitKnown: true,
      runningMemberNames: ['other_member'],
      mainRunning: false,
    })).toBeFalsy()
  })

  it('settles every member once the drain report clears the list and the main agent is idle', () => {
    expect(mountedLiveOf({
      memberWaitKnown: true,
      runningMemberNames: [],
      mainRunning: false,
    })).toBeFalsy()
  })

  it('keeps a member live while the wait list still names it', () => {
    expect(mountedLiveOf({
      memberWaitKnown: true,
      runningMemberNames: ['renderer_dev'],
      mainRunning: false,
    })).toBe(true)
  })

  it('does not settle from a cleared list while the main agent is working', () => {
    // 同一轮里主代理回到前台后的委派不是"挂起等待"，名单为空不能当作收敛。
    expect(mountedLiveOf({
      memberWaitKnown: true,
      runningMemberNames: [],
      mainRunning: true,
    })).toBe(true)
  })

  it('does not settle when the runtime never published the members fact', () => {
    expect(mountedLiveOf({
      memberWaitKnown: false,
      runningMemberNames: [],
      mainRunning: false,
    })).toBe(true)
  })

  it('keeps the status label on the member own status, not on the members fact', () => {
    // 成员事实（等成员 / 运行中成员名单）只在回合终态之后发布、最后一名成员结束时清空：
    // 它表达的是"还有谁在跑"这一瞬时集合，表达不了某个成员的实时状态。状态标签因此只读
    // 这个成员自己的状态（投影 + 监督者记录）；事实只决定它是否还在实时路径上。
    const wrapper = mount(CoreSubAgentPane, {
      props: {
        run: residueRun(),
        transport: testTransport,
        teleportTo: 'body',
        memberWaitKnown: true,
        runningMemberNames: ['other_member'],
        mainRunning: false,
      },
    })
    expect(paneElement().querySelector('.sub-agent-pane-head')?.textContent).toContain('运行中')
    wrapper.unmount()
  })

  it('prefers the member own published status over the projected one', () => {
    // 后端在回合进行中就按成员发布实时状态：投影只能说"这条还在跑"，
    // 已发布的状态才是这个成员自己的状态。
    const wrapper = mount(CoreSubAgentPane, {
      props: {
        run: paneRun({ status: 'running' }),
        transport: testTransport,
        teleportTo: 'body',
        memberStatuses: { renderer_dev: 'idle' },
      },
    })
    const head = paneElement().querySelector('.sub-agent-pane-head')?.textContent ?? ''
    expect(head).toContain('空闲')
    expect(head).not.toContain('运行中')
    wrapper.unmount()
  })

  it('ignores a published status for another member', () => {
    const wrapper = mount(CoreSubAgentPane, {
      props: {
        run: paneRun({ status: 'running' }),
        transport: testTransport,
        teleportTo: 'body',
        memberStatuses: { other_member: 'idle' },
      },
    })
    expect(paneElement().querySelector('.sub-agent-pane-head')?.textContent).toContain('运行中')
    wrapper.unmount()
  })
})
