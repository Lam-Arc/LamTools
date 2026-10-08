import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import CoreSubAgentPanel from '../src/components/CoreSubAgentPanel.vue'
import CoreSubAgentDialog from '../src/components/CoreSubAgentDialog.vue'
import ComposerBar from '../src/components/ComposerBar.vue'
import { selectCoreSubAgentRuns } from '../src/agents/subAgentProjection'
import type { CoreMessage, CoreSubAgentRun, MessagePartStatus } from '../src/types'
import { createFakeTransport } from './fake-transport'

const testTransport = createFakeTransport()

afterEach(() => {
  document.body.querySelectorAll('.core-sub-agent-tooltip').forEach(element => element.remove())
})

describe('selectCoreSubAgentRuns', () => {
  it('groups updates by sub_session_id and preserves the first task and child timeline', () => {
    const messages: CoreMessage[] = [
      assistantMessage('parent-1', [agentPart({
        id: 'agent-a-1',
        sessionId: 'sub-a',
        name: 'repo_reader',
        task: '先读取项目边界。',
        status: 'completed',
        childText: '已读取项目。',
      }), agentPart({
        id: 'agent-b-1',
        sessionId: 'sub-b',
        name: 'reviewer',
        task: '复核可访问性。',
        status: 'running',
        childText: '正在复核。',
      })]),
      assistantMessage('parent-2', [agentPart({
        id: 'agent-a-2',
        sessionId: 'sub-a',
        name: 'repo_reader',
        task: '这条后续任务不应覆盖首条。',
        status: 'running',
        childText: '继续检查测试。',
      })]),
    ]

    const runs = selectCoreSubAgentRuns(messages)

    expect(runs.map(run => run.subSessionId)).toEqual(['sub-a', 'sub-b'])
    expect(runs[0]).toMatchObject({
      id: 'sub-a',
      name: 'repo_reader',
      task: '先读取项目边界。',
      status: 'running',
      sourcePartIds: ['agent-a-1', 'agent-a-2'],
    })
    expect(runs[0].timeline).toHaveLength(3)
    expect(runs[0].timeline[0]).toMatchObject({ role: 'user', content: '先读取项目边界。' })
    expect(runs[0].timeline[1].parts?.[0]).toMatchObject({ partType: 'model_text', content: '已读取项目。' })
    expect(runs[0].timeline[2].metadata).toMatchObject({ live: true, subSessionId: 'sub-a' })
  })

  it('ignores agent summaries without a durable sub session id', () => {
    const part = agentPart({ id: 'agent-no-session', sessionId: '', name: 'worker', task: 'Do work', status: 'completed' })
    expect(selectCoreSubAgentRuns([assistantMessage('parent', [part])])).toEqual([])
  })

  it('projects a direct child userMessage as a user row instead of assistant process text', () => {
    const part = agentPart({
      id: 'agent-a-1',
      sessionId: 'sub-a',
      name: 'reviewer',
      task: '先检查现状。',
      status: 'completed',
    })
    part.metadata = {
      ...part.metadata,
      subLineParts: [
        {
          id: 'child-user-1',
          partType: 'model_text',
          status: 'completed',
          content: '继续检查交互细节。',
          metadata: { type: 'userMessage' },
        },
        {
          id: 'child-answer-1',
          partType: 'model_text',
          status: 'completed',
          content: '已继续检查。',
        },
      ],
    }

    const [run] = selectCoreSubAgentRuns([assistantMessage('parent', [part])])

    expect(run.timeline.map(message => message.role)).toEqual(['user', 'user', 'assistant'])
    expect(run.timeline[1]).toMatchObject({ role: 'user', content: '继续检查交互细节。', parts: [] })
    expect(run.timeline[2].parts).toEqual([
      expect.objectContaining({ id: 'child-answer-1', partType: 'model_text', content: '已继续检查。' }),
    ])
  })

  it('derives a resumed child status from its latest child event', () => {
    const part = agentPart({
      id: 'agent-resumed',
      sessionId: 'sub-resumed',
      name: 'reviewer',
      task: 'Review',
      status: 'completed',
    })
    part.metadata = {
      ...part.metadata,
      subLineParts: [{
        id: 'child-tool-running',
        partType: 'tool_call',
        status: 'running',
        content: 'Checking files',
        toolName: 'read_file',
      }],
    }

    expect(selectCoreSubAgentRuns([assistantMessage('parent', [part])])[0].status).toBe('running')
  })

  it('keeps a parent run active after its latest child event completes', () => {
    const part = agentPart({
      id: 'agent-active',
      sessionId: 'sub-active',
      name: 'reviewer',
      task: 'Review',
      status: 'running',
    })
    part.metadata = {
      ...part.metadata,
      subLineParts: [{
        id: 'child-tool-complete',
        partType: 'tool_call',
        status: 'completed',
        content: 'Checked files',
        toolName: 'read_file',
      }],
    }

    expect(selectCoreSubAgentRuns([assistantMessage('parent', [part])])[0].status).toBe('running')
  })

  it('keeps a live event without sub_session_id and folds resumed lifecycles by name', () => {
    const first = agentPart({
      id: 'agent-live-1',
      sessionId: '',
      name: 'reviewer',
      task: 'Review',
      status: 'running',
    })
    first.startedAt = '2026-07-18T00:00:00.000Z'
    first.metadata = { ...first.metadata, type: 'consider', model: 'model-a', reasoning_level: 'high' }
    const resumed = agentPart({
      id: 'agent-live-2',
      sessionId: 'child-2',
      name: 'reviewer',
      task: 'Review again',
      status: 'completed',
    })
    resumed.startedAt = '2026-07-18T00:01:00.000Z'
    resumed.completedAt = '2026-07-18T00:01:02.000Z'
    resumed.metadata = { ...resumed.metadata, model: 'model-b', reasoning_level: 'medium' }

    const runs = selectCoreSubAgentRuns([
      assistantMessage('parent-1', [first]),
      assistantMessage('parent-2', [resumed]),
    ])

    expect(runs).toHaveLength(1)
    expect(runs[0]).toMatchObject({
      name: 'reviewer',
      status: 'completed',
      model: 'model-b',
      reasoningLevel: 'medium',
      sourceMessageIds: ['parent-1', 'parent-2'],
      sourcePartIds: ['agent-live-1', 'agent-live-2'],
      subSessionIds: ['child-2'],
    })
    expect(runs[0].elapsedMs).toBe(2000)
  })

  it('preserves explicit consider/model/reasoning metadata when a later child event omits it', () => {
    const first = agentPart({
      id: 'agent-consider-1',
      sessionId: 'sub-consider',
      name: 'planner',
      task: 'Plan the change.',
      status: 'running',
    })
    first.metadata = {
      ...first.metadata,
      type: 'consider',
      model: 'model-a',
      reasoning_level: 'high',
    }
    const later = agentPart({
      id: 'agent-consider-2',
      sessionId: 'sub-consider',
      name: 'planner',
      task: 'Continue the plan.',
      status: 'completed',
    })

    const [run] = selectCoreSubAgentRuns([
      assistantMessage('parent-1', [first]),
      assistantMessage('parent-2', [later]),
    ])

    expect(run).toMatchObject({
      type: 'consider',
      model: 'model-a',
      reasoningLevel: 'high',
    })
  })

  it('keeps a delegated run\'s own process on the mailbox row that carried it', () => {
    // Real shape: the parent's `sub_agent_message` row owns the child's whole
    // timeline (reasoning + tool calls) as nested parts. Treating that row as a
    // bare "message sent" left every sub-agent view with the assignment only.
    const messageRow = agentPart({
      id: 'agent-msg-1',
      sessionId: 'thread-1:sub:renderer_dev',
      name: 'renderer_dev',
      task: '',
      status: 'completed',
    })
    messageRow.toolName = 'sub_agent_message'
    messageRow.toolArgs = { type: 'execute', name: 'renderer_dev', prompt: '做渲染器，交付 render.js。' }
    messageRow.metadata = {
      ...messageRow.metadata,
      subLineParts: [
        { id: 'child-1', partType: 'reasoning', status: 'completed', content: '先看现有渲染管线。' },
        {
          id: 'child-2',
          partType: 'tool_call',
          status: 'completed',
          label: 'run_command',
          toolName: 'run_command',
          toolArgs: { command: 'node render.js' },
          toolResult: 'PASS 37 checks',
        },
        { id: 'child-3', partType: 'model_text', status: 'completed', content: '渲染器完成，验证全过。' },
      ],
    }

    const [run] = selectCoreSubAgentRuns([assistantMessage('parent-1', [messageRow])])

    expect(run.timeline.map(message => message.role)).toEqual(['user', 'assistant'])
    expect(run.timeline[0].content).toContain('做渲染器')
    const child = run.timeline[1]
    expect(child.content).toBe('渲染器完成，验证全过。')
    expect((child.parts ?? []).map(part => part.partType)).toEqual(['reasoning', 'tool_call', 'model_text'])
    expect(child.metadata?.timeline).toBe(true)
  })
})

describe('CoreSubAgentPanel', () => {
  it('shows four rows by default, expands the rest, and opens one run', async () => {
    const runs = Array.from({ length: 6 }, (_, index) => fakeRun(index + 1))
    const wrapper = mount(CoreSubAgentPanel, { props: { runs, dialogId: 'agent-dialog' } })

    expect(wrapper.findAll('[data-sub-agent-id]')).toHaveLength(4)
    expect(wrapper.get('.core-sub-agent-panel__more').text()).toContain('查看其余 2 个')

    await wrapper.get('.core-sub-agent-panel__more').trigger('click')
    expect(wrapper.findAll('[data-sub-agent-id]')).toHaveLength(6)
    expect(wrapper.get('.core-sub-agent-panel__more').text()).toContain('收起')

    await wrapper.get('[data-sub-agent-id="sub-1"]').trigger('click')
    expect(wrapper.emitted('open')).toEqual([['sub-1']])
    wrapper.unmount()
  })

  it('never shows more than four rows before expansion', () => {
    const wrapper = mount(CoreSubAgentPanel, {
      props: { runs: Array.from({ length: 8 }, (_, index) => fakeRun(index + 1)), limit: 8 },
    })

    expect(wrapper.findAll('[data-sub-agent-id]')).toHaveLength(4)
    expect(wrapper.get('.core-sub-agent-panel__more').text()).toContain('查看其余 4 个')
    wrapper.unmount()
  })

  it('keeps the overflow list open when live updates only reorder existing agents', async () => {
    const runs = Array.from({ length: 6 }, (_, index) => fakeRun(index + 1))
    const wrapper = mount(CoreSubAgentPanel, { props: { runs } })

    await wrapper.get('.core-sub-agent-panel__more').trigger('click')
    await wrapper.setProps({ runs: [...runs].reverse() })

    expect(wrapper.findAll('[data-sub-agent-id]')).toHaveLength(6)
    expect(wrapper.findAll('[data-sub-agent-id]').map(row => row.attributes('data-sub-agent-id')))
      .toEqual(['sub-6', 'sub-5', 'sub-4', 'sub-3', 'sub-2', 'sub-1'])
    expect(wrapper.get('.core-sub-agent-panel__more').text()).toContain('收起')
    wrapper.unmount()
  })

  it('keeps the stable named row and overflow state when a reused agent gets a new child session', async () => {
    const runs = Array.from({ length: 6 }, (_, index) => fakeRun(index + 1))
    const wrapper = mount(CoreSubAgentPanel, { props: { runs } })

    await wrapper.get('.core-sub-agent-panel__more').trigger('click')
    const firstRow = wrapper.get('[data-sub-agent-id="sub-1"]').element
    await wrapper.setProps({
      runs: runs.map((run, index) => index === 0 ? { ...run, subSessionId: 'sub-1-resumed' } : run),
    })

    expect(wrapper.findAll('[data-sub-agent-id]')).toHaveLength(6)
    expect(wrapper.get('[data-sub-agent-id="sub-1-resumed"]').element).toBe(firstRow)
    expect(wrapper.get('.core-sub-agent-panel__more').text()).toContain('收起')
    wrapper.unmount()
  })

  it('reveals and removes the inline timeline for a run without a source message', async () => {
    const run = fakeRun(1)
    const wrapper = mount(CoreSubAgentPanel, {
      props: { runs: [run], activeSubAgentId: '' },
    })

    expect(wrapper.find('.core-sub-agent-panel__timeline').exists()).toBe(false)
    await wrapper.setProps({ activeSubAgentId: run.subSessionId })
    expect(wrapper.get('.core-sub-agent-panel__timeline').text()).toContain('任务 1')
    await wrapper.setProps({ activeSubAgentId: '' })
    expect(wrapper.find('.core-sub-agent-panel__timeline').exists()).toBe(false)
    wrapper.unmount()
  })

  it('shows the first task on pointer hover and keyboard focus', async () => {
    const wrapper = mount(CoreSubAgentPanel, { props: { runs: [fakeRun(1)] } })
    const row = wrapper.get('[data-sub-agent-id="sub-1"]')

    await row.trigger('mouseenter')
    await nextTick()
    expect(document.body.querySelector('.core-sub-agent-tooltip')?.textContent).toContain('首次任务')
    expect(document.body.querySelector('.core-sub-agent-tooltip')?.textContent).toContain('任务 1')

    await row.trigger('mouseleave')
    await row.trigger('focus')
    await nextTick()
    expect(document.body.querySelector('.core-sub-agent-tooltip')?.getAttribute('role')).toBe('tooltip')
    wrapper.unmount()
  })

  it('distinguishes a failed list refresh from an empty agent list', async () => {
    const wrapper = mount(CoreSubAgentPanel, {
      props: { runs: [], errorText: '记录更新失败。' },
    })

    expect(wrapper.get('[role="alert"]').text()).toContain('记录更新失败。')
    expect(wrapper.text()).not.toContain('尚未启动 Sub Agent')
    await wrapper.get('[role="alert"] button').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
    wrapper.unmount()
  })

  it('shows type and status text while exposing model/reasoning in the row title', () => {
    const run = fakeRun(1)
    run.type = 'consider'
    run.model = 'model-a'
    run.reasoningLevel = 'high'
    const wrapper = mount(CoreSubAgentPanel, { props: { runs: [run] } })
    const row = wrapper.get('[data-sub-agent-id="sub-1"]')
    expect(row.text()).toContain('consider')
    expect(row.text()).toContain('运行中')
    expect(row.attributes('title')).toBe('model-a · high')
    wrapper.unmount()
  })

  it('keeps list, timeline, status, backdrop, and reduced-motion transitions in the source contract', () => {
    const panelSource = readFileSync(resolve(process.cwd(), 'src/components/CoreSubAgentPanel.vue'), 'utf8')
    const dialogSource = readFileSync(resolve(process.cwd(), 'src/components/CoreSubAgentDialog.vue'), 'utf8')

    expect(panelSource).toContain('<TransitionGroup name="sub-agent-list"')
    expect(panelSource).toContain('<Transition name="sub-agent-timeline">')
    expect(panelSource).toContain('<Transition name="sub-agent-status-icon" mode="out-in">')
    expect(panelSource).toContain('.sub-agent-list-move')
    expect(panelSource).toContain('grid-template-rows var(--dur-slow) var(--ease-out)')
    expect(panelSource).toContain('@media (prefers-reduced-motion: reduce)')
    expect(dialogSource).toContain('<Transition name="sub-agent-dialog-status" mode="out-in">')
    expect(dialogSource).toContain('sub-agent-dialog-backdrop-enter var(--dur-base) var(--ease-out)')
    expect(dialogSource).toContain('.core-sub-agent-dialog::backdrop')
    expect(dialogSource).toContain('@media (prefers-reduced-motion: reduce)')
  })

  it('wires the split sub-agent view from both the thread row and the right rail', () => {
    const appSource = readFileSync(resolve(process.cwd(), 'src/app/LamToolsApp.vue'), 'utf8')
    const hostSource = readFileSync(resolve(process.cwd(), 'src/components/RightSidebarHost.vue'), 'utf8')
    const threadSource = readFileSync(resolve(process.cwd(), 'src/components/ChatThread.vue'), 'utf8')
    const shellCss = readFileSync(resolve(process.cwd(), 'src/styles/workspace-shell.css'), 'utf8')
    const paneSource = readFileSync(resolve(process.cwd(), 'src/components/CoreSubAgentPane.vue'), 'utf8')

    // 主线程与右栏都汇到同一条打开路径，壳体只按身份解析运行。
    expect(appSource).toContain('@open-sub-agent="openSubAgentPane"')
    expect(appSource).toContain("'workspace-shell--sub-agent-split': Boolean(openSubAgentRun)")
    expect(appSource).toContain('<CoreSubAgentPane')
    expect(appSource).toContain('findCoreSubAgentRun(selectCoreSubAgentRuns(messages.value), ref)')
    // 续跑过的子代理以监督者记录为准（状态/耗时在消息投影里看不到）。
    expect(appSource).toContain("'sub_agent.list'")
    expect(appSource).toContain(':durable-record=')
    expect(hostSource).toContain("emit('open-sub-agent', run)")
    expect(threadSource).toContain('@open-sub-agent="onOpenSubAgent"')
    // 旧的「定位到源消息并高亮」已由分屏取代。
    expect(appSource).not.toContain('sub-agent-source-highlight')
    // 分屏是整块聊天区的分裂：主区右内缩叠加卡宽，输入栏与正文跟着变窄；
    // 子代理卡是同一层级的第二张卡（固定几何 + 自己的圆角描边）。
    expect(shellCss).toContain('--main-right: calc(var(--main-right-base) + var(--sub-agent-split-extra, 0px))')
    expect(shellCss).toContain('--sub-agent-split-extra: calc(var(--sub-agent-pane-width) + var(--sub-agent-split-gap))')
    expect(paneSource).toContain('position: fixed')
    expect(paneSource).toContain('var(--right-peek')
    expect(paneSource).toContain('<Teleport defer :to="teleportTo">')
  })
})

describe('CoreSubAgentDialog and composer reuse', () => {
  it('renders the selected timeline with embedded composer and forwards controls', async () => {
    const run = fakeRun(1)
    run.timeline = [
      { id: 'sub-task', role: 'user', content: '检查界面', timestamp: '', parts: [] },
      {
        id: 'sub-answer',
        role: 'assistant',
        content: '检查完成。',
        timestamp: '',
        metadata: { timeline: true },
        parts: [{
          id: 'sub-tool',
          partType: 'tool_call',
          status: 'completed',
          content: 'Read component',
          toolName: 'read_file',
          toolArgs: { path: 'CoreSubAgentPanel.vue' },
          toolResult: 'Read component',
        }],
      },
    ]
    const wrapper = mount(CoreSubAgentDialog, {
      props: {
        run,
        transport: testTransport,
        teleportTo: 'body',
        draft: '',
        modelOptions: [
          { value: '', label: 'Current' },
          { value: 'model-2', label: 'Model 2' },
        ],
      },
      global: { stubs: { Teleport: true } },
    })
    await nextTick()
    await nextTick()

    expect(wrapper.get('dialog').attributes('open')).toBeDefined()
    expect(wrapper.text()).toContain('检查界面')
    expect(wrapper.find('.process-card-state-icon--completed').exists()).toBe(true)
    expect(wrapper.text()).toContain('读取 CoreSubAgentPanel.vue')
    expect(wrapper.find('.composer-bar--embedded').exists()).toBe(true)

    await wrapper.get('.composer-bar--embedded textarea').setValue('继续检查')
    await wrapper.get('[data-core-model-thinking-menu] .core-model-thinking-menu__trigger').trigger('click')
    await wrapper.get('[data-model-thinking-section="model"]').trigger('mouseenter')
    await wrapper.findAll('[data-model-thinking-model-option]')[1].trigger('click')
    await wrapper.get('.composer-bar--embedded').trigger('submit')
    await wrapper.get('.core-sub-agent-dialog__close').trigger('click')

    expect(wrapper.emitted('update:draft')?.at(-1)).toEqual(['继续检查'])
    expect(wrapper.emitted('update:selectedModelId')).toEqual([['model-2']])
    expect(wrapper.emitted('submit')).toHaveLength(1)
    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })

  it('restores focus to the workspace tool button when the originating row is hidden', async () => {
    const toolButton = document.createElement('button')
    toolButton.dataset.workspaceRightToggle = ''
    document.body.appendChild(toolButton)
    const hiddenRow = document.createElement('button')
    hiddenRow.style.pointerEvents = 'none'
    document.body.appendChild(hiddenRow)
    hiddenRow.focus()

    const wrapper = mount(CoreSubAgentDialog, {
      props: { run: fakeRun(1), transport: testTransport, open: true, teleportTo: 'body' },
      global: { stubs: { Teleport: true } },
    })
    await nextTick()
    await nextTick()
    await wrapper.setProps({ open: false })
    await nextTick()

    expect(document.activeElement).toBe(toolButton)
    wrapper.unmount()
    hiddenRow.remove()
    toolButton.remove()
  })

  it('keeps WorkspaceShell on the shared ComposerBar implementation', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/components/WorkspaceShell.vue'), 'utf8')
    expect(source).toContain("import ComposerBar from './ComposerBar.vue'")
    expect(source).toContain('<ComposerBar')
  })

  it('supports an embedded ComposerBar without fixed positioning', () => {
    const wrapper = mount(ComposerBar, { props: { modelValue: 'hello', variant: 'embedded' } })
    expect(wrapper.get('form').classes()).toContain('composer-bar--embedded')
    expect(wrapper.get('.composer-root').classes()).toContain('composer-root--embedded')
  })
})

function assistantMessage(id: string, parts: CoreMessage['parts']): CoreMessage {
  return { id, role: 'assistant', content: '', timestamp: '2026-07-18T00:00:00.000Z', parts }
}

function agentPart(options: {
  id: string
  sessionId: string
  name: string
  task: string
  status: MessagePartStatus
  childText?: string
}): NonNullable<CoreMessage['parts']>[number] {
  return {
    id: options.id,
    partType: 'agent_summary',
    status: options.status,
    content: options.status === 'completed' ? '已完成。' : '',
    toolName: 'sub_agent',
    toolArgs: { task: options.task },
    metadata: {
      sub_session_id: options.sessionId,
      agent_name: options.name,
      subLineParts: options.childText ? [{
        id: options.id + '-text',
        partType: 'model_text',
        status: options.status,
        content: options.childText,
      }] : [],
    },
  }
}

function fakeRun(index: number): CoreSubAgentRun {
  return {
    id: 'sub-' + index,
    subSessionId: 'sub-' + index,
    name: 'agent-' + index,
    task: '任务 ' + index,
    status: index === 1 ? 'running' : 'completed',
    modelId: '',
    startedAt: '',
    updatedAt: '',
    timeline: [{ id: 'task-' + index, role: 'user', content: '任务 ' + index, timestamp: '', parts: [] }],
    sourcePartIds: ['part-' + index],
  }
}
