<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, provide, ref, watch } from 'vue'
import { SplitKeyboardScopeKey } from '@/split/keyboardScope'
import CoreAppPage from './CoreAppPage.vue'
import CoreAuxiliaryChat from './CoreAuxiliaryChat.vue'
import CoreSplitBrowser from './CoreSplitBrowser.vue'
import CoreSplitTextEditor from './CoreSplitTextEditor.vue'
import CoreSplitPreview from './CoreSplitPreview.vue'
import CoreSplitFileTree from './CoreSplitFileTree.vue'
import CoreSplitPluginPage from './CoreSplitPluginPage.vue'
import { contributionState, contributionsRpc, ensureContributions } from '@/plugins/contributions'
import { findPluginFilePage } from '@/plugins/pages'
import CoreSubAgentView from './CoreSubAgentView.vue'
import type { SplitTab } from '@/workspace/types'
import { useSplitAgent } from '@/split/useSplitAgent'
import { selectCoreSubAgentRuns, type CoreSubAgentRef } from '@/agents/subAgentProjection'
import type { CoreSubAgentDurableRecord, CoreMessage } from '@/types'
import type { LamToolsTransport } from '@/transport'
import type { WorkspaceController } from '@/workspace/types'
import { openFileInSplit, openFileWithDefaultApp } from '@/split/openFile'
import type { createSplitDocuments } from '@/split/documents'
const props = defineProps<{
  tab: SplitTab; pane: string; visible: boolean; controller: WorkspaceController; documents: ReturnType<typeof createSplitDocuments>
  bindings: Record<string, Record<string, any>>; workRoot: string; transport: LamToolsTransport; messages: CoreMessage[]; activeSessionId: string
  memberStatuses: Record<string, string>; memberStatusRecords: Record<string, CoreSubAgentDurableRecord>; durableRecords: Record<string, CoreSubAgentDurableRecord>
  memberWaitKnown: boolean; runningMemberNames: string[]; mainRunning: boolean
}>()
const emit = defineEmits<{
  dirty: [id: string, value: boolean]
  'decision-select': [payload: any]
  /** user:“页眉同时作为下拉框，可切换到别的子代理”+(由宿主在同一个分屏里切标签/补标签)。 */
  'open-sub-agent': [payload: { ref: CoreSubAgentRef; pane: string }]
}>()
provide(SplitKeyboardScopeKey, computed(() => props.visible && props.controller.state.activePane === props.pane))
const root = props.tab.root || props.workRoot
const pluginRpc = computed(() => props.bindings.plugins?.requestRpc || contributionsRpc())
const localBindings = computed(() => ({
  ...props.bindings,
  [props.tab.resource]: {
    ...props.bindings[props.tab.resource],
    ...(props.tab.projectId ? { projectId: props.tab.projectId } : {}),
    workRoot: root,
    // user:“把库和easy file统合到一起”+(分屏资料库的文件从当前分屏旁打开，沿用该标签绑定的项目)。
    ...(props.tab.resource === 'library' ? { openProjectFile: openFile } : {}),
  },
}))
const pageRef = ref<InstanceType<typeof CoreAppPage> | null>(null)
const { run, current: currentAgent, error: agentError, refresh: refreshAgent } = useSplitAgent(props)
// user:“页眉显示子代理名…”+(字符串入口先开标签时还不知道名字：run 解析出来后补齐标题/资源)。
watch(
  () => [run.value?.name, run.value?.subSessionId, run.value?.id] as const,
  ([name, subSessionId, id]) => {
    if (props.tab.kind !== 'agent') return
    // 先让渲染完成再写回布局：setup 阶段直接 commit 会在父组件渲染中改状态。
    void nextTick(() => {
      const patch: Partial<Pick<SplitTab, 'title' | 'resource'>> = {}
      if (name && props.tab.title !== name) patch.title = name
      const resource = String(subSessionId || id || '')
      if (resource && !props.tab.resource) patch.resource = resource
      if (Object.keys(patch).length) props.controller.updateTabMetadata(props.tab.id, patch)
    })
  },
  { immediate: true },
)
/** 下拉打开时才投影全部子代理：不在每帧把整会话的时间线都重建一遍。 */
const subAgentRuns = () => selectCoreSubAgentRuns(props.messages)
const unregister = props.controller.registerGuard(props.tab.id, proceed => { if (pageRef.value) pageRef.value.requestNavigation(proceed); else proceed() })
onBeforeUnmount(unregister)
async function openFile(path: string, bound?: {workRoot: string; projectId?: string; sessionId?: string}) {
  // user:“该修就修，不用停下”+(启动时先完成插件目录加载，再决定文件使用哪个页面)。
  if (!contributionState().loaded && pluginRpc.value) await ensureContributions(pluginRpc.value)
  // user:“该修就修，不用停下”+(已声明的画图文件交给插件页面，其他文件继续使用分屏预览或文本编辑器)。
  const pluginPage = findPluginFilePage(contributionState().pages, path)
  const fileRoot = bound?.workRoot || root
  if (pluginPage) {
    const target = props.controller.tabs.value.find(({ tab }) => tab.kind === 'editor' || tab.kind === 'preview')?.pane
    const pane = target || props.controller.split(props.pane, 'right') || props.pane
    props.controller.openPluginPage(pluginPage, pane, {workRoot:fileRoot, projectId:bound?.projectId ?? props.tab.projectId, sessionId:bound?.sessionId ?? props.tab.sessionId, filePath:path})
  }
  // user:“分屏预览器不支持图片吗？改一下图片，视频 office，什么东西都尽可能支持一下”+
  // (富媒体与文档进预览器，文本仍进编辑器；已经有同类标签就复用它)。
  // user:“设置中把它标记为实验性功能”+(实验性预览关闭时，预览类文件改回默认应用打开)。
  else if (!openFileInSplit(props.controller, path, { workRoot: fileRoot, projectId: bound?.projectId ?? props.tab.projectId, sessionId: bound?.sessionId ?? props.tab.sessionId, fromPane: props.pane })) {
    void openFileWithDefaultApp(props.transport, path, fileRoot)
  }
}
function openPluginPage(target: { plugin: string; id: string }) {
  const page = contributionState().pages.find(page => page.plugin === target.plugin && page.id === target.id)
  // user:“支持一下”+(插件内页面跳转沿用来源标签绑定的项目)。
  if (page) props.controller.openPluginPage(page, props.pane, { workRoot: root, projectId: props.tab.projectId, sessionId: props.tab.sessionId })
}
</script>
<template>
  <CoreAppPage v-if="tab.kind === 'page'" ref="pageRef" :page="tab.resource" :bindings="localBindings" auxiliary @close="controller.closeTab(pane, tab)" />
  <!-- user:“能开多个标签”+(浏览器自己也能开标签：新建、弹窗承接、关闭栈恢复都在同一个分屏里) -->
  <CoreSplitBrowser v-else-if="tab.kind === 'browser'" :tab="tab" :visible="visible" :pane="pane" :controller="(controller as any)" />

  <CoreAuxiliaryChat v-else-if="tab.kind === 'conversation'" :tab="tab" :visible="visible" />
  <CoreSplitTextEditor v-else-if="tab.kind === 'editor'" :tab="tab" :root="root" :visible="visible" :controller="(controller as any)" :documents="documents" @dirty="(id, value) => emit('dirty', id, value)" />
  <CoreSplitPreview v-else-if="tab.kind === 'preview'" :tab="tab" :root="root" :pane="pane" :controller="(controller as any)" :transport="transport" />
  <!-- user:“给现有 search_files 能力一个可见入口”+(文件树同时是检索入口；检索要有后台通道)。 -->
  <CoreSplitFileTree v-else-if="tab.kind === 'files'" :root="tab.resource || root" :transport="transport" @open="openFile" />
  <template v-else-if="tab.kind === 'plugin'">
    <CoreSplitPluginPage v-if="pluginRpc" :tab="tab" :work-root="root" :visible="visible" :request-rpc="pluginRpc" @open-page="openPluginPage" @open-file="openFile" />
    <div v-else class="split-empty">{{ '正在连接插件页面…' }}</div>
  </template>
  <template v-else-if="tab.kind === 'agent'">
    <!-- user:“来自其他聊天 · Agent · 提问与审批请回到来源聊天处理。这种东西不要出现了 该关就关，切回去再显示”+(不再显示跨会话提示，仅在当前会话子代理就绪时渲染) -->
    <p v-if="agentError && !currentAgent" class="split-content-error" role="alert">{{ agentError }} <button class="split-text-button" @click="refreshAgent">重试</button></p>
    <CoreSubAgentView v-if="run && currentAgent" :run="run" :transport="transport" :durable-record="durableRecords[run.name.toLowerCase()]" :member-wait-known="memberWaitKnown" :running-member-names="runningMemberNames" :main-running="mainRunning" :member-statuses="memberStatuses" :member-status-records="memberStatusRecords" :decisions-disabled="false" :load-runs="subAgentRuns" @decision-select="emit('decision-select', $event)" @open-sub-agent="ref => emit('open-sub-agent', { ref, pane: props.pane })" />
  </template>
</template>
