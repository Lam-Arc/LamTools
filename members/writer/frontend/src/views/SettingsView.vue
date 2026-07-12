<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  PROVIDER_PRESETS,
  SettingsShell,
  ThemeEditor,
  UiSelect,
  type ProviderPreset,
  type ThemeArea,
  type ThemePreset,
  type ThemeStop,
} from '@lamtools/ui'
import { useConfigStore } from '@/stores/config'
import type { AgentCapability, SubAgentDefinition, ToolCapability, ProviderUpdate } from '@/types'
import { defaultTheme, normalizeColor, clampNumber, normalizeGradientStops, gradientFromStops } from '@/lib/theme'

const router = useRouter()
const configStore = useConfigStore()

type AgentSetting = {
  name: string
  label: string
  type: 'agent'
  description: string
  capabilities: string[]
  network: boolean
  nested: boolean
  modes: string[]
  aliases: string[]
  maxDepth: number
  enabled: boolean
}
type SubAgentSetting = {
  name: string
  label: string
  description: string
  role: string
  developerInstructions: string
  tools: string[]
  model: string
  maxToolRounds: number
  aliases: string[]
  source: string
  enabled: boolean
}
type AgentFlowNode = {
  id: string
  label: string
  note: string
}
type AgentFlowVariant = {
  id: string
  title: string
  condition: string
  nodes: AgentFlowNode[]
}
type ToolSetting = {
  name: string
  description: string
  risk: string
  enabled: boolean
}
type CommandPolicy = 'auto_allow' | 'ask_user'
type WriterThemePreset = ThemePreset & { theme: Partial<typeof defaultTheme> }

const selectedProviderId = ref('')
const selectedModelId = ref('')
const noticeText = ref('')
const modelRouting = ref<Record<string, { mode: string; model_id?: string | null }>>({})

const showProviderForm = ref(false)
const editingProvider = ref<string | null>(null)
const provName = ref('')
const provApiType = ref('openai')
const provBaseUrl = ref('')
const provApiKey = ref('')
const provAdapterProfile = ref('')
const provExtraJson = ref('')
const provPresetId = ref('')
const provPresetModelId = ref('')
const provCreateDefaultModel = ref(true)

const showModelForm = ref(false)
const editingModel = ref<string | null>(null)
const modelProviderId = ref('')
const modelModelId = ref('')
const modelDisplayName = ref('')
const modelContextWindow = ref(128000)
const modelMaxOutput = ref(16384)
const modelThinkingSupported = ref(false)
const modelThinkingBudget = ref(10000)
const modelTemperature = ref(0.7)
const modelAdapterProfile = ref('')
const modelExtraJson = ref('')

const apiTypeOptions = [
  { value: 'openai', label: 'OpenAI Compatible' },
  { value: 'anthropic', label: 'Anthropic Compatible' },
]

const adapterProfileOptions = computed(() => [
  { value: '', label: '自动匹配' },
  ...configStore.adapterProfiles.map(profile => ({
    value: profile.id,
    label: profile.label ? `${profile.label} (${profile.id})` : profile.id,
  })),
])

const qualityModeOptions = [
  { value: 'auto', label: 'auto' },
  { value: 'toy', label: 'toy' },
  { value: 'low', label: 'low' },
  { value: 'medium', label: 'medium' },
  { value: 'high', label: 'high' },
  { value: 'crazy', label: 'crazy' },
]

const densityOptions = [
  { value: 'compact', label: '紧凑' },
  { value: 'standard', label: '标准' },
  { value: 'loose', label: '宽松' },
]

const baseRoutePurposes = [
  { taskType: 'writer', label: 'Writer 主模型', note: '主循环执行任务时使用；其他 Agent 未指定时跟随它' },
  { taskType: 'sub_agent', label: 'Sub Agent 通用模型', note: '所有子代理的通用配置；留空则跟随 Writer 主模型' },
]

const settingsSections = [
  { id: 'model-api', label: '模型与供应商', icon: '◇' },
  { id: 'ui-system', label: '界面外观', icon: '▯' },
  { id: 'permissions', label: '权限状态', icon: '✓' },
]

const baselineAgents: AgentCapability[] = [
  {
    name: 'architecture',
    description: 'Design software/application architecture and return an implementation handoff.',
    aliases: [],
    modes: ['auto', 'toy', 'low', 'medium', 'high', 'crazy', 'max'],
    capabilities: ['architecture_design', 'candidate_scoring', 'runtime_feasibility'],
    can_parallel: false,
    can_call_agents: false,
    max_depth: 0,
    enabled: true,
  },
  {
    name: 'sub',
    description: 'Run a generic sub-agent for a delegated role and task.',
    aliases: [],
    modes: ['auto', 'low', 'medium', 'high'],
    capabilities: ['delegated_reasoning', 'focused_handoff'],
    can_parallel: true,
    can_call_agents: false,
    max_depth: 1,
    enabled: true,
  },
]

const writerDefaults = ref({
  qualityMode: 'auto',
})

const projectDefaults = ref({
  workRoot: 'E:\\writertest',
})

const agentRows = ref<AgentSetting[]>([])
const subAgentRows = ref<SubAgentSetting[]>([])
const toolRows = ref<ToolSetting[]>([])
const selectedAgentName = ref('')
const selectedSubAgentName = ref('')
const subAgentDraft = ref({
  name: '',
  description: '',
  role: '',
  developerInstructions: '',
  toolsText: '',
  model: '',
  maxToolRounds: 3,
  aliasesText: '',
})
const subAgentSaving = ref(false)
const commandPolicies = ref<Record<'regular' | 'dangerous', CommandPolicy>>({
  regular: 'auto_allow',
  dangerous: 'auto_allow',
})

const writerThemePresets: WriterThemePreset[] = [
  {
    id: 'writer-default-light',
    group: 'solid',
    name: '默认亮色',
    note: '暖白纸面层级，适合日间。',
    method: '主界面保持 #f8f8ef，背景、输入栏和控件提升到接近 A4 纸的暖白纯色。',
    rationale: '默认亮色是跨成员基线，强调稳定、清晰和可读，避免灰底在暖白主面旁显脏。',
    theme: {
      backdropStart: '#f2f1e8',
      backdropEnd: '#f2f1e8',
      backdropStops: [
        { color: '#f2f1e8', position: 0 },
        { color: '#f2f1e8', position: 100 },
      ],
      backdropAngle: 180,
      backdropText: '#1f1f1f',
      mainSurface: '#f8f7f3',
      mainSurfaceEnd: '#f8f8ef',
      mainStops: [
        { color: '#f8f8ef', position: 0 },
        { color: '#f8f8ef', position: 100 },
      ],
      mainAngle: 180,
      mainText: '#1f1f1f',
      mainOpacity: 1,
      composerSurface: '#fffefa',
      composerSurfaceEnd: '#fffefa',
      composerStops: [
        { color: '#fffefa', position: 0 },
        { color: '#fffefa', position: 100 },
      ],
      composerAngle: 180,
      composerText: '#1f1f1f',
      composerOpacity: 1,
      controlSurface: '#fbfaf4',
      controlSurfaceEnd: '#fbfaf4',
      controlStops: [
        { color: '#fbfaf4', position: 0 },
        { color: '#fbfaf4', position: 100 },
      ],
      controlAngle: 180,
      controlText: '#1f1f1f',
      controlOpacity: 1,
    },
  },
  {
    id: 'writer-default-dark',
    group: 'solid',
    name: '默认暗色',
    note: '通用黑灰层级，适合夜间。',
    method: '按通用暗色方案使用 #111111、#202020、#404040，保持清晰层级。',
    rationale: '默认暗色是跨成员基线，不引入成员品牌色。',
    theme: {
      backdropStart: '#202020',
      backdropEnd: '#202020',
      backdropStops: [
        { color: '#202020', position: 0 },
        { color: '#202020', position: 100 },
      ],
      backdropAngle: 180,
      backdropText: '#f5f5f5',
      mainSurface: '#111111',
      mainSurfaceEnd: '#111111',
      mainStops: [
        { color: '#111111', position: 0 },
        { color: '#111111', position: 100 },
      ],
      mainAngle: 180,
      mainText: '#f5f5f5',
      mainOpacity: 1,
      composerSurface: '#404040',
      composerSurfaceEnd: '#404040',
      composerStops: [
        { color: '#404040', position: 0 },
        { color: '#404040', position: 100 },
      ],
      composerAngle: 180,
      composerText: '#f5f5f5',
      composerOpacity: 1,
      controlSurface: '#404040',
      controlSurfaceEnd: '#404040',
      controlStops: [
        { color: '#404040', position: 0 },
        { color: '#404040', position: 100 },
      ],
      controlAngle: 180,
      controlText: '#f5f5f5',
      controlOpacity: 1,
    },
  },
]

const uiSystem = ref({
  density: 'standard',
  contentWidth: 780,
  showGitGraph: true,
  showRuntime: true,
  theme: { ...defaultTheme },
})

const contentWidthText = computed(() => `${uiSystem.value.contentWidth}px`)
const themePreviewStyle = computed(() => ({
  background: gradientFromStops(uiSystem.value.theme.backdropAngle, uiSystem.value.theme.backdropStops, 1),
  color: uiSystem.value.theme.backdropText,
}))
const themePreviewMainStyle = computed(() => ({
  background: gradientFromStops(
    uiSystem.value.theme.mainAngle,
    uiSystem.value.theme.mainStops,
    uiSystem.value.theme.mainOpacity,
  ),
  color: uiSystem.value.theme.mainText,
}))
const themePreviewComposerStyle = computed(() => ({
  background: gradientFromStops(
    uiSystem.value.theme.composerAngle,
    uiSystem.value.theme.composerStops,
    uiSystem.value.theme.composerOpacity,
  ),
  color: uiSystem.value.theme.composerText,
}))
const themePreviewControlStyle = computed(() => ({
  background: gradientFromStops(
    uiSystem.value.theme.controlAngle,
    uiSystem.value.theme.controlStops,
    uiSystem.value.theme.controlOpacity,
  ),
  color: uiSystem.value.theme.controlText,
}))
const settingsThemeStyle = computed(() => ({
  '--settings-backdrop-background': gradientFromStops(uiSystem.value.theme.backdropAngle, uiSystem.value.theme.backdropStops, 1),
  '--settings-backdrop-text': uiSystem.value.theme.backdropText,
  '--settings-main-background': gradientFromStops(
    uiSystem.value.theme.mainAngle,
    uiSystem.value.theme.mainStops,
    uiSystem.value.theme.mainOpacity,
  ),
  '--settings-main-text': uiSystem.value.theme.mainText,
  '--settings-card-background': gradientFromStops(
    uiSystem.value.theme.composerAngle,
    uiSystem.value.theme.composerStops,
    Math.max(0.92, uiSystem.value.theme.composerOpacity),
  ),
  '--settings-card-text': uiSystem.value.theme.composerText,
  '--settings-control-background': gradientFromStops(
    uiSystem.value.theme.controlAngle,
    uiSystem.value.theme.controlStops,
    uiSystem.value.theme.controlOpacity,
  ),
  '--settings-control-text': uiSystem.value.theme.controlText,
}))

const localSettingKeys = {
  writerDefaults: 'lamwriter.settings.writerDefaults',
  projectDefaults: 'lamwriter.settings.projectDefaults',
  uiSystem: 'lamwriter.ui',
}
const legacyUiSystemKey = 'lamwriter.settings.uiSystem'
let settingsHydrated = false
let saveTimers: Record<string, number | undefined> = {}

const selectedProvider = computed(() => (
  configStore.providers.find((p) => p.id === selectedProviderId.value) || configStore.providers[0] || null
))

const selectedModel = computed(() => (
  configStore.models.find((m) => m.id === selectedModelId.value) || configStore.models[0] || null
))

const modelsForSelectedProvider = computed(() => {
  const provider = selectedProvider.value
  if (!provider) return []
  return configStore.models.filter((m) => m.provider_id === provider.id)
})

const routePurposes = computed(() => [
  ...baseRoutePurposes,
  ...agentRows.value.map((agent) => ({
    taskType: `${agent.name}_agent`,
    label: agent.label,
    note: agent.enabled ? `${agent.description}` : '已停用，不参与运行',
  })),
  ...subAgentRows.value.map((agent) => ({
    taskType: `sub_agent:${agent.name}`,
    label: agent.label,
    note: agent.description || `${agent.role} 子代理`,
  })),
])

const providerPresets: ProviderPreset[] = PROVIDER_PRESETS

const providerPresetOptions = [
  { value: '', label: '手动配置' },
  ...providerPresets.map(preset => ({ value: preset.id, label: preset.label })),
]

const selectedProviderPreset = computed(() => providerPresets.find(preset => preset.id === provPresetId.value) || null)
const providerPresetModelOptions = computed(() => (
  selectedProviderPreset.value?.models.map(model => ({
    value: model.modelId,
    label: `${model.displayName} · ${Math.round(model.contextWindow / 1000)}k`,
  })) ?? []
))

watch(provPresetId, (presetId) => {
  applyProviderPreset(presetId)
})

const selectedAgent = computed(() => (
  agentRows.value.find((agent) => agent.name === selectedAgentName.value) || agentRows.value[0] || null
))

const selectedSubAgent = computed(() => (
  subAgentRows.value.find((agent) => agent.name === selectedSubAgentName.value) || subAgentRows.value[0] || null
))

const canDeleteSelectedSubAgent = computed(() => selectedSubAgent.value?.source === 'project')

const selectedAgentFlowVariants = computed((): AgentFlowVariant[] => {
  if (!selectedAgent.value) return []
  const name = selectedAgent.value.name
  const flows: Record<string, AgentFlowVariant[]> = {
    architecture: [
      {
        id: 'standard',
        title: '标准路径',
        condition: 'medium / high / crazy 使用完整架构链路；适合影响多模块、需要比较方案或需要明确验收合同的任务。',
        nodes: [
          { id: 'intake_input', label: '输入整理', note: '读取任务、模式和硬约束' },
          { id: 'route_task', label: '任务路由', note: '判断任务类型和设计深度' },
          { id: 'frame_problem', label: '问题界定', note: '整理目标、非目标、约束和验收' },
          { id: 'generate_candidates', label: '候选架构', note: '生成多个可落地方案' },
          { id: 'select_architecture', label: '方案选择', note: '评分、取舍并选定方案' },
          { id: 'elaborate_architecture', label: '架构展开', note: '展开模块、数据流、交互和边界' },
          { id: 'review_architecture', label: '质量评审', note: '检查美感、复杂度位置和可执行性；不合格会返工' },
          { id: 'build_outputs', label: '生成交付', note: '输出设计报告、handoff 和验收合同' },
        ],
      },
      {
        id: 'compact',
        title: '轻量路径',
        condition: 'toy / low 会合并前置判断，减少轮次；适合小改动、单点功能或用户明确要求快速落地的任务。',
        nodes: [
          { id: 'intake_input', label: '输入整理', note: '读取任务、模式和硬约束' },
          { id: 'route_and_frame', label: '路由并界定', note: '一次完成任务类型、边界和验收整理' },
          { id: 'generate_candidates', label: '候选架构', note: '通常只保留一个最稳妥方案' },
          { id: 'elaborate_architecture', label: '架构展开', note: '只展开必要模块和数据流' },
          { id: 'review_architecture', label: '质量评审', note: '低成本检查；必要时返工' },
          { id: 'build_outputs', label: '生成交付', note: '输出简版 handoff' },
        ],
      },
    ],
    sub: [
      {
        id: 'delegated',
        title: '命名子代理路径',
        condition: '主循环按任务选择 explorer、worker、reviewer 或项目自定义 agent；定义文件决定工具、模型和专用指令。',
        nodes: [
          { id: 'choose_agent', label: '选择子代理', note: '按 description 匹配任务' },
          { id: 'load_definition', label: '加载定义', note: '读取工具、模型、轮次和专用指令' },
          { id: 'bounded_context', label: '限定上下文', note: '只携带必要资料和边界' },
          { id: 'focused_work', label: '专项处理', note: '按定义范围调用工具' },
          { id: 'handoff', label: '回传结果', note: '以结构化 JSON 交回主循环' },
        ],
      },
    ],
  }
  return flows[name] || [
    {
      id: 'default',
      title: '默认路径',
      condition: '后端未提供专用说明时使用通用 Agent 展示。',
      nodes: [
        { id: 'input', label: '输入', note: '任务' },
        { id: 'run', label: '处理', note: 'Agent 执行' },
        { id: 'output', label: '输出', note: '结果' },
      ],
    },
  ]
})

const selectedAgentFlowTitle = computed(() => (
  !selectedAgent.value
    ? 'Agent 流程图'
    : selectedAgent.value.name === 'architecture' ? '架构 Agent 运行逻辑' : `${selectedAgent.value.label} 运行逻辑`
))

function selectAgent(name: string) {
  selectedAgentName.value = name
}

function selectSubAgent(name: string) {
  selectedSubAgentName.value = name
  syncSubAgentDraft()
}

onMounted(async () => {
  await loadPersistedSettings()
  await Promise.all([
    configStore.fetchProviders(),
    configStore.fetchModels(),
    configStore.fetchResolvedConfig('writer'),
    configStore.fetchAdapterProfiles(),
    loadRuntimeCapabilities(),
  ])
  await loadModelRouting()
  selectedProviderId.value = configStore.providers[0]?.id || ''
  selectedModelId.value = configStore.models[0]?.id || ''
})

watch(writerDefaults, () => saveLocalSetting(localSettingKeys.writerDefaults, writerDefaults.value), { deep: true })
watch(projectDefaults, () => saveLocalSetting(localSettingKeys.projectDefaults, projectDefaults.value), { deep: true })
watch(uiSystem, () => {
  saveLocalSetting(localSettingKeys.uiSystem, uiSystem.value)
}, { deep: true })

async function loadPersistedSettings() {
  await Promise.all([
    applyRemoteSetting(localSettingKeys.writerDefaults, writerDefaults.value),
    applyRemoteSetting(localSettingKeys.projectDefaults, projectDefaults.value),
    applyRemoteSetting(localSettingKeys.uiSystem, uiSystem.value),
  ])
  settingsHydrated = true
}

async function applyRemoteSetting<T extends object>(namespace: string, target: T) {
  try {
    const setting = await configStore.fetchAppSetting(namespace)
    if (setting.value && Object.keys(setting.value).length > 0) {
      applySettingValue(target, setting.value)
      return
    }
    applyLocalSetting(namespace, target)
  } catch {
    applyLocalSetting(namespace, target)
  }
}

function applySettingValue<T extends object>(target: T, value: Record<string, unknown>) {
  Object.assign(target, value)
  if (target === uiSystem.value) {
    uiSystem.value.theme = { ...defaultTheme, ...(value.theme || {}) }
    migrateLegacyDefaultTheme()
    normalizeThemeSettings()
  }
}

async function loadRuntimeCapabilities() {
  try {
    const capabilities = await configStore.fetchRuntimeCapabilities(projectDefaults.value.workRoot)
    applyCommandPolicies(capabilities.command_policies || {})
    agentRows.value = mergeAgentSettings(capabilities.agents?.length ? capabilities.agents : baselineAgents)
    subAgentRows.value = mergeSubAgentSettings(capabilities.subagents || [])
    toolRows.value = mergeToolSettings(capabilities.tools)
    if (!selectedAgentName.value || !agentRows.value.some((agent) => agent.name === selectedAgentName.value)) {
      selectedAgentName.value = agentRows.value[0]?.name || ''
    }
    if (!selectedSubAgentName.value || !subAgentRows.value.some((agent) => agent.name === selectedSubAgentName.value)) {
      selectedSubAgentName.value = subAgentRows.value[0]?.name || ''
    }
    syncSubAgentDraft()
  } catch {
    applyCommandPolicies({})
    agentRows.value = mergeAgentSettings(baselineAgents)
    subAgentRows.value = []
    toolRows.value = mergeToolSettings([])
    selectedAgentName.value = agentRows.value[0]?.name || ''
    syncSubAgentDraft()
  }
}

function applyCommandPolicies(policies: Record<string, string>) {
  commandPolicies.value = {
    regular: normalizeCommandPolicy(policies.regular, 'auto_allow'),
    dangerous: normalizeCommandPolicy(policies.dangerous, 'auto_allow'),
  }
}

function normalizeCommandPolicy(value: string | undefined, fallback: CommandPolicy): CommandPolicy {
  return value === 'ask_user' || value === 'auto_allow' ? value : fallback
}

function normalizeContentWidth() {
  const next = Math.min(1120, Math.max(560, Number(uiSystem.value.contentWidth) || 780))
  if (next !== uiSystem.value.contentWidth) uiSystem.value.contentWidth = next
}

function normalizeThemeSettings() {
  const theme = uiSystem.value.theme
  theme.backdropStart = normalizeColor(theme.backdropStart, defaultTheme.backdropStart)
  theme.backdropEnd = normalizeColor(theme.backdropEnd, defaultTheme.backdropEnd)
  theme.backdropStops = normalizeGradientStops(theme.backdropStops, theme.backdropStart, theme.backdropEnd)
  theme.backdropText = normalizeColor(theme.backdropText, defaultTheme.backdropText)
  theme.mainSurface = normalizeColor(theme.mainSurface, defaultTheme.mainSurface)
  theme.mainSurfaceEnd = normalizeColor(theme.mainSurfaceEnd, defaultTheme.mainSurfaceEnd)
  theme.mainStops = normalizeGradientStops(theme.mainStops, theme.mainSurface, theme.mainSurfaceEnd)
  theme.mainText = normalizeColor(theme.mainText, defaultTheme.mainText)
  theme.composerSurface = normalizeColor(theme.composerSurface, defaultTheme.composerSurface)
  theme.composerSurfaceEnd = normalizeColor(theme.composerSurfaceEnd, defaultTheme.composerSurfaceEnd)
  theme.composerStops = normalizeGradientStops(theme.composerStops, theme.composerSurface, theme.composerSurfaceEnd)
  theme.composerText = normalizeColor(theme.composerText, defaultTheme.composerText)
  theme.controlSurface = normalizeColor(theme.controlSurface, theme.composerSurface)
  theme.controlSurfaceEnd = normalizeColor(theme.controlSurfaceEnd, theme.composerSurfaceEnd)
  theme.controlStops = normalizeGradientStops(theme.controlStops, theme.controlSurface, theme.controlSurfaceEnd)
  theme.controlText = normalizeColor(theme.controlText, theme.composerText)
  theme.backdropAngle = clampNumber(theme.backdropAngle, 0, 360, defaultTheme.backdropAngle)
  theme.mainAngle = clampNumber(theme.mainAngle, 0, 360, defaultTheme.mainAngle)
  theme.mainOpacity = clampNumber(theme.mainOpacity, 0.1, 1, defaultTheme.mainOpacity)
  theme.composerAngle = clampNumber(theme.composerAngle, 0, 360, defaultTheme.composerAngle)
  theme.composerOpacity = clampNumber(theme.composerOpacity, 0.1, 1, defaultTheme.composerOpacity)
  theme.controlAngle = clampNumber(theme.controlAngle, 0, 360, theme.composerAngle)
  theme.controlOpacity = clampNumber(theme.controlOpacity, 0.1, 1, theme.composerOpacity)
}

function isSolidStops(stops: ThemeStop[], color: string) {
  return stops.length === 2 && stops.every((stop) => stop.color.toLowerCase() === color.toLowerCase())
}

function migrateLegacyDefaultTheme() {
  const theme = uiSystem.value.theme
  if (
    theme.backdropAngle === 180
    && theme.backdropStart === '#000000'
    && theme.backdropEnd === '#000000'
    && isSolidStops(theme.backdropStops, '#000000')
    && theme.mainAngle === 180
    && theme.mainSurface === '#202020'
    && theme.mainSurfaceEnd === '#202020'
    && isSolidStops(theme.mainStops, '#202020')
    && theme.mainOpacity === 1
  ) {
    theme.backdropStart = defaultTheme.backdropStart
    theme.backdropEnd = defaultTheme.backdropEnd
    theme.backdropStops = defaultTheme.backdropStops.map((stop) => ({ ...stop }))
    theme.mainSurface = defaultTheme.mainSurface
    theme.mainSurfaceEnd = defaultTheme.mainSurfaceEnd
    theme.mainStops = defaultTheme.mainStops.map((stop) => ({ ...stop }))
  }
  if (
    theme.backdropAngle === 180
    && theme.backdropStart === '#dfdfdf'
    && theme.backdropEnd === '#dfdfdf'
    && isSolidStops(theme.backdropStops, '#dfdfdf')
    && theme.mainAngle === 180
    && theme.mainSurface === '#f8f7f3'
    && theme.mainSurfaceEnd === '#f8f8ef'
    && isSolidStops(theme.mainStops, '#f8f8ef')
    && theme.composerAngle === 180
    && theme.composerSurface === '#dfdfdf'
    && theme.composerSurfaceEnd === '#dfdfdf'
    && isSolidStops(theme.composerStops, '#dfdfdf')
    && theme.controlAngle === 180
    && theme.controlSurface === '#bfbfbf'
    && theme.controlSurfaceEnd === '#bfbfbf'
    && isSolidStops(theme.controlStops, '#bfbfbf')
  ) {
    const light = writerThemePresets.find((preset) => preset.id === 'writer-default-light')?.theme
    if (!light) return
    Object.assign(theme, {
      ...light,
      backdropStops: light.backdropStops?.map((stop) => ({ ...stop })),
      mainStops: light.mainStops?.map((stop) => ({ ...stop })),
      composerStops: light.composerStops?.map((stop) => ({ ...stop })),
      controlStops: light.controlStops?.map((stop) => ({ ...stop })),
    })
  }
}

function resetTheme() {
  uiSystem.value.theme = { ...defaultTheme }
  flash('主题已恢复默认')
}

function swapBackdropAndMainTheme() {
  const theme = uiSystem.value.theme
  const backdrop = {
    start: theme.backdropStart,
    end: theme.backdropEnd,
    stops: theme.backdropStops.map((stop) => ({ ...stop })),
    angle: theme.backdropAngle,
    text: theme.backdropText,
  }
  theme.backdropStart = theme.mainSurface
  theme.backdropEnd = theme.mainSurfaceEnd
  theme.backdropStops = theme.mainStops.map((stop) => ({ ...stop }))
  theme.backdropAngle = theme.mainAngle
  theme.backdropText = theme.mainText
  theme.mainSurface = backdrop.start
  theme.mainSurfaceEnd = backdrop.end
  theme.mainStops = backdrop.stops
  theme.mainAngle = backdrop.angle
  theme.mainText = backdrop.text
  normalizeThemeSettings()
  flash('主界面与背景板已互换')
}

const themeAreaFields = {
  backdrop: { stops: 'backdropStops', angle: 'backdropAngle', text: 'backdropText' },
  main: { stops: 'mainStops', angle: 'mainAngle', text: 'mainText' },
  composer: { stops: 'composerStops', angle: 'composerAngle', text: 'composerText' },
  control: { stops: 'controlStops', angle: 'controlAngle', text: 'controlText' },
} as const

function gradientStops(area: ThemeArea): ThemeStop[] {
  return uiSystem.value.theme[themeAreaFields[area].stops]
}

function themeAngle(area: ThemeArea): number {
  return uiSystem.value.theme[themeAreaFields[area].angle]
}

function themeOpacity(area: ThemeArea): number {
  if (area === 'backdrop') return 1
  return uiSystem.value.theme[`${area}Opacity` as 'mainOpacity' | 'composerOpacity' | 'controlOpacity']
}

function themeTextColor(area: ThemeArea): string {
  return uiSystem.value.theme[themeAreaFields[area].text]
}

function updateThemeStops(area: ThemeArea, stops: ThemeStop[]) {
  const currentStops = gradientStops(area)
  const normalized = normalizeGradientStops(stops, currentStops[0]?.color || '#000000', currentStops.at(-1)?.color || '#000000')
  currentStops.splice(0, currentStops.length, ...normalized)
}

function updateThemeAngle(area: ThemeArea, angle: number) {
  uiSystem.value.theme[themeAreaFields[area].angle] = clampNumber(angle, 0, 360, themeAngle(area))
}

function updateThemeOpacity(area: ThemeArea, opacity: number) {
  if (area === 'backdrop') return
  uiSystem.value.theme[`${area}Opacity` as 'mainOpacity' | 'composerOpacity' | 'controlOpacity'] = clampNumber(opacity, 0.1, 1, themeOpacity(area))
}

function updateThemeTextColor(area: ThemeArea, color: string) {
  uiSystem.value.theme[themeAreaFields[area].text] = normalizeColor(color, themeTextColor(area))
}

function addGradientStop(area: ThemeArea) {
  const stops = gradientStops(area)
  if (stops.length >= 8) return
  const middle = stops.length > 1
    ? Math.round((stops[stops.length - 2].position + stops[stops.length - 1].position) / 2)
    : 50
  stops.splice(stops.length - 1, 0, {
    color: stops[stops.length - 1]?.color || '#222222',
    position: middle,
  })
  sortGradientStops(area)
}

function removeGradientStop(area: ThemeArea, index: number) {
  const stops = gradientStops(area)
  if (stops.length <= 2) return
  stops.splice(index, 1)
  sortGradientStops(area)
}

function sortGradientStops(area: ThemeArea) {
  const stops = gradientStops(area)
  const normalized = normalizeGradientStops(stops, stops[0]?.color || '#000000', stops[stops.length - 1]?.color || '#000000')
  stops.splice(0, stops.length, ...normalized)
}

function presetsByGroup(group: ThemePreset['group']) {
  return writerThemePresets.filter((preset) => preset.group === group)
}

async function applyThemePreset(preset: ThemePreset) {
  const writerPreset = preset as WriterThemePreset
  uiSystem.value.theme = {
    ...defaultTheme,
    ...writerPreset.theme,
    controlSurface: writerPreset.theme.controlSurface || writerPreset.theme.composerSurface || defaultTheme.controlSurface,
    controlSurfaceEnd: writerPreset.theme.controlSurfaceEnd || writerPreset.theme.composerSurfaceEnd || writerPreset.theme.composerSurface || defaultTheme.controlSurfaceEnd,
    controlAngle: writerPreset.theme.controlAngle ?? writerPreset.theme.composerAngle ?? defaultTheme.controlAngle,
    controlText: writerPreset.theme.controlText || writerPreset.theme.composerText || defaultTheme.controlText,
    controlOpacity: writerPreset.theme.controlOpacity ?? writerPreset.theme.composerOpacity ?? defaultTheme.controlOpacity,
  }
  normalizeThemeSettings()
  const storage = getLocalStorage()
  if (storage) storage.setItem(localSettingKeys.uiSystem, JSON.stringify(uiSystem.value))
  try {
    await configStore.saveAppSetting(localSettingKeys.uiSystem, uiSystem.value)
  } catch {
    flash('主题已保存到本地')
  } finally {
    window.location.reload()
  }
}

function mergeAgentSettings(agents: AgentCapability[]): AgentSetting[] {
  return agents.map((agent) => agentFromCapability(agent))
}

function mergeSubAgentSettings(agents: SubAgentDefinition[]): SubAgentSetting[] {
  return agents.map((agent) => ({
    name: agent.name,
    label: subAgentLabel(agent.name),
    description: agent.description,
    role: agent.role,
    developerInstructions: agent.developer_instructions || '',
    tools: agent.tools,
    model: agent.model,
    maxToolRounds: agent.max_tool_rounds,
    aliases: agent.aliases,
    source: agent.source,
    enabled: agent.enabled,
  }))
}

function syncSubAgentDraft() {
  const agent = selectedSubAgent.value
  if (!agent) {
    subAgentDraft.value = {
      name: '',
      description: '',
      role: '',
      developerInstructions: '',
      toolsText: '',
      model: '',
      maxToolRounds: 3,
      aliasesText: '',
    }
    return
  }
  subAgentDraft.value = {
    name: agent.name,
    description: agent.description,
    role: agent.role,
    developerInstructions: agent.developerInstructions,
    toolsText: agent.tools.join('\n'),
    model: agent.model,
    maxToolRounds: agent.maxToolRounds,
    aliasesText: agent.aliases.join('\n'),
  }
}

function createSubAgentDraft() {
  selectedSubAgentName.value = ''
  subAgentDraft.value = {
    name: 'project-worker',
    description: '项目专用子任务',
    role: 'implementation',
    developerInstructions: '只处理委派给你的项目任务，完成后交回结果、风险和需要主 Writer 复核的内容。',
    toolsText: 'read_file\nsearch_content\nwrite_file\nedit_file\nrun_tests',
    model: '',
    maxToolRounds: 3,
    aliasesText: '',
  }
}

async function saveSubAgentDraft() {
  const workRoot = projectDefaults.value.workRoot.trim()
  const name = subAgentDraft.value.name.trim()
  if (!workRoot || !name) {
    flash('需要工作区和 Agent 名称')
    return
  }
  subAgentSaving.value = true
  try {
    const saved = await configStore.saveProjectSubAgent(workRoot, {
      name,
      description: subAgentDraft.value.description.trim(),
      role: subAgentDraft.value.role.trim() || name,
      developer_instructions: subAgentDraft.value.developerInstructions.trim(),
      tools: splitLines(subAgentDraft.value.toolsText),
      model: subAgentDraft.value.model.trim(),
      max_tool_rounds: Math.max(0, Math.min(5, Number(subAgentDraft.value.maxToolRounds) || 3)),
      aliases: splitLines(subAgentDraft.value.aliasesText),
    })
    await loadRuntimeCapabilities()
    selectedSubAgentName.value = saved.name
    syncSubAgentDraft()
    flash('Agent 定义已保存')
  } catch (err) {
    flash(err instanceof Error ? err.message : String(err))
  } finally {
    subAgentSaving.value = false
  }
}

async function deleteSelectedSubAgent() {
  const agent = selectedSubAgent.value
  if (!agent || agent.source !== 'project') return
  const confirmed = window.confirm(`删除项目 Agent「${agent.name}」？内置定义不会受影响。`)
  if (!confirmed) return
  subAgentSaving.value = true
  try {
    await configStore.deleteProjectSubAgent(projectDefaults.value.workRoot, agent.name)
    await loadRuntimeCapabilities()
    selectedSubAgentName.value = subAgentRows.value[0]?.name || ''
    syncSubAgentDraft()
    flash('Agent 定义已删除')
  } catch (err) {
    flash(err instanceof Error ? err.message : String(err))
  } finally {
    subAgentSaving.value = false
  }
}

function splitLines(value: string): string[] {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function mergeToolSettings(tools: ToolCapability[]): ToolSetting[] {
  return tools.map((tool) => toolFromCapability(tool))
}

function agentFromCapability(agent: AgentCapability): AgentSetting {
  const network = agent.capabilities.some((capability) => (
    capability.includes('web') || capability.includes('search') || capability.includes('fetch')
  ))
  return {
    name: agent.name,
    label: agentLabel(agent.name),
    type: 'agent',
    description: agentDescription(agent.name, agent.description),
    capabilities: agent.capabilities.map((capability) => capabilityLabel(capability)),
    network,
    nested: agent.can_call_agents,
    modes: agent.modes,
    aliases: agent.aliases,
    maxDepth: agent.max_depth,
    enabled: agent.enabled,
  }
}

function toolFromCapability(tool: ToolCapability): ToolSetting {
  return {
    name: tool.name,
    description: toolDescription(tool.name, tool.description),
    risk: permissionLabel(tool.permission),
    enabled: tool.enabled,
  }
}

async function setAgentEnabled(name: string, enabled: boolean) {
  const nextAgents = Object.fromEntries(agentRows.value.map((agent) => [
    agent.name,
    agent.name === name ? enabled : agent.enabled,
  ]))
  const nextTools = Object.fromEntries(toolRows.value.map((tool) => [tool.name, tool.enabled]))
  await saveRuntimeControls(nextAgents, nextTools, commandPolicies.value)
  flash(`${agentLabel(name)} 已${enabled ? '启用' : '停用'}`)
}

async function setToolEnabled(name: string, enabled: boolean) {
  const nextAgents = Object.fromEntries(agentRows.value.map((agent) => [agent.name, agent.enabled]))
  const nextTools = Object.fromEntries(toolRows.value.map((tool) => [
    tool.name,
    tool.name === name ? enabled : tool.enabled,
  ]))
  await saveRuntimeControls(nextAgents, nextTools, commandPolicies.value)
  flash(`${name} 已${enabled ? '启用' : '停用'}`)
}

async function setCommandPolicy(group: 'regular' | 'dangerous', policy: string) {
  const normalized = normalizeCommandPolicy(policy, commandPolicies.value[group])
  const nextPolicies = { ...commandPolicies.value, [group]: normalized }
  commandPolicies.value = nextPolicies
  const nextAgents = Object.fromEntries(agentRows.value.map((agent) => [agent.name, agent.enabled]))
  const nextTools = Object.fromEntries(toolRows.value.map((tool) => [tool.name, tool.enabled]))
  await saveRuntimeControls(nextAgents, nextTools, nextPolicies)
  flash(`${group === 'regular' ? '常规命令' : '高危命令'}已设为${permissionLabel(normalized)}`)
}

async function saveRuntimeControls(
  agents: Record<string, boolean>,
  tools: Record<string, boolean>,
  policies: Record<'regular' | 'dangerous', CommandPolicy>,
) {
  await configStore.saveAppSetting('lamwriter.runtimeControls', {
    agents,
    tools,
    command_policies: policies,
  })
  await loadRuntimeCapabilities()
}

function agentLabel(name: string): string {
  const labels: Record<string, string> = {
    architecture: '架构 Agent',
    sub: 'Sub agent',
  }
  return labels[name] || `${name.charAt(0).toUpperCase()}${name.slice(1)}Agent`
}

function subAgentLabel(name: string): string {
  const labels: Record<string, string> = {
    default: '通用子任务',
    explorer: '探索子任务',
    worker: '执行子任务',
    reviewer: '复核子任务',
  }
  return labels[name] || name
}

function agentSourceLabel(source: string): string {
  const labels: Record<string, string> = {
    builtin: '内置',
    user: '用户',
    project: '项目',
  }
  return labels[source] || source
}

function permissionLabel(permission: string): string {
  const labels: Record<string, string> = {
    auto_allow: '自动允许',
    ask_user: '需要确认',
    hard_block: '禁止',
    unknown: '未分类',
  }
  return labels[permission] || permission
}

function agentDescription(name: string, fallback: string): string {
  const descriptions: Record<string, string> = {
    architecture: '设计软件和应用架构，输出可交给 Writer 执行的方案。',
    sub: '按临时角色执行委派任务，返回聚焦结论、风险和交接信息。',
  }
  return descriptions[name] || fallback
}

function capabilityLabel(capability: string): string {
  const labels: Record<string, string> = {
    architecture_design: '架构设计',
    candidate_scoring: '候选评分',
    runtime_feasibility: '执行可行性',
    delegated_reasoning: '委派推理',
    focused_handoff: '聚焦交付',
    web_search: '网络搜索',
    web_fetch: '网页抓取',
    source_summary: '来源摘要',
    inspect_project: '项目检查',
    run_tests: '运行测试',
    defect_review: '缺陷审查',
    test_plan: '测试计划',
    ui_handoff: '界面交付说明',
    interaction_design: '交互设计',
    dependency_strategy: '依赖策略',
  }
  return labels[capability] || capability
}

function agentToolLabel(name: string): string {
  return name
}

function toolDescription(name: string, fallback: string): string {
  const descriptions: Record<string, string> = {
    read_file: '读取项目文件内容。',
    write_file: '写入文件，必要时创建新文件。',
    edit_file: '用精确文本替换修改已有文件。',
    search_content: '按正则搜索文件内容。',
    search_files: '按 glob 查找文件。',
    recall_session: '按路径、标签或 output_id 找回会话内完整记录。',
    load_skill: '加载匹配任务的 Writer skill 指令。',
    web_search: '搜索当前文档、许可证、依赖和生态事实。',
    run_command: '执行 shell 命令。',
    git_status: '查看当前 Git 状态。',
    git_diff: '查看当前 Git diff。',
    list_dir: '列出目录内容。',
    web_fetch: '抓取 URL 内容。',
    run_tests: '运行检测到或指定的测试命令。',
    inspect_project: '检查项目结构、技术栈、脚本和测试。',
    browser_check: '检查本地或远程页面的基础可达性和页面信号。',
    decision_point: '记录需要用户决策的阻塞点。',
    write_checklist: '声明将要创建或修改的文件清单。',
    update_checklist: '根据执行发现更新计划清单。',
    verify_design: '按设计稿检查跨文件一致性。',
    delegate_to_member: '委派任务给 LamTools 其他成员。',
  }
  return descriptions[name] || fallback
}

function applyLocalSetting<T extends object>(key: string, target: T) {
  const parsed = readLocalSetting<unknown>(key) || (key === localSettingKeys.uiSystem ? readLocalSetting<unknown>(legacyUiSystemKey) : null)
  if (!parsed) return
  if (Array.isArray(target) && Array.isArray(parsed)) {
    target.splice(0, target.length, ...parsed)
    return
  }
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    applySettingValue(target, parsed as Record<string, unknown>)
  }
}

function readLocalSetting<T>(key: string): T | null {
  const storage = getLocalStorage()
  if (!storage) return null
  const raw = storage.getItem(key)
  if (!raw) return null
  try {
    return JSON.parse(raw) as T
  } catch {
    storage.removeItem(key)
    return null
  }
}

function saveLocalSetting(key: string, value: unknown) {
  const storage = getLocalStorage()
  if (storage) storage.setItem(key, JSON.stringify(value))
  if (!settingsHydrated || !value || typeof value !== 'object' || Array.isArray(value)) return
  if (saveTimers[key]) window.clearTimeout(saveTimers[key])
  saveTimers[key] = window.setTimeout(() => {
    configStore.saveAppSetting(key, value as Record<string, unknown>).catch(() => {
      flash('设置保存失败')
    })
  }, 180)
}

function getLocalStorage(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

function flash(message: string) {
  noticeText.value = message
  window.setTimeout(() => {
    if (noticeText.value === message) noticeText.value = ''
  }, 2600)
}

function goBack() {
  router.push('/')
}

function providerName(id: string): string {
  return configStore.providers.find((p) => p.id === id)?.name || id.slice(0, 8)
}

function modelName(id: string): string {
  const model = configStore.models.find((m) => m.id === id)
  return model?.display_name || model?.model_id || id.slice(0, 8)
}

function modelsForProvider(providerId: string) {
  return configStore.models.filter((m) => m.provider_id === providerId)
}

const providerOptions = computed(() => configStore.providers.map((p) => ({ value: p.id, label: p.name })))
const modelOptions = computed(() => configStore.models.map((m) => ({
  value: m.id,
  label: `${providerName(m.provider_id)} / ${m.display_name || m.model_id}`,
})))

function modelOptionsForProvider(providerId: string) {
  return configStore.models
    .filter((m) => m.provider_id === providerId)
    .map((m) => ({ value: m.id, label: m.display_name || m.model_id }))
}

function providerApiTypeLabel(value: string): string {
  return apiTypeOptions.find((x) => x.value === value)?.label || value
}

function routeModelId(taskType: string): string {
  const route = modelRouting.value[taskType]
  return route?.mode === 'model' ? String(route.model_id || '') : ''
}

async function loadModelRouting() {
  const setting = await configStore.fetchAppSetting('lamwriter.modelRouting')
  const routes = setting.value?.routes
  modelRouting.value = routes && typeof routes === 'object'
    ? routes as Record<string, { mode: string; model_id?: string | null }>
    : {}
}

async function setRouteModel(taskType: string, modelId: string) {
  const routes = { ...modelRouting.value }
  if (!modelId) {
    if (taskType === 'writer') {
      flash('Writer 主模型必须指定')
      return
    }
    routes[taskType] = { mode: 'follow_default', model_id: null }
  } else {
    const model = configStore.models.find((m) => m.id === modelId)
    if (!model) return
    routes[taskType] = { mode: 'model', model_id: model.id }
  }
  const saved = await configStore.saveAppSetting('lamwriter.modelRouting', { routes })
  const savedRoutes = saved.value?.routes
  modelRouting.value = savedRoutes && typeof savedRoutes === 'object'
    ? savedRoutes as Record<string, { mode: string; model_id?: string | null }>
    : routes
  await Promise.all([
    configStore.fetchResolvedConfig('writer'),
  ])
  flash(`${routePurposes.value.find((x) => x.taskType === taskType)?.label || taskType} 已更新`)
}

function openNewProvider() {
  editingProvider.value = null
  provName.value = ''
  provApiType.value = 'openai'
  provBaseUrl.value = ''
  provApiKey.value = ''
  provAdapterProfile.value = ''
  provExtraJson.value = ''
  provPresetId.value = ''
  provPresetModelId.value = ''
  provCreateDefaultModel.value = true
  showProviderForm.value = true
}

function applyProviderPreset(presetId: string) {
  const preset = providerPresets.find(item => item.id === presetId)
  if (!preset) {
    provPresetModelId.value = ''
    return
  }
  provName.value = preset.name
  provApiType.value = preset.apiType
  provBaseUrl.value = preset.baseUrl
  provAdapterProfile.value = preset.adapterProfile
  provExtraJson.value = preset.extra ? JSON.stringify(preset.extra, null, 2) : ''
  provPresetModelId.value = preset.defaultModelId
}

function startEditProvider(p: { id: string; name: string; api_type: string; base_url: string; is_default: boolean; extra?: Record<string, unknown> | null }) {
  editingProvider.value = p.id
  provPresetId.value = ''
  provPresetModelId.value = ''
  provCreateDefaultModel.value = false
  provName.value = p.name
  provApiType.value = p.api_type
  provBaseUrl.value = p.base_url
  provApiKey.value = ''
  provAdapterProfile.value = String(p.extra?.adapter_profile_id || p.extra?.adapter_profile || p.extra?.llm_adapter_id || '')
  provExtraJson.value = stringifyExtraWithoutProfile(p.extra)
  showProviderForm.value = true
}

function resetProviderForm() {
  showProviderForm.value = false
  editingProvider.value = null
  provPresetId.value = ''
  provPresetModelId.value = ''
  provCreateDefaultModel.value = true
}

function parseExtraJson(text: string): Record<string, unknown> {
  const trimmed = text.trim()
  if (!trimmed) return {}
  const parsed = JSON.parse(trimmed)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Extra 必须是 JSON object')
  }
  return parsed as Record<string, unknown>
}

function stringifyExtraWithoutProfile(extra?: Record<string, unknown> | null): string {
  if (!extra) return ''
  const clone = { ...extra }
  delete clone.adapter_profile
  delete clone.adapter_profile_id
  delete clone.llm_adapter_id
  if (Object.keys(clone).length === 0) return ''
  return JSON.stringify(clone, null, 2)
}

function buildExtraFromForm(profileId: string, jsonText: string): Record<string, unknown> | undefined {
  const extra = parseExtraJson(jsonText)
  if (profileId) extra.adapter_profile_id = profileId
  return Object.keys(extra).length > 0 ? extra : undefined
}

async function createPresetModels(providerId: string, preset: ProviderPreset) {
  return Promise.all(preset.models.map((presetModel) => configStore.createModel({
    provider_id: providerId,
    model_id: presetModel.modelId,
    display_name: presetModel.displayName,
    context_window: presetModel.contextWindow,
    max_output_tokens: presetModel.maxOutputTokens,
    thinking_supported: presetModel.thinkingSupported,
    thinking_budget: presetModel.thinkingBudget,
    temperature: presetModel.temperature,
    extra: presetModel.extra,
  })))
}

async function saveProvider() {
  if (!provName.value.trim() || !provBaseUrl.value.trim()) return
  let extra: Record<string, unknown> | undefined
  try {
    extra = buildExtraFromForm(provAdapterProfile.value, provExtraJson.value)
  } catch (err) {
    flash(err instanceof Error ? err.message : 'Extra JSON 格式错误')
    return
  }
  let savedProviderId = editingProvider.value
  let preferredModelId = ''
  try {
    if (editingProvider.value) {
      const data: ProviderUpdate = {
        name: provName.value.trim(),
        api_type: provApiType.value.trim(),
        base_url: provBaseUrl.value.trim(),
        extra: extra ?? null,
      }
      if (provApiKey.value.trim()) data.api_key = provApiKey.value.trim()
      const provider = await configStore.updateProvider(editingProvider.value, data)
      savedProviderId = provider.id
    } else {
      if (!provApiKey.value.trim()) return
      const provider = await configStore.createProvider({
        name: provName.value.trim(),
        api_type: provApiType.value.trim(),
        base_url: provBaseUrl.value.trim(),
        api_key: provApiKey.value.trim(),
        extra,
      })
      savedProviderId = provider.id
      const preset = selectedProviderPreset.value
      if (provCreateDefaultModel.value && preset) {
        const createdModels = await createPresetModels(provider.id, preset)
        preferredModelId = (
          createdModels.find(model => model.model_id === provPresetModelId.value)
          || createdModels[0]
        )?.id || ''
      }
    }
    await Promise.all([configStore.fetchProviders(), configStore.fetchModels(), configStore.fetchResolvedConfig('writer')])
  } catch (err) {
    flash(err instanceof Error && err.message ? err.message : 'Provider 保存失败')
    return
  }
  selectedProviderId.value = savedProviderId || configStore.providers[0]?.id || ''
  if (preferredModelId) selectedModelId.value = preferredModelId
  resetProviderForm()
  flash('Provider 已保存')
}

async function onDeleteProvider(id: string) {
  await configStore.deleteProvider(id)
  await configStore.fetchModels()
  selectedProviderId.value = configStore.providers[0]?.id || ''
  flash('Provider 已删除')
}

async function importCurrentEnvironment() {
  const result = await configStore.importEnvConfig()
  selectedProviderId.value = result.provider.id
  selectedModelId.value = result.model.id
  await loadModelRouting()
  flash('已从当前环境导入 API，并设为 Writer 主模型')
}

function openNewModel(providerId = selectedProvider.value?.id || configStore.providers[0]?.id || '') {
  editingModel.value = null
  modelProviderId.value = providerId
  modelModelId.value = ''
  modelDisplayName.value = ''
  modelContextWindow.value = 128000
  modelMaxOutput.value = 16384
  modelThinkingSupported.value = false
  modelThinkingBudget.value = 10000
  modelTemperature.value = 0.7
  modelAdapterProfile.value = ''
  modelExtraJson.value = ''
  showModelForm.value = true
}

function startEditModel(m: {
  id: string
  provider_id: string
  model_id: string
  display_name: string
  context_window: number
  max_output_tokens: number
  thinking_supported: boolean
  thinking_budget: number
  temperature: number
  is_default: boolean
  extra?: Record<string, unknown> | null
}) {
  editingModel.value = m.id
  modelProviderId.value = m.provider_id
  modelModelId.value = m.model_id
  modelDisplayName.value = m.display_name
  modelContextWindow.value = m.context_window
  modelMaxOutput.value = m.max_output_tokens
  modelThinkingSupported.value = m.thinking_supported
  modelThinkingBudget.value = m.thinking_budget
  modelTemperature.value = m.temperature
  modelAdapterProfile.value = String(m.extra?.adapter_profile_id || m.extra?.adapter_profile || m.extra?.llm_adapter_id || '')
  modelExtraJson.value = stringifyExtraWithoutProfile(m.extra)
  showModelForm.value = true
}

function resetModelForm() {
  showModelForm.value = false
  editingModel.value = null
}

async function saveModel() {
  if (!modelProviderId.value || !modelModelId.value.trim()) return
  let extra: Record<string, unknown> | undefined
  try {
    extra = buildExtraFromForm(modelAdapterProfile.value, modelExtraJson.value)
  } catch (err) {
    flash(err instanceof Error ? err.message : 'Extra JSON 格式错误')
    return
  }
  if (editingModel.value) {
    await configStore.updateModel(editingModel.value, {
      provider_id: modelProviderId.value,
      model_id: modelModelId.value.trim(),
      display_name: modelDisplayName.value.trim(),
      context_window: modelContextWindow.value,
      max_output_tokens: modelMaxOutput.value,
      thinking_supported: modelThinkingSupported.value,
      thinking_budget: modelThinkingBudget.value,
      temperature: modelTemperature.value,
      extra: extra ?? null,
    })
  } else {
    await configStore.createModel({
      provider_id: modelProviderId.value,
      model_id: modelModelId.value.trim(),
      display_name: modelDisplayName.value.trim(),
      context_window: modelContextWindow.value,
      max_output_tokens: modelMaxOutput.value,
      thinking_supported: modelThinkingSupported.value,
      thinking_budget: modelThinkingBudget.value,
      temperature: modelTemperature.value,
      extra,
    })
  }
  await Promise.all([configStore.fetchModels(), configStore.fetchResolvedConfig('writer')])
  selectedModelId.value = configStore.models[0]?.id || ''
  resetModelForm()
  flash('Model 已保存')
}

async function onDeleteModel(id: string) {
  await configStore.deleteModel(id)
  await loadModelRouting()
  selectedModelId.value = configStore.models[0]?.id || ''
  flash('Model 已删除')
}
</script>

<template>
  <SettingsShell
    :sections="settingsSections"
    title="设置"
    :settings-theme-style="settingsThemeStyle"
    @close="goBack"
  >
    <template #notice>
      <div v-if="noticeText" class="settings-notice">{{ noticeText }}</div>
    </template>

    <template #default="{ activeSection: shellActiveSection }">
      <section v-if="shellActiveSection === 'model-api'">
        <div class="settings-title">
          <h1>模型与供应商</h1>
          <p>Provider 管 API Key 和 Base URL；Model 管上下文、输出、思考参数。</p>
        </div>

        <div class="settings-panel">
            <div class="setting-card">
              <div class="subhead">
                <strong>配置导入</strong>
                <button class="small-btn" @click="importCurrentEnvironment">从当前环境导入</button>
              </div>
              <p class="muted">Provider 只管理 API；Writer 主模型可在输入框下方快速切换。</p>
            </div>

            <div v-for="p in configStore.providers" :key="p.id" class="provider-card">
              <div class="provider-head">
                <div>
                  <strong>{{ p.name }}</strong>
                  <span>{{ providerApiTypeLabel(p.api_type) }} · Provider</span>
                </div>
                <div class="provider-actions">
                  <button class="small-btn" @click="selectedProviderId = p.id; startEditProvider(p)">编辑</button>
                  <button class="small-btn danger" :aria-label="`删除 Provider ${p.name}`" @click="onDeleteProvider(p.id)">删除</button>
                </div>
              </div>
              <div class="provider-body">
                <div class="api-fields">
                  <div class="api-field"><span>API Key</span><code>{{ p.has_api_key ? '已配置' : '未配置' }}</code></div>
                  <div class="api-field"><span>Base URL</span><code>{{ p.base_url }}</code></div>
                </div>

                <div class="subhead">
                  <strong>Models</strong>
                  <button class="small-btn" @click="selectedProviderId = p.id; openNewModel(p.id)">+ 新增 model</button>
                </div>
                <div class="model-list">
                  <div v-if="modelsForProvider(p.id).length === 0" class="empty compact-empty">暂无模型</div>
                  <div v-for="m in modelsForProvider(p.id)" :key="m.id" class="model-row">
                    <div>
                      <strong>{{ m.display_name || m.model_id }}</strong>
                      <div class="model-params">
                        <span class="param">上下文 {{ m.context_window }}</span>
                        <span class="param">输出 {{ m.max_output_tokens }}</span>
                        <span class="param">{{ m.thinking_supported ? `思考 ${m.thinking_budget}` : '无思考' }}</span>
                        <span class="param">温度 {{ m.temperature }}</span>
                      </div>
                    </div>
                    <div class="row-actions">
                      <button class="small-btn" @click="selectedModelId = m.id; startEditModel(m)">参数</button>
                      <button class="small-btn danger" :aria-label="`删除模型 ${m.display_name || m.model_id}`" @click="onDeleteModel(m.id)">删除</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <button class="add-row" @click="openNewProvider">+ 新增 provider</button>

        </div>
      </section>

      <section v-if="false && shellActiveSection === 'writer'">
        <div class="settings-title">
          <h1>Writer 行为</h1>
          <p>控制新会话和主界面输入区的默认质量档位。这里和模型 thinking 参数不是一回事。</p>
        </div>
        <div class="settings-panel">
          <div class="setting-card">
            <h3>执行质量</h3>
            <label class="field">默认质量档位
              <UiSelect v-model="writerDefaults.qualityMode" :options="qualityModeOptions" />
            </label>
          </div>
        </div>
      </section>

      <section v-if="false && shellActiveSection === 'project'">
        <div class="settings-title">
          <h1>项目默认值</h1>
          <p>配置新项目创建时默认填入的 work root。</p>
        </div>
        <div class="settings-panel">
          <div class="setting-card">
            <h3>新项目默认配置</h3>
            <label class="field">默认 work root <input v-model="projectDefaults.workRoot" /></label>
          </div>
        </div>
      </section>

      <section v-if="false && shellActiveSection === 'agents'">
        <div class="settings-title">
          <h1>工具与 Agent</h1>
          <p>自动读取后端当前注册的 Agent 和 Tool，并在这里统一控制启用状态与模型分配。</p>
        </div>
        <div class="settings-panel">
          <div class="setting-card">
            <div class="subhead">
              <strong>LLM 分配</strong>
            </div>
            <div class="route-purpose-list">
              <div v-for="route in routePurposes" :key="route.taskType" class="route-purpose-row">
                <div>
                  <strong>{{ route.label }}</strong>
                  <span>{{ route.note }}</span>
                </div>
                <UiSelect
                  :model-value="routeModelId(route.taskType)"
                  :options="[
                    { value: '', label: route.taskType === 'writer' ? '必须指定 Writer 主模型' : '跟随 Writer 主模型' },
                    ...modelOptions,
                  ]"
                  @update:model-value="setRouteModel(route.taskType, $event)"
                />
              </div>
            </div>
          </div>

          <div class="setting-card agent-manager">
            <div class="subhead">
              <strong>{{ selectedAgentFlowTitle }}</strong>
              <span class="muted">{{ agentRows.filter((agent) => agent.enabled).length }} / {{ agentRows.length }} 已启用</span>
            </div>
            <div class="agent-logic">
              <div class="agent-flow-cases">
                <section
                  v-for="variant in selectedAgentFlowVariants"
                  :key="variant.id"
                  class="agent-flow-case"
                >
                  <div class="agent-flow-case-head">
                    <strong>{{ variant.title }}</strong>
                    <span>{{ variant.condition }}</span>
                  </div>
                  <ol class="agent-flow-steps">
                    <li v-for="(node, index) in variant.nodes" :key="node.id">
                      <b>{{ index + 1 }}</b>
                      <span>
                        <strong>{{ node.label }}</strong>
                        <em>{{ node.note }}</em>
                      </span>
                    </li>
                  </ol>
                </section>
              </div>
              <div v-if="!selectedAgent" class="empty compact-empty">暂无后端注册 Agent</div>
              <aside v-if="selectedAgent" class="agent-detail">
                <div class="agent-tabs">
                  <button
                    v-for="agent in agentRows"
                    :key="agent.name"
                    type="button"
                    :class="{ active: selectedAgentName === agent.name }"
                    @click="selectAgent(agent.name)"
                  >
                    {{ agent.label }}
                  </button>
                </div>
                <div class="agent-detail-head">
                  <div>
                    <strong>{{ selectedAgent.label }}</strong>
                    <span>{{ selectedAgent.name }}</span>
                  </div>
                  <label class="switch-line">
                    <input
                      type="checkbox"
                      :checked="selectedAgent.enabled"
                      @change="setAgentEnabled(selectedAgent.name, ($event.target as HTMLInputElement).checked)"
                    />
                    <span></span>
                  </label>
                </div>
                <p>{{ selectedAgent.description }}</p>
                <div class="agent-detail-grid">
                  <span>{{ selectedAgent.network ? '可联网' : '不联网' }}</span>
                  <span>{{ selectedAgent.nested ? '可嵌套' : '不可嵌套' }}</span>
                  <span>深度 {{ selectedAgent.maxDepth }}</span>
                  <span>{{ selectedAgent.modes.join(' / ') || 'auto' }}</span>
                </div>
                <p v-if="selectedAgent.name === 'architecture'" class="agent-runtime-note">
                  标准模式运行输入整理、任务路由、问题界定、候选生成、方案选择、架构展开、质量评审和交付生成；toy/low 会把任务路由与问题界定合并成轻量路径。
                </p>
                <p v-else-if="selectedAgent.name === 'sub'" class="agent-runtime-note">
                  Sub agent 是临时委派能力，不是固定 UI/研究/测试 Agent；ui_brief、dependency、research 只是运行时传入的临时角色。
                </p>
                <div v-if="selectedAgent.capabilities.length" class="capability-tags">
                  <span v-for="capability in selectedAgent.capabilities" :key="capability">{{ capability }}</span>
                </div>
              </aside>
            </div>
          </div>

          <div class="setting-card agent-manager">
            <div class="subhead">
              <strong>Sub agent 库</strong>
              <button type="button" class="mini-button" @click="createSubAgentDraft">新增</button>
            </div>
            <div v-if="subAgentRows.length === 0" class="empty compact-empty">
              暂无子代理定义
            </div>
            <div v-else class="agent-logic">
              <div class="agent-flow-cases">
                <section
                  v-for="agent in subAgentRows"
                  :key="agent.name"
                  class="agent-flow-case"
                  :class="{ active: selectedSubAgentName === agent.name }"
                  @click="selectSubAgent(agent.name)"
                >
                  <div class="agent-flow-case-head">
                    <strong>{{ agent.label }}</strong>
                    <span>{{ agent.description }}</span>
                  </div>
                  <div class="agent-detail-grid compact-grid">
                    <span>{{ agentSourceLabel(agent.source) }}</span>
                    <span>{{ agent.tools.length }} 个工具</span>
                  <span>{{ agent.model || '跟随 Writer 主模型' }}</span>
                    <span>{{ agent.maxToolRounds }} 轮工具</span>
                  </div>
                </section>
              </div>
              <aside v-if="selectedSubAgent" class="agent-detail">
                <div class="agent-detail-head">
                  <div>
                    <strong>{{ selectedSubAgent.label }}</strong>
                    <span>{{ selectedSubAgent.name }}</span>
                  </div>
                  <span class="muted">{{ agentSourceLabel(selectedSubAgent.source) }}</span>
                </div>
                <p>{{ selectedSubAgent.description }}</p>
                <div class="agent-detail-grid">
                  <span>角色 {{ selectedSubAgent.role }}</span>
                  <span>{{ selectedSubAgent.model || '跟随 Writer 主模型' }}</span>
                  <span>{{ selectedSubAgent.maxToolRounds }} 轮</span>
                  <span>{{ selectedSubAgent.aliases.length ? selectedSubAgent.aliases.join(' / ') : '无别名' }}</span>
                </div>
                <div class="capability-tags">
                  <span v-for="tool in selectedSubAgent.tools" :key="tool">{{ agentToolLabel(tool) }}</span>
                </div>
              </aside>
            </div>
            <div class="sub-agent-editor">
              <div class="sub-agent-editor-grid">
                <label>
                  <span>名称</span>
                  <input v-model="subAgentDraft.name" placeholder="project-worker" />
                </label>
                <label>
                  <span>角色</span>
                  <input v-model="subAgentDraft.role" placeholder="implementation" />
                </label>
                <label>
                  <span>模型</span>
                  <input v-model="subAgentDraft.model" placeholder="留空跟随 Writer 主模型" />
                </label>
                <label>
                  <span>工具轮次</span>
                  <input v-model.number="subAgentDraft.maxToolRounds" type="number" min="0" max="5" />
                </label>
              </div>
              <label>
                <span>说明</span>
                <input v-model="subAgentDraft.description" placeholder="什么时候应该派给它" />
              </label>
              <label>
                <span>工具</span>
                <textarea v-model="subAgentDraft.toolsText" rows="4" placeholder="read_file&#10;search_content"></textarea>
              </label>
              <label>
                <span>专用指令</span>
                <textarea v-model="subAgentDraft.developerInstructions" rows="5" placeholder="这个 Agent 应该怎样完成任务"></textarea>
              </label>
              <label>
                <span>别名</span>
                <input v-model="subAgentDraft.aliasesText" placeholder="每行一个，可留空" />
              </label>
              <div class="sub-agent-actions">
                <button type="button" :disabled="subAgentSaving" @click="saveSubAgentDraft">保存为项目 Agent</button>
                <button type="button" :disabled="subAgentSaving || !canDeleteSelectedSubAgent" @click="deleteSelectedSubAgent">删除项目定义</button>
              </div>
            </div>
          </div>

          <div class="setting-card">
            <div class="subhead">
              <strong>命令执行策略</strong>
              <span class="muted">按风险分组控制</span>
            </div>
            <div class="command-policy-list">
              <div class="command-policy-row">
                <div>
                  <strong>常规命令</strong>
                  <span>读取、搜索、测试、构建、状态查看等低风险操作。默认自动放行。</span>
                </div>
                <div class="binary-segment" role="group" aria-label="常规命令审批策略">
                  <button
                    type="button"
                    :class="{ active: commandPolicies.regular === 'auto_allow' }"
                    @click="setCommandPolicy('regular', 'auto_allow')"
                  >自动放行</button>
                  <button
                    type="button"
                    :class="{ active: commandPolicies.regular === 'ask_user' }"
                    @click="setCommandPolicy('regular', 'ask_user')"
                  >需要审批</button>
                </div>
              </div>
              <div class="command-policy-row">
                <div>
                  <strong>高危命令</strong>
                  <span>删除、移动、重命名、重置、权限变更等会改变资产的操作。默认需要审批。</span>
                </div>
                <div class="binary-segment" role="group" aria-label="高危命令审批策略">
                  <button
                    type="button"
                    :class="{ active: commandPolicies.dangerous === 'auto_allow' }"
                    @click="setCommandPolicy('dangerous', 'auto_allow')"
                  >自动放行</button>
                  <button
                    type="button"
                    :class="{ active: commandPolicies.dangerous === 'ask_user' }"
                    @click="setCommandPolicy('dangerous', 'ask_user')"
                  >需要审批</button>
                </div>
              </div>
            </div>
          </div>

          <div class="setting-card">
            <div class="subhead">
              <strong>Tool 列表</strong>
              <span class="muted">{{ toolRows.filter((tool) => tool.enabled).length }} / {{ toolRows.length }} 已启用</span>
            </div>
            <div class="tool-table">
              <div class="tool-table-head">
                <span>工具</span>
                <span>权限</span>
                <span>说明</span>
                <span>状态</span>
              </div>
              <div v-if="toolRows.length === 0" class="empty compact-empty">暂无后端注册 Tool</div>
              <div v-for="tool in toolRows" :key="tool.name" class="tool-table-row" :class="{ disabled: !tool.enabled }">
                <strong>{{ tool.name }}</strong>
                <span>{{ tool.risk }}</span>
                <span>{{ tool.description }}</span>
                <label class="switch-line">
                  <input
                    type="checkbox"
                    :checked="tool.enabled"
                    @change="setToolEnabled(tool.name, ($event.target as HTMLInputElement).checked)"
                  />
                  <span></span>
                </label>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section v-if="shellActiveSection === 'permissions'">
        <div class="settings-title">
          <h1>权限状态</h1>
          <p>控制 Writer 命令执行策略。默认自动放行；敏感文件边界仍由后端硬拦截。</p>
        </div>
        <div class="settings-panel">
          <div class="setting-card">
            <div class="subhead">
              <strong>命令执行策略</strong>
              <span class="muted">当前默认：自动放行</span>
            </div>
            <div class="command-policy-list">
              <div class="command-policy-row">
                <div>
                  <strong>常规命令</strong>
                  <span>读取、搜索、测试、构建、状态查看等低风险操作。</span>
                </div>
                <div class="binary-segment" role="group" aria-label="常规命令审批策略">
                  <button
                    type="button"
                    :class="{ active: commandPolicies.regular === 'auto_allow' }"
                    @click="setCommandPolicy('regular', 'auto_allow')"
                  >自动放行</button>
                  <button
                    type="button"
                    :class="{ active: commandPolicies.regular === 'ask_user' }"
                    @click="setCommandPolicy('regular', 'ask_user')"
                  >需要审批</button>
                </div>
              </div>
              <div class="command-policy-row">
                <div>
                  <strong>高危命令</strong>
                  <span>删除、移动、重命名、重置、权限变更等会改变资产的操作。</span>
                </div>
                <div class="binary-segment" role="group" aria-label="高危命令审批策略">
                  <button
                    type="button"
                    :class="{ active: commandPolicies.dangerous === 'auto_allow' }"
                    @click="setCommandPolicy('dangerous', 'auto_allow')"
                  >自动放行</button>
                  <button
                    type="button"
                    :class="{ active: commandPolicies.dangerous === 'ask_user' }"
                    @click="setCommandPolicy('dangerous', 'ask_user')"
                  >需要审批</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section v-if="shellActiveSection === 'ui-system'">
        <div class="settings-title">
          <h1>界面外观</h1>
          <p>控制界面密度、三块主区域配色、透明度和运行面板信息。</p>
        </div>
        <div class="settings-panel">
          <div class="setting-card">
            <h3>界面</h3>
            <label class="field">密度 <UiSelect v-model="uiSystem.density" :options="densityOptions" /></label>
            <label class="field width-field">
              <span>内容宽度 <em>{{ contentWidthText }}</em></span>
              <div class="width-control">
                <input v-model.number="uiSystem.contentWidth" type="range" min="560" max="1120" step="20" />
                <input v-model.number="uiSystem.contentWidth" type="number" min="560" max="1120" step="20" />
              </div>
            </label>
          </div>
          <div class="subhead">
            <strong>主题布局</strong>
            <button class="small-btn" type="button" @click="swapBackdropAndMainTheme">互换背景/主界面</button>
          </div>
          <ThemeEditor
            product-name="LamWriter"
            content-description="任务内容 / 时间线 / 状态"
            :get-stops="gradientStops"
            :get-angle="themeAngle"
            :get-opacity="themeOpacity"
            :get-text-color="themeTextColor"
            :presets="writerThemePresets"
            :presets-by-group="presetsByGroup"
            :theme-preview-style="themePreviewStyle"
            :theme-preview-main-style="themePreviewMainStyle"
            :theme-preview-composer-style="themePreviewComposerStyle"
            :theme-preview-control-style="themePreviewControlStyle"
            @reset-theme="resetTheme"
            @apply-preset="applyThemePreset"
            @update-stops="updateThemeStops"
            @update-angle="updateThemeAngle"
            @update-opacity="updateThemeOpacity"
            @update-text-color="updateThemeTextColor"
            @add-stop="addGradientStop"
            @remove-stop="removeGradientStop"
            @sort-stops="sortGradientStops"
          />
        </div>
      </section>
    </template>
  </SettingsShell>

    <div v-if="showProviderForm" class="modal-overlay" @click.self="resetProviderForm">
      <div class="modal-card">
        <h2>{{ editingProvider ? '编辑 Provider' : '新增 Provider' }}</h2>
        <div class="form-grid">
          <label v-if="!editingProvider" class="field">官方模板
            <UiSelect v-model="provPresetId" :options="providerPresetOptions" />
          </label>
          <label class="field">名称 <input v-model="provName" /></label>
          <label class="field">API 协议
            <UiSelect v-model="provApiType" :options="apiTypeOptions" />
          </label>
          <label class="field">Base URL <input v-model="provBaseUrl" /></label>
          <label class="field">API Key <input v-model="provApiKey" type="password" :placeholder="editingProvider ? '留空表示不修改' : '必填'" /></label>
          <label class="field">接口适配
            <UiSelect v-model="provAdapterProfile" :options="adapterProfileOptions" />
          </label>
          <label v-if="!editingProvider && selectedProviderPreset" class="toggle-line">
            <input v-model="provCreateDefaultModel" type="checkbox" /> 创建全部内置模型
          </label>
          <label v-if="!editingProvider && selectedProviderPreset && provCreateDefaultModel" class="field">首选模型
            <UiSelect v-model="provPresetModelId" :options="providerPresetModelOptions" />
          </label>
          <label class="field field-wide">高级适配 JSON
            <textarea
              v-model="provExtraJson"
              class="field-textarea"
              spellcheck="false"
              placeholder='{"adapter_profile_override":{"request":{"unsupported_fields":["thinking"]}}}'
            ></textarea>
          </label>
        </div>
        <div class="modal-actions">
          <button @click="resetProviderForm">取消</button>
          <button class="btn-primary" @click="saveProvider">{{ editingProvider ? '更新' : '创建' }}</button>
        </div>
      </div>
    </div>

    <div v-if="showModelForm" class="modal-overlay" @click.self="resetModelForm">
      <div class="modal-card">
        <h2>{{ editingModel ? '编辑 Model' : '新增 Model' }}</h2>
        <div class="form-grid">
          <label class="field">Provider
            <UiSelect v-model="modelProviderId" :options="providerOptions" />
          </label>
          <label class="field">Model ID <input v-model="modelModelId" /></label>
          <label class="field">显示名称 <input v-model="modelDisplayName" /></label>
          <label class="field">上下文长度 <input v-model.number="modelContextWindow" type="number" /></label>
          <label class="field">最大输出 <input v-model.number="modelMaxOutput" type="number" /></label>
          <label class="toggle-line"><input v-model="modelThinkingSupported" type="checkbox" /> 支持 thinking/reasoning</label>
          <label class="field">Thinking Budget <input v-model.number="modelThinkingBudget" type="number" /></label>
          <label class="field">Temperature <input v-model.number="modelTemperature" type="number" step="0.1" /></label>
          <label class="field">接口适配
            <UiSelect v-model="modelAdapterProfile" :options="adapterProfileOptions" />
          </label>
          <label class="field field-wide">高级适配 JSON
            <textarea
              v-model="modelExtraJson"
              class="field-textarea"
              spellcheck="false"
              placeholder='{"adapter_profile_override":{"stream_response":{"reasoning_delta":"choices.0.delta.reasoning_content"}}}'
            ></textarea>
          </label>
        </div>
        <div class="modal-actions">
          <button @click="resetModelForm">取消</button>
          <button class="btn-primary" @click="saveModel">{{ editingModel ? '更新' : '创建' }}</button>
        </div>
      </div>
    </div>

</template>

<style scoped>
.mini-button,
.sub-agent-actions button {
  min-height: 30px;
  padding: 0 10px;
  border-radius: 6px;
  border: 1px solid color-mix(in srgb, currentColor 16%, transparent);
  background: color-mix(in srgb, currentColor 5%, transparent);
  color: inherit;
}

.sub-agent-editor {
  display: grid;
  gap: 10px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid color-mix(in srgb, currentColor 10%, transparent);
}

.sub-agent-editor label {
  display: grid;
  gap: 5px;
  font-size: 12px;
}

.sub-agent-editor input,
.sub-agent-editor textarea {
  width: 100%;
  min-width: 0;
  border: 1px solid color-mix(in srgb, currentColor 14%, transparent);
  border-radius: 6px;
  background: color-mix(in srgb, currentColor 4%, transparent);
  color: inherit;
  padding: 8px 9px;
  font: inherit;
}

.sub-agent-editor textarea {
  resize: vertical;
}

.sub-agent-editor-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.sub-agent-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.modal-overlay {
  padding: 24px;
  align-items: center;
}

.modal-card {
  width: min(500px, calc(100vw - 48px));
  max-height: min(820px, calc(100vh - 48px));
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
}

.modal-card h2 {
  margin: 0;
}

.form-grid {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 4px;
  display: grid;
  gap: 12px;
}

.modal-actions {
  padding-top: 2px;
}

@media (max-width: 720px) {
  .sub-agent-editor-grid {
    grid-template-columns: 1fr;
  }

  .modal-overlay {
    padding: 12px;
  }

  .modal-card {
    width: calc(100vw - 24px);
    max-height: calc(100vh - 24px);
  }
}
</style>
