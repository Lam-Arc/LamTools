<template>
  <div class="right-sidebar-web-search">
    <!-- 插件被禁用时只说明状态：留一个可点的引擎下拉会把"关掉的搜索"装成还在
         运行，而且它写下去的配置没人会用。 -->
    <template v-if="pluginDisabled">
      <p class="right-sidebar-web-search-message" data-state="disabled">
        搜索插件未启用。到「插件」页启用 websearch 后可用。
      </p>
      <div class="right-sidebar-web-search-health" data-state="unavailable">
        <button class="right-sidebar-web-search-action" type="button" :disabled="healthLoading" @click="recheck">
          <RefreshCw :size="13" :stroke-width="1.8" :class="{ spinning: healthLoading }" aria-hidden="true" />
          <span>重新检查</span>
        </button>
      </div>
    </template>
    <template v-else>
      <div class="right-sidebar-web-search-row">
        <span class="right-sidebar-web-search-label">引擎</span>
        <UiSelect
          v-model="engine"
          :options="engineOptions"
          aria-label="Web Search 引擎"
          :disabled="!requestRpc || loadingConfig"
          @update:model-value="saveEngine"
        />
      </div>
      <div class="right-sidebar-web-search-health" :data-state="connectionState">
        <span class="right-sidebar-web-search-health-dot" aria-hidden="true"></span>
        <span>{{ connectionLabel }}</span>
        <span v-if="latencyMs !== null" class="right-sidebar-web-search-latency">{{ latencyMs }} ms</span>
        <button
          class="right-sidebar-web-search-action"
          type="button"
          :disabled="!requestRpc || healthLoading"
          @click="checkHealth"
        >
          <RefreshCw :size="13" :stroke-width="1.8" :class="{ spinning: healthLoading }" aria-hidden="true" />
          <span>{{ healthLoading ? '检查中…' : '检查连接' }}</span>
        </button>
      </div>
      <p v-if="message" class="right-sidebar-web-search-message" :data-state="connectionState">{{ message }}</p>
      <p v-else-if="!requestRpc" class="right-sidebar-web-search-message">未连接到搜索服务</p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import UiSelect from './UiSelect.vue'
import { getPluginWidget, invokePluginWidget } from '../plugins/api'
import type { PluginWidgetEntry, RightSidebarRpc, RightSidebarWidgetSnapshot } from '../right-sidebar/types'

const props = withDefaults(defineProps<{
  requestRpc?: RightSidebarRpc
  projectId?: string | null
  workRoot?: string | null
  widgetEntry?: PluginWidgetEntry | null
  snapshot?: RightSidebarWidgetSnapshot | null
}>(), {
  requestRpc: undefined,
  projectId: null,
  workRoot: null,
  widgetEntry: null,
  snapshot: null,
})

type ConnectionState = 'unknown' | 'connected' | 'error' | 'unavailable'
const engine = ref('baidu')
const configContent = ref('')
const loadingConfig = ref(false)
const healthLoading = ref(false)
const connectionState = ref<ConnectionState>('unknown')
const latencyMs = ref<number | null>(null)
const message = ref('')
const pluginDisabled = ref(false)

// 只列内置内核：外部内核必须在设置页声明 transport/url，这里放一个没有
// 后端支持的 “Custom” 会把 websearch.jsonc 写成非法内核，之后每轮对话都
// 在工具箱装配阶段失败（2026-09-26 事故）。
const engineOptions = [
  { value: 'baidu', label: 'Baidu' },
  { value: 'bing', label: 'Bing' },
  { value: 'ddg', label: 'DuckDuckGo' },
]

const connectionLabel = computed(() => {
  switch (connectionState.value) {
    case 'connected': return '已连接'
    case 'error': return '连接异常'
    case 'unavailable': return '不可用'
    default: return '未检查'
  }
})

function parseConfig(value: string): Record<string, unknown> {
  if (!value.trim()) return {}
  try {
    // Config is JSONC.  This intentionally handles comments only; values are
    // still parsed as JSON and are never evaluated as code.
    const withoutComments = value
      .replace(/\/\/.*$/gm, '')
      .replace(/\/\*[\s\S]*?\*\//g, '')
    const parsed = JSON.parse(withoutComments)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

function readSnapshot(result: Record<string, unknown>): RightSidebarWidgetSnapshot | null {
  const candidate = result.snapshot || result.result || result.widget || result
  if (!candidate || typeof candidate !== 'object') return null
  const value = candidate as RightSidebarWidgetSnapshot
  const blocks = Array.isArray(value.blocks) ? value.blocks : []
  return { ...value, blocks, schemaVersion: value.schemaVersion ?? value.schema_version ?? 1 }
}

async function loadConfig(): Promise<void> {
  if (!props.requestRpc) {
    connectionState.value = 'unavailable'
    return
  }
  loadingConfig.value = true
  try {
    const result = await props.requestRpc('websearch.config.get', {})
    configContent.value = String(result.content || '')
    const configured = parseConfig(configContent.value).provider
    if (typeof configured === 'string' && engineOptions.some((item) => item.value === configured)) engine.value = configured
  } catch {
    // Configuration is optional; health still gives the user a direct signal.
  } finally {
    loadingConfig.value = false
  }
}

async function loadSnapshot(): Promise<void> {
  if (!props.requestRpc) return
  try {
    const result = props.widgetEntry
      ? await getPluginWidget(props.requestRpc, {
        pluginId: props.widgetEntry.pluginId,
        widgetId: props.widgetEntry.id,
        projectId: props.projectId,
        workRoot: props.workRoot,
      })
      : await props.requestRpc('websearch.widget.snapshot', {
        project_id: props.projectId ?? undefined,
        work_root: props.workRoot ?? undefined,
      })
    const snapshot = readSnapshot(result)
    const state = snapshot?.state
    if (state === 'ok') connectionState.value = 'connected'
    else if (state === 'error') connectionState.value = 'error'
    if (typeof snapshot?.summary === 'string') message.value = snapshot.summary
    pluginDisabled.value = false
  } catch (cause) {
    // A missing optional widget operation should not turn the host into an
    // error page; the explicit health action remains available.
    if (isUnsupportedMethod(cause)) pluginDisabled.value = true
    connectionState.value = 'unavailable'
  }
}

/** 插件被禁用时它的操作整体不存在——"方法不存在"就是"未启用"的可靠信号；
 *  网络/超时之类的失败仍按"不可用"处理，不误报成未启用。 */
function isUnsupportedMethod(cause: unknown): boolean {
  const text = cause instanceof Error ? cause.message : String(cause ?? '')
  return /unsupported method/i.test(text)
}

async function recheck(): Promise<void> {
  pluginDisabled.value = false
  await loadConfig()
  await loadSnapshot()
}

async function saveEngine(value: string): Promise<void> {
  engine.value = value
  if (!props.requestRpc) return
  const config = parseConfig(configContent.value)
  config.provider = value
  loadingConfig.value = true
  message.value = ''
  try {
    await props.requestRpc('websearch.config.update', { content: JSON.stringify(config, null, 2) })
    configContent.value = JSON.stringify(config, null, 2)
  } catch (cause) {
    message.value = cause instanceof Error ? cause.message : String(cause)
    connectionState.value = 'error'
  } finally {
    loadingConfig.value = false
  }
}

async function checkHealth(): Promise<void> {
  if (!props.requestRpc || healthLoading.value) return
  healthLoading.value = true
  message.value = ''
  const started = typeof performance !== 'undefined' ? performance.now() : Date.now()
  try {
    let result: Record<string, unknown>
    const entry = props.widgetEntry
    const action = entry?.actions?.find((item) => item.id === 'test') || entry?.actions?.[0]
    if (entry && action) {
      result = await invokePluginWidget(props.requestRpc, {
        pluginId: entry.pluginId,
        widgetId: entry.id,
        actionId: action.id,
        projectId: props.projectId,
        workRoot: props.workRoot,
        input: { query: 'OpenAI' },
      })
    } else {
      result = await props.requestRpc('websearch.widget.health', {
        query: 'OpenAI',
        project_id: props.projectId ?? undefined,
        work_root: props.workRoot ?? undefined,
      })
    }
    const health = result.result && typeof result.result === 'object'
      ? result.result as Record<string, unknown>
      : result
    const state = String(health.state || (result.status === 'ok' ? 'ok' : ''))
    connectionState.value = state === 'ok' ? 'connected' : 'error'
    const elapsed = (typeof performance !== 'undefined' ? performance.now() : Date.now()) - started
    latencyMs.value = Math.max(0, Math.round(elapsed))
    if (state !== 'ok' && health.error) message.value = String(health.error)
    else if (health.provider) message.value = `当前内核：${String(health.provider)}`
    else message.value = '搜索服务响应正常'
  } catch (cause) {
    connectionState.value = 'error'
    latencyMs.value = null
    message.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    healthLoading.value = false
  }
}

onMounted(() => {
  void loadConfig()
  if (props.snapshot) {
    const state = props.snapshot.state
    connectionState.value = state === 'ok' ? 'connected' : state === 'error' ? 'error' : 'unknown'
    message.value = props.snapshot.message || ''
  } else {
    void loadSnapshot()
  }
})
</script>

<style scoped>
.right-sidebar-web-search { display: grid; gap: var(--space-2); min-width: 0; }
.right-sidebar-web-search-row,
.right-sidebar-web-search-health { display: flex; align-items: center; gap: var(--space-2); min-width: 0; }
.right-sidebar-web-search-label { flex: 0 0 auto; color: color-mix(in srgb, var(--theme-backdrop-text) 58%, transparent); font-size: 11px; }
.right-sidebar-web-search-row .ui-select { min-width: 0; flex: 1 1 auto; }
.right-sidebar-web-search-row :deep(.ui-select-trigger) { min-height: 30px; color: var(--theme-control-text); background: color-mix(in srgb, var(--theme-control-background) 70%, transparent); }
.right-sidebar-web-search-health { min-height: 30px; color: color-mix(in srgb, var(--theme-backdrop-text) 72%, transparent); font-size: 12px; }
.right-sidebar-web-search-health-dot { width: 7px; height: 7px; flex: 0 0 auto; border-radius: 50%; background: color-mix(in srgb, var(--theme-backdrop-text) 42%, transparent); }
.right-sidebar-web-search-health[data-state="connected"] .right-sidebar-web-search-health-dot { background: var(--green); }
.right-sidebar-web-search-health[data-state="error"] .right-sidebar-web-search-health-dot { background: var(--red); }
.right-sidebar-web-search-health[data-state="unavailable"] .right-sidebar-web-search-health-dot { background: var(--orange); }
.right-sidebar-web-search-latency { margin-left: auto; color: color-mix(in srgb, var(--theme-backdrop-text) 48%, transparent); font-family: var(--font-mono); font-size: 11px; }
.right-sidebar-web-search-action { display: inline-flex; align-items: center; gap: var(--space-1); min-height: 30px; padding: 0 var(--space-2); border: 1px solid color-mix(in srgb, var(--theme-control-text) 14%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-control-background) 70%, transparent); color: var(--theme-control-text); font-size: 11px; }
.right-sidebar-web-search-action:hover { background: color-mix(in srgb, var(--theme-control-text) var(--alpha-hover), var(--theme-control-background)); }
.right-sidebar-web-search-action:active { background: color-mix(in srgb, var(--theme-control-text) var(--alpha-active), var(--theme-control-background)); }
.right-sidebar-web-search-action:disabled { opacity: .45; cursor: default; }
.right-sidebar-web-search-action .spinning { animation: right-sidebar-spin .8s linear infinite; }
.right-sidebar-web-search-message { margin: 0; color: color-mix(in srgb, var(--theme-backdrop-text) 52%, transparent); font-size: 11px; line-height: 1.45; }
.right-sidebar-web-search-message[data-state="error"] { color: color-mix(in srgb, var(--red) 72%, var(--theme-backdrop-text) 28%); }
@keyframes right-sidebar-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .right-sidebar-web-search-action .spinning { animation: none; } }
</style>
