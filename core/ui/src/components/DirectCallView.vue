<script setup lang="ts">
/**
 * DirectCallView — 调用台。
 *
 * 这里的模型来自「设置 → 模型与供应商」，结果能存进资料库，历史按次落盘。
 * 交互跟着模型的输出类型走：文本给提示词与采样参数，图片给尺寸与张数，
 * 视频给时长与比例，音频给声音与格式。
 *
 * user:“该做的你都做一下 把它给打磨成熟”
 * +(文本边跑边出字、失败的一条能单独重跑、历史能筛能翻页、生图工具配好的模型能一键带进来。)
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  AlertCircle,
  ArrowDownToLine,
  Copy,
  Download,
  History,
  Loader2,
  Play,
  RefreshCw,
  RotateCw,
  Sparkles,
  Square,
  Trash2,
} from 'lucide-vue-next'
import { t } from '@/i18n/index.ts'
import UiSelect from '@/components/UiSelect.vue'

type OutputType = 'text' | 'image' | 'video' | 'audio'
type HistoryFilter = 'all' | OutputType

interface DirectModel {
  model_record_id: string
  model_id: string
  display_name: string
  provider_id: string
  provider_name: string
  output_type: OutputType
  capability: string
  context_window: number
  max_output_tokens: number
  temperature: number
  thinking_supported: boolean
  pricing: Record<string, number>
  has_api_key: boolean
  notes: string
}

interface DirectFile {
  path: string
  relative_path?: string
  name: string
  mime_type: string
  kind?: string
}

interface DirectResult {
  index: number
  prompt: string
  status: 'pending' | 'ok' | 'error' | 'cancelled'
  text: string
  files: DirectFile[]
  error: string
  usage: Record<string, number>
  cost?: number | null
  duration_ms: number
}

interface DirectCall {
  id: string
  model_record_id: string
  model_id: string
  display_name: string
  provider_id: string
  provider_name: string
  output_type: OutputType
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  prompts: string[]
  system: string
  params: Record<string, unknown>
  results: DirectResult[]
  error: string
  created_at: string
  started_at: string
  finished_at: string
  finished: boolean
}

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  projectId?: string | null
  workRoot?: string | null
  bandActions?: boolean
}>()

const models = ref<DirectModel[]>([])
const history = ref<DirectCall[]>([])
const selectedModelId = ref('')
const inputText = ref('')
const systemPrompt = ref('')
const activeCall = ref<DirectCall | null>(null)
const loading = ref(false)
const running = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const imagegen = ref<{ configured: boolean; model: string }>({ configured: false, model: '' })
const historyFilter = ref<HistoryFilter>('all')
const historyOffset = ref(0)
const historyHasMore = ref(false)
const referenceUrls = ref('')

const temperature = ref('0.7')
const maxTokens = ref('')
const imageSize = ref('1024x1024')
const imageCount = ref('1')
const videoSeconds = ref('8')
const videoRatio = ref('16:9')
const audioVoice = ref('alloy')
const audioFormat = ref('mp3')

const selectedModel = computed(() => models.value.find(model => model.model_record_id === selectedModelId.value) || null)
const outputType = computed<OutputType>(() => selectedModel.value?.output_type || 'text')
const prompts = computed(() => inputText.value.split('\n').map(line => line.trim()).filter(Boolean))
const promptCount = computed(() => prompts.value.length)
const modelReady = computed(() => Boolean(selectedModel.value?.has_api_key))
const hasImageModel = computed(() => models.value.some(model => model.output_type === 'image'))

const outputOptions: Array<{ value: OutputType; label: string }> = [
  { value: 'text', get label() { return t('文本') } },
  { value: 'image', get label() { return t('图片') } },
  { value: 'video', get label() { return t('视频') } },
  { value: 'audio', get label() { return t('音频') } },
]

const historyFilters: Array<{ value: HistoryFilter; label: string }> = [
  { value: 'all', get label() { return t('全部') } },
  ...outputOptions,
]

const groupedModels = computed(() => {
  const groups = new Map<OutputType, DirectModel[]>()
  for (const model of models.value) {
    const bucket = groups.get(model.output_type) || []
    bucket.push(model)
    groups.set(model.output_type, bucket)
  }
  return outputOptions
    .map(option => ({ ...option, models: groups.get(option.value) || [] }))
    .filter(group => group.models.length > 0)
})

const progressText = computed(() => {
  const results = activeCall.value?.results || []
  if (!results.length) return ''
  const done = results.filter(result => result.status === 'ok' || result.status === 'error' || result.status === 'cancelled').length
  return t('第 {0}/{1} 条', { 0: done, 1: results.length })
})

const sizeOptions = computed(() => [
  { value: '1024x1024', label: '1024 × 1024' },
  { value: '1536x1024', label: '1536 × 1024' },
  { value: '1024x1536', label: '1024 × 1536' },
  { value: '512x512', label: '512 × 512' },
])
const countOptions = ['1', '2', '3', '4'].map(value => ({ value, label: value }))
const secondsOptions = ['4', '8', '12'].map(value => ({ value, label: `${value}s` }))
const ratioOptions = ['16:9', '9:16', '1:1'].map(value => ({ value, label: value }))
const voiceOptions = ['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'].map(value => ({ value, label: value }))
const formatOptions = ['mp3', 'wav', 'opus'].map(value => ({ value, label: value }))

const inputLabel = computed(() => {
  if (outputType.value === 'image') return t('画面描述（每行一条）')
  if (outputType.value === 'video') return t('镜头描述（每行一条）')
  if (outputType.value === 'audio') return t('要朗读的文本（每行一条）')
  return t('输入（每行一条，一次执行多条）')
})

const inputPlaceholder = computed(() => {
  if (outputType.value === 'image') return t('例如：雨夜的便利店门口，霓虹倒映在水洼里')
  if (outputType.value === 'video') return t('例如：镜头从窗外缓慢推进到桌上的咖啡杯')
  if (outputType.value === 'audio') return t('例如：今天的三条进展，第一……')
  return t('例如：用三句话解释什么是向量检索')
})

function outputLabel(value: OutputType): string {
  return outputOptions.find(option => option.value === value)?.label || value
}

function statusLabel(status: DirectCall['status'] | DirectResult['status']): string {
  const labels: Record<string, string> = {
    queued: t('排队中'),
    running: t('执行中'),
    completed: t('已完成'),
    failed: t('失败'),
    cancelled: t('已取消'),
    pending: t('等待'),
    ok: t('完成'),
    error: t('出错'),
  }
  return labels[status] || status
}

/* ---- 参数记忆：同一个模型下次打开还是上次那套 ---- */

const PARAM_STORAGE_KEY = 'lamtools.direct.params'

function readStoredParams(modelId: string): Record<string, unknown> {
  try {
    const all = JSON.parse(window.localStorage.getItem(PARAM_STORAGE_KEY) || '{}')
    const value = all && typeof all === 'object' ? (all as Record<string, unknown>)[modelId] : null
    return value && typeof value === 'object' ? value as Record<string, unknown> : {}
  } catch {
    return {}
  }
}

function writeStoredParams(modelId: string, params: Record<string, unknown>): void {
  try {
    const all = JSON.parse(window.localStorage.getItem(PARAM_STORAGE_KEY) || '{}')
    const next = all && typeof all === 'object' ? all as Record<string, unknown> : {}
    next[modelId] = params
    window.localStorage.setItem(PARAM_STORAGE_KEY, JSON.stringify(next))
  } catch {
    // 存不下不影响本次调用
  }
}

function applyStoredParams(modelId: string): void {
  const stored = readStoredParams(modelId)
  if (typeof stored.temperature === 'number') temperature.value = String(stored.temperature)
  if (typeof stored.max_tokens === 'number') maxTokens.value = String(stored.max_tokens)
  if (typeof stored.size === 'string') imageSize.value = stored.size
  if (typeof stored.n === 'number') imageCount.value = String(stored.n)
  if (typeof stored.seconds === 'number') videoSeconds.value = String(stored.seconds)
  if (typeof stored.aspect_ratio === 'string') videoRatio.value = stored.aspect_ratio
  if (typeof stored.voice === 'string') audioVoice.value = stored.voice
  if (typeof stored.format === 'string') audioFormat.value = stored.format
  if (Array.isArray(stored.reference_urls)) referenceUrls.value = stored.reference_urls.join('\n')
}

/* ---- 数据加载 ---- */

async function loadCatalog(): Promise<void> {
  const result = await props.requestRpc('direct.catalog', { project_id: props.projectId || '' })
  models.value = Array.isArray(result.models) ? result.models as DirectModel[] : []
  const status = result.imagegen
  imagegen.value = status && typeof status === 'object'
    ? { configured: Boolean((status as { configured?: unknown }).configured), model: String((status as { model?: unknown }).model || '') }
    : { configured: false, model: '' }
  if (!models.value.some(model => model.model_record_id === selectedModelId.value)) {
    selectedModelId.value = models.value[0]?.model_record_id || ''
  }
}

async function loadHistory(reset = true): Promise<void> {
  const offset = reset ? 0 : historyOffset.value
  const result = await props.requestRpc('direct.list', {
    limit: 20,
    offset,
    output_type: historyFilter.value === 'all' ? '' : historyFilter.value,
  })
  const calls = Array.isArray(result.calls) ? result.calls as DirectCall[] : []
  history.value = reset ? calls : [...history.value, ...calls]
  historyOffset.value = offset + calls.length
  historyHasMore.value = calls.length === 20
}

async function refreshAll(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    await Promise.all([loadCatalog(), loadHistory(true)])
  } catch (cause) {
    error.value = messageOf(cause)
  } finally {
    loading.value = false
  }
}

function selectModel(model: DirectModel): void {
  selectedModelId.value = model.model_record_id
}

function buildParams(): Record<string, unknown> {
  const params: Record<string, unknown> = {}
  if (outputType.value === 'text') {
    // type=number 的 v-model 会把输入转成数字，这里统一按字符串判断空值。
    const temperatureText = String(temperature.value ?? '')
    const temperatureValue = Number(temperatureText)
    if (temperatureText.trim() && Number.isFinite(temperatureValue)) params.temperature = temperatureValue
    const maxTokensText = String(maxTokens.value ?? '')
    const maxTokensValue = Number(maxTokensText)
    if (maxTokensText.trim() && Number.isFinite(maxTokensValue) && maxTokensValue > 0) params.max_tokens = maxTokensValue
  }
  if (outputType.value === 'image') {
    params.size = imageSize.value
    params.n = Number(imageCount.value) || 1
    const refs = referenceUrls.value.split('\n').map(line => line.trim()).filter(Boolean)
    if (refs.length) params.reference_urls = refs
  }
  if (outputType.value === 'video') {
    params.seconds = Number(videoSeconds.value) || 8
    params.aspect_ratio = videoRatio.value
  }
  if (outputType.value === 'audio') {
    params.voice = audioVoice.value
    params.format = audioFormat.value
  }
  return params
}

async function run(): Promise<void> {
  if (!selectedModel.value || !promptCount.value || running.value) return
  if (!modelReady.value) {
    error.value = t('这个供应商还没有密钥，先到 设置 → 模型与供应商 补上')
    return
  }
  error.value = ''
  notice.value = ''
  const params = buildParams()
  try {
    const result = await props.requestRpc('direct.run', {
      model_ref: selectedModelId.value,
      prompts: prompts.value,
      system: systemPrompt.value,
      params,
      project_id: props.projectId || '',
    })
    writeStoredParams(selectedModelId.value, params)
    activeCall.value = result.call as DirectCall
    running.value = !activeCall.value.finished
    startPolling(activeCall.value.id)
  } catch (cause) {
    error.value = messageOf(cause)
  }
}

let pollTimer: number | null = null

function stopPolling(): void {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function startPolling(callId: string): void {
  stopPolling()
  const tick = async () => {
    try {
      const result = await props.requestRpc('direct.get', { call_id: callId })
      activeCall.value = result.call as DirectCall
      if (activeCall.value?.finished) {
        running.value = false
        pollTimer = null
        await loadHistory(true)
        return
      }
    } catch (cause) {
      error.value = messageOf(cause)
      running.value = false
      return
    }
    // 流式文本会不断落盘，轮询跟着更新就能边跑边看。
    pollTimer = window.setTimeout(tick, 600)
  }
  pollTimer = window.setTimeout(tick, 400)
}

async function cancel(): Promise<void> {
  if (!activeCall.value) return
  try {
    await props.requestRpc('direct.cancel', { call_id: activeCall.value.id })
  } catch (cause) {
    error.value = messageOf(cause)
  }
}

async function retryResult(result: DirectResult): Promise<void> {
  if (!activeCall.value || running.value) return
  try {
    const response = await props.requestRpc('direct.retry', {
      call_id: activeCall.value.id,
      index: result.index,
      project_id: props.projectId || '',
    })
    activeCall.value = response.call as DirectCall
    running.value = !activeCall.value.finished
    startPolling(activeCall.value.id)
  } catch (cause) {
    error.value = messageOf(cause)
  }
}

async function saveToLibrary(): Promise<void> {
  if (!activeCall.value || saving.value) return
  if (!props.projectId) {
    error.value = t('请先选择一个项目，结果才有地方归档')
    return
  }
  saving.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('direct.save', {
      call_id: activeCall.value.id,
      project_id: props.projectId,
    })
    const artifacts = Array.isArray(result.artifacts) ? result.artifacts : []
    notice.value = t('已保存 {0} 份到资料库', { 0: artifacts.length })
  } catch (cause) {
    error.value = messageOf(cause)
  } finally {
    saving.value = false
  }
}

async function importImagegen(): Promise<void> {
  try {
    const result = await props.requestRpc('direct.import_imagegen')
    await refreshAll()
    const modelId = String(result.model_record_id || '')
    if (modelId) selectedModelId.value = modelId
    notice.value = t('已把生图工具的模型带进来')
  } catch (cause) {
    error.value = messageOf(cause)
  }
}

function loadCall(call: DirectCall): void {
  stopPolling()
  running.value = false
  activeCall.value = call
  selectedModelId.value = call.model_record_id
  inputText.value = call.prompts.join('\n')
  systemPrompt.value = call.system || ''
  if (call.params && typeof call.params.temperature === 'number') temperature.value = String(call.params.temperature)
  if (call.params && typeof call.params.max_tokens === 'number') maxTokens.value = String(call.params.max_tokens)
  if (call.params && typeof call.params.size === 'string') imageSize.value = call.params.size
  if (call.params && typeof call.params.n === 'number') imageCount.value = String(call.params.n)
  if (call.params && typeof call.params.voice === 'string') audioVoice.value = call.params.voice
  if (call.params && Array.isArray(call.params.reference_urls)) referenceUrls.value = (call.params.reference_urls as string[]).join('\n')
  notice.value = ''
  error.value = ''
}

async function removeCall(call: DirectCall, event: Event): Promise<void> {
  event.stopPropagation()
  try {
    await props.requestRpc('direct.delete', { call_id: call.id })
    if (activeCall.value?.id === call.id) activeCall.value = null
    await loadHistory(true)
  } catch (cause) {
    error.value = messageOf(cause)
  }
}

async function copyText(value: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(value)
    notice.value = t('已复制')
  } catch {
    notice.value = t('复制失败，请手动选择文本')
  }
}

function fileUrl(file: DirectFile): string {
  const path = file.relative_path || file.path
  if (!path || !props.projectId) return ''
  return `/projects/${encodeURIComponent(props.projectId)}/files/raw?path=${encodeURIComponent(path)}`
}

function isImage(file: DirectFile): boolean {
  return (file.mime_type || '').startsWith('image/')
}

function isVideo(file: DirectFile): boolean {
  return (file.mime_type || '').startsWith('video/')
}

function isAudio(file: DirectFile): boolean {
  return (file.mime_type || '').startsWith('audio/')
}

function usageText(result: DirectResult): string {
  const total = Number(result.usage?.total_tokens || 0)
  const seconds = Math.max(0, Math.round(result.duration_ms / 1000))
  const parts: string[] = []
  if (total) parts.push(t('{0} tokens', { 0: total }))
  if (typeof result.cost === 'number') parts.push(`$${result.cost.toFixed(4)}`)
  if (seconds) parts.push(t('{0} 秒', { 0: seconds }))
  return parts.join(' · ')
}

function messageOf(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause)
}

function onComposerKeydown(event: KeyboardEvent): void {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
    event.preventDefault()
    void run()
  }
}

watch(() => props.projectId, () => {
  activeCall.value = null
  void refreshAll()
})

watch(selectedModelId, (modelId) => {
  if (modelId) applyStoredParams(modelId)
})

watch(historyFilter, () => {
  void loadHistory(true)
})

onMounted(() => { void refreshAll() })
onBeforeUnmount(() => { stopPolling() })
</script>

<template>
  <div class="direct-call full-area-view" data-ui-id="direct-call.root" @keydown="onComposerKeydown">
    <header class="dc-head">
      <div class="dc-heading">
        <span class="dc-mark" aria-hidden="true"><Sparkles :size="16" :stroke-width="1.8" /></span>
        <div>
          <h1>{{ t('调用台') }}</h1>
          <p>{{ t('直接调用模型，不进对话流程；结果可以存进资料库') }}</p>
        </div>
      </div>
      <button class="dc-icon-btn" type="button" :disabled="loading" :title="t('刷新')" @click="refreshAll">
        <RefreshCw :size="15" :stroke-width="1.9" :class="{ 'dc-spin': loading }" />
      </button>
    </header>

    <p v-if="error" class="dc-banner dc-banner--error" role="alert"><AlertCircle :size="14" />{{ error }}</p>
    <p v-else-if="notice" class="dc-banner">{{ notice }}</p>

    <div v-if="!models.length && !loading" class="dc-empty">
      <p>{{ t('还没有可用模型') }}</p>
      <span>{{ t('先到 设置 → 模型与供应商 添加供应商和模型，再回来调用。') }}</span>
      <button v-if="imagegen.configured" class="btn" type="button" data-direct-import-imagegen @click="importImagegen">
        <Download :size="13" />{{ t('把生图工具的模型带进来') }}
      </button>
    </div>

    <div v-else class="dc-layout">
      <aside class="dc-models" :aria-label="t('可用模型')">
        <template v-for="group in groupedModels" :key="group.value">
          <p class="dc-group">{{ group.label }}</p>
          <button
            v-for="model in group.models"
            :key="model.model_record_id"
            type="button"
            class="dc-model"
            :class="{ 'is-active': model.model_record_id === selectedModelId }"
            :data-direct-model="model.model_record_id"
            @click="selectModel(model)"
          >
            <span class="dc-model-name">{{ model.display_name }}</span>
            <span class="dc-model-meta">
              {{ model.provider_name || model.provider_id }}
              <i v-if="!model.has_api_key" class="dc-warn">{{ t('缺密钥') }}</i>
            </span>
          </button>
        </template>
        <button
          v-if="imagegen.configured && !hasImageModel"
          class="dc-import"
          type="button"
          data-direct-import-imagegen
          @click="importImagegen"
        >
          <Download :size="12" />{{ t('导入生图模型') }}
        </button>
      </aside>

      <section class="dc-work">
        <div class="dc-compose">
          <label class="dc-field">
            <span>{{ inputLabel }}</span>
            <textarea
              v-model="inputText"
              class="dc-input"
              rows="6"
              spellcheck="false"
              data-direct-input
              :placeholder="inputPlaceholder"
            />
          </label>

          <details v-if="outputType === 'text'" class="dc-advanced">
            <summary>{{ t('系统提示与采样参数') }}</summary>
            <label class="dc-field">
              <span>{{ t('系统提示') }}</span>
              <textarea v-model="systemPrompt" class="dc-input" rows="2" spellcheck="false" :placeholder="t('选填')" />
            </label>
            <div class="dc-params">
              <label class="dc-field">
                <span>{{ t('温度') }}</span>
                <input v-model="temperature" type="number" min="0" max="2" step="0.1" />
              </label>
              <label class="dc-field">
                <span>{{ t('最大输出') }}</span>
                <input v-model="maxTokens" type="number" min="0" step="512" :placeholder="t('模型默认')" />
              </label>
            </div>
          </details>

          <div v-if="outputType === 'image'" class="dc-params">
            <label class="dc-field">
              <span>{{ t('尺寸') }}</span>
              <UiSelect v-model="imageSize" :options="sizeOptions" :aria-label="t('尺寸')" />
            </label>
            <label class="dc-field">
              <span>{{ t('张数') }}</span>
              <UiSelect v-model="imageCount" :options="countOptions" :aria-label="t('张数')" />
            </label>
          </div>

          <details v-if="outputType === 'image'" class="dc-advanced">
            <summary>{{ t('参考图') }}</summary>
            <label class="dc-field">
              <span>{{ t('每行一个图片地址或项目内路径，最多 4 张') }}</span>
              <textarea v-model="referenceUrls" class="dc-input" rows="2" spellcheck="false" placeholder="https://…/ref.png" />
            </label>
          </details>

          <div v-if="outputType === 'video'" class="dc-params">
            <label class="dc-field">
              <span>{{ t('时长') }}</span>
              <UiSelect v-model="videoSeconds" :options="secondsOptions" :aria-label="t('时长')" />
            </label>
            <label class="dc-field">
              <span>{{ t('画面比例') }}</span>
              <UiSelect v-model="videoRatio" :options="ratioOptions" :aria-label="t('画面比例')" />
            </label>
          </div>

          <div v-if="outputType === 'audio'" class="dc-params">
            <label class="dc-field">
              <span>{{ t('声音') }}</span>
              <UiSelect v-model="audioVoice" :options="voiceOptions" :aria-label="t('声音')" />
            </label>
            <label class="dc-field">
              <span>{{ t('格式') }}</span>
              <UiSelect v-model="audioFormat" :options="formatOptions" :aria-label="t('格式')" />
            </label>
          </div>

          <p v-if="!modelReady" class="dc-hint">{{ t('这个供应商还没有密钥，先到 设置 → 模型与供应商 补上。') }}</p>

          <footer class="dc-actions">
            <span class="dc-count">{{ t('将执行 {0} 条', { 0: promptCount }) }}</span>
            <span v-if="running" class="dc-progress">{{ progressText }}</span>
            <button v-if="running" class="btn dc-stop" type="button" data-direct-cancel @click="cancel">
              <Square :size="13" :stroke-width="2.2" />{{ t('取消') }}
            </button>
            <button v-else class="btn btn--primary" type="button" :disabled="!promptCount || !modelReady" data-direct-run @click="run">
              <Play :size="13" :stroke-width="2.2" />{{ t('运行') }}
            </button>
          </footer>
        </div>

        <div v-if="activeCall" class="dc-results" data-direct-results>
          <header class="dc-results-head">
            <div>
              <strong>{{ activeCall.display_name }}</strong>
              <span>{{ activeCall.provider_name }} · {{ outputLabel(activeCall.output_type) }}</span>
            </div>
            <span class="dc-status" :data-status="activeCall.status">
              <Loader2 v-if="!activeCall.finished" :size="13" class="dc-spin" />
              {{ statusLabel(activeCall.status) }}
            </span>
          </header>

          <p v-if="activeCall.error" class="dc-result-error">{{ activeCall.error }}</p>

          <article
            v-for="result in activeCall.results"
            :key="result.index"
            class="dc-result"
            :data-status="result.status"
          >
            <p class="dc-result-prompt">{{ result.prompt }}</p>
            <pre v-if="result.text" class="dc-result-text">{{ result.text }}</pre>
            <div v-if="result.files.length" class="dc-media">
              <template v-for="file in result.files" :key="file.path">
                <div class="dc-media-item">
                  <img v-if="isImage(file)" :src="fileUrl(file)" :alt="file.name" loading="lazy" />
                  <video v-else-if="isVideo(file)" :src="fileUrl(file)" controls />
                  <audio v-else-if="isAudio(file)" :src="fileUrl(file)" controls />
                  <a v-else :href="fileUrl(file)" target="_blank" rel="noreferrer">{{ file.name }}</a>
                  <a class="dc-download" :href="fileUrl(file)" :download="file.name" :title="t('下载')">
                    <Download :size="13" />
                  </a>
                </div>
              </template>
            </div>
            <p v-if="result.error" class="dc-result-error">{{ result.error }}</p>
            <footer class="dc-result-foot">
              <span>{{ usageText(result) }}</span>
              <span class="dc-result-tools">
                <button
                  v-if="result.status === 'error' || result.status === 'cancelled'"
                  class="dc-text-btn"
                  type="button"
                  :disabled="running"
                  data-direct-retry
                  @click="retryResult(result)"
                >
                  <RotateCw :size="12" />{{ t('重试') }}
                </button>
                <button v-if="result.text" class="dc-text-btn" type="button" @click="copyText(result.text)">
                  <Copy :size="12" />{{ t('复制') }}
                </button>
              </span>
            </footer>
          </article>

          <footer class="dc-results-actions">
            <button
              class="btn"
              type="button"
              :disabled="saving || !activeCall.results.some(result => result.status === 'ok')"
              data-direct-save
              @click="saveToLibrary"
            >
              <ArrowDownToLine :size="13" :stroke-width="2" />{{ saving ? t('保存中') : t('保存到资料库') }}
            </button>
          </footer>
        </div>
      </section>

      <aside class="dc-history" :aria-label="t('调用历史')">
        <header class="dc-history-head">
          <span><History :size="14" :stroke-width="1.9" />{{ t('历史') }}</span>
        </header>
        <div class="dc-history-filters" role="tablist" :aria-label="t('按输出类型筛选')">
          <button
            v-for="item in historyFilters"
            :key="item.value"
            type="button"
            role="tab"
            :aria-selected="historyFilter === item.value"
            :class="{ 'is-on': historyFilter === item.value }"
            @click="historyFilter = item.value"
          >{{ item.label }}</button>
        </div>
        <p v-if="!history.length" class="dc-history-empty">{{ t('还没有调用记录') }}</p>
        <button
          v-for="call in history"
          :key="call.id"
          type="button"
          class="dc-history-item"
          :class="{ 'is-active': activeCall?.id === call.id }"
          :data-direct-history="call.id"
          @click="loadCall(call)"
        >
          <span class="dc-history-name">{{ call.display_name }}</span>
          <span class="dc-history-meta">{{ statusLabel(call.status) }} · {{ call.created_at.replace('T', ' ') }}</span>
          <span class="dc-history-remove" role="button" tabindex="0" :title="t('删除记录')" @click="removeCall(call, $event)">
            <Trash2 :size="12" />
          </span>
        </button>
        <button
          v-if="historyHasMore"
          class="dc-more"
          type="button"
          data-direct-history-more
          @click="loadHistory(false)"
        >{{ t('加载更多') }}</button>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.direct-call {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  container: direct-call / inline-size;
}

.dc-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.dc-heading {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.dc-mark {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: var(--radius-sm);
  background: var(--theme-control-background);
  color: var(--theme-control-text);
  flex: 0 0 auto;
}

.dc-heading h1 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.dc-heading p {
  margin: 2px 0 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--theme-main-text) 58%, transparent);
}

.dc-icon-btn,
.dc-text-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 68%, transparent);
  cursor: pointer;
  padding: 5px 7px;
}

.dc-icon-btn:hover,
.dc-text-btn:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--theme-main-text);
}

.dc-text-btn:disabled {
  opacity: 0.45;
  cursor: default;
}

.dc-banner {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  margin: 0;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: var(--theme-main-soft-background);
  font-size: 12px;
}

.dc-banner--error {
  color: var(--red);
}

.dc-hint {
  margin: var(--space-2) 0 0;
  font-size: 11px;
  color: var(--orange);
}

.dc-empty {
  display: grid;
  place-items: center;
  gap: var(--space-1);
  padding: var(--space-6) var(--space-3);
  border: 1px dashed var(--theme-main-border);
  border-radius: var(--radius);
  text-align: center;
}

.dc-empty p {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.dc-empty span {
  font-size: 12px;
  color: color-mix(in srgb, var(--theme-main-text) 58%, transparent);
}

.dc-layout {
  display: grid;
  grid-template-columns: minmax(150px, 190px) minmax(0, 1fr) minmax(160px, 220px);
  gap: var(--space-3);
  align-items: start;
  min-height: 0;
}

.dc-models,
.dc-history {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: var(--space-2);
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius);
  background: var(--theme-main-soft-background);
}

.dc-group {
  margin: var(--space-2) 0 4px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--theme-main-text) 45%, transparent);
}

.dc-model {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  padding: 6px 8px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.dc-model:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
}

.dc-model.is-active {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-active), transparent);
}

.dc-model-name {
  font-size: 12.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dc-model-meta,
.dc-history-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10.5px;
  color: color-mix(in srgb, var(--theme-main-text) 50%, transparent);
}

.dc-warn {
  font-style: normal;
  color: var(--orange);
}

.dc-import {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: var(--space-2);
  padding: 5px 7px;
  border: 1px dashed var(--theme-main-border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 62%, transparent);
  font-size: 11px;
  cursor: pointer;
}

.dc-import:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--theme-main-text);
}

.dc-work {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-width: 0;
}

.dc-compose,
.dc-results {
  padding: var(--space-3);
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius);
  background: var(--theme-main-background);
  box-shadow: var(--shadow-md);
}

.dc-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
  font-size: 11px;
  color: color-mix(in srgb, var(--theme-main-text) 62%, transparent);
}

.dc-input,
.dc-params input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: var(--theme-composer-background);
  color: var(--theme-composer-text);
  font: inherit;
  font-size: 13px;
  line-height: 1.55;
  resize: vertical;
}

.dc-input:focus,
.dc-params input:focus {
  outline: none;
}

.dc-advanced {
  margin-top: var(--space-2);
}

.dc-advanced summary {
  cursor: pointer;
  font-size: 11px;
  color: color-mix(in srgb, var(--theme-main-text) 55%, transparent);
}

.dc-advanced[open] summary {
  margin-bottom: var(--space-2);
}

.dc-params {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.dc-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.dc-count {
  margin-right: auto;
  font-size: 11px;
  color: color-mix(in srgb, var(--theme-main-text) 52%, transparent);
}

.dc-progress {
  font-size: 11px;
  color: color-mix(in srgb, var(--theme-main-text) 62%, transparent);
}

.dc-stop {
  color: var(--red);
}

.dc-results {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.dc-results-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-2);
}

.dc-results-head strong {
  display: block;
  font-size: 13px;
}

.dc-results-head span {
  font-size: 11px;
  color: color-mix(in srgb, var(--theme-main-text) 52%, transparent);
}

.dc-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: color-mix(in srgb, var(--theme-main-text) 62%, transparent);
}

.dc-status[data-status="failed"],
.dc-status[data-status="cancelled"] {
  color: var(--red);
}

.dc-result {
  padding: var(--space-2);
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 9%, transparent);
  border-radius: var(--radius-sm);
  background: var(--theme-main-soft-background);
}

.dc-result[data-status="error"] {
  border-color: color-mix(in srgb, var(--red) 40%, transparent);
}

.dc-result-prompt {
  margin: 0 0 6px;
  font-size: 11px;
  color: color-mix(in srgb, var(--theme-main-text) 55%, transparent);
  overflow-wrap: anywhere;
}

.dc-result-text {
  margin: 0;
  font-family: var(--font-sans);
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.dc-result-error {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--red);
  overflow-wrap: anywhere;
}

.dc-media {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.dc-media-item {
  position: relative;
  display: inline-block;
  max-width: 100%;
}

.dc-media img,
.dc-media video {
  display: block;
  width: 100%;
  max-width: 520px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--theme-main-border);
}

.dc-media audio {
  width: 100%;
  max-width: 420px;
}

.dc-media a {
  font-size: 12px;
  color: var(--blue);
}

.dc-download {
  position: absolute;
  top: 6px;
  right: 6px;
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-background) 78%, transparent);
  color: var(--theme-main-text) !important;
  opacity: 0;
  transition: opacity 0.12s ease-out;
}

.dc-media-item:hover .dc-download,
.dc-media-item:focus-within .dc-download {
  opacity: 1;
}

.dc-result-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-top: 6px;
  font-size: 10.5px;
  color: color-mix(in srgb, var(--theme-main-text) 45%, transparent);
}

.dc-result-tools {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.dc-results-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--space-1);
}

.dc-history-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 4px 6px;
  font-size: 11px;
  font-weight: 700;
  color: color-mix(in srgb, var(--theme-main-text) 58%, transparent);
}

.dc-history-head span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.dc-history-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  padding-bottom: 6px;
}

.dc-history-filters button {
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 52%, transparent);
  font-size: 10.5px;
  padding: 3px 6px;
  cursor: pointer;
}

.dc-history-filters button:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
}

.dc-history-filters button.is-on {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-active), transparent);
  color: var(--theme-main-text);
}

.dc-history-empty {
  margin: 0;
  padding: var(--space-2) 4px;
  font-size: 11px;
  color: color-mix(in srgb, var(--theme-main-text) 45%, transparent);
}

.dc-history-item {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  padding: 6px 8px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.dc-history-item:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
}

.dc-history-item.is-active {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-active), transparent);
}

.dc-history-name {
  font-size: 12px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dc-history-remove {
  position: absolute;
  top: 6px;
  right: 6px;
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: var(--radius-sm);
  opacity: 0;
  color: color-mix(in srgb, var(--theme-main-text) 55%, transparent);
}

.dc-history-item:hover .dc-history-remove,
.dc-history-item:focus-within .dc-history-remove {
  opacity: 1;
}

.dc-history-remove:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--red);
}

.dc-more {
  margin-top: var(--space-1);
  padding: 5px 7px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 58%, transparent);
  font-size: 11px;
  cursor: pointer;
}

.dc-more:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--theme-main-text);
}

.dc-spin {
  animation: dc-rotate 0.9s linear infinite;
}

@keyframes dc-rotate {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .dc-spin { animation: none; }
}

@container direct-call (max-width: 1080px) {
  .dc-layout {
    grid-template-columns: minmax(140px, 170px) minmax(0, 1fr);
  }

  .dc-history {
    grid-column: 1 / -1;
    max-height: 220px;
    overflow-y: auto;
  }
}

@container direct-call (max-width: 720px) {
  .dc-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .dc-models {
    flex-direction: row;
    flex-wrap: wrap;
    align-items: center;
  }

  .dc-group {
    flex-basis: 100%;
    margin-top: 0;
  }

  .dc-model {
    width: auto;
    padding-inline: 8px;
  }

  .dc-params {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
