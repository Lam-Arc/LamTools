import { secureStorage, type SecureStorage } from '../native/secureStorage'
import {
  createStandaloneStateStorage,
  type StandaloneStateStorage,
} from './StandaloneStateStorage'
import { cloneState } from '../storage/cloneState'

export interface StandaloneProvider {
  id: string
  name: string
  api_type: string
  base_url: string
  has_api_key: boolean
  extra?: Record<string, unknown>
}

export interface StandaloneModel {
  id: string
  provider_id: string
  model_id: string
  display_name: string
  context_window?: number
  max_output_tokens?: number
  thinking_supported?: boolean
  thinking_budget?: number
  reasoning_off_supported?: boolean
  temperature?: number
  extra?: Record<string, unknown>
}

export interface StandaloneRuntimeModel {
  id: string
  displayName: string
  provider: StandaloneProvider
  model: StandaloneModel
  apiKey: string
}

interface StandaloneConfigState {
  providers: StandaloneProvider[]
  models: StandaloneModel[]
  defaultModelId: string
  settings: Record<string, Record<string, unknown>>
}

const CONFIG_KEY = 'lamtools.mobile.standalone.config.v1'
// Users may paste an entire Authorization header from a provider's curl example.
// Store/pass only the credential; the native provider adds its authentication scheme.
function providerApiKey(value: unknown): string {
  if (typeof value !== 'string') return ''
  const key = value.trim()
    .replace(/^authorization\s*:\s*/i, '')
    .replace(/^bearer(?:\s+|$)/i, '')
    .trim()
  if (/^[*•]+$/u.test(key) || /\s/u.test(key)) return ''
  return key
}
const SUB_AGENT_DEFAULT_GUIDE = 'Use reusable sub-agents for bounded independent work. Keep parent ownership, avoid recursive delegation, and return durable evidence.'

export class StandaloneConfigStore {
  private state: StandaloneConfigState | null = null

  constructor(
    private readonly secrets: SecureStorage = secureStorage(),
    private readonly storage: StandaloneStateStorage<StandaloneConfigState> = createStandaloneStateStorage({
      database: 'lamtools-mobile-config',
      scope: 'config',
      legacyKey: CONFIG_KEY,
    }),
  ) {}

  async handleRpc(method: string, params: Record<string, unknown>): Promise<Record<string, unknown> | null> {
    const state = await this.load()
    if (method === 'config.providers.list') return { providers: state.providers }
    if (method === 'config.models.list') return { models: state.models, default_model_id: state.defaultModelId }
    if (method === 'settings.get') {
      const namespace = String(params.namespace || '')
      return { namespace, value: state.settings[namespace] || {} }
    }
    if (method === 'settings.update') {
      const namespace = String(params.namespace || '')
      const value = isRecord(params.value) ? params.value : {}
      // Clone so a reactive object from a settings panel never becomes
      // stored state; structuredClone would later reject it.
      state.settings[namespace] = cloneState({ ...(state.settings[namespace] || {}), ...value })
      await this.persist()
      return { ok: true, namespace, value: state.settings[namespace] }
    }
    if (method === 'config.subagent.guide.get') {
      const scope = params.scope === 'project' ? 'project' : 'global'
      const projectKey = this.subAgentProjectKey(String(params.work_root || params.project_id || ''))
      const globalGuide = String(state.settings['core.subagent.guide.global']?.content || '')
      const projectGuide = projectKey ? String(state.settings[projectKey]?.content || '') : ''
      const own = scope === 'project' ? projectGuide : globalGuide
      return {
        content: own || globalGuide || SUB_AGENT_DEFAULT_GUIDE,
        is_builtin: !own,
      }
    }
    if (method === 'config.subagent.guide.set') {
      const scope = params.scope === 'project' ? 'project' : 'global'
      const namespace = scope === 'project'
        ? this.subAgentProjectKey(String(params.work_root || params.project_id || ''))
        : 'core.subagent.guide.global'
      if (!namespace) throw new Error('项目级 Sub Agent guide 需要项目标识')
      const content = String(params.content || '').trim()
      if (content) state.settings[namespace] = { content }
      else delete state.settings[namespace]
      await this.persist()
      return { ok: true }
    }
    if (method === 'config.subagent.settings.get') {
      return this.subAgentSettingsPayload(params)
    }
    if (method === 'config.subagent.settings.set') {
      const scope = params.scope === 'project' ? 'project' : 'global'
      const namespace = scope === 'project'
        ? this.subAgentProjectSettingsKey(String(params.work_root || params.project_id || ''))
        : 'core.subagent.settings.global'
      if (!namespace) throw new Error('项目级 Sub Agent 设置需要项目标识')
      const current = { ...(state.settings[namespace] || {}) }
      const patch = isRecord(params.settings) ? params.settings : {}
      for (const [key, value] of Object.entries(patch)) {
        if (value == null) delete current[key]
        else current[key] = cloneState(value)
      }
      if (Object.keys(current).length) state.settings[namespace] = current
      else delete state.settings[namespace]
      await this.persist()
      return this.subAgentSettingsPayload(params)
    }
    if (method === 'config.provider.create') {
      const provider = await this.createProvider(params)
      return { ok: true, provider }
    }
    if (method === 'config.provider.update') {
      const provider = await this.updateProvider(params)
      return { ok: true, provider }
    }
    if (method === 'config.provider.delete') {
      await this.deleteProvider(String(params.provider_id || params.id || ''))
      return { ok: true }
    }
    if (method === 'config.models.upsert') {
      const model = this.upsertModel(params)
      await this.persist()
      return { ok: true, model }
    }
    if (method === 'config.models.delete') {
      const modelId = String(params.model_id || params.id || '')
      state.models = state.models.filter((model) => model.id !== modelId)
      if (state.defaultModelId === modelId) state.defaultModelId = state.models[0]?.id || ''
      await this.persist()
      return { ok: true }
    }
    if (method === 'config.models.set_default') {
      const modelId = String(params.model_id || '')
      if (!state.models.some((model) => model.id === modelId)) throw new Error('模型不存在')
      state.defaultModelId = modelId
      await this.persist()
      return { ok: true, default_model_id: modelId }
    }
    return null
  }

  async activeModel(requestedId?: string): Promise<{ provider: StandaloneProvider; model: StandaloneModel; apiKey: string }> {
    const state = await this.load()
    const model = state.models.find((candidate) => candidate.id === requestedId)
      || state.models.find((candidate) => candidate.id === state.defaultModelId)
      || state.models[0]
    if (!model) throw new Error('请先在设置中添加模型与供应商')
    const provider = state.providers.find((candidate) => candidate.id === model.provider_id)
    if (!provider) throw new Error('模型对应的供应商不存在')
    const apiKey = providerApiKey(await this.secrets.get<string>(this.secretKey(provider.id)))
    if (!apiKey) throw new Error('请先配置供应商 API Key')
    return { provider, model, apiKey }
  }

  async runtimeModels(): Promise<StandaloneRuntimeModel[]> {
    const state = await this.load()
    const providers = new Map(state.providers.map(provider => [provider.id, provider]))
    const keys = new Map<string, string>()
    await Promise.all(state.providers.map(async provider => {
      keys.set(provider.id, providerApiKey(await this.secrets.get<string>(this.secretKey(provider.id))))
    }))
    return state.models.flatMap(model => {
      const provider = providers.get(model.provider_id)
      if (!provider) return []
      return [{
        id: model.id,
        displayName: model.display_name,
        provider,
        model,
        apiKey: keys.get(provider.id) || '',
      }]
    })
  }

  async settings(namespace: string): Promise<Record<string, unknown>> {
    const state = await this.load()
    // Hand back a copy: the caller must not mutate stored state, and a
    // reactive copy of it must not be able to leak back in either.
    return cloneState(state.settings[namespace] || {})
  }

  async subAgentRuntime(projectId: string): Promise<{ enabled: boolean; guide: string }> {
    const state = await this.load()
    const globalSettings = this.normalizedSubAgentSettings(state.settings['core.subagent.settings.global'])
    const projectKeys = [projectId, `mobile://${projectId}`]
    const projectSettings = this.normalizedSubAgentSettings(projectKeys
      .map(key => state.settings[this.subAgentProjectSettingsKey(key)])
      .find(isRecord), true)
    const strategy = String(projectSettings.delegation_strategy || globalSettings.delegation_strategy || 'medium')
    const globalGuide = String(state.settings['core.subagent.guide.global']?.content || '')
    const projectGuide = String(projectKeys
      .map(key => state.settings[this.subAgentProjectKey(key)]?.content)
      .find(value => typeof value === 'string' && value) || '')
    return {
      enabled: strategy !== 'forbidden',
      guide: projectGuide || globalGuide || SUB_AGENT_DEFAULT_GUIDE,
    }
  }

  private subAgentSettingsPayload(params: Record<string, unknown>): Record<string, unknown> {
    if (!this.state) throw new Error('配置尚未初始化')
    const scope = params.scope === 'project' ? 'project' : 'global'
    const projectId = String(params.work_root || params.project_id || '')
    const globalSettings = this.normalizedSubAgentSettings(this.state.settings['core.subagent.settings.global'])
    const projectRaw = projectId
      ? this.normalizedSubAgentSettings(this.state.settings[this.subAgentProjectSettingsKey(projectId)], true)
      : {}
    const effective = { ...globalSettings, ...projectRaw }
    const globalRoles = normalizeRoleAssignments(globalSettings.role_assignments)
    const projectRoles = normalizeRoleAssignments(projectRaw.role_assignments)
    const roleMap = new Map(globalRoles.map(role => [String(role.task_type).toLowerCase(), role]))
    for (const role of projectRoles) roleMap.set(String(role.task_type).toLowerCase(), role)
    const effectiveRoles = [...roleMap.values()]
    return {
      settings: scope === 'project' ? projectRaw : globalSettings,
      effective_delegation_strategy: effective.delegation_strategy || 'medium',
      global_delegation_strategy: globalSettings.delegation_strategy || 'medium',
      inherited_delegation_strategy: globalSettings.delegation_strategy || 'medium',
      delegation_strategy_inherited: scope === 'project' && !('delegation_strategy' in projectRaw),
      effective_role_assignments: effectiveRoles,
      role_assignments_inherited: scope === 'project' && !('role_assignments' in projectRaw),
    }
  }

  private normalizedSubAgentSettings(
    value: Record<string, unknown> | undefined,
    allowEmpty = false,
  ): Record<string, unknown> {
    const result = isRecord(value) ? cloneState(value) : {}
    if (!allowEmpty && !('delegation_strategy' in result)) result.delegation_strategy = 'medium'
    if (!allowEmpty && !('role_assignments' in result)) result.role_assignments = []
    return result
  }

  private subAgentProjectKey(projectId: string): string {
    const normalized = projectId.trim()
    return normalized ? `core.subagent.guide.project:${normalized}` : ''
  }

  private subAgentProjectSettingsKey(projectId: string): string {
    const normalized = projectId.trim()
    return normalized ? `core.subagent.settings.project:${normalized}` : ''
  }

  private async createProvider(params: Record<string, unknown>): Promise<StandaloneProvider> {
    const state = await this.load()
    const id = uniqueId(slug(String(params.preset_id || params.name || 'provider')), state.providers.map((item) => item.id))
    const apiKey = providerApiKey(params.api_key)
    if (params.api_key && !apiKey) throw new Error('API Key 无效，请粘贴完整密钥，不能使用脱敏占位符')
    const provider: StandaloneProvider = {
      id,
      name: String(params.name || id),
      api_type: String(params.api_type || 'openai'),
      base_url: String(params.base_url || '').replace(/\/$/, ''),
      has_api_key: Boolean(apiKey),
      extra: isRecord(params.extra) ? params.extra : {},
    }
    if (apiKey) await this.secrets.set(this.secretKey(id), apiKey)
    state.providers.push(provider)
    const models = Array.isArray(params.models) ? params.models.filter(isRecord) : []
    for (const raw of models) this.upsertModel({ ...raw, provider_id: id })
    if (!state.defaultModelId && state.models.length) state.defaultModelId = state.models[0].id
    await this.persist()
    return provider
  }

  private async updateProvider(params: Record<string, unknown>): Promise<StandaloneProvider> {
    const state = await this.load()
    const id = String(params.provider_id || params.id || '')
    const index = state.providers.findIndex((provider) => provider.id === id)
    if (index < 0) throw new Error('供应商不存在')
    const current = state.providers[index]
    const suppliedKey = String(params.api_key || '').trim()
    const apiKey = suppliedKey === '********' ? '' : providerApiKey(params.api_key)
    if (suppliedKey && suppliedKey !== '********' && !apiKey) throw new Error('API Key 无效，请粘贴完整密钥，不能使用脱敏占位符')
    if (apiKey && apiKey !== '********') await this.secrets.set(this.secretKey(id), apiKey)
    const provider: StandaloneProvider = {
      ...current,
      ...(params.name ? { name: String(params.name) } : {}),
      ...(params.api_type ? { api_type: String(params.api_type) } : {}),
      ...(params.base_url ? { base_url: String(params.base_url).replace(/\/$/, '') } : {}),
      has_api_key: current.has_api_key || Boolean(apiKey && apiKey !== '********'),
      ...(isRecord(params.extra) ? { extra: params.extra } : {}),
    }
    state.providers[index] = provider
    await this.persist()
    return provider
  }

  private async deleteProvider(id: string): Promise<void> {
    const state = await this.load()
    state.providers = state.providers.filter((provider) => provider.id !== id)
    state.models = state.models.filter((model) => model.provider_id !== id)
    if (!state.models.some((model) => model.id === state.defaultModelId)) state.defaultModelId = state.models[0]?.id || ''
    await this.secrets.remove(this.secretKey(id))
    await this.persist()
  }

  private upsertModel(params: Record<string, unknown>): StandaloneModel {
    if (!this.state) throw new Error('配置尚未初始化')
    const providerId = String(params.provider_id || '')
    const upstreamId = String(params.model_id || params.id || '')
    if (!providerId || !upstreamId) throw new Error('模型配置不完整')
    const existingId = String(params.model_record_id || params.id || '')
    const id = existingId || `${providerId}:${upstreamId}`
    const current = this.state.models.find((model) => model.id === id)
    const model: StandaloneModel = {
      ...current,
      id,
      provider_id: providerId,
      model_id: upstreamId,
      display_name: String(params.display_name || current?.display_name || upstreamId),
      context_window: numberOrUndefined(params.context_window) ?? current?.context_window,
      max_output_tokens: numberOrUndefined(params.max_output_tokens) ?? current?.max_output_tokens,
      thinking_supported: booleanOrUndefined(params.thinking_supported) ?? current?.thinking_supported,
      thinking_budget: numberOrUndefined(params.thinking_budget) ?? current?.thinking_budget,
      reasoning_off_supported: booleanOrUndefined(params.reasoning_off_supported) ?? current?.reasoning_off_supported,
      temperature: numberOrUndefined(params.temperature) ?? current?.temperature,
      extra: isRecord(params.extra) ? params.extra : current?.extra,
    }
    this.state.models = [model, ...this.state.models.filter((candidate) => candidate.id !== id)]
    if (!this.state.defaultModelId) this.state.defaultModelId = id
    return model
  }

  private async load(): Promise<StandaloneConfigState> {
    if (this.state) return this.state
    const parsed = await this.storage.read() || {} as Partial<StandaloneConfigState>
    this.state = {
      providers: Array.isArray(parsed.providers) ? parsed.providers : [],
      models: Array.isArray(parsed.models) ? parsed.models : [],
      defaultModelId: String(parsed.defaultModelId || ''),
      settings: isRecord(parsed.settings) ? parsed.settings as Record<string, Record<string, unknown>> : {},
    }
    return this.state
  }

  private async persist(): Promise<void> {
    if (!this.state) return
    await this.storage.write(this.state)
  }

  private secretKey(providerId: string): string {
    return `standalone.provider.${providerId}.api-key`
  }
}

function slug(value: string): string {
  return value.toLowerCase().trim().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'provider'
}

function uniqueId(base: string, existing: string[]): string {
  if (!existing.includes(base)) return base
  let index = 2
  while (existing.includes(`${base}-${index}`)) index += 1
  return `${base}-${index}`
}

function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function numberOrUndefined(value: unknown): number | undefined {
  if (value == null || value === '') return undefined
  const result = Number(value)
  return Number.isFinite(result) ? result : undefined
}

function booleanOrUndefined(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined
}

function normalizeRoleAssignments(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter(isRecord).map(item => ({ ...item })) : []
}
