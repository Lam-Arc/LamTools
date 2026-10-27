import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createWorkbench } from '../src/workbench/createWorkbench'
import { useAuxiliaryChat } from '../src/auxiliary/useAuxiliaryChat'
import type { AuxiliaryEnvironment } from '../src/auxiliary/workspace'
import type { SplitTab } from '../src/split/layout'
import type { LamToolsTransport } from '../src/transport'
import CoreAuxiliaryChat from '../src/components/CoreAuxiliaryChat.vue'
import { AuxiliaryWorkspaceKey } from '../src/auxiliary/workspace'
vi.mock('../src/workbench/createWorkbench', () => ({ createWorkbench: vi.fn() }))
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.clearAllMocks(); localStorage.clear() })
function fixture() {
  const runtime = { activeSessionId: ref(''), messages: ref([]), composerText: ref(''), turnActive: ref(false),
    createSession: vi.fn(async () => ({ id: 'aux-id' })), selectSession: vi.fn().mockResolvedValue(undefined),
    composer: { submit: vi.fn().mockResolvedValue({ status: 'started', ok: true }) }, close: vi.fn(), stop: vi.fn() }
  Object.assign(runtime, { actionMode: ref('send'), hasMoreHistory: ref(false), processExpandedIds: ref(new Set()), activeTurnId: ref(''), turnState: ref('idle') })
  vi.mocked(createWorkbench).mockReturnValue(runtime as unknown as ReturnType<typeof createWorkbench>)
  const currentMain = ref<string | null>('main-original')
  const environment: AuxiliaryEnvironment = { transport: { fork: () => ({}) } as LamToolsTransport, modelId: ref('model'), models: ref([]), sourceSessionId: currentMain, workRoot: ref('E:/project'), projectId: ref('project'), openMain: vi.fn(), jump: vi.fn(), refreshSessions: vi.fn() }
  const tab: SplitTab = { id: 'helper', kind: 'conversation', resource: '', title: '辅助对话', sessionId: 'main-original', context: { anchor: { document_id: 'm', block_id: 'body|0', start: 0, end: 5, quote: 'hello', prefix: 'before', suffix: 'after' } } }
  let chat!: ReturnType<typeof useAuxiliaryChat>
  wrappers.push(mount(defineComponent({ setup() { chat = useAuxiliaryChat(tab, environment); return () => h('div') } })))
  return { runtime, currentMain, tab, chat, environment, options: vi.mocked(createWorkbench).mock.calls[0][0] }
}
// user:“选中以一个“附加信息”传入”+(正文只保留用户问题，选文通过独立运行参数送入，并固定关联原主聊天)。
describe('main conversation assistant', () => {
  it('sends selected text as additional information, not as question text', async () => {
    const { chat, runtime, options } = fixture()
    chat.draft.value = 'What is the main task doing?'; await chat.send()
    expect(runtime.composerText.value).toBe('What is the main task doing?')
    expect(options.getTurnOptions?.()).toMatchObject({ active_mode: 'consider', auxiliary_additional_information: { selected_text: 'hello', before: 'before', after: 'after' } })
  })
  it('keeps the source pinned when the main area switches chats', async () => {
    const { chat, runtime, currentMain } = fixture()
    currentMain.value = 'different-main'
    chat.draft.value = 'Continue'; await chat.send()
    expect(runtime.createSession).toHaveBeenCalledWith(expect.objectContaining({ metadata: expect.objectContaining({ ui_surface: 'auxiliary', parent_session_id: 'main-original', runtime_preferences: expect.objectContaining({ base_tier: 'read_only', permission_preset: 'ask' }) }) }))
  })
  it('keeps additional information on later questions without duplicating it in the transcript', async () => {
    const { chat, runtime, options } = fixture()
    chat.draft.value = 'First'; await chat.send()
    chat.draft.value = 'Follow up'; await chat.send()
    expect(runtime.composerText.value).toBe('Follow up')
    expect(options.getTurnOptions?.()).toMatchObject({ auxiliary_additional_information: { selected_text: 'hello' } })
    expect(runtime.createSession).toHaveBeenCalledTimes(1)
  })
  it('shows the read-only role and labels the selected passage as additional information', async () => {
    const { tab, environment } = fixture()
    const wrapper = mount(CoreAuxiliaryChat, { props: { tab, visible: true }, global: { provide: { [AuxiliaryWorkspaceKey as symbol]: { environment } }, stubs: { UiSelect: true, CoreSendStopButton: true, ChatThread: true, MarkdownRenderer: true } } }); wrappers.push(wrapper)
    expect(wrapper.text()).toContain('只读助手')
    expect(wrapper.find('summary').text()).toContain('附加信息')
    expect(environment.openMain).not.toHaveBeenCalled()
    await wrapper.find('.auxiliary-origin button').trigger('click')
    expect(environment.openMain).toHaveBeenCalledWith('main-original')
  })
})
