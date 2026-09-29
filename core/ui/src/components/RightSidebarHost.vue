<template>
  <section
    class="right-sidebar-host"
    ref="hostElement"
    :class="{ 'right-sidebar-host--editing': editingLayout }"
    aria-label="右侧工作区面板"
    data-right-sidebar-host
  >
    <header class="right-sidebar-host-head">
      <div class="right-sidebar-host-title">
        <PanelRightOpen :size="16" :stroke-width="1.8" aria-hidden="true" />
        <strong>{{ title }}</strong>
        <span v-if="projectId" class="right-sidebar-host-scope">项目</span>
      </div>
      <button
        class="right-sidebar-host-edit"
        type="button"
        :aria-expanded="editingLayout"
        aria-controls="right-sidebar-layout-editor"
        :aria-label="editingLayout ? '完成编辑面板布局' : '编辑面板布局'"
        :title="editingLayout ? '完成' : '编辑布局'"
        @click="editingLayout = !editingLayout"
      >
        <Check v-if="editingLayout" :size="15" :stroke-width="1.8" aria-hidden="true" />
        <SlidersHorizontal v-else :size="15" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </header>

    <nav class="right-sidebar-mode-tabs" aria-label="右侧面板模式" role="tablist">
      <button
        v-for="mode in panelModes"
        :key="mode.id"
        class="right-sidebar-mode-tab"
        :class="{ active: activeMode === mode.id }"
        type="button"
        role="tab"
        :aria-selected="activeMode === mode.id"
        :tabindex="activeMode === mode.id ? 0 : -1"
        @click="selectMode(mode.id)"
      >
        <component :is="mode.icon" :size="13" :stroke-width="1.8" aria-hidden="true" />
        {{ mode.label }}
      </button>
    </nav>

    <Transition
      :css="false"
      @before-enter="beforeEditorEnter"
      @enter="enterEditor"
      @leave="leaveEditor"
      @before-leave="beforeEditorLeave"
      @enter-cancelled="cancelEditorMotion"
      @leave-cancelled="cancelEditorMotion"
    >
      <RightSidebarLayoutEditor
        v-if="editingLayout"
        id="right-sidebar-layout-editor"
        :modules="moduleDefinitions"
        :layout="layout.layout.value"
        @toggle-visible="layout.setVisible"
        @reset="layout.reset"
      />
    </Transition>

    <Transition name="right-sidebar-mode" mode="out-in">
      <div v-if="activeMode === 'files'" ref="modePanelElement" key="files" class="right-sidebar-stage" data-right-sidebar-stage>
        <slot name="stage" />
      </div>
      <div v-else ref="modePanelElement" key="modules" class="right-sidebar-module-list" data-right-sidebar-module-list>
        <PlanLibraryPanel
          v-if="plansModeActivated"
          v-show="activeMode === 'plans'"
          :project-id="projectId"
          :request-rpc="requestRpc"
          @start-plan="onStartPlan"
        />
        <TransitionGroup
          v-show="activeMode !== 'plans'"
          name="right-sidebar-module-list"
          tag="div"
          class="right-sidebar-module-items"
          move-class="right-sidebar-module-list-move"
        >
          <RightSidebarModule
            v-for="(module, index) in orderedModules"
            :key="module.id"
            :module="module"
            :style="{ '--module-motion-index': Math.min(index, 2) }"
            :collapsed="layout.layout.value.collapsed[module.id] === true"
            :can-move-up="editingLayout && index > 0"
            :can-move-down="editingLayout && index < orderedModules.length - 1"
            :show-reorder-controls="editingLayout"
            :dragging="draggingId === module.id"
            :drag-over="dragOverId === module.id"
            @toggle-collapsed="layout.toggleCollapsed(module.id)"
            @move="(direction) => layout.move(module.id, direction)"
            @dragstart="startDrag(module.id, $event)"
            @dragend="endDrag"
            @dragover="dragOver(module.id, $event)"
            @drop="dropModule(module.id, $event)"
            v-show="moduleVisibleInMode(module)"
          >
            <component
              :is="module.component"
              v-if="module.component"
              v-bind="module.componentProps || {}"
            />
            <RightSidebarWidgetRenderer
              v-else-if="module.widget"
              :entry="module.widget"
              :project-id="projectId"
              :work-root="workRoot"
              :session-id="sessionId"
              :request-rpc="requestRpc"
              :snapshot="module.widget.snapshot"
            />
          </RightSidebarModule>
        </TransitionGroup>
        <div v-if="!orderedModules.length && activeMode !== 'plans'" class="right-sidebar-host-empty">
          <span>暂无显示中的模块</span>
          <button type="button" @click="editingLayout = true">编辑布局</button>
        </div>
      </div>
    </Transition>
  </section>
</template>

<script setup lang="ts">
import { gsap } from 'gsap'
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, watch, type Component } from 'vue'
import { Activity, Check, FolderKanban, FolderOpen, ListChecks, PanelRightOpen, SlidersHorizontal } from 'lucide-vue-next'
import { refreshPluginUIWidgets } from '../plugins/api'
import type { PluginWidgetEntry } from '../right-sidebar/types'
import type {
  RightSidebarLayoutState,
  RightSidebarModuleDefinition,
  RightSidebarPluginContribution,
  RightSidebarRpc,
} from '../right-sidebar/types'
import { useRightSidebarLayout } from '../composables/useRightSidebarLayout'
import RightSidebarLayoutEditor from './RightSidebarLayoutEditor.vue'
import RightSidebarModule from './RightSidebarModule.vue'
import RightSidebarWidgetRenderer from './RightSidebarWidgetRenderer.vue'
import RightSidebarRuntimeStatus from './RightSidebarRuntimeStatus.vue'
import RightSidebarWebSearch from './RightSidebarWebSearch.vue'
import RightSidebarRag from './RightSidebarRag.vue'
import CoreResourceStats from './CoreResourceStats.vue'
import CoreSubAgentPanel from './CoreSubAgentPanel.vue'
import ArtifactPanel from './ArtifactPanel.vue'
import PlanLibraryPanel from '../plans/PlanLibraryPanel.vue'
import type { PlanPackage } from '../plans/types'
import type { ArtifactRevision, CoreMessage, CoreSubAgentRun, CoreSubAgentStatus, ProjectArtifact } from '../types'
import { selectCoreSubAgentRuns } from '../agents/subAgentProjection'
import type { LamToolsTransport } from '../transport'

const props = withDefaults(defineProps<{
  title?: string
  storageKey?: string
  projectId?: string | null
  workRoot?: string | null
  sessionId?: string | null
  requestRpc?: RightSidebarRpc
  transport?: LamToolsTransport
  messages?: CoreMessage[]
  contextWindow?: number | null
  runtimeStatus?: string | null
  runtimeModeLabel?: string
  runtimeDetail?: string
  stageOpen?: boolean
  /** Explicit right-rail mode; artifact mode stays active while StagePane opens. */
  mode?: 'runtime' | 'files' | 'artifacts' | 'plans'
  artifactSignal?: unknown
  openArtifact?: (artifact: ProjectArtifact, revision?: ArtifactRevision) => void | Promise<void>
  /** Host callback that turns a ready plan into a session turn. */
  startPlan?: (plan: PlanPackage) => void | Promise<void>
  /** Parent-shell navigation callback for source-backed sub-agent rows. */
  locateSubAgent?: (run: CoreSubAgentRun) => void | Promise<void>
  activePluginId?: string | null
  activeModeId?: string | null
  pluginWidgets?: PluginWidgetEntry[]
  pluginContributions?: RightSidebarPluginContribution[]
  modules?: RightSidebarModuleDefinition[]
}>(), {
  title: '工作区',
  storageKey: 'lamtools.core.ui',
  projectId: null,
  workRoot: null,
  sessionId: null,
  requestRpc: undefined,
  transport: undefined,
  messages: () => [],
  contextWindow: null,
  runtimeStatus: 'idle',
  runtimeModeLabel: '',
  runtimeDetail: '',
  stageOpen: false,
  mode: 'runtime',
  openArtifact: undefined,
  startPlan: undefined,
  locateSubAgent: undefined,
  activePluginId: null,
  activeModeId: null,
  pluginWidgets: () => [],
  pluginContributions: () => [],
  modules: () => [],
})

const emit = defineEmits<{
  'mode-change': [mode: 'runtime' | 'files' | 'artifacts' | 'plans']
  'start-plan': [plan: PlanPackage]
}>()

const editingLayout = ref(false)
const activeMode = ref<'runtime' | 'files' | 'artifacts' | 'plans'>(props.stageOpen ? 'files' : props.mode)
// Once the plan workbench is opened it stays mounted: switching modes must not
// throw away an in-progress plan edit.
const plansModeActivated = ref(activeMode.value === 'plans')
watch(activeMode, (mode) => {
  if (mode === 'plans') plansModeActivated.value = true
})
const hostElement = ref<HTMLElement | null>(null)
const modePanelElement = ref<HTMLElement | null>(null)
const remoteWidgetEntries = ref<PluginWidgetEntry[]>([])
const draggingId = ref('')
const dragOverId = ref('')
const loadedComponents = shallowRef(new Map<string, Component>())
const moduleLoadStates = ref<Record<string, { status: 'loading' | 'error'; error?: string }>>({})
const subAgentRemoteRuns = ref<CoreSubAgentRun[] | null>(null)
const subAgentLoading = ref(false)
const subAgentError = ref('')
const activeSubAgentId = ref('')
let subAgentLoadRevision = 0
let moduleLoadRevision = 0
let hostMotionContext: gsap.Context | null = null
let editorMotionTween: gsap.core.Tween | null = null
let modeMotionTween: gsap.core.Tween | null = null
let editorMotionRevision = 0

const panelModes = [
  { id: 'runtime' as const, label: '运行', icon: Activity },
  { id: 'files' as const, label: '文件', icon: FolderOpen },
  { id: 'artifacts' as const, label: '成果', icon: FolderKanban },
  { id: 'plans' as const, label: '方案', icon: ListChecks },
]

const localSubAgentRuns = computed(() => selectCoreSubAgentRuns(props.messages))
const subAgentRuns = computed(() => mergeSubAgentRuns(subAgentRemoteRuns.value || [], localSubAgentRuns.value))

const allWidgetEntries = computed(() => {
  const result: PluginWidgetEntry[] = []
  const seen = new Set<string>()
  const entries = [...props.pluginWidgets, ...remoteWidgetEntries.value]
  for (const entry of entries) {
    if (!entry || typeof entry.id !== 'string' || !entry.id || typeof entry.pluginId !== 'string' || !entry.pluginId) continue
    if (props.activePluginId && entry.pluginId !== props.activePluginId) continue
    const key = `${entry.pluginId}:${entry.id}`
    if (seen.has(key) || entry.enabled === false) continue
    seen.add(key)
    result.push(entry)
  }
  return result
})

const webSearchEntry = computed(() => allWidgetEntries.value.find((entry) => (
  entry.pluginId === 'websearch' || entry.id === 'websearch.engine'
)) || null)
const ragEntry = computed(() => allWidgetEntries.value.find((entry) => (
  entry.pluginId === 'rag' || entry.id === 'rag.index' || entry.id.startsWith('rag.')
)) || null)

const moduleDefinitions = computed<RightSidebarModuleDefinition[]>(() => {
  const core: RightSidebarModuleDefinition[] = [
    {
      id: 'runtime',
      title: 'Runtime Status',
      description: '当前回合',
      order: 0,
      defaultCollapsed: true,
      icon: PanelRightOpen,
      component: RightSidebarRuntimeStatus,
      componentProps: {
        status: props.runtimeStatus,
        modeLabel: props.runtimeModeLabel,
        detail: props.runtimeDetail,
      },
    },
    {
      id: 'resources',
      title: 'Resources',
      order: 10,
      defaultCollapsed: false,
      component: CoreResourceStats,
      componentProps: {
        messages: props.messages,
        contextWindow: props.contextWindow,
      },
    },
    {
      id: 'sub-agents',
      title: 'Sub Agents',
      description: '当前会话',
      // Keep the long-standing Runtime/Resources ordering stable; this module
      // follows Resources so existing per-project layout preferences survive.
      order: 15,
      defaultCollapsed: false,
      component: CoreSubAgentPanel,
      componentProps: {
        runs: subAgentRuns.value,
        activeSubAgentId: activeSubAgentId.value,
        loading: subAgentLoading.value,
        errorText: subAgentError.value,
        onOpen: openSubAgent,
        onRetry: loadSubAgentRuns,
      },
    },
    {
      id: 'web-search',
      title: 'Web Search',
      order: 20,
      defaultCollapsed: false,
      component: RightSidebarWebSearch,
      componentProps: {
        requestRpc: props.requestRpc,
        projectId: props.projectId,
        workRoot: props.workRoot,
        widgetEntry: webSearchEntry.value,
      },
    },
    {
      id: 'rag',
      title: 'RAG',
      order: 30,
      defaultCollapsed: false,
      component: RightSidebarRag,
      componentProps: {
        requestRpc: props.requestRpc,
        projectId: props.projectId,
        workRoot: props.workRoot,
        widgetEntry: ragEntry.value,
      },
    },
    {
      id: 'artifacts',
      title: 'Artifacts',
      order: 40,
      defaultCollapsed: false,
      status: props.projectId && props.transport && (props.requestRpc as unknown) ? 'ready' : 'disabled',
      disabledReason: '选择项目后可查看 Artifacts',
      component: ArtifactPanel,
      componentProps: {
        projectId: props.projectId,
        transport: props.transport,
        requestRpc: props.requestRpc,
        artifactSignal: props.artifactSignal,
        openArtifact: props.openArtifact,
      },
    },
  ]

  const custom = props.modules.map((module) => ({ ...module }))
  const plugin = allWidgetEntries.value
    .filter((entry) => entry.id !== webSearchEntry.value?.id && entry.id !== ragEntry.value?.id)
    .map((entry): RightSidebarModuleDefinition => ({
      id: `plugin:${entry.pluginId}:${entry.id}`,
      title: entry.title,
      order: 100 + (Number(entry.order) || 0),
      defaultVisible: entry.enabled !== false,
      defaultCollapsed: false,
      status: entry.status || 'ready',
      error: entry.error,
      icon: undefined,
      widget: entry,
    }))
  const surface = props.pluginContributions.map((contribution) => ({
    ...contribution,
    id: contribution.id,
    componentProps: contribution.componentProps,
  })) as RightSidebarModuleDefinition[]
  return [...core, ...custom, ...plugin, ...surface]
})

const resolvedModuleDefinitions = computed<RightSidebarModuleDefinition[]>(() => (
  moduleDefinitions.value.map((module) => {
    const loaded = loadedComponents.value.get(module.id)
    const loadState = moduleLoadStates.value[module.id]
    return {
      ...module,
      component: module.component || loaded,
      status: loadState?.status || module.status,
      error: loadState?.error || module.error,
    }
  })
))

const moduleDefaults = computed<Record<string, { visible?: boolean; collapsed?: boolean }>>(() => {
  const result: Record<string, { visible?: boolean; collapsed?: boolean }> = {}
  for (const module of resolvedModuleDefinitions.value) {
    result[module.id] = {
      visible: module.defaultVisible !== false,
      collapsed: module.defaultCollapsed === true,
    }
  }
  return result
})
const layout = useRightSidebarLayout({
  storageKey: `${props.storageKey}.right-sidebar`,
  moduleIds: computed(() => moduleDefinitions.value.map((module) => module.id)),
  moduleDefaults,
  activeProjectId: computed(() => props.projectId),
})

const orderedModules = computed(() => {
  const byId = new Map(resolvedModuleDefinitions.value.map((module) => [module.id, module]))
  return layout.layout.value.order
    .map((id) => byId.get(id))
    .filter((module): module is RightSidebarModuleDefinition => Boolean(module && layout.layout.value.visible[module.id] !== false))
})

function moduleVisibleInMode(module: RightSidebarModuleDefinition): boolean {
  if (activeMode.value === 'plans') return false
  if (activeMode.value === 'artifacts') return module.id === 'artifacts'
  if (activeMode.value === 'files') return false
  return module.id !== 'artifacts'
}

function onStartPlan(plan: PlanPackage): void {
  emit('start-plan', plan)
  void props.startPlan?.(plan)
}

function openSubAgent(subSessionId: string, run?: CoreSubAgentRun): void {
  const selected = run || subAgentRuns.value.find(item => item.subSessionId === subSessionId)
  activeSubAgentId.value = selected?.subSessionId || subSessionId
  if ((selected?.sourceMessageId || selected?.sourcePartId) && props.locateSubAgent) {
    void props.locateSubAgent(selected)
  }
}

async function loadSubAgentRuns(): Promise<void> {
  const sessionId = props.sessionId
  const requestRpc = props.requestRpc
  const revision = ++subAgentLoadRevision
  activeSubAgentId.value = ''
  subAgentRemoteRuns.value = null
  subAgentError.value = ''
  if (!sessionId || !requestRpc) return

  subAgentLoading.value = true
  try {
    let parsed: CoreSubAgentRun[] = []
    let hadPayload = false
    const methods = ['sub_agent.list', 'sub_agent.snapshot']
    for (const method of methods) {
      try {
        const response = await requestRpc(method, {
          session_id: sessionId,
          thread_id: sessionId,
        })
        const candidate = parseSubAgentRunsPayload(response)
        if (candidate !== null) {
          parsed = candidate
          hadPayload = true
          break
        }
      } catch {
        // A backend may expose only one of list/snapshot. Keep trying the
        // compatibility spelling before falling back to the local projection.
      }
      if (revision !== subAgentLoadRevision) return
    }
    if (revision !== subAgentLoadRevision) return
    if (!hadPayload) {
      subAgentError.value = localSubAgentRuns.value.length > 0 ? '' : 'Sub Agent 记录暂不可用。'
      return
    }
    subAgentRemoteRuns.value = parsed
  } catch {
    if (revision === subAgentLoadRevision) {
      subAgentError.value = localSubAgentRuns.value.length > 0 ? '' : 'Sub Agent 记录暂不可用。'
    }
  } finally {
    if (revision === subAgentLoadRevision) subAgentLoading.value = false
  }
}

function parseSubAgentRunsPayload(value: unknown): CoreSubAgentRun[] | null {
  const root = asRecord(value)
  const candidates: unknown[] = [
    root.runs,
    root.items,
    root.agents,
    root.sub_agents,
    asRecord(root.snapshot).runs,
    asRecord(root.snapshot).items,
    asRecord(root.data).runs,
    asRecord(root.result).runs,
  ]
  for (const candidate of candidates) {
    if (Array.isArray(candidate)) return candidate.map(normalizeSubAgentRun).filter((run): run is CoreSubAgentRun => Boolean(run))
    if (candidate && typeof candidate === 'object') {
      const values = Object.values(candidate as Record<string, unknown>)
      if (values.length > 0 && values.every(item => asRecord(item).name || asRecord(item).sub_session_id || asRecord(item).subSessionId)) {
        return values.map(normalizeSubAgentRun).filter((run): run is CoreSubAgentRun => Boolean(run))
      }
    }
  }
  return null
}

function normalizeSubAgentRun(value: unknown): CoreSubAgentRun | null {
  const raw = asRecord(value)
  if (!Object.keys(raw).length) return null
  const name = stringValue(raw.name, raw.agent_name, raw.agentName) || 'Sub Agent'
  const subSessionId = stringValue(raw.subSessionId, raw.sub_session_id, raw.id) || name
  const model = stringValue(raw.model, raw.model_id, raw.modelId)
  const status = normalizeSubAgentStatus(raw.status)
  const explicitSourceMessageId = stringValue(
    raw.sourceMessageId,
    raw.source_message_id,
    raw.message_id,
  )
  const sourceTurnId = stringValue(raw.sourceTurnId, raw.source_turn_id, raw.turn_id)
  const sourceRunId = stringValue(raw.sourceRunId, raw.source_run_id, raw.run_id)
  const sourceMessageId = explicitSourceMessageId
    || (sourceTurnId ? assistantMessageId(sourceTurnId) : sourceRunId ? assistantMessageId(sourceRunId) : '')
  const sourceCallId = stringValue(raw.sourceCallId, raw.source_call_id, raw.call_id, raw.callId)
  const sourcePartId = stringValue(
    raw.sourcePartId,
    raw.source_part_id,
    raw.part_id,
    sourceCallId ? `part-${sourceCallId}` : '',
  )
  const timeline = Array.isArray(raw.timeline) ? raw.timeline.filter(item => asRecord(item).id).map(item => item as CoreMessage) : []
  const sourcePartIds = stringArray(raw.sourcePartIds, raw.source_part_ids)
  if (sourcePartId && !sourcePartIds.includes(sourcePartId)) sourcePartIds.push(sourcePartId)
  const sourceMessageIds = stringArray(raw.sourceMessageIds, raw.source_message_ids)
  if (sourceMessageId && !sourceMessageIds.includes(sourceMessageId)) sourceMessageIds.push(sourceMessageId)
  const startedAt = timestampValue(raw.startedAt, raw.started_at)
  const completedAt = timestampValue(raw.completedAt, raw.completed_at)
  const updatedAt = stringValue(raw.updatedAt, raw.updated_at, completedAt, startedAt)
  return {
    id: stringValue(raw.id) || subSessionId,
    subSessionId,
    name,
    task: stringValue(raw.task, raw.summary) || '',
    status,
    modelId: model,
    startedAt,
    updatedAt,
    timeline,
    sourcePartIds,
    type: stringValue(raw.type, raw.agent_type, raw.agentType, raw.mode) || 'execute',
    model,
    reasoningLevel: stringValue(raw.reasoningLevel, raw.reasoning_level, raw.reasoning_effort),
    summary: stringValue(raw.summary, raw.task),
    completedAt: completedAt || undefined,
    elapsedMs: numberValue(raw.elapsedMs, raw.elapsed_ms, raw.durationMs, raw.duration_ms),
    sourceMessageId: sourceMessageId || undefined,
    sourcePartId: sourcePartId || undefined,
    sourceMessageIds,
    subSessionIds: stringArray(raw.subSessionIds, raw.sub_session_ids, subSessionId),
  }
}

function assistantMessageId(value: string): string {
  const text = String(value || '').trim()
  if (!text) return ''
  return text.startsWith('assistant:') ? text : `assistant:${text}`
}

function mergeSubAgentRuns(remote: readonly CoreSubAgentRun[], local: readonly CoreSubAgentRun[]): CoreSubAgentRun[] {
  const merged = new Map<string, CoreSubAgentRun>()
  for (const run of [...remote, ...local]) {
    const key = run.name.trim().toLowerCase() || run.subSessionId
    const current = merged.get(key)
    if (!current) {
      merged.set(key, { ...run, sourcePartIds: [...run.sourcePartIds], sourceMessageIds: [...(run.sourceMessageIds || [])] })
      continue
    }
    const prefer = run.sourceMessageId || run.sourcePartId ? run : current
    merged.set(key, {
      ...current,
      ...run,
      // A live local projection may omit fields that only the durable snapshot
      // knows (model, timestamps, summary).  Keep the non-empty value from
      // either side while allowing the fresher source to update it.
      subSessionId: run.subSessionId || current.subSessionId,
      name: run.name || current.name,
      task: run.task || current.task,
      modelId: run.modelId || current.modelId,
      model: run.model || current.model || run.modelId || current.modelId,
      type: run.type || current.type,
      reasoningLevel: run.reasoningLevel || current.reasoningLevel,
      summary: run.summary || current.summary || run.task || current.task,
      startedAt: run.startedAt || current.startedAt,
      updatedAt: run.updatedAt || current.updatedAt,
      completedAt: run.completedAt || current.completedAt,
      elapsedMs: run.elapsedMs ?? current.elapsedMs,
      sourceCallId: run.sourceCallId || current.sourceCallId,
      // Local stream fields are fresher while remote snapshots fill history.
      timeline: run.timeline.length > 0 ? run.timeline : current.timeline,
      sourcePartIds: uniqueStrings([...current.sourcePartIds, ...run.sourcePartIds]),
      sourceMessageIds: uniqueStrings([...(current.sourceMessageIds || []), ...(run.sourceMessageIds || [])]),
      subSessionIds: uniqueStrings([...(current.subSessionIds || []), ...(run.subSessionIds || [])]),
      sourceMessageId: prefer.sourceMessageId || current.sourceMessageId,
      sourcePartId: prefer.sourcePartId || current.sourcePartId,
    })
  }
  return [...merged.values()].sort(compareSubAgentRuns)
}

function compareSubAgentRuns(left: CoreSubAgentRun, right: CoreSubAgentRun): number {
  const rank: Record<string, number> = {
    running: 0,
    pending: 1,
    paused: 2,
    error: 3,
    interrupted: 4,
    idle: 5,
    closed: 6,
    completed: 7,
  }
  const stateDelta = (rank[String(left.status)] ?? 8) - (rank[String(right.status)] ?? 8)
  if (stateDelta !== 0) return stateDelta
  const leftTime = Date.parse(left.updatedAt || left.completedAt || left.startedAt || '')
  const rightTime = Date.parse(right.updatedAt || right.completedAt || right.startedAt || '')
  if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) return rightTime - leftTime
  return String(left.name || left.id).localeCompare(String(right.name || right.id))
}

function asRecord(value: unknown): Record<string, any> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {}
}

function stringValue(...values: unknown[]): string {
  for (const value of values) {
    if (value === null || value === undefined) continue
    const text = String(value).trim()
    if (text) return text
  }
  return ''
}

function stringArray(...values: unknown[]): string[] {
  const result: string[] = []
  for (const value of values) {
    if (Array.isArray(value)) {
      for (const item of value) {
        const text = stringValue(item)
        if (text && !result.includes(text)) result.push(text)
      }
    } else {
      const text = stringValue(value)
      if (text && !result.includes(text)) result.push(text)
    }
  }
  return result
}

function numberValue(...values: unknown[]): number | undefined {
  for (const value of values) {
    const parsed = typeof value === 'number' ? value : Number(value)
    if (Number.isFinite(parsed)) return Math.max(0, Math.round(parsed))
  }
  return undefined
}

function timestampValue(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return new Date(value < 1e12 ? value * 1000 : value).toISOString()
    }
    const text = stringValue(value)
    if (!text) continue
    const numeric = Number(text)
    if (Number.isFinite(numeric)) {
      return new Date(numeric < 1e12 ? numeric * 1000 : numeric).toISOString()
    }
    if (Number.isFinite(Date.parse(text))) return text
  }
  return ''
}

function normalizeSubAgentStatus(value: unknown): CoreSubAgentStatus {
  const status = String(value || '').toLowerCase()
  if (status === 'running' || status === 'active' || status === 'interrupting') return 'running'
  if (status === 'pending' || status === 'waiting' || status === 'queued') return 'pending'
  if (status === 'error' || status === 'failed' || status === 'rejected') return 'error'
  if (status === 'paused' || status === 'blocked' || status === 'wait') return 'paused'
  if (status === 'closed' || status === 'disabled') return 'closed'
  if (status === 'interrupted' || status === 'cancelled' || status === 'canceled') return 'interrupted'
  if (status === 'idle' || status === 'ready' || status === 'enabled') return 'idle'
  if (status === 'completed' || status === 'done' || status === 'success' || status === 'ok') return 'completed'
  return 'completed'
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))]
}

function selectMode(mode: 'runtime' | 'files' | 'artifacts' | 'plans'): void {
  activeMode.value = mode
  emit('mode-change', mode)
}

async function loadModuleComponents(): Promise<void> {
  const revision = ++moduleLoadRevision
  const modules = moduleDefinitions.value
  const activeIds = new Set(modules.map((module) => module.id))
  const nextStates: Record<string, { status: 'loading' | 'error'; error?: string }> = {}
  for (const [id, state] of Object.entries(moduleLoadStates.value)) {
    if (activeIds.has(id)) nextStates[id] = state
  }
  moduleLoadStates.value = nextStates
  for (const module of modules) {
    if (module.component || !module.load || loadedComponents.value.has(module.id)) continue
    moduleLoadStates.value = { ...moduleLoadStates.value, [module.id]: { status: 'loading' } }
    try {
      const loaded = await module.load()
      if (revision !== moduleLoadRevision) return
      const component = 'default' in loaded ? loaded.default : loaded
      loadedComponents.value = new Map(loadedComponents.value).set(module.id, component)
      const { [module.id]: _removed, ...remaining } = moduleLoadStates.value
      moduleLoadStates.value = remaining
    } catch (cause) {
      if (revision !== moduleLoadRevision) return
      moduleLoadStates.value = {
        ...moduleLoadStates.value,
        [module.id]: {
          status: 'error',
          error: `加载 ${module.title} 失败：${cause instanceof Error ? cause.message : String(cause)}`,
        },
      }
    }
  }
}

function startDrag(moduleId: string, event: DragEvent): void {
  draggingId.value = moduleId
  dragOverId.value = ''
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', moduleId)
  }
}

function dragOver(moduleId: string, event: DragEvent): void {
  if (!draggingId.value || draggingId.value === moduleId) return
  dragOverId.value = moduleId
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
}

function dropModule(targetId: string, event: DragEvent): void {
  const sourceId = draggingId.value || event.dataTransfer?.getData('text/plain') || ''
  if (!sourceId || sourceId === targetId) {
    endDrag()
    return
  }
  const order = [...layout.layout.value.order]
  const sourceIndex = order.indexOf(sourceId)
  const targetIndex = order.indexOf(targetId)
  if (sourceIndex < 0 || targetIndex < 0) {
    endDrag()
    return
  }
  order.splice(sourceIndex, 1)
  order.splice(order.indexOf(targetId), 0, sourceId)
  layout.reorder(order)
  endDrag()
}

function endDrag(): void {
  draggingId.value = ''
  dragOverId.value = ''
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function canAnimateEditor(): boolean {
  return Boolean(hostMotionContext)
    && typeof requestAnimationFrame === 'function'
    && !prefersReducedMotion()
}

function clearEditorMotion(target: HTMLElement): void {
  editorMotionRevision += 1
  editorMotionTween?.kill()
  editorMotionTween = null
  gsap.set(target, { clearProps: 'opacity,transform,visibility,willChange' })
}

function beforeEditorEnter(el: Element): void {
  const target = el as HTMLElement
  clearEditorMotion(target)
  if (!canAnimateEditor()) return
  hostMotionContext?.add(() => {
    gsap.set(target, { autoAlpha: 0, y: -6, willChange: 'transform,opacity' })
  })
}

function beforeEditorLeave(el: Element): void {
  const target = el as HTMLElement
  clearEditorMotion(target)
  if (!canAnimateEditor()) return
  hostMotionContext?.add(() => {
    gsap.set(target, { autoAlpha: 1, y: 0, willChange: 'transform,opacity' })
  })
}

function runEditorMotion(
  el: Element,
  from: { autoAlpha: number; y: number },
  to: { autoAlpha: number; y: number },
  done: () => void,
): void {
  const target = el as HTMLElement
  editorMotionTween?.kill()
  editorMotionTween = null
  const revision = ++editorMotionRevision
  if (!canAnimateEditor()) {
    gsap.set(target, { ...to, clearProps: 'opacity,transform,visibility,willChange' })
    done()
    return
  }

  hostMotionContext?.add(() => {
    editorMotionTween = gsap.fromTo(target, from, {
      ...to,
      duration: 0.18,
      ease: 'power2.out',
      overwrite: 'auto',
      clearProps: 'opacity,transform,visibility,willChange',
      onComplete: () => {
        if (revision !== editorMotionRevision) return
        editorMotionTween = null
        done()
      },
    })
  })
}

function enterEditor(el: Element, done: () => void): void {
  runEditorMotion(el, { autoAlpha: 0, y: -6 }, { autoAlpha: 1, y: 0 }, done)
}

function leaveEditor(el: Element, done: () => void): void {
  runEditorMotion(el, { autoAlpha: 1, y: 0 }, { autoAlpha: 0, y: -6 }, done)
}

function cancelEditorMotion(el: Element): void {
  clearEditorMotion(el as HTMLElement)
}

async function animateModuleModeChange(): Promise<void> {
  await nextTick()
  const target = modePanelElement.value
  if (!target) return
  modeMotionTween?.kill()
  modeMotionTween = null
  if (!hostMotionContext || prefersReducedMotion()) {
    gsap.set(target, { clearProps: 'opacity,transform,visibility,willChange' })
    return
  }
  hostMotionContext.add(() => {
    modeMotionTween = gsap.fromTo(
      target,
      { autoAlpha: 0, y: 4, willChange: 'transform,opacity' },
      {
        autoAlpha: 1,
        y: 0,
        duration: 0.18,
        ease: 'power2.out',
        overwrite: true,
        clearProps: 'opacity,transform,visibility,willChange',
        onComplete: () => { modeMotionTween = null },
      },
    )
  })
}

async function refreshWidgets(): Promise<void> {
  if (!props.requestRpc) return
  try {
    const entries = await refreshPluginUIWidgets(props.requestRpc, {
      project_id: props.projectId ?? undefined,
      session_id: props.sessionId ?? undefined,
      plugin_id: props.activePluginId ?? undefined,
      mode_id: props.activeModeId ?? undefined,
    })
    remoteWidgetEntries.value = entries
  } catch {
    // Optional widget discovery is deliberately best effort.  Existing
    // built-ins and explicitly provided descriptors remain usable.
  }
}

onMounted(() => {
  if (hostElement.value) {
    hostMotionContext = gsap.context(() => {}, hostElement.value)
  }
  void refreshWidgets()
  void loadSubAgentRuns()
})
watch(() => [props.activePluginId, props.activeModeId], () => { void refreshWidgets() })
watch(() => props.projectId, () => { void refreshWidgets() })
watch(() => props.sessionId, () => { void loadSubAgentRuns() })
watch(() => props.messages, () => {
  // The local projection remains live while an RPC snapshot is loading and
  // supplies streaming updates after the snapshot has arrived.
  if (!props.sessionId) subAgentRemoteRuns.value = null
}, { deep: false })
watch(() => props.mode, mode => {
  if (mode && mode !== activeMode.value) activeMode.value = mode
})
watch(() => props.stageOpen, open => {
  if (open && activeMode.value !== 'artifacts' && props.mode !== 'artifacts') activeMode.value = 'files'
})
watch(activeMode, (mode, previous) => {
  // The files/modules boundary is handled by the retained Vue transition.
  // Runtime/artifacts reuse the same mounted module tree, so animate its
  // newly visible contents without remounting stateful widgets.
  if (mode !== 'files' && previous !== 'files') void animateModuleModeChange()
})
watch(moduleDefinitions, () => { void loadModuleComponents() }, { immediate: true })

onUnmounted(() => {
  subAgentLoadRevision += 1
  editorMotionRevision += 1
  editorMotionTween?.kill()
  editorMotionTween = null
  modeMotionTween?.kill()
  modeMotionTween = null
  hostMotionContext?.revert()
  hostMotionContext = null
})

defineExpose({
  layout,
  moduleDefinitions: resolvedModuleDefinitions,
  orderedModules,
  refreshWidgets,
  editingLayout,
  activeMode,
  selectMode,
})
</script>

<style scoped>
.right-sidebar-host { --host-text: var(--theme-backdrop-text); display: flex; flex-direction: column; min-width: 0; min-height: 100%; color: var(--host-text); }
.right-sidebar-host-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); min-height: 42px; padding: var(--space-2) var(--space-3); border-bottom: 1px solid color-mix(in srgb, var(--host-text) 10%, transparent); }
.right-sidebar-host-title { display: flex; align-items: center; gap: var(--space-2); min-width: 0; }
.right-sidebar-host-title svg { flex: 0 0 auto; color: color-mix(in srgb, var(--host-text) 68%, transparent); }
.right-sidebar-host-title strong { overflow: hidden; font-size: 13px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.right-sidebar-host-scope { color: color-mix(in srgb, var(--host-text) 48%, transparent); font-size: 10px; }
.right-sidebar-host-edit { display: inline-flex; align-items: center; justify-content: center; min-width: 30px; min-height: 30px; padding: 0; border: 0; border-radius: var(--radius-sm); background: transparent; color: color-mix(in srgb, var(--host-text) 62%, transparent); }
.right-sidebar-host-edit:hover { background: color-mix(in srgb, var(--host-text) var(--alpha-hover), transparent); color: var(--host-text); }
.right-sidebar-host-edit:active { background: color-mix(in srgb, var(--host-text) var(--alpha-active), transparent); }
.right-sidebar-host-edit:focus-visible { outline: 2px solid color-mix(in srgb, var(--blue) 75%, transparent); outline-offset: 1px; }
.right-sidebar-mode-tabs { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 2px; padding: 0 var(--space-2) var(--space-2); }
.right-sidebar-mode-tab { display: inline-flex; align-items: center; justify-content: center; gap: var(--space-1); min-height: 30px; border: 0; border-radius: var(--radius-sm); padding: 0 var(--space-1); background: transparent; color: color-mix(in srgb, var(--host-text) 54%, transparent); font-size: 11px; transition: background-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out); }
.right-sidebar-mode-tab:hover { background: color-mix(in srgb, var(--host-text) var(--alpha-hover), transparent); color: var(--host-text); }
.right-sidebar-mode-tab:active, .right-sidebar-mode-tab.active { background: color-mix(in srgb, var(--host-text) var(--alpha-active), transparent); color: var(--host-text); }
.right-sidebar-mode-tab:focus-visible { outline: 2px solid color-mix(in srgb, var(--blue) 75%, transparent); outline-offset: 1px; }
.right-sidebar-module-list { flex: 1 1 auto; min-height: 0; overflow: auto; }
.right-sidebar-mode-enter-active,
.right-sidebar-mode-leave-active {
  transition: opacity var(--dur-base) var(--ease-out), transform var(--dur-base) var(--ease-out);
}
.right-sidebar-mode-enter-from { opacity: 0; transform: translateY(var(--space-1)); }
.right-sidebar-mode-leave-to { opacity: 0; transform: translateY(calc(var(--space-1) * -1)); }
.right-sidebar-module-items { position: relative; }
.right-sidebar-module-items :deep(.right-sidebar-module-list-enter-active),
.right-sidebar-module-items :deep(.right-sidebar-module-list-leave-active) {
  transition: opacity var(--dur-base) var(--ease-out), transform var(--dur-base) var(--ease-out);
  transition-delay: calc(var(--module-motion-index, 0) * 12ms);
}
.right-sidebar-module-items :deep(.right-sidebar-module-list-enter-from),
.right-sidebar-module-items :deep(.right-sidebar-module-list-leave-to) {
  opacity: 0;
  transform: translateY(8px);
}
.right-sidebar-module-items :deep(.right-sidebar-module-list-leave-active) {
  position: absolute;
  inset-inline: 0;
}
.right-sidebar-module-items :deep(.right-sidebar-module-list-move) {
  transition: transform var(--dur-base) var(--ease-out);
}
.right-sidebar-stage { flex: 1 1 auto; min-height: 0; overflow: auto; }
.right-sidebar-host-empty { display: grid; justify-items: center; gap: var(--space-2); padding: var(--space-5) var(--space-3); color: color-mix(in srgb, var(--host-text) 52%, transparent); font-size: 12px; }
.right-sidebar-host-empty button { min-height: 30px; padding: 0 var(--space-2); border: 1px solid color-mix(in srgb, var(--theme-control-text) 14%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-control-background) 70%, transparent); color: var(--theme-control-text); font-size: 12px; }
.right-sidebar-host-empty button:hover { background: color-mix(in srgb, var(--theme-control-text) var(--alpha-hover), var(--theme-control-background)); }
@media (max-width: 640px) { .right-sidebar-host-head { min-height: 52px; } .right-sidebar-host-edit { min-width: 44px; min-height: 44px; } }
@media (prefers-reduced-motion: reduce) {
  .right-sidebar-host-edit,
  .right-sidebar-mode-tab { transition: none; }
  .right-sidebar-mode-enter-active,
  .right-sidebar-mode-leave-active { transition: none; }
  .right-sidebar-mode-enter-from,
  .right-sidebar-mode-leave-to { transform: none; }
  .right-sidebar-module-items :deep(.right-sidebar-module-list-enter-active),
  .right-sidebar-module-items :deep(.right-sidebar-module-list-leave-active) {
    transition: opacity 80ms linear;
    transition-delay: 0s;
  }
  .right-sidebar-module-items :deep(.right-sidebar-module-list-enter-from),
  .right-sidebar-module-items :deep(.right-sidebar-module-list-leave-to) { transform: none; }
  .right-sidebar-module-items :deep(.right-sidebar-module-list-move) { transition: none; }
}
</style>
