import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import CoreSubAgentPane from '../src/components/CoreSubAgentPane.vue'
import { findCoreSubAgentRun, selectCoreSubAgentRuns } from '../src/agents/subAgentProjection'
import { formatSubAgentElapsed, normalizeSubAgentType, subAgentStatusLabel } from '../src/agents/subAgentDisplay'
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
      { id: 'sub-task', role: 'user', content: '做渲染器', timestamp: '', parts: [] },
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
    expect(subAgentStatusLabel('paused')).toBe('已暂停')
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
