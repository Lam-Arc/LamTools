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

    <div v-if="stageOpen" class="right-sidebar-stage" data-right-sidebar-stage>
      <slot name="stage" />
    </div>
    <div v-else class="right-sidebar-module-list" data-right-sidebar-module-list>
      <TransitionGroup
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
      <div v-if="!orderedModules.length" class="right-sidebar-host-empty">
        <span>暂无显示中的模块</span>
        <button type="button" @click="editingLayout = true">编辑布局</button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { gsap } from 'gsap'
import { computed, onMounted, onUnmounted, ref, shallowRef, watch, type Component } from 'vue'
import { Check, PanelRightOpen, SlidersHorizontal } from 'lucide-vue-next'
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
import ArtifactPanel from './ArtifactPanel.vue'
import type { CoreMessage } from '../types'
import type { LamToolsTransport } from '../transport'

const props = withDefaults(defineProps<{
  title?: string
  storageKey?: string
  projectId?: string | null
  workRoot?: string | null
  sessionId?: string | null
  requestRpc?: RightSidebarRpc
  transport?: LamToolsTransport
  messages?: Array<Pick<CoreMessage, 'metadata' | 'id'> & Partial<Pick<CoreMessage, 'parts'>>>
  contextWindow?: number | null
  runtimeStatus?: string | null
  runtimeModeLabel?: string
  runtimeDetail?: string
  stageOpen?: boolean
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
  activePluginId: null,
  activeModeId: null,
  pluginWidgets: () => [],
  pluginContributions: () => [],
  modules: () => [],
})

const editingLayout = ref(false)
const hostElement = ref<HTMLElement | null>(null)
const remoteWidgetEntries = ref<PluginWidgetEntry[]>([])
const draggingId = ref('')
const dragOverId = ref('')
const loadedComponents = shallowRef(new Map<string, Component>())
const moduleLoadStates = ref<Record<string, { status: 'loading' | 'error'; error?: string }>>({})
let moduleLoadRevision = 0
let hostMotionContext: gsap.Context | null = null
let editorMotionTween: gsap.core.Tween | null = null
let editorMotionRevision = 0

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
      status: props.projectId && props.transport && props.requestRpc ? 'ready' : 'disabled',
      disabledReason: '选择项目后可查看 Artifacts',
      component: ArtifactPanel,
      componentProps: {
        projectId: props.projectId,
        transport: props.transport,
        requestRpc: props.requestRpc,
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
})
watch(() => [props.activePluginId, props.activeModeId], () => { void refreshWidgets() })
watch(() => props.projectId, () => { void refreshWidgets() })
watch(moduleDefinitions, () => { void loadModuleComponents() }, { immediate: true })

onUnmounted(() => {
  editorMotionRevision += 1
  editorMotionTween?.kill()
  editorMotionTween = null
  hostMotionContext?.revert()
  hostMotionContext = null
})

defineExpose({
  layout,
  moduleDefinitions: resolvedModuleDefinitions,
  orderedModules,
  refreshWidgets,
  editingLayout,
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
.right-sidebar-module-list { flex: 1 1 auto; min-height: 0; overflow: auto; }
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
  .right-sidebar-host-edit { transition: none; }
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
