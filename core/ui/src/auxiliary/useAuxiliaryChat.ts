import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { createWorkbench } from '@/workbench/createWorkbench'
import { auxiliaryReference, auxiliaryAdditionalInformation, type AuxiliaryEnvironment } from './workspace'
import { usePendingAttachments } from '@/composables/usePendingAttachments'
import { coreThinkingModeOptions, coreThinkingPayload, normalizeCoreThinkingMode } from '@/composer/execution'
import { insertReferences, replaceReference, referenceSpans, type ReferenceSelection } from '@/composer/fileReferences'
import { encodeMultipartFile } from '@/composer/upload'
import type { CoreAttachment } from '@/types'
import type { SplitTab } from '@/split/layout'

// user:“实现”辅助对话”功能”+(复用已有会话存储、流式回答与停止能力；每个侧屏独立运行，不借用主区连接)。
export function useAuxiliaryChat(tab: SplitTab, environment: AuxiliaryEnvironment) {
  const error = ref(''), connecting = ref(false), sending = ref(false), draft = ref(''), modelId = ref(tab.modelId || environment.modelId.value)
  const thinkingMode = ref(environment.thinkingMode?.value || 'high')
  const shallowThinking = ref(environment.shallowThinking?.value || false)
  const activeModel = computed(() => environment.executionModels?.value.find(model => model.id === modelId.value))
  const thinkingOptions = computed(() => coreThinkingModeOptions({ model: activeModel.value }))
  watch(thinkingOptions, options => { if (!options.some(option => option.value === thinkingMode.value)) thinkingMode.value = options[0]?.value || 'off' }, { immediate: true })
  const attachments = usePendingAttachments()
  const uploading = ref(false)
  const failedSources = new Map<string, File | { path: string; name: string }>()
  const key = `lamtools:auxiliary-draft:${tab.id}`
  try { draft.value = localStorage.getItem(key) || '' } catch { /* Keep the live draft when storage is unavailable. */ }
  const persist = () => { try { if (draft.value) localStorage.setItem(key, draft.value); else localStorage.removeItem(key) } catch { error.value = '草稿暂时无法备份，请保留此分屏并稍后重试' } }
  watch(draft, persist, { flush: 'sync' })
  watch(modelId, value => { tab.modelId = value })
  const channel = environment.transport.fork?.()
  const runtime = channel ? createWorkbench({
    transport: channel, getWorkRoot: () => tab.root ?? environment.workRoot.value,
    // user:“工具组可以用consider模式（只读）”+(每轮显式声明只读；真实能力上限仍由服务端固定)。
    shallowThinking,
    getTurnOptions: () => ({ model_id: modelId.value, active_mode: 'consider', ...coreThinkingPayload({ mode: normalizeCoreThinkingMode(thinkingMode.value), model: activeModel.value }),
      shallow_thinking_enabled: shallowThinking.value,
      ...(Number(activeModel.value?.context_window || 0) > 0 ? { context_window_tokens: Number(activeModel.value?.context_window) } : {}),
      ...(Number(activeModel.value?.max_output_tokens || 0) > 0 ? { max_tokens: Number(activeModel.value?.max_output_tokens) } : {}),
      auxiliary_additional_information: auxiliaryAdditionalInformation(tab.context) }), onError: message => { error.value = message },
  }) : null
  if (!runtime) error.value = '当前连接不支持独立辅助对话，请重新连接桌面应用'
  let disposed = false
  async function restore() {
    if (!runtime || !tab.resource) return
    connecting.value = true; error.value = ''
    try {
      await runtime.selectSession(tab.resource)
      const prefix = auxiliaryReference(tab.context)
      if (prefix && runtime.messages.value.some(message => message.role === 'user' && message.content.startsWith(prefix))) tab.contextSent = true
    } catch (cause) { if (!disposed) error.value = String(cause) }
    finally { if (disposed) runtime.close(); else connecting.value = false }
  }
  let creating: Promise<void> | null = null
  async function ensureSession() {
    if (!runtime) throw Error('辅助会话连接不可用')
    if (tab.resource) return
    if (creating) return creating
    creating = (async () => {
      if (!tab.resource) {
        if (!tab.context?.anchor && tab.title === '辅助对话' && draft.value.trim()) tab.title = draft.value.trim().replace(/\s+/g, ' ').slice(0, 24)
        const session = await runtime.createSession({ title: tab.title, metadata: { ui_surface: 'auxiliary', parent_session_id: tab.sessionId || '', project_id: tab.projectId, work_root: tab.root ?? environment.workRoot.value, model_id: modelId.value,
          auxiliary_additional_information: auxiliaryAdditionalInformation(tab.context),
          runtime_preferences: { base_tier: 'read_only', permission_preset: 'ask', base_allow_access_outside_workdir: false },
        } })
        if (!session) throw Error('未能创建辅助对话，请重试')
        tab.resource = session.id
        if (typeof session.metadata?.work_root === 'string') tab.root = session.metadata.work_root
        if (typeof session.metadata?.project_id === 'string') tab.projectId = session.metadata.project_id
        void Promise.resolve(environment.refreshSessions()).catch(() => {})
      }
    })()
    try { await creating } finally { creating = null }
  }
  // user:“包括附件上传、模型与思考等级，只是模式强制设为consider”+(附件进入本侧屏会话，复用主聊天的处理状态、引用和上传编码)。
  watch(attachments.attachmentInputItems, items => { if (runtime) runtime.attachments.value = items }, { flush: 'sync' })
  watch(draft, text => {
    const paths = new Set(referenceSpans(text).map(span => span.path))
    attachments.pendingAttachments.value.forEach(item => { if (item.path && !paths.has(item.path.replace(/\\/g, '/'))) { attachments.removeAttachment(item.id); failedSources.delete(item.path) } })
  })
  async function uploadFiles(files: ArrayLike<File | { path: string; name: string }>, selection: ReferenceSelection | null = null) {
    if (!runtime || uploading.value || connecting.value || disposed) return
    uploading.value = true; error.value = ''
    try {
      await ensureSession()
      if (disposed) return
      if (!environment.request) throw Error('附件上传连接不可用')
      const slots = Array.from(files).map(file => ({ file, id: `processing:${crypto.randomUUID()}`, path: `pending://${crypto.randomUUID()}/${file.name}` }))
      draft.value = insertReferences(draft.value, slots.map(slot => slot.path), selection).text
      slots.forEach(slot => attachments.addProcessing(slot.id, slot.file.name, slot.path))
      for (const slot of slots) {
        try {
          const native = (slot.file as { path?: string }).path
          const multipart = native ? null : await encodeMultipartFile(slot.file as File)
          const query = tab.projectId ? `?project_id=${encodeURIComponent(tab.projectId)}` : ''
          const response = await environment.request({ kind: 'http', method: 'POST', path: `/sessions/${encodeURIComponent(tab.resource)}/attachments${native ? '/reference' : ''}${query}`,
            headers: { 'Content-Type': native ? 'application/json' : multipart!.contentType }, body: native ? new TextEncoder().encode(JSON.stringify({ path: native })) : multipart!.body })
          if (response.status < 200 || response.status >= 300) throw Error(new TextDecoder().decode(response.body) || '附件上传失败')
          const result = JSON.parse(new TextDecoder().decode(response.body)) as CoreAttachment
          if (!result.path) throw Error('附件未返回文件路径')
          if (disposed) return
          const updated = replaceReference(draft.value, slot.path, result.path)
          draft.value = updated.text
          attachments.removeAttachment(slot.id)
          if (updated.replaced) attachments.addUploaded(result)
        } catch (cause) {
          if (disposed) return
          if (referenceSpans(draft.value).some(span => span.path === slot.path)) {
            failedSources.set(slot.path, slot.file)
            attachments.markFailed(slot.id, slot.file.name, String(cause))
            error.value = `附件处理失败：${slot.file.name}，点击引用重试或删除后发送`
          }
        }
      }
    } catch (cause) { if (!disposed) error.value = String(cause) }
    finally { uploading.value = false; if (disposed) runtime.close() }
  }
  async function retryFile(path: string) {
    const source = failedSources.get(path), span = referenceSpans(draft.value).find(item => item.path === path)
    if (!source || !span) return
    await uploadFiles([source], { start: span.from, end: span.to })
  }
  async function chooseAttachments(selection: ReferenceSelection | null = null) {
    try {
      const picker = environment.files
      if (!picker) throw Error('当前环境不支持附件选择')
      const paths = await picker.pickPaths?.()
      if (picker.pickPaths) { if (paths?.length) await uploadFiles(paths.map(path => ({ path, name: path.split(/[\\/]/).pop() || path })), selection) }
      else { const files = await picker.pick({ multiple: true }); if (files?.length) await uploadFiles(files, selection) }
    } catch (cause) { error.value = String(cause) }
  }
  async function send() {
    if (!runtime || sending.value || connecting.value || (!draft.value.trim() && runtime.actionMode?.value !== 'resume') || uploading.value || attachments.hasBlockingFailure.value || runtime.turnActive.value) return
    sending.value = true; error.value = ''
    const question = draft.value.trim()
    try {
      await ensureSession()
      if (disposed) return
      runtime.composerText.value = question
      const resuming = runtime.actionMode?.value === 'resume'
      const result = await runtime.composer.submit({ clearComposer: true })
      const accepted = (resuming && !error.value && !runtime.composerText.value) || (result && (result.status === 'guided' || result.status === 'queued' || ((result.status === 'started' || result.status === 'command') && result.ok)))
      if (accepted) { attachments.clearAttachments(); tab.contextSent = true; if (draft.value.trim() === question) draft.value = '' }
      else if (!error.value) error.value = '未能发送，问题和原文已保留，可重试'
    } catch (cause) { if (!disposed) error.value = String(cause) }
    finally { if (disposed) runtime.close(); else sending.value = false }
  }
  const messages = computed(() => {
    const prefix = auxiliaryReference(tab.context)
    return (runtime?.messages.value || []).map(message => message.role === 'user' && prefix && message.content.startsWith(prefix)
      ? { ...message, metadata: { ...message.metadata, auxiliary_reference_prefix: prefix } } : message)
  })
  async function stop() { try { await runtime?.stop() } catch (cause) { error.value = String(cause) } }
  onMounted(restore)
  onBeforeUnmount(() => { disposed = true; persist(); runtime?.close(); if (!runtime) void channel?.close() })
  return { runtime, messages, draft, modelId, thinkingMode, thinkingOptions, shallowThinking, pendingAttachments: attachments.pendingAttachments, hasBlockingFailure: attachments.hasBlockingFailure, uploading, uploadFiles, retryFile, chooseAttachments, error, connecting, sending, send, stop, restore }
}
