<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowDown, ArrowUpRight, ChevronDown, MessageCircle, Quote, RotateCw } from 'lucide-vue-next'
import ChatThread from './ChatThread.vue'
import MarkdownRenderer from './MarkdownRenderer.vue'
import CoreSendStopButton from './CoreSendStopButton.vue'
import ComposerBar from './ComposerBar.vue'
import InlineFileComposer, { type ComposerEditorHandle } from './InlineFileComposer.vue'
import CoreExecutionControls from './CoreExecutionControls.vue'
import AttachmentSourceMenu from './AttachmentSourceMenu.vue'
import ReferenceItems from './ReferenceItems.vue'
import type { ReferenceSelection } from '@/composer/fileReferences'
import type { CoreModelCatalogView } from '@/composer/execution'
import { useAuxiliaryWorkspace } from '@/auxiliary/workspace'
import { useAuxiliaryChat } from '@/auxiliary/useAuxiliaryChat'
import { useSplitKeyboardScope } from '@/split/keyboardScope'
import type { SplitTab } from '@/split/layout'
import '@/styles/auxiliary-chat.css'
const props = defineProps<{ tab: SplitTab; visible: boolean }>()
const workspace = useAuxiliaryWorkspace()
if (!workspace) throw Error('辅助对话工作区不可用')
const environment = workspace.environment
const { runtime, messages, draft, modelId, thinkingMode, thinkingOptions, shallowThinking, pendingAttachments, hasBlockingFailure, uploading, uploadFiles, retryFile, chooseAttachments, error, connecting, sending, send, stop, restore } = useAuxiliaryChat(props.tab, environment)
const unregisterAttachments = workspace.registerAttachmentTarget?.(props.tab.id, files => { void uploadFiles(files) })
onBeforeUnmount(() => unregisterAttachments?.())
const input = ref<ComposerEditorHandle | null>(null), scroller = ref<HTMLElement | null>(null), atBottom = ref(true)
const keyboardActive = useSplitKeyboardScope()
const preview = ref<InstanceType<typeof ReferenceItems> | null>(null)
const catalogView = ref<CoreModelCatalogView>('provider')
const modelOptions = computed(() => environment.modelOptionsForView?.(catalogView.value) || environment.models.value)
let attachmentSelection: ReferenceSelection | null = null
function rememberSelection() { const editor = input.value; attachmentSelection = editor?.hasFocus() ? { start: editor.selectionStart, end: editor.selectionEnd } : null }
async function attach() { const selection = attachmentSelection; attachmentSelection = null; await chooseAttachments(selection); input.value?.focus() }
function drop(event: DragEvent) { if (event.dataTransfer?.files.length) void uploadFiles(event.dataTransfer.files) }
function paste(event: ClipboardEvent) { if (event.clipboardData?.files.length) { event.preventDefault(); rememberSelection(); void uploadFiles(event.clipboardData.files, attachmentSelection) } }
const running = computed(() => runtime?.turnActive.value || false)
const anchor = computed(() => props.tab.context?.anchor)
const mode = computed(() => running.value ? 'stop' : runtime?.actionMode.value || 'send')
function scrollState() { const el = scroller.value; if (el) atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 48 }
function bottom() { const el = scroller.value; if (el) el.scrollTop = el.scrollHeight; atBottom.value = true }
async function jumpSource() { try { if (anchor.value) await environment.jump(anchor.value) } catch (cause) { error.value = String(cause) } }
async function openMain() { try { await environment.openMain(props.tab.resource) } catch (cause) { error.value = String(cause) } }
async function openSource() { try { if (props.tab.sessionId) await environment.openMain(props.tab.sessionId) } catch (cause) { error.value = String(cause) } }
async function decision(payload: Parameters<NonNullable<typeof runtime>['approval']['handleDecision']>[0]) {
  if (!runtime) return
  await runtime.approval.handleDecision(payload)
  if (runtime.approval.lastError.value) error.value = runtime.approval.lastError.value
}
async function submit() {
  if (running.value) await stop()
  else if (uploading.value || hasBlockingFailure.value) return
  else await send()
}
function key(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    if (!running.value && !sending.value) void submit()
  }
}
watch(() => [messages.value.length, messages.value.at(-1)?.content, messages.value.at(-1)?.parts?.length], () => {
  if (atBottom.value) void nextTick(bottom)
})
watch(() => props.visible, visible => { if (visible && keyboardActive()) void nextTick(() => input.value?.focus({ preventScroll: true })) })
onMounted(() => { if (props.visible && keyboardActive()) input.value?.focus({ preventScroll: true }) })
</script>
<template>
  <!-- user:“价值一致就行，不必逐项功能对齐”+(用一套独立对话承接追问，工具栏保留原文与打开主区，输入使用主聊天的组件)。 -->
  <div class="auxiliary-chat" :data-source-session-id="tab.resource || undefined">
    <header class="split-content-toolbar auxiliary-toolbar">
      <span class="auxiliary-caption">主聊天助手</span>
      <button v-if="tab.resource" class="split-icon-button" type="button" title="在主区打开此对话" aria-label="在主区打开此对话" @click="openMain"><ArrowUpRight :size="14" /></button>
    </header>
    <div class="auxiliary-origin"><button v-if="tab.sessionId" class="split-text-button" type="button" title="每次提问时读取此来源聊天的最新上下文" @click="openSource">来源主聊天 ↗</button><span v-else>独立对话</span><span title="consider 模式：仅可读取与分析">只读助手</span></div>
    <details v-if="anchor" class="auxiliary-reference">
      <summary title="展开附加信息和已有结果"><Quote :size="13" aria-hidden="true" /><span>{{ anchor.quote }}</span><span class="auxiliary-reference-label">附加信息</span><ChevronDown class="auxiliary-reference-chevron" :size="12" aria-hidden="true" /></summary>
      <blockquote>{{ anchor.quote }}</blockquote>
      <div v-if="tab.context?.mark" class="auxiliary-previous">
        <MarkdownRenderer v-if="tab.context.mark.explain" :content="tab.context.mark.explain" :mermaid="false" />
        <MarkdownRenderer v-if="tab.context.mark.translate" :content="tab.context.mark.translate" :mermaid="false" />
        <template v-for="(turn, index) in tab.context.mark.thread" :key="index"><p v-if="turn.role === 'user'">{{ turn.content }}</p><MarkdownRenderer v-else :content="turn.content" :mermaid="false" /></template>
      </div>
      <button class="split-text-button" type="button" @click="jumpSource">回到原文</button>
    </details>
    <p v-if="connecting" class="split-content-notice" role="status">正在恢复对话…</p>
    <p v-if="error" class="split-content-error" role="alert">{{ error }} <button v-if="tab.resource && !connecting" class="split-icon-button" aria-label="重新连接辅助对话" type="button" @click="restore"><RotateCw :size="13" /></button></p>
    <div class="auxiliary-scroll-area">
    <div ref="scroller" class="auxiliary-transcript" @scroll.passive="scrollState">
      <button v-if="runtime?.hasMoreHistory.value" type="button" class="split-text-button" @click="runtime.loadMoreHistory">查看更早消息</button>
      <ChatThread v-if="runtime && messages.length" :messages="messages" :transport="environment.transport" :work-root="tab.root" :project-id="tab.projectId" :process-expanded-ids="runtime.processExpandedIds.value" :active-turn-id="runtime.activeTurnId.value" :turn-active="running" :turn-status="runtime.turnState.value" :sub-agent-rows-inert="true" @toggle-process="runtime.toggleProcess" @decision-select="decision" />
      <div v-else-if="!connecting" class="auxiliary-empty"><MessageCircle :size="24" :stroke-width="1.3" /><span>{{ tab.sessionId ? '围绕主聊天，继续讨论' : '在这里，展开另一个想法' }}</span><small>{{ anchor ? '选文作为附加信息，结合聊天上下文回答' : '可阅读上下文与项目内容，主聊天可以继续' }}</small></div>
      <p v-if="sending || running" class="split-content-notice" role="status">{{ sending ? '正在发送…' : '正在回答…' }}</p>
    </div>
    <button v-if="!atBottom" class="auxiliary-latest split-text-button" type="button" @click="bottom"><ArrowDown :size="12" /> 回到最新</button>
    </div>
    <!-- user:“辅助会话的输入栏样式与正常版一样就行”+(复用主聊天编辑器、输入卡、附件入口与模型思考菜单，模式固定为 consider)。 -->
    <ComposerBar v-model="draft" class="auxiliary-composer" variant="embedded" :action-mode="mode" :disabled="!runtime || connecting" @submit="submit" @drop="drop">
      <template #textarea>
        <InlineFileComposer ref="input" v-model="draft" :attachments="pendingAttachments" :disabled="!runtime || connecting" placeholder="给 Sunday 发送任务..." @keydown="key" @paste="paste" @retry-file="retryFile" @preview-file="preview?.previewPath($event)" />
        <ReferenceItems ref="preview" preview-only :attachments="pendingAttachments" :transport="environment.transport" :project-id="tab.projectId" :work-root="tab.root" />
      </template>
      <template #tools>
        <CoreExecutionControls v-model="modelId" v-model:thinking-mode="thinkingMode" v-model:shallow-thinking-enabled="shallowThinking" v-model:catalog-view="catalogView" :model-options="modelOptions" :thinking-mode-options="thinkingOptions" :show-runtime-menu="false" :disabled="sending || connecting">
          <template #leading><AttachmentSourceMenu :disabled="!runtime || connecting || uploading || !environment.files" @pointerdown.capture="rememberSelection" @select="attach" /></template>
          <template #after-runtime><span class="auxiliary-consider" title="固定为只读模式">consider</span></template>
        </CoreExecutionControls>
      </template>
      <template #action><CoreSendStopButton :action-mode="mode" :disabled="!runtime || sending || connecting || (mode !== 'stop' && (uploading || hasBlockingFailure || (mode === 'send' && !draft.trim())))" :hold-enabled="false" /></template>
    </ComposerBar>
  </div>
</template>
