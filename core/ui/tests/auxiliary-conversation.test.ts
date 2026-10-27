import { afterEach, describe, expect, it, vi } from 'vitest'
import { computed, defineComponent, h, ref } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { useSplitWorkspace } from '../src/split/useSplitWorkspace'
import { restoreSplitState } from '../src/split/layout'
import { createAuxiliaryWorkspace } from '../src/auxiliary/workspace'
import { useAuxiliaryChat } from '../src/auxiliary/useAuxiliaryChat'
import { DirectTransport } from '../src/transport/directTransport'
import CoreAuxiliaryChat from '../src/components/CoreAuxiliaryChat.vue'
import { AuxiliaryWorkspaceKey } from '../src/auxiliary/workspace'
import { createWorkbench } from '../src/workbench/createWorkbench'
import type { SplitTab } from '../src/split/layout'
import type { LamToolsTransport } from '../src/transport'

vi.mock('../src/workbench/createWorkbench', () => ({ createWorkbench: vi.fn() }))
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); localStorage.clear(); vi.clearAllMocks() })
const anchor = { document_id: 'm1', block_id: 'body|0', start: 0, end: 5, quote: 'hello', prefix: 'Say ', suffix: ' world', session_id: 'origin' }
function environment() {
  const fork = { close: vi.fn() } as unknown as LamToolsTransport
  const transport = { fork: vi.fn(() => fork), close: vi.fn() } as unknown as LamToolsTransport
  return { transport, modelId: ref('model-a'), models: ref([]), sourceSessionId: ref('origin'), workRoot: ref('E:/project'), projectId: ref('project'), openMain: vi.fn(), jump: vi.fn(), refreshSessions: vi.fn() }
}
function mockWorkbench() {
  const runtime = {
    messages: ref([]), composerText: ref(''), activeSessionId: ref<string | null>(null), turnActive: ref(false),
    createSession: vi.fn(async () => { runtime.activeSessionId.value = 'aux-session'; return { id: 'aux-session' } }),
    selectSession: vi.fn().mockResolvedValue(undefined), close: vi.fn(), stop: vi.fn(),
    actionMode: ref<'send' | 'stop' | 'resume'>('send'), hasMoreHistory: ref(false), processExpandedIds: ref(new Set<string>()), activeTurnId: ref(''), turnState: ref('idle'), toggleProcess: vi.fn(),
    composer: { submit: vi.fn().mockResolvedValue({ status: 'started', ok: true }) },
  }
  vi.mocked(createWorkbench).mockReturnValue(runtime as unknown as ReturnType<typeof createWorkbench>)
  return runtime
}
function chat(tab: SplitTab, env = environment()) {
  let controller!: ReturnType<typeof useAuxiliaryChat>
  const wrapper = mount(defineComponent({ setup() { controller = useAuxiliaryChat(tab, env); return () => h('div') } })); wrappers.push(wrapper)
  return { controller, env }
}
// user:“搭配这个测评，实现”辅助对话”功能”+(独立侧屏聊天保留原文、草稿和来源，不切换或关闭主聊天)。
describe('auxiliary conversation acceptance', () => {
  it('opens and restores a conversation alongside the main area without creating a main tab', async () => {
    let workspace!: ReturnType<typeof createAuxiliaryWorkspace>, split!: ReturnType<typeof useSplitWorkspace>
    const env = environment()
    wrappers.push(mount(defineComponent({ setup() { split = useSplitWorkspace(computed(() => 'aux-test')); workspace = createAuxiliaryWorkspace(split, env); return () => h('div') } })))
    workspace.open({ anchor }); workspace.open({ anchor })
    expect(split.tabs.value).toHaveLength(1)
    expect(split.tabs.value[0].tab.kind).toBe('conversation')
    expect(split.tabs.value[0].tab.context?.anchor?.quote).toBe('hello')
    expect(restoreSplitState(JSON.stringify(split.state)).panes).toEqual(JSON.parse(JSON.stringify(split.state.panes)))
    expect(env.openMain).not.toHaveBeenCalled()
    split.state.focused = 'main'; workspace.open({ anchor })
    expect(split.state.focused).toBeNull()
  })
  it('creates its own session and keeps questions separate from additional information', async () => {
    const runtime = mockWorkbench(), tab: SplitTab = { id: 'aux', kind: 'conversation', title: '辅助对话', resource: '', context: { anchor } }
    const { controller, env } = chat(tab)
    controller.draft.value = '解释这个词'; await controller.send()
    expect(runtime.createSession).toHaveBeenCalledTimes(1)
    expect(tab.resource).toBe('aux-session')
    expect(vi.mocked(createWorkbench).mock.calls[0][0].getTurnOptions?.()).toMatchObject({ auxiliary_additional_information: { selected_text: 'hello' } })
    expect(runtime.composerText.value).toContain('解释这个词')
    expect(controller.draft.value).toBe('')
    controller.draft.value = '还有例子吗'; await controller.send()
    expect(runtime.composerText.value).toBe('还有例子吗')
    expect(runtime.createSession).toHaveBeenCalledTimes(1)
    expect(env.transport.fork).toHaveBeenCalledTimes(1)
    expect(env.openMain).not.toHaveBeenCalled()
  })
  it('retains a failed question and its reference for retry', async () => {
    const runtime = mockWorkbench(); runtime.composer.submit.mockResolvedValueOnce({ status: 'started', ok: false })
    const { controller } = chat({ id: 'retry', kind: 'conversation', title: '辅助对话', resource: '', context: { anchor } })
    controller.draft.value = '为什么'; await controller.send()
    expect(controller.draft.value).toBe('为什么')
    await controller.send()
    expect(runtime.composerText.value).toBe('为什么')
    expect(controller.draft.value).toBe('')
  })
  it('resumes saved history and disconnects only the auxiliary runtime', async () => {
    const runtime = mockWorkbench(), { env } = chat({ id: 'resume', kind: 'conversation', title: '辅助对话', resource: 'saved' })
    await flushPromises()
    expect(runtime.selectSession).toHaveBeenCalledWith('saved')
    wrappers.pop()!.unmount()
    expect(runtime.close).toHaveBeenCalled()
    expect(env.transport.close).not.toHaveBeenCalled()
  })
  it('forks the authenticated transport with a separate connection lifecycle', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response('ok'))
    const primary = new DirectTransport({ apiBase: 'http://localhost:1234', token: 'test-token', fetchImpl })
    const close = vi.spyOn(primary, 'close'), fork = primary.fork()
    expect(fork).not.toBe(primary)
    await fork.request({ kind: 'http', method: 'GET', path: '/sessions' }); await fork.close()
    expect(fetchImpl.mock.calls[0][1].headers.Authorization).toBe('Bearer test-token')
    expect(close).not.toHaveBeenCalled()
  })
  it('does not submit an input-method confirmation or Shift+Enter', async () => {
    const runtime = mockWorkbench(), env = environment()
    const wrapper = mount(CoreAuxiliaryChat, { props: { tab: { id: 'ime', kind: 'conversation', resource: '', title: '辅助对话' }, visible: true }, global: {
      provide: { [AuxiliaryWorkspaceKey as symbol]: { environment: env } },
      stubs: { UiSelect: true, CoreSendStopButton: true, ChatThread: true },
    } }); wrappers.push(wrapper)
    await wrapper.find('textarea').setValue('我的问题')
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter', isComposing: true })
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter', shiftKey: true })
    expect(runtime.createSession).not.toHaveBeenCalled()
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter' }); await flushPromises()
    expect(runtime.createSession).toHaveBeenCalledTimes(1)
  })
  it('stops its own answer without discarding the next drafted question', async () => {
    const runtime = mockWorkbench(), env = environment(); runtime.turnActive.value = true
    const wrapper = mount(CoreAuxiliaryChat, { props: { tab: { id: 'stop', kind: 'conversation', resource: 'saved', title: '辅助对话' }, visible: true }, global: {
      provide: { [AuxiliaryWorkspaceKey as symbol]: { environment: env } },
      stubs: { UiSelect: true, CoreSendStopButton: true, ChatThread: true },
    } }); wrappers.push(wrapper); await flushPromises()
    await wrapper.find('textarea').setValue('下一条问题')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    expect(runtime.stop).toHaveBeenCalledTimes(1)
    expect(wrapper.find('textarea').element.value).toBe('下一条问题')
    expect(env.transport.close).not.toHaveBeenCalled()
  })
  it('cleans up a session creation that finishes after the pane was closed', async () => {
    const runtime = mockWorkbench()
    let complete!: (session: { id: string }) => void
    runtime.createSession.mockImplementationOnce(() => new Promise(resolve => { complete = resolve }))
    const { controller, env } = chat({ id: 'closing', kind: 'conversation', title: '辅助对话', resource: '' })
    controller.draft.value = '保留这个问题'; const pending = controller.send()
    wrappers.pop()!.unmount(); complete({ id: 'late-session' }); await pending
    expect(runtime.composer.submit).not.toHaveBeenCalled()
    expect(runtime.close.mock.calls.length).toBeGreaterThanOrEqual(2)
    expect(env.transport.close).not.toHaveBeenCalled()
    expect(localStorage.getItem('lamtools:auxiliary-draft:closing')).toBe('保留这个问题')
  })
  it('pins its model independently of main chat model changes', () => {
    mockWorkbench()
    const { controller, env } = chat({ id: 'model', kind: 'conversation', title: '辅助对话', resource: '', modelId: 'model-a' })
    env.modelId.value = 'main-model-b'
    expect(controller.modelId.value).toBe('model-a')
    controller.modelId.value = 'aux-model-c'
    expect(createWorkbench).toHaveBeenCalled()
    const options = vi.mocked(createWorkbench).mock.calls[0][0]
    expect(options.getTurnOptions?.()).toMatchObject({ model_id: 'aux-model-c', active_mode: 'consider' })
    expect(env.modelId.value).toBe('main-model-b')
  })
})
