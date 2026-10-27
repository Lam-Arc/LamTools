<script setup lang="ts">
import { computed, onBeforeUnmount, provide, ref } from 'vue'
import { SplitKeyboardScopeKey } from '@/split/keyboardScope'
import CoreAppPage from './CoreAppPage.vue'
import CoreAuxiliaryChat from './CoreAuxiliaryChat.vue'
import CoreSplitBrowser from './CoreSplitBrowser.vue'
import CoreSplitTextEditor from './CoreSplitTextEditor.vue'
import CoreSplitFileTree from './CoreSplitFileTree.vue'
import CoreSplitPluginPage from './CoreSplitPluginPage.vue'
import { contributionState, contributionsRpc, ensureContributions } from '@/plugins/contributions'
import { findPluginFilePage } from '@/plugins/pages'
import CoreSubAgentView from './CoreSubAgentView.vue'
import type { SplitTab } from '@/split/layout'
import { useSplitAgent } from '@/split/useSplitAgent'
import type { CoreSubAgentDurableRecord, CoreMessage } from '@/types'
import type { LamToolsTransport } from '@/transport'
import type { SplitWorkspaceController } from '@/split/useSplitWorkspace'
import type { createSplitDocuments } from '@/split/documents'
const props = defineProps<{
  tab: SplitTab; pane: string; visible: boolean; controller: SplitWorkspaceController; documents: ReturnType<typeof createSplitDocuments>
  bindings: Record<string, Record<string, any>>; workRoot: string; transport: LamToolsTransport; messages: CoreMessage[]; activeSessionId: string
  memberStatuses: Record<string, string>; memberStatusRecords: Record<string, CoreSubAgentDurableRecord>; durableRecords: Record<string, CoreSubAgentDurableRecord>
  memberWaitKnown: boolean; runningMemberNames: string[]; mainRunning: boolean
}>()
const emit = defineEmits<{ dirty: [id: string, value: boolean]; 'decision-select': [payload: any] }>()
provide(SplitKeyboardScopeKey, computed(() => props.visible && props.controller.state.activePane === props.pane))
const root = props.tab.root || props.workRoot
const pluginRpc = computed(() => props.bindings.plugins?.requestRpc || contributionsRpc())
const localBindings = computed(() => ({ ...props.bindings, [props.tab.resource]: { ...props.bindings[props.tab.resource], ...(props.tab.projectId ? { projectId: props.tab.projectId } : {}), workRoot: root } }))
const pageRef = ref<InstanceType<typeof CoreAppPage> | null>(null)
const { run, current: currentAgent, error: agentError, refresh: refreshAgent } = useSplitAgent(props)
const unregister = props.controller.registerGuard(props.tab.id, proceed => { if (pageRef.value) pageRef.value.requestNavigation(proceed); else proceed() })
onBeforeUnmount(unregister)
async function openFile(path: string, bound?: {workRoot: string; projectId?: string; sessionId?: string}) {
  // user:“该修就修，不用停下”+(启动时先完成插件目录加载，再决定文件使用哪个页面)。
  if (!contributionState().loaded && pluginRpc.value) await ensureContributions(pluginRpc.value)
  const target = props.controller.tabs.value.find(({ tab }) => tab.kind === 'editor')?.pane
  const pane = target || props.controller.split(props.pane, 'right') || props.pane
  // user:“该修就修，不用停下”+(已声明的画图文件交给插件页面，其他文件继续使用文本编辑器)。
  const pluginPage = findPluginFilePage(contributionState().pages, path)
  const fileRoot = bound?.workRoot || root
  if (pluginPage) props.controller.openPluginPage(pluginPage, pane, {workRoot:fileRoot, projectId:bound?.projectId ?? props.tab.projectId, sessionId:bound?.sessionId ?? props.tab.sessionId, filePath:path})
  else props.controller.add('editor', path, path.split(/[\\/]/).pop() || path, pane, bound?.sessionId, fileRoot, bound?.projectId ?? props.tab.projectId)
}
function openPluginPage(target: { plugin: string; id: string }) {
  const page = contributionState().pages.find(page => page.plugin === target.plugin && page.id === target.id)
  // user:“支持一下”+(插件内页面跳转沿用来源标签绑定的项目)。
  if (page) props.controller.openPluginPage(page, props.pane, { workRoot: root, projectId: props.tab.projectId, sessionId: props.tab.sessionId })
}
</script>
<template>
  <CoreAppPage v-if="tab.kind === 'page'" ref="pageRef" :page="tab.resource" :bindings="localBindings" auxiliary @close="controller.closeTab(pane, tab)" />
  <CoreSplitBrowser v-else-if="tab.kind === 'browser'" :tab="tab" :visible="visible" />
  <CoreAuxiliaryChat v-else-if="tab.kind === 'conversation'" :tab="tab" :visible="visible" />
  <CoreSplitTextEditor v-else-if="tab.kind === 'editor'" :tab="tab" :root="root" :controller="controller" :documents="documents" @dirty="(id, value) => emit('dirty', id, value)" />
  <CoreSplitFileTree v-else-if="tab.kind === 'files'" :root="tab.resource || root" @open="openFile" />
  <template v-else-if="tab.kind === 'plugin'">
    <CoreSplitPluginPage v-if="pluginRpc" :tab="tab" :work-root="root" :visible="visible" :request-rpc="pluginRpc" @open-page="openPluginPage" @open-file="openFile" />
    <div v-else class="split-empty">{{ '正在连接插件页面…' }}</div>
  </template>
  <template v-else-if="tab.kind === 'agent'">
    <p v-if="!currentAgent" class="split-content-notice">来自其他聊天 · {{ tab.title }} · 提问与审批请回到来源聊天处理</p>
    <p v-if="agentError && !currentAgent" class="split-content-error" role="alert">{{ agentError }} <button class="split-text-button" @click="refreshAgent">重试</button></p>
    <CoreSubAgentView v-if="run" :run="run" :transport="transport" :durable-record="currentAgent ? durableRecords[run.name.toLowerCase()] : null" :member-wait-known="currentAgent && memberWaitKnown" :running-member-names="currentAgent ? runningMemberNames : []" :main-running="currentAgent && mainRunning" :member-statuses="currentAgent ? memberStatuses : {}" :member-status-records="currentAgent ? memberStatusRecords : {}" :decisions-disabled="!currentAgent" @decision-select="emit('decision-select', $event)" />
    <div v-else class="split-empty"><span>子代理过程暂不可用</span><small>回到来源聊天后可继续查看</small></div>
  </template>
</template>
