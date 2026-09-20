import { secureStorage, type SecureStorage } from '../native/secureStorage'

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

interface StandaloneConfigState {
  providers: StandaloneProvider[]
  models: StandaloneModel[]
  defaultModelId: string
  settings: Record<string, Record<string, unknown>>
}

const CONFIG_KEY = 'lamtools.mobile.standalone.config.v1'

export class StandaloneConfigStore {
  private state: StandaloneConfigState | null = null

  constructor(private readonly secrets: SecureStorage = secureStorage()) {}

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
      state.settings[namespace] = { ...(state.settings[namespace] || {}), ...value }
      await this.persist()
      return { ok: true, namespace, value: state.settings[namespace] }
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
    const apiKey = await this.secrets.get<string>(this.secretKey(provider.id)) || ''
    if (!apiKey) throw new Error('请先配置供应商 API Key')
    return { provider, model, apiKey }
  }

  private async createProvider(params: Record<string, unknown>): Promise<StandaloneProvider> {
    const state = await this.load()
    const id = uniqueId(slug(String(params.preset_id || params.name || 'provider')), state.providers.map((item) => item.id))
    const apiKey = String(params.api_key || '').trim()
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
    const apiKey = String(params.api_key || '').trim()
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
    try {
      const raw = globalThis.localStorage?.getItem(CONFIG_KEY)
      const parsed = raw ? JSON.parse(raw) as Partial<StandaloneConfigState> : {}
      this.state = {
        providers: Array.isArray(parsed.providers) ? parsed.providers : [],
        models: Array.isArray(parsed.models) ? parsed.models : [],
        defaultModelId: String(parsed.defaultModelId || ''),
        settings: isRecord(parsed.settings) ? parsed.settings as Record<string, Record<string, unknown>> : {},
      }
    } catch {
      this.state = { providers: [], models: [], defaultModelId: '', settings: {} }
    }
    return this.state
  }

  private async persist(): Promise<void> {
    if (!this.state) return
    globalThis.localStorage?.setItem(CONFIG_KEY, JSON.stringify(this.state))
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
