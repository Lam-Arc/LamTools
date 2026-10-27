import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import CoreAuxiliaryChat from '../src/components/CoreAuxiliaryChat.vue'
import { AuxiliaryWorkspaceKey, createAuxiliaryWorkspace } from '../src/auxiliary/workspace'
import ComposerBar from '../src/components/ComposerBar.vue'
import CoreExecutionControls from '../src/components/CoreExecutionControls.vue'
import AttachmentSourceMenu from '../src/components/AttachmentSourceMenu.vue'
import InlineFileComposer from '../src/components/InlineFileComposer.vue'
import { createWorkbench } from '../src/workbench/createWorkbench'
import { useAuxiliaryChat } from '../src/auxiliary/useAuxiliaryChat'
import type { AuxiliaryEnvironment } from '../src/auxiliary/workspace'
import type { SplitTab } from '../src/split/layout'
import type { SplitWorkspaceController } from '../src/split/useSplitWorkspace'
vi.mock('../src/workbench/createWorkbench', () => ({ createWorkbench: vi.fn() }))
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.clearAllMocks(); localStorage.clear() })
// user:“无法输入文字，会点到‘给sunday发送任务’这个提示”+(空提示必须把焦点交给真正的编辑区，分屏不能改变可编辑性)。
it('focuses the editor when its empty hint is pressed after a split resize', async () => {
  const wrapper = mount(InlineFileComposer, { attachTo: document.body, props: { modelValue: '', placeholder: '给 Sunday 发送任务...' } }); wrappers.push(wrapper)
  wrapper.element.style.width = '260px'
  await wrapper.get('.cm-placeholder').trigger('pointerdown')
  expect(document.activeElement).toBe(wrapper.get('[role=textbox]').element)
  expect(wrapper.get('[role=textbox]').attributes('contenteditable')).toBe('true')
  await wrapper.setProps({ modelValue: '中文输入' })
  expect(wrapper.get('[role=textbox]').text()).toContain('中文输入')
  await wrapper.setProps({ modelValue: '', disabled: true })
  ;(document.activeElement as HTMLElement).blur()
  await wrapper.get('.cm-placeholder').trigger('pointerdown')
  expect(document.activeElement).not.toBe(wrapper.get('[role=textbox]').element)
})
it('uses the ordinary composer, editor, attachment entry and execution controls', () => {
  const source = readFileSync('src/components/CoreAuxiliaryChat.vue', 'utf8')
  for (const component of ['ComposerBar', 'InlineFileComposer', 'CoreExecutionControls', 'AttachmentSourceMenu']) expect(source).toContain(`<${component}`)
  expect(source).not.toContain('<textarea')
  expect(source).toContain(':show-runtime-menu="false"')
})
it('restricts split geometry to floating composers so embedded assistants stay in their pane', () => {
  const css = readFileSync('src/styles/split-workspace.css', 'utf8')
  expect(css).not.toMatch(/\.workspace-shell--split \.composer-root\s*\{/)
  expect(css).not.toMatch(/\.workspace-shell--split \.composer-root \.floating-composer\s*\{/)
})
function fixture() {
  const runtime = { actionMode: ref('send'), hasMoreHistory: ref(false), attachments: ref([]), messages: ref([]), composerText: ref(''), turnActive: ref(false), createSession: vi.fn(async () => ({ id: 'aux', metadata: { work_root: 'E:/source', project_id: 'source' } })), composer: { submit: vi.fn(async (): Promise<{ status: string; ok: boolean } | null> => ({ status: 'started', ok: true })) }, selectSession: vi.fn(), close: vi.fn() }
  vi.mocked(createWorkbench).mockReturnValue(runtime as unknown as ReturnType<typeof createWorkbench>)
  const request = vi.fn(async (_request: { path: string }) => ({ status: 200, body: new TextEncoder().encode(JSON.stringify({ id: 'a', filename: 'a.txt', path: 'E:/source/a.txt', mime_type: 'text/plain', size: 2, preview_type: 'text' })) }))
  const environment = { transport: { fork: () => ({}) }, modelId: ref('model'), models: ref([]), executionModels: ref([{ id: 'model', thinking_supported: true, reasoning_levels: ['high', 'max'] }]), workRoot: ref('E:/other'), projectId: ref('other'), request, refreshSessions: vi.fn() } as unknown as AuxiliaryEnvironment
  const tab: SplitTab = { id: 'test', kind: 'conversation', resource: '', title: '辅助对话', sessionId: 'parent' }
  let chat!: ReturnType<typeof useAuxiliaryChat>
  wrappers.push(mount(defineComponent({ setup() { chat = useAuxiliaryChat(tab, environment); return () => h('div') } })))
  return { chat, runtime, request, tab, environment }
}
it('passes independent reasoning and uploaded attachments through the auxiliary runtime, keeping consider fixed', async () => {
  const { chat, runtime, request } = fixture()
  chat.thinkingMode.value = 'max'
  chat.shallowThinking.value = true
  await chat.uploadFiles([{ path: 'E:/source/a.txt', name: 'a.txt' }])
  expect(request.mock.calls[0][0].path).toContain('project_id=source')
  expect(runtime.attachments.value).toMatchObject([{ attachment_id: 'a' }])
  expect(chat.draft.value).toContain('@"E:/source/a.txt"')
  await chat.send()
  expect(vi.mocked(createWorkbench).mock.calls[0][0].getTurnOptions?.()).toMatchObject({ active_mode: 'consider', reasoning_level: 'max', shallow_thinking_enabled: true })
  expect(runtime.composer.submit).toHaveBeenCalledTimes(1)
})

it('blocks a failed upload, retries its existing reference, and retains the draft when sending fails', async () => {
  const { chat, runtime, request } = fixture()
  request.mockResolvedValueOnce({ status: 500, body: new TextEncoder().encode('failed') })
  await chat.uploadFiles([{ path: 'E:/source/a.txt', name: 'a.txt' }])
  expect(chat.hasBlockingFailure.value).toBe(true)
  await chat.send()
  expect(runtime.composer.submit).not.toHaveBeenCalled()
  const failedPath = chat.pendingAttachments.value[0].path!
  await chat.retryFile(failedPath)
  expect(chat.hasBlockingFailure.value).toBe(false)
  expect(chat.draft.value.match(/@/g)).toHaveLength(1)
  runtime.composer.submit.mockResolvedValueOnce({ status: 'started', ok: false })
  await chat.send()
  expect(chat.draft.value).toContain('E:/source/a.txt')
  expect(chat.pendingAttachments.value).toHaveLength(1)
})
it('mounts shared controls and sends once with Enter while preserving IME confirmation', async () => {
  const { runtime, tab, environment } = fixture()
  const wrapper = mount(CoreAuxiliaryChat, { attachTo: document.body, props: { tab, visible: true }, global: { provide: { [AuxiliaryWorkspaceKey as symbol]: { environment } }, stubs: { ChatThread: true, MarkdownRenderer: true, ReferenceItems: true } } }); wrappers.push(wrapper)
  expect(wrapper.findComponent(ComposerBar).props('variant')).toBe('embedded')
  expect(wrapper.findComponent(CoreExecutionControls).props('showRuntimeMenu')).toBe(false)
  expect(wrapper.findComponent(AttachmentSourceMenu).exists()).toBe(true)
  const editor = wrapper.findComponent(InlineFileComposer)
  editor.vm.$emit('update:modelValue', '中文问题')
  editor.vm.$emit('keydown', new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, cancelable: true }))
  await flushPromises()
  expect(runtime.composer.submit).not.toHaveBeenCalled()
  editor.vm.$emit('keydown', new KeyboardEvent('keydown', { key: 'Enter', cancelable: true }))
  await flushPromises()
  expect(runtime.composer.submit).toHaveBeenCalledTimes(1)
  expect(runtime.composerText.value).toBe('中文问题')
})
it('routes native and overlay drops to the active auxiliary tab, and releases closed targets', () => {
  const { environment } = fixture()
  const state = { activePane: 'right', hidden: false, panes: { right: { activeTab: 'helper' } } }
  const workspace = createAuxiliaryWorkspace({ state } as unknown as SplitWorkspaceController, environment)
  const upload = vi.fn(), files = [{ path: 'E:/a.txt', name: 'a.txt' }]
  const unregister = workspace.registerAttachmentTarget('helper', upload)
  expect(workspace.routeAttachmentDrop(files)).toBe(true)
  expect(upload).toHaveBeenCalledExactlyOnceWith(files)
  state.activePane = 'main'
  expect(workspace.routeAttachmentDrop(files)).toBe(false)
  state.activePane = 'right'; state.hidden = true
  expect(workspace.routeAttachmentDrop(files)).toBe(false)
  state.hidden = false; unregister()
  expect(workspace.routeAttachmentDrop(files)).toBe(false)
})

it('continues a paused auxiliary turn through the shared composer without reporting a false send failure', async () => {
  const { chat, runtime, tab } = fixture()
  tab.resource = 'aux-existing'; runtime.actionMode.value = 'resume'
  chat.draft.value = '继续时补充说明'
  runtime.composer.submit.mockImplementationOnce(async () => { runtime.composerText.value = ''; return null })
  await chat.send()
  expect(chat.error.value).toBe('')
  expect(chat.draft.value).toBe('')
  expect(runtime.createSession).not.toHaveBeenCalled()
})
