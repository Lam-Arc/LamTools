/**
 * 模型与供应商 · 视觉稿。
 *
 * 用真实的 CoreModelCatalog / CoreSettings 渲染，只把供应商、模型、用量和
 * 连接状态换成假数据；方便在没有后端或不想动真配置时看界面。
 *
 * ?theme=light  浅色
 * ?view=group   分组视图
 */
import { createApp, h, ref } from 'vue'
import CoreSettings from '@/components/CoreSettings.vue'
import type {
  CoreSettingsModel,
  CoreSettingsModelGroup,
  CoreSettingsProvider,
} from '@/components/model-catalog/types'
import { DEFAULT_THEME, themeForMode } from '@/helpers/theme.ts'
import { THEME_PRESETS } from '@/data/theme-presets.ts'
import '@/styles/variables.css'
import '@/styles/base.css'
import '@/styles/layout.css'
import '@/styles/sunday-controls.css'

const params = new URLSearchParams(location.search)
const light = params.get('theme') === 'light'

const providers = ref<CoreSettingsProvider[]>([
  {
    id: 'opencode-go', name: 'OpenCode Go', api_type: 'openai',
    base_url: 'https://opencode.ai/inference/go/v1', has_api_key: true,
    extra: { monthly_budget_usd: 20 },
  },
  {
    id: 'deepseek-official', name: 'DeepSeek Official', api_type: 'openai',
    base_url: 'https://api.deepseek.com', has_api_key: true, extra: {},
  },
  {
    id: 'anthropic', name: 'Anthropic', api_type: 'anthropic',
    base_url: 'https://api.anthropic.com/v1', has_api_key: true,
    extra: { monthly_budget_usd: 30 },
  },
  {
    id: 'local-gateway', name: 'Local Gateway', api_type: 'openai',
    base_url: 'http://127.0.0.1:8000/v1', has_api_key: false, extra: {},
  },
])

const models = ref<CoreSettingsModel[]>([
  {
    id: 'opencode-go-deepseek-v4.1-flash', provider_id: 'opencode-go', provider_name: 'OpenCode Go',
    model_id: 'deepseek-v4.1-flash', display_name: 'DeepSeek V4.1 Flash',
    context_window: 1000000, max_output_tokens: 131072, thinking_supported: true,
    thinking_budget: 10000, temperature: 0.7, is_default: true, capability: 'multimodal',
    notes: '',
    pricing: { input_per_1m: 0.14, output_per_1m: 0.28, cache_read_per_1m: 0.028, currency: 'USD' },
  },
  {
    id: 'opencode-go-glm-5.3-flash', provider_id: 'opencode-go', provider_name: 'OpenCode Go',
    model_id: 'glm-5.3-flash', display_name: 'GLM-5.3 Flash',
    context_window: 200000, max_output_tokens: 32768, thinking_supported: true,
    thinking_budget: 6000, temperature: 0.6, capability: 'text',
    pricing: { input_per_1m: 0.2, output_per_1m: 0.6, currency: 'USD' },
  },
  {
    id: 'opencode-go-kimi-k3', provider_id: 'opencode-go', provider_name: 'OpenCode Go',
    model_id: 'kimi-k3', display_name: 'Kimi K3',
    context_window: 512000, max_output_tokens: 65536, thinking_supported: true,
    thinking_budget: 8000, temperature: 0.7, capability: 'multimodal',
  },
  {
    id: 'opencode-go-qwen38max', provider_id: 'opencode-go', provider_name: 'OpenCode Go',
    model_id: 'qwen3.8-max', display_name: 'Qwen3.8 Max',
    context_window: 256000, max_output_tokens: 32768, thinking_supported: false,
    temperature: 0.7, capability: 'text', enabled: false,
  },
  {
    id: 'deepseek-official-deepseek-v4-pro', provider_id: 'deepseek-official', provider_name: 'DeepSeek Official',
    model_id: 'deepseek-v4-pro', display_name: 'DeepSeek V4 Pro',
    context_window: 1000000, max_output_tokens: 393216, thinking_supported: true,
    thinking_budget: 12000, temperature: 0.6, capability: 'text',
    pricing: { input_per_1m: 0.55, output_per_1m: 2.2, currency: 'USD' },
  },
  {
    id: 'deepseek-official-deepseek-flash', provider_id: 'deepseek-official', provider_name: 'DeepSeek Official',
    model_id: 'deepseek-flash', display_name: 'DeepSeek Flash',
    context_window: 1000000, max_output_tokens: 393216, thinking_supported: true,
    thinking_budget: 10000, temperature: 0.7, capability: 'multimodal',
  },
  {
    id: 'anthropic-claude-sonnet-5', provider_id: 'anthropic', provider_name: 'Anthropic',
    model_id: 'claude-sonnet-5', display_name: 'Claude Sonnet 5',
    context_window: 400000, max_output_tokens: 64000, thinking_supported: true,
    thinking_budget: 16000, temperature: 0.7, capability: 'multimodal',
    pricing: { input_per_1m: 3, output_per_1m: 15, currency: 'USD' },
  },
  {
    id: 'local-gateway-local-qwen', provider_id: 'local-gateway', provider_name: 'Local Gateway',
    model_id: 'local-qwen', display_name: 'Local Qwen',
    context_window: 128000, max_output_tokens: 8192, thinking_supported: false,
    temperature: 0.5, capability: 'text',
  },
])

const extraProviders = Number(params.get('providers') || 0)
const extraModels = Number(params.get('models') || 0)
for (let index = 0; index < extraProviders; index += 1) {
  providers.value.push({
    id: `extra-${index}`,
    name: `额外供应商 ${index + 1}`,
    api_type: 'openai',
    base_url: `https://gw${index + 1}.example.com/v1`,
    has_api_key: index % 3 !== 0,
    extra: {},
  })
}
for (let index = 0; index < extraModels; index += 1) {
  const provider = providers.value[(index + 1) % providers.value.length]
  models.value.push({
    id: `${provider.id}-extra-${index}`,
    provider_id: provider.id,
    provider_name: provider.name,
    model_id: `extra-model-${index}`,
    display_name: `Extra Model ${index + 1}`,
    context_window: 128000,
    max_output_tokens: 16384,
    thinking_supported: index % 2 === 0,
    temperature: 0.7,
    capability: index % 3 === 0 ? 'multimodal' : 'text',
    enabled: index % 4 !== 0,
  })
}

const groups = ref<CoreSettingsModelGroup[]>([
  {
    id: 'g-common', name: '常用',
    model_ids: ['opencode-go-deepseek-v4.1-flash', 'opencode-go-glm-5.3-flash', 'anthropic-claude-sonnet-5'],
    revision: 1,
  },
  {
    id: 'g-free', name: 'Free',
    model_ids: ['opencode-go-qwen38max', 'local-gateway-local-qwen'],
    revision: 1,
  },
])

function buildDaily(days: number): Array<Record<string, unknown>> {
  const today = new Date()
  return Array.from({ length: days }, (_, index) => {
    const date = new Date(today)
    date.setDate(today.getDate() - (days - 1 - index))
    const wave = Math.sin(index / 3.1) * 0.35 + Math.cos(index / 5.7) * 0.2
    const tokens = Math.max(0, Math.round(420000 + wave * 380000 + (index > days - 8 ? 260000 : 0)))
    return {
      date: date.toISOString().slice(0, 10),
      tokens,
      input_tokens: Math.round(tokens * 0.74),
      output_tokens: Math.round(tokens * 0.26),
      calls: Math.round(tokens / 9000),
      cached_tokens: Math.round(tokens * 0.32),
    }
  })
}

const daily = buildDaily(30)
const series = (base: number) => Array.from({ length: 14 }, (_, index) =>
  Math.round(base * (0.4 + Math.sin(index / 2.4) * 0.3 + index * 0.04)))

const usage = {
  range: '30d',
  days: 30,
  totals: {
    calls: 1842, input_tokens: 18_240_000, output_tokens: 6_380_000,
    cached_tokens: 5_420_000, tokens: 24_620_000, cost: 18.42,
    unpriced_tokens: 3_100_000, currency: 'USD',
  },
  by_model: [
    { model_record_id: 'opencode-go-deepseek-v4.1-flash', model_id: 'deepseek-v4.1-flash', provider_id: 'opencode-go', provider_name: 'OpenCode Go', calls: 980, input_tokens: 12_100_000, output_tokens: 4_100_000, cached_tokens: 3_900_000, tokens: 16_200_000, cost: 3.82, priced: true, last_used_at: new Date().toISOString() },
    { model_record_id: 'opencode-go-glm-5.3-flash', model_id: 'glm-5.3-flash', provider_id: 'opencode-go', provider_name: 'OpenCode Go', calls: 402, input_tokens: 2_400_000, output_tokens: 900_000, cached_tokens: 620_000, tokens: 3_300_000, cost: 1.02, priced: true, last_used_at: new Date().toISOString() },
    { model_record_id: 'anthropic-claude-sonnet-5', model_id: 'claude-sonnet-5', provider_id: 'anthropic', provider_name: 'Anthropic', calls: 120, input_tokens: 1_100_000, output_tokens: 420_000, cached_tokens: 300_000, tokens: 1_520_000, cost: 9.6, priced: true, last_used_at: new Date().toISOString() },
    { model_record_id: 'deepseek-official-deepseek-v4-pro', model_id: 'deepseek-v4-pro', provider_id: 'deepseek-official', provider_name: 'DeepSeek Official', calls: 72, input_tokens: 700_000, output_tokens: 260_000, cached_tokens: 120_000, tokens: 960_000, cost: 0.96, priced: true, last_used_at: new Date().toISOString() },
    { model_record_id: 'opencode-go-kimi-k3', model_id: 'kimi-k3', provider_id: 'opencode-go', provider_name: 'OpenCode Go', calls: 160, input_tokens: 1_400_000, output_tokens: 540_000, cached_tokens: 410_000, tokens: 1_940_000, cost: null, priced: false },
  ],
  by_provider: [
    { provider_id: 'opencode-go', provider_name: 'OpenCode Go', calls: 1602, input_tokens: 17_300_000, output_tokens: 6_150_000, cached_tokens: 5_100_000, tokens: 23_450_000, cost: 4.84, priced_tokens: 19_500_000, unpriced_tokens: 1_940_000, budget_usd: 20, month_cost: 4.84, month_tokens: 23_450_000 },
    { provider_id: 'anthropic', provider_name: 'Anthropic', calls: 120, input_tokens: 1_100_000, output_tokens: 420_000, cached_tokens: 300_000, tokens: 1_520_000, cost: 9.6, priced_tokens: 1_520_000, unpriced_tokens: 0, budget_usd: 30, month_cost: 9.6, month_tokens: 1_520_000 },
    { provider_id: 'deepseek-official', provider_name: 'DeepSeek Official', calls: 72, input_tokens: 700_000, output_tokens: 260_000, cached_tokens: 120_000, tokens: 960_000, cost: 0.96, priced_tokens: 960_000, unpriced_tokens: 0, budget_usd: null, month_cost: 0.96, month_tokens: 960_000 },
  ],
  daily,
  series: {
    'opencode-go-deepseek-v4.1-flash': series(1_400_000),
    'opencode-go-glm-5.3-flash': series(420_000),
    'anthropic-claude-sonnet-5': series(180_000),
    'deepseek-official-deepseek-v4-pro': series(120_000),
    'opencode-go-kimi-k3': series(90_000),
  },
  tracking_since: daily[0].date,
  since: daily[0].date,
}

const statuses: Record<string, Record<string, unknown>> = {
  'opencode-go': { state: 'ok', detail: '', latency_ms: 214, http_status: 200, model_count: 41, checked_at: new Date().toISOString() },
  'deepseek-official': { state: 'no_model_list', detail: '网关未提供模型列表接口', latency_ms: 96, http_status: 404, model_count: 0, checked_at: new Date().toISOString() },
  anthropic: { state: 'unauthorized', detail: 'API Key 被拒绝', latency_ms: 180, http_status: 401, model_count: 0, checked_at: new Date().toISOString() },
  'local-gateway': { state: 'missing_key', detail: '尚未配置 API Key', latency_ms: 0, http_status: 0, model_count: 0, checked_at: '' },
}

const requestRpc = async (method: string, payload?: Record<string, unknown>) => {
  if (method === 'config.models.usage') return structuredClone(usage)
  if (method === 'config.providers.status') return { providers: statuses, updated_at: new Date().toISOString() }
  if (method === 'config.providers.probe') return { providers: statuses, updated_at: new Date().toISOString() }
  if (method === 'config.model_groups.list') return { groups: groups.value, revision: 1 }
  if (method === 'settings.get') return { namespace: String(payload?.namespace || ''), value: {} }
  return {}
}

const persistCatalog = async (operation: string, payload: Record<string, unknown>) => {
  if (operation === 'create-provider') {
    const id = String(payload.name || 'provider').toLowerCase().replace(/\s+/g, '-')
    providers.value = [...providers.value, {
      id,
      name: String(payload.name || id),
      api_type: String(payload.api_type || 'openai'),
      base_url: String(payload.base_url || ''),
      has_api_key: true,
      extra: (payload.extra as Record<string, unknown>) || {},
    }]
    return
  }
  if (operation === 'update-provider') {
    providers.value = providers.value.map(provider => provider.id === payload.provider_id
      ? { ...provider, name: String(payload.name || provider.name), base_url: String(payload.base_url || provider.base_url), extra: (payload.extra as Record<string, unknown>) || {} }
      : provider)
    return
  }
  if (operation === 'create-model' || operation === 'update-model') {
    const id = String(payload.model_record_id || `${payload.provider_id}-${payload.model_id}`)
    const next = {
      id,
      provider_id: String(payload.provider_id || ''),
      provider_name: providers.value.find(provider => provider.id === payload.provider_id)?.name || '',
      model_id: String(payload.model_id || ''),
      display_name: String(payload.display_name || ''),
      context_window: Number(payload.context_window || 0),
      max_output_tokens: Number(payload.max_output_tokens || 0),
      temperature: Number(payload.temperature || 0),
      thinking_supported: Boolean(payload.thinking_supported),
      thinking_budget: Number(payload.thinking_budget || 0),
      capability: String(payload.capability || ''),
      notes: String(payload.notes || ''),
      enabled: payload.enabled !== false,
      is_default: Boolean(payload.is_default),
      pricing: payload.pricing as Record<string, number> | undefined,
    }
    models.value = [...models.value.filter(model => model.id !== id), next]
    return
  }
  if (operation === 'set-model-group-members') {
    groups.value = groups.value.map(group => group.id === payload.group_id
      ? { ...group, model_ids: payload.model_ids as string[] }
      : group)
    return
  }
  if (operation === 'create-model-group') {
    groups.value = [...groups.value, { id: `g-${groups.value.length + 1}`, name: String(payload.name || ''), model_ids: [], revision: 1 }]
    return
  }
  if (operation === 'update-model-group') {
    groups.value = groups.value.map(group => group.id === payload.group_id
      ? { ...group, name: String(payload.name || group.name) }
      : group)
  }
}

const lightPreset = THEME_PRESETS.find(preset => preset.id === 'sunday') || THEME_PRESETS[0]
const theme = light ? { ...DEFAULT_THEME, ...themeForMode(lightPreset, 'light') } : DEFAULT_THEME

createApp({
  render: () => h('div', { style: 'position:fixed;inset:0' }, [
    h(CoreSettings, {
      models: models.value,
      providers: providers.value,
      modelGroups: groups.value,
      catalogView: params.get('view') === 'group' ? 'group' : 'provider',
      section: 'models',
      density: 'standard',
      theme,
      themeMode: light ? 'light' : 'dark',
      effectiveThemeMode: light ? 'light' : 'dark',
      allowEnvironmentImport: true,
      commandShellPlatform: 'windows',
      requestRpc,
      persistCatalog,
      onClose() {},
      onSectionChange() {},
      'onUpdate:catalogView'() {},
      onCreateProvider() {},
      onUpdateProvider() {},
      onDeleteModel() {},
      onSetDefaultModel() {},
      onCreateModelGroup() {},
      onUpdateModelGroup() {},
      onDeleteModelGroup() {},
      onSetModelGroupMembers() {},
      onCreateModelWithProvider() {},
      onImportEnvironment() {},
    }),
  ]),
}).mount('#app')
