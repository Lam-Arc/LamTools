import { secureStorage, type SecureStorage } from '../native/secureStorage'
import {
  hasEmbeddedRustCore,
  listEmbeddedPluginModeTools,
  readEmbeddedModelReasoningDeclaration,
  readEmbeddedPluginSchemas,
  readEmbeddedToolCatalog,
  type EmbeddedCatalogTool,
  type EmbeddedPluginSchema,
} from '../native/rustAgent'
import {
  hasSecretField,
  maskPluginSecrets,
  pluginConfigNamespace,
  preservePluginSecrets,
  validatePluginConfig,
} from './pluginSchema'
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

/** One grade a model declares, in the model's own order and wording. */
export interface StandaloneReasoningLevel {
  value: string
  label: string
}

export interface StandaloneModel {
  id: string
  provider_id: string
  model_id: string
  display_name: string
  notes?: string
  context_window?: number
  max_output_tokens?: number
  thinking_supported?: boolean
  thinking_budget?: number
  reasoning_off_supported?: boolean
  /**
   * The reasoning ladder this model declares, in the desktop's
   * `reasoning_levels` shape. Absent or empty keeps the product ladder, so no
   * surface offers a grade the model never claimed.
   *
   * Attached to every model this store hands to the shared Composer; see
   * `modelWithReasoningDeclaration` for where the ladder comes from.
   */
  reasoning_levels?: StandaloneReasoningLevel[]
  temperature?: number
  extra?: Record<string, unknown>
}

export interface LoadToolMode {
  description: string
  tools: string[]
}

export type LoadToolModes = Record<string, LoadToolMode>

export interface StandaloneToolCatalogEntry {
  name: string
  category: string
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
  modelGroups: StandaloneModelGroupsState
}

interface StandaloneModelGroup {
  id: string
  name: string
  order: number
}

interface StandaloneModelGroupMembership {
  group_id: string
  model_id: string
  order: number
}

interface StandaloneModelGroupsState {
  version: 1
  revision: number
  groups: StandaloneModelGroup[]
  memberships: StandaloneModelGroupMembership[]
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
  private pluginSchemas: Record<string, EmbeddedPluginSchema> | null = null

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
    if (method === 'config.models.list') {
      // The shared Composer reads each model's declared reasoning ladder off this
      // response, so every model is handed out with its ladder attached.
      const providers = new Map(state.providers.map(provider => [provider.id, provider]))
      const models = await Promise.all(state.models.map(
        model => modelWithReasoningDeclaration(model, providers.get(model.provider_id)),
      ))
      return { models, default_model_id: state.defaultModelId }
    }
    if (method === 'config.model_groups.list') return this.modelGroupsSnapshot(true)
    if (method === 'config.model_group.create') return await this.createModelGroup(params)
    if (method === 'config.model_group.update') return await this.updateModelGroup(params)
    if (method === 'config.model_group.delete') return await this.deleteModelGroup(params)
    if (method === 'config.model_group.members.set') return await this.setModelGroupMembers(params)
    if (method === 'config.model_groups.reorder') return await this.reorderModelGroups(params)
    if (method === 'config.model.create_with_provider') return await this.createModelWithProvider(params)
    if (method === 'settings.get') {
      const namespace = String(params.namespace || '')
      return { namespace, value: this.settingsValue(namespace) }
    }
    if (method === 'settings.update') {
      const namespace = String(params.namespace || '')
      const value = isRecord(params.value) ? params.value : {}
      if (namespace === 'core.modelRetry') {
        const merged = validateModelRetryUpdate(this.settingsValue(namespace), value)
        state.settings[namespace] = merged
        await this.persist()
        return { ok: true, namespace, value: cloneState(merged) }
      }
      if (namespace === 'core.loadContext') {
        const merged = validateLoadContext({ ...this.settingsValue(namespace), ...value })
        state.settings[namespace] = merged
        await this.persist()
        return { ok: true, namespace, value: cloneState(merged) }
      }
      if (namespace === 'core.globalContext') {
        const merged = normalizeGlobalContext({ ...this.settingsValue(namespace), ...value })
        state.settings[namespace] = merged
        await this.persist()
        return { ok: true, namespace, value: cloneState(merged) }
      }
      // Clone so a reactive object from a settings panel never becomes
      // stored state; structuredClone would later reject it.
      state.settings[namespace] = cloneState({ ...(state.settings[namespace] || {}), ...value })
      await this.persist()
      return { ok: true, namespace, value: state.settings[namespace] }
    }
    if (method === 'config.agents_md.get') {
      const globalContext = state.settings['core.globalContext'] || {}
      return { agents_md: { content: stringSetting(globalContext.instructions), exists: hasOwn(globalContext, 'instructions') } }
    }
    if (method === 'config.agents_md.set') {
      const globalContext = { ...normalizeGlobalContext(state.settings['core.globalContext'] || {}) }
      globalContext.instructions = String(params.content || '')
      state.settings['core.globalContext'] = globalContext
      await this.persist()
      return { agents_md: { content: globalContext.instructions, exists: true } }
    }
    if (method === 'config.load_context.get') {
      const exists = hasOwn(state.settings, 'core.loadContext')
      return { ...normalizeLoadContext(state.settings['core.loadContext'] || {}), exists }
    }
    if (method === 'config.load_context.set') {
      const config = validateLoadContext(params)
      state.settings['core.loadContext'] = config
      await this.persist()
      return { ...cloneState(config), exists: true }
    }
    if (method === 'websearch.config.get') {
      // The desktop forwards this to the websearch plugin config and hands back
      // the JSONC document; the editor edits that text, so the phone answers in
      // the same shape from the namespace the runtime reads.
      const stored = await this.pluginConfig('websearch')
      return {
        content: Object.keys(stored).length ? `${JSON.stringify(stored, null, 2)}
` : '',
        path: 'mobile://config/websearch.jsonc',
      }
    }
    if (method === 'websearch.config.update') {
      const content = String(params.content ?? '')
      let parsed: unknown = {}
      if (content.trim()) {
        try {
          parsed = JSON.parse(stripJsoncComments(content))
        } catch (error) {
          throw new Error(`Invalid JSON/JSONC: ${error instanceof Error ? error.message : String(error)}`)
        }
      }
      if (!isRecord(parsed)) throw new Error('websearch 配置必须是对象')
      const state2 = await this.load()
      state2.settings[pluginConfigNamespace('websearch')] = parsed
      await this.persist()
      return { path: 'mobile://config/websearch.jsonc', saved: true }
    }
    if (method === 'plugin.config.get') {
      const name = String(params.name || '')
      const entry = await this.pluginSchema(name)
      return {
        name,
        config: maskPluginSecrets(entry.schema, await this.pluginConfig(name)),
        schema: entry.schema,
        config_schema_path: entry.path,
        has_secrets: hasSecretField(entry.schema),
        work_root: '',
      }
    }
    if (method === 'plugin.config.update') {
      const name = String(params.name || '')
      const entry = await this.pluginSchema(name)
      if (!isRecord(params.config)) throw new Error('config 必须是对象')
      const errors = validatePluginConfig(entry.schema, params.config)
      if (errors.length) throw new Error(`config validation failed: ${errors.join('; ')}`)
      const current = await this.pluginConfig(name)
      const merged = preservePluginSecrets(entry.schema, params.config, current)
      state.settings[pluginConfigNamespace(name)] = merged
      await this.persist()
      return { name, config: merged, validated: true }
    }
    if (method === 'config.loadtools.get') {
      const { modes, source } = await this.loadTools()
      return { modes: cloneState(modes), source, catalog: await this.toolCatalog() }
    }
    if (method === 'config.loadtools.set') {
      const raw = params.modes
      if (!isRecord(raw)) throw new Error('modes 不能为空')
      const modes = normalizeLoadToolModes(raw, { requireNonEmpty: true })
      if (Object.keys(modes).length === 0) throw new Error('至少需要一个模式')
      // Stored exactly as sent — a name this host cannot run stays on disk so a
      // later version that implements it does not have to ask again — but the
      // answer reports what is actually in force, which is what the panel shows.
      state.settings[LOAD_TOOLS_NAMESPACE] = { modes }
      await this.persist()
      const known = new Set((await this.toolCatalog()).map(tool => tool.name))
      return {
        modes: cloneState(known.size ? restrictModesToCatalog(modes, known) : modes),
        source: 'config',
      }
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
      this.removeModelGroupMemberships([modelId])
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
    return { provider, model: await modelWithReasoningDeclaration(model, provider), apiKey }
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

  /**
   * Mode tool-sets, with the source they came from.
   *
   * The desktop reads `loadtools.jsonc` and falls back to its built-in modes;
   * the phone has no config directory, so the same document lives in this store
   * under one namespace and the shape stays identical.
   *
   * Tool names the host cannot run are dropped, so a mode can never promise the
   * model a tool that would be refused: the desktop's built-in `consider` mode
   * names `git_status`, which has no implementation here.
   */
  async loadTools(): Promise<{ modes: LoadToolModes; source: 'builtin' | 'config' }> {
    const state = await this.load()
    const stored = state.settings[LOAD_TOOLS_NAMESPACE]
    const modes = stored && isRecord(stored.modes) && Object.keys(stored.modes).length > 0
      ? normalizeLoadToolModes(stored.modes)
      : builtinLoadToolModes()
    const source = stored && isRecord(stored.modes) && Object.keys(stored.modes).length > 0
      ? 'config' as const
      : 'builtin' as const
    const known = new Set((await this.toolCatalog()).map(tool => tool.name))
    if (!known.size) return { modes, source }
    return { modes: restrictModesToCatalog(modes, known), source }
  }

  /**
   * Everything a turn needs to enforce the active mode.
   *
   * `tools` is the whitelist, or `null` when the mode restricts nothing — the
   * same answer the desktop's `mode_tool_set` gives for an unknown mode or a
   * full-access (empty) whitelist. `promptLine` mirrors the desktop's
   * `mode_prompt_line`, so the model is told which mode it is running in.
   */
  async modePlan(activeMode: string): Promise<{ tools: string[] | null; promptLine: string }> {
    const mode = activeMode.trim()
    if (!mode) return { tools: null, promptLine: '' }
    if (mode.includes(':')) {
      // Plugin modes are declared by the plugin rather than by loadtools.jsonc,
      // and the plugin speaks for its own prompt.
      const declared = await listEmbeddedPluginModeTools(mode)
      return { tools: declared.length ? declared : null, promptLine: '' }
    }
    const { modes } = await this.loadTools()
    const entry = modes[mode]
    if (!entry) return { tools: null, promptLine: '' }
    return {
      tools: entry.tools.length ? [...entry.tools] : null,
      promptLine: `Current mode: ${mode} — ${entry.description || mode}`,
    }
  }

  /** Tool names and categories for the mode editor's checklist. */
  async toolCatalog(): Promise<StandaloneToolCatalogEntry[]> {
    if (!hasEmbeddedRustCore()) return []
    return await readEmbeddedToolCatalog()
  }

  /** The plugin's settings document, from the namespace the runtime reads. */
  private async pluginConfig(name: string): Promise<Record<string, unknown>> {
    const state = await this.load()
    return cloneState(state.settings[pluginConfigNamespace(name)] || {})
  }

  /**
   * The schema the host ships for one plugin.
   *
   * A plugin without one has nothing to configure on this device, and saying so
   * is better than showing a form whose values nothing reads.
   */
  private async pluginSchema(name: string): Promise<EmbeddedPluginSchema> {
    if (this.pluginSchemas === null) {
      try {
        this.pluginSchemas = hasEmbeddedRustCore() ? await readEmbeddedPluginSchemas() : {}
      } catch (error) {
        this.pluginSchemas = null
        throw new Error(`插件配置结构读取失败：${error instanceof Error ? error.message : String(error)}`)
      }
    }
    const entry = this.pluginSchemas[name]
    if (!entry) throw new Error(`插件 '${name}' 没有可配置项`)
    return entry
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

  private settingsValue(namespace: string): Record<string, unknown> {
    if (!this.state) throw new Error('配置尚未初始化')
    const stored = this.state.settings[namespace] || {}
    if (namespace === 'core.globalContext') return normalizeGlobalContext(stored)
    if (namespace === 'core.loadContext') return normalizeLoadContext(stored)
    if (namespace === 'core.modelRetry') return normalizeModelRetryConfig(stored)
    return cloneState(stored)
  }

  private modelGroupsSnapshot(includeAvailability: boolean): Record<string, unknown> {
    if (!this.state) throw new Error('配置尚未初始化')
    const groupsState = this.state.modelGroups
    const availableIds = new Set(this.state.models.map(model => model.id))
    const memberships = [...groupsState.memberships]
      .sort((left, right) => left.group_id.localeCompare(right.group_id)
        || left.order - right.order || left.model_id.localeCompare(right.model_id))
    const renderedMemberships = memberships.map(item => ({
      ...item,
      ...(includeAvailability ? { available: availableIds.has(item.model_id) } : {}),
    }))
    const visibleByGroup = new Map<string, string[]>()
    const danglingByGroup = new Map<string, string[]>()
    for (const item of memberships) {
      const target = includeAvailability && !availableIds.has(item.model_id) ? danglingByGroup : visibleByGroup
      const list = target.get(item.group_id) || []
      list.push(item.model_id)
      target.set(item.group_id, list)
    }
    const groups = [...groupsState.groups]
      .sort((left, right) => left.order - right.order || left.id.localeCompare(right.id))
      .map(group => ({
        ...group,
        model_ids: visibleByGroup.get(group.id) || [],
        dangling_model_ids: danglingByGroup.get(group.id) || [],
      }))
    return {
      version: 1,
      revision: groupsState.revision,
      groups,
      memberships: renderedMemberships,
    }
  }

  private async createModelGroup(params: Record<string, unknown>): Promise<Record<string, unknown>> {
    const state = this.requireState()
    const name = validateModelGroupName(params.name)
    checkGroupRevision(state.modelGroups, params.expected_revision)
    ensureUniqueGroupName(state.modelGroups, name)
    const modelIds = this.validatedModelIds(params.model_ids)
    const id = uniqueId(`mg-${randomHex()}`, state.modelGroups.groups.map(item => item.id))
    const order = state.modelGroups.groups.length
    state.modelGroups.groups.push({ id, name, order })
    state.modelGroups.memberships.push(...modelIds.map((model_id, membershipOrder) => ({
      group_id: id, model_id, order: membershipOrder,
    })))
    commitGroupMutation(state.modelGroups)
    await this.persist()
    return { group_id: id, ...this.modelGroupsSnapshot(false) }
  }

  private async updateModelGroup(params: Record<string, unknown>): Promise<Record<string, unknown>> {
    const state = this.requireState()
    checkGroupRevision(state.modelGroups, params.expected_revision)
    const group = findModelGroup(state.modelGroups, params.group_id || params.id)
    const name = validateModelGroupName(params.name)
    ensureUniqueGroupName(state.modelGroups, name, group.id)
    group.name = name
    commitGroupMutation(state.modelGroups)
    await this.persist()
    return this.modelGroupsSnapshot(false)
  }

  private async deleteModelGroup(params: Record<string, unknown>): Promise<Record<string, unknown>> {
    const state = this.requireState()
    checkGroupRevision(state.modelGroups, params.expected_revision)
    const group = findModelGroup(state.modelGroups, params.group_id || params.id)
    state.modelGroups.groups = state.modelGroups.groups.filter(item => item.id !== group.id)
    state.modelGroups.memberships = state.modelGroups.memberships.filter(item => item.group_id !== group.id)
    normalizeModelGroupOrders(state.modelGroups)
    commitGroupMutation(state.modelGroups)
    await this.persist()
    return this.modelGroupsSnapshot(false)
  }

  private async setModelGroupMembers(params: Record<string, unknown>): Promise<Record<string, unknown>> {
    const state = this.requireState()
    checkGroupRevision(state.modelGroups, params.expected_revision)
    const group = findModelGroup(state.modelGroups, params.group_id)
    const modelIds = this.validatedModelIds(params.model_ids)
    state.modelGroups.memberships = state.modelGroups.memberships.filter(item => item.group_id !== group.id)
    state.modelGroups.memberships.push(...modelIds.map((model_id, order) => ({
      group_id: group.id, model_id, order,
    })))
    commitGroupMutation(state.modelGroups)
    await this.persist()
    return this.modelGroupsSnapshot(false)
  }

  private async reorderModelGroups(params: Record<string, unknown>): Promise<Record<string, unknown>> {
    const state = this.requireState()
    checkGroupRevision(state.modelGroups, params.expected_revision)
    if (!Array.isArray(params.group_ids)) throw new Error('group_ids must be an array')
    const requested = params.group_ids.map(value => validateConfigId('model group', value))
    if (requested.length !== new Set(requested).size) throw new Error('group_ids must not contain duplicates')
    const existing = new Set(state.modelGroups.groups.map(item => item.id))
    if (requested.length !== existing.size || requested.some(id => !existing.has(id))) {
      throw new Error('group_ids must contain every model group exactly once')
    }
    const orderById = new Map(requested.map((id, order) => [id, order]))
    for (const group of state.modelGroups.groups) group.order = orderById.get(group.id)!
    commitGroupMutation(state.modelGroups)
    await this.persist()
    return this.modelGroupsSnapshot(false)
  }

  private async createModelWithProvider(params: Record<string, unknown>): Promise<Record<string, unknown>> {
    const state = this.requireState()
    if (!isRecord(params.model) || !isRecord(params.provider)) throw new Error('model and provider objects are required')
    const groupId = validateConfigId('model group', params.group_id)
    const group = findModelGroup(state.modelGroups, groupId)
    checkGroupRevision(state.modelGroups, params.expected_revision)
    const modelInput = params.model
    const providerInput = params.provider
    const baseUrl = normalizeProviderBaseUrl(providerInput.base_url)
    const mode = String(providerInput.mode || '').trim().toLowerCase()
    let provider = state.providers.find(item => item.id === String(providerInput.provider_id || ''))
    let createdProvider = false
    let apiKey = ''
    if (mode === 'existing') {
      if (!provider) throw new Error(`provider not found: ${providerInput.provider_id || ''}`)
      if (normalizeProviderBaseUrl(provider.base_url) !== baseUrl) throw new Error('base_url does not match the selected provider')
    } else if (mode === 'new') {
      const name = String(providerInput.name || '').trim()
      if (!name) throw new Error('provider.name is required for mode=new')
      const explicitId = String(providerInput.id || '').trim()
      const baseId = validateConfigId('provider', explicitId || slug(name))
      const providerId = uniqueId(baseId, state.providers.map(item => item.id))
      apiKey = providerApiKey(providerInput.api_key)
      if (providerInput.api_key && !apiKey) throw new Error('API Key 无效，请粘贴完整密钥，不能使用脱敏占位符')
      const extra: Record<string, unknown> = isRecord(providerInput.extra) ? { ...providerInput.extra } : {}
      for (const key of ['adapter_profile_id', 'request_body', 'adapter_profile_override', 'reasoning']) {
        if (providerInput[key] !== undefined) extra[key] = cloneState(providerInput[key])
      }
      provider = {
        id: providerId,
        name,
        api_type: String(providerInput.api_type || 'openai').trim(),
        base_url: baseUrl,
        has_api_key: Boolean(apiKey),
        extra,
      }
      createdProvider = true
    } else {
      throw new Error('provider.mode must be existing or new')
    }

    const upstreamId = String(modelInput.model_id || '').trim()
    if (!upstreamId) throw new Error('model.model_id is required')
    const baseModelId = String(modelInput.model_record_id || modelInput.id || `${provider!.id}:${upstreamId}`).trim()
    const modelRecordId = uniqueId(baseModelId, state.models.map(item => item.id))
    const before = cloneState(state)
    const extra: Record<string, unknown> = isRecord(modelInput.extra) ? { ...modelInput.extra } : {}
    if (modelInput.adapter_profile_id !== undefined) extra.adapter_profile_id = modelInput.adapter_profile_id
    if (modelInput.request_body !== undefined) extra.request_body = cloneState(modelInput.request_body)
    if (modelInput.capability !== undefined) extra.capability = modelInput.capability
    const model = this.upsertModel({
      ...modelInput,
      model_record_id: modelRecordId,
      provider_id: provider!.id,
      model_id: upstreamId,
      extra,
    })
    if (createdProvider) state.providers.push(provider!)
    const groupIds = state.modelGroups.memberships
      .filter(item => item.group_id === group.id)
      .sort((left, right) => left.order - right.order)
      .map(item => item.model_id)
    groupIds.push(model.id)
    state.modelGroups.memberships = state.modelGroups.memberships.filter(item => item.group_id !== group.id)
    state.modelGroups.memberships.push(...uniqueStrings(groupIds).map((model_id, order) => ({
      group_id: group.id, model_id, order,
    })))
    commitGroupMutation(state.modelGroups)
    try {
      if (createdProvider && apiKey) await this.secrets.set(this.secretKey(provider!.id), apiKey)
      await this.persist()
    } catch (error) {
      // Do not expose a half-created catalog when the native write fails.
      if (createdProvider) await this.secrets.remove(this.secretKey(provider!.id))
      this.state = before
      throw error
    }
    return {
      provider: providerResponse(provider!, apiKey),
      model: await modelResponse(model, provider),
      groups: this.modelGroupsSnapshot(false),
      created_provider: createdProvider,
    }
  }

  private validatedModelIds(value: unknown): string[] {
    if (value == null) return []
    if (!Array.isArray(value)) throw new Error('model_ids must be an array')
    const existing = new Set(this.requireState().models.map(item => item.id))
    const result: string[] = []
    for (const raw of value) {
      const id = String(raw || '').trim()
      if (!existing.has(id)) throw new Error(`model not found: ${id}`)
      if (!result.includes(id)) result.push(id)
    }
    return result
  }

  private removeModelGroupMemberships(modelIds: string[]): void {
    if (!this.state || !modelIds.length) return
    const removed = new Set(modelIds)
    const before = this.state.modelGroups.memberships.length
    this.state.modelGroups.memberships = this.state.modelGroups.memberships.filter(item => !removed.has(item.model_id))
    if (this.state.modelGroups.memberships.length !== before) {
      normalizeModelGroupOrders(this.state.modelGroups)
      commitGroupMutation(this.state.modelGroups)
    }
  }

  private requireState(): StandaloneConfigState {
    if (!this.state) throw new Error('配置尚未初始化')
    return this.state
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
    const removedModelIds = state.models.filter(model => model.provider_id === id).map(model => model.id)
    state.providers = state.providers.filter((provider) => provider.id !== id)
    state.models = state.models.filter((model) => model.provider_id !== id)
    if (!state.models.some((model) => model.id === state.defaultModelId)) state.defaultModelId = state.models[0]?.id || ''
    this.removeModelGroupMemberships(removedModelIds)
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
      // Model notes are user-authored system context, so an explicit empty
      // string must clear them while an omitted field preserves the old value.
      notes: typeof params.notes === 'string' ? params.notes : current?.notes,
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
      modelGroups: normalizeStoredModelGroups(parsed.modelGroups),
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

const DEFAULT_MODEL_RETRY_CONFIG: Record<string, unknown> = {
  retry_delays_seconds: [1, 1, 2, 5, 5],
  model_retries: 10,
  model_timeout_seconds: 360,
  model_stream_idle_timeout_seconds: 120,
  empty_response_retries: 3,
  jitter: true,
}

function normalizeGlobalContext(value: unknown): Record<string, unknown> {
  const raw = isRecord(value) ? value : {}
  return { instructions: stringSetting(raw.instructions) }
}

function normalizeLoadContext(value: unknown): Record<string, unknown> {
  const raw = isRecord(value) ? value : {}
  const addition = Array.isArray(raw.addition)
    ? raw.addition.filter(item => isRecord(item) && typeof item.name === 'string').map(item => ({
      name: item.name.trim(),
      priority: normalizeContextPriority(item.priority),
      kind: String(item.kind || 'system'),
    }))
    : []
  const except = Array.isArray(raw.except)
    ? raw.except.filter((item): item is string => typeof item === 'string').map(item => item.trim()).filter(Boolean)
    : []
  return { addition, except }
}

function validateLoadContext(value: Record<string, unknown>): { addition: Array<Record<string, unknown>>; except: string[] } {
  if (!Array.isArray(value.addition) || !Array.isArray(value.except)) {
    throw new Error('addition (list) and except (list) are required')
  }
  const addition = value.addition.map(item => {
    if (!isRecord(item) || typeof item.name !== 'string') {
      throw new Error('addition items must be objects with a string name')
    }
    return {
      name: item.name.trim(),
      priority: parseContextPriority(item.priority),
      kind: String(item.kind || 'system'),
    }
  })
  const except = value.except
    .filter((item): item is string => typeof item === 'string')
    .map(item => item.trim())
    .filter(Boolean)
  return { addition, except }
}

function normalizeModelRetryConfig(value: unknown): Record<string, unknown> {
  const raw = isRecord(value) ? value : {}
  const normalized = cloneState(DEFAULT_MODEL_RETRY_CONFIG)
  if (Array.isArray(raw.retry_delays_seconds)) {
    const delays = raw.retry_delays_seconds.filter(isPolicyDelay)
    if (delays.length) normalized.retry_delays_seconds = delays
  }
  if (isPositiveInteger(raw.model_retries)) normalized.model_retries = raw.model_retries
  if (isPolicySeconds(raw.model_timeout_seconds)) normalized.model_timeout_seconds = raw.model_timeout_seconds
  if (hasOwn(raw, 'model_stream_idle_timeout_seconds')) {
    if (raw.model_stream_idle_timeout_seconds === null) normalized.model_stream_idle_timeout_seconds = null
    else if (isPolicySeconds(raw.model_stream_idle_timeout_seconds)) {
      normalized.model_stream_idle_timeout_seconds = raw.model_stream_idle_timeout_seconds
    }
  }
  if (isNonNegativeInteger(raw.empty_response_retries)) normalized.empty_response_retries = raw.empty_response_retries
  if (typeof raw.jitter === 'boolean') normalized.jitter = raw.jitter
  return normalized
}

function validateModelRetryUpdate(
  current: Record<string, unknown>,
  patch: Record<string, unknown>,
): Record<string, unknown> {
  const supported = new Set(Object.keys(DEFAULT_MODEL_RETRY_CONFIG))
  for (const [key, value] of Object.entries(patch)) {
    if (!supported.has(key)) throw new Error(`unsupported model retry setting: ${key}`)
    if (key === 'retry_delays_seconds') {
      if (!Array.isArray(value) || !value.every(isPolicyDelay)) {
        throw new Error('retry_delays_seconds must be an array of finite numbers from 0 to less than 1e12')
      }
    } else if (key === 'model_retries') {
      if (!isPositiveInteger(value)) throw new Error('model_retries must be a positive integer')
    } else if (key === 'model_timeout_seconds') {
      if (!isPolicySeconds(value)) throw new Error('model_timeout_seconds must be greater than 0 and less than 1e12')
    } else if (key === 'model_stream_idle_timeout_seconds') {
      if (value !== null && !isPolicySeconds(value)) {
        throw new Error('model_stream_idle_timeout_seconds must be null or greater than 0 and less than 1e12')
      }
    } else if (key === 'empty_response_retries') {
      if (!isNonNegativeInteger(value)) throw new Error('empty_response_retries must be a non-negative integer')
    } else if (key === 'jitter' && typeof value !== 'boolean') {
      throw new Error('jitter must be a boolean')
    }
  }
  const merged = { ...normalizeModelRetryConfig(current), ...cloneState(patch) }
  if (Array.isArray(merged.retry_delays_seconds) && merged.retry_delays_seconds.length === 0) {
    merged.retry_delays_seconds = [1, 1, 2, 5, 5]
  }
  return normalizeModelRetryConfig(merged)
}

function isPolicyDelay(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value < 1e12
}

function isPolicySeconds(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 && value < 1e12
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function parseContextPriority(value: unknown): number {
  if (value == null || value === '' || value === false || value === 0) return 50
  if (typeof value === 'number' && Number.isFinite(value)) return Math.trunc(value)
  if (typeof value === 'string' && /^[+-]?\d+$/u.test(value.trim())) return Number.parseInt(value, 10)
  throw new Error('priority must be an integer')
}

function normalizeContextPriority(value: unknown): number {
  try { return parseContextPriority(value) }
  catch { return 50 }
}

function stringSetting(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function hasOwn(value: object, key: PropertyKey): boolean {
  return Object.prototype.hasOwnProperty.call(value, key)
}

function normalizeStoredModelGroups(value: unknown): StandaloneModelGroupsState {
  if (!isRecord(value) || !Array.isArray(value.groups) || !Array.isArray(value.memberships)) {
    return { version: 1, revision: 0, groups: [], memberships: [] }
  }
  const groups: StandaloneModelGroup[] = []
  const ids = new Set<string>()
  const names = new Set<string>()
  for (const [index, raw] of value.groups.entries()) {
    if (!isRecord(raw) || typeof raw.id !== 'string' || typeof raw.name !== 'string') continue
    let id: string
    try { id = validateConfigId('model group', raw.id) }
    catch { continue }
    const name = raw.name.trim()
    if (!name || name.length > 100 || ids.has(id) || names.has(name.toLowerCase())) continue
    ids.add(id)
    names.add(name.toLowerCase())
    groups.push({ id, name, order: nonNegativeOrder(raw.order, index) })
  }
  const memberships: StandaloneModelGroupMembership[] = []
  const membershipKeys = new Set<string>()
  for (const [index, raw] of value.memberships.entries()) {
    if (!isRecord(raw) || typeof raw.group_id !== 'string' || typeof raw.model_id !== 'string') continue
    if (!ids.has(raw.group_id) || !raw.model_id.trim()) continue
    const key = `${raw.group_id}\u0000${raw.model_id}`
    if (membershipKeys.has(key)) continue
    membershipKeys.add(key)
    memberships.push({ group_id: raw.group_id, model_id: raw.model_id, order: nonNegativeOrder(raw.order, index) })
  }
  const revision = typeof value.revision === 'number' && Number.isSafeInteger(value.revision) && value.revision >= 0
    ? value.revision
    : 0
  const state: StandaloneModelGroupsState = { version: 1, revision, groups, memberships }
  normalizeModelGroupOrders(state)
  return state
}

function nonNegativeOrder(value: unknown, fallback: number): number {
  if (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0) return value
  return fallback
}

function normalizeModelGroupOrders(state: StandaloneModelGroupsState): void {
  state.groups.sort((left, right) => left.order - right.order || left.id.localeCompare(right.id))
  state.groups.forEach((group, order) => { group.order = order })
  state.memberships.sort((left, right) => left.group_id.localeCompare(right.group_id)
    || left.order - right.order || left.model_id.localeCompare(right.model_id))
  const nextOrder = new Map<string, number>()
  for (const membership of state.memberships) {
    const order = nextOrder.get(membership.group_id) || 0
    membership.order = order
    nextOrder.set(membership.group_id, order + 1)
  }
}

function commitGroupMutation(state: StandaloneModelGroupsState): void {
  state.revision += 1
  normalizeModelGroupOrders(state)
}

function validateConfigId(kind: string, value: unknown): string {
  const id = String(value || '').trim()
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u.test(id)) {
    throw new Error(`invalid ${kind} id '${id}': only letters, digits, '.', '_', '-' are allowed (no path separators, '..' or leading dots)`)
  }
  return id
}

function validateModelGroupName(value: unknown): string {
  const name = String(value || '').trim()
  if (!name) throw new Error('model group name is required')
  if (name.length > 100) throw new Error('model group name must be at most 100 characters')
  return name
}

function ensureUniqueGroupName(state: StandaloneModelGroupsState, name: string, exceptId = ''): void {
  if (state.groups.some(group => group.id !== exceptId && group.name.toLowerCase() === name.toLowerCase())) {
    throw new Error(`model group name already exists: ${name}`)
  }
}

function findModelGroup(state: StandaloneModelGroupsState, rawId: unknown): StandaloneModelGroup {
  const id = validateConfigId('model group', rawId)
  const group = state.groups.find(item => item.id === id)
  if (!group) throw new Error(`model group not found: ${id}`)
  return group
}

function checkGroupRevision(state: StandaloneModelGroupsState, value: unknown): void {
  if (value == null || value === '') return
  const revision = typeof value === 'number'
    ? Math.trunc(value)
    : /^[+-]?\d+$/u.test(String(value).trim())
      ? Number.parseInt(String(value), 10)
      : Number.NaN
  if (!Number.isSafeInteger(revision)) throw new Error('expected_revision must be an integer')
  if (revision !== state.revision) {
    throw new Error(`model group revision conflict: expected ${revision}, current ${state.revision}`)
  }
}

function normalizeProviderBaseUrl(value: unknown): string {
  const raw = String(value || '').trim()
  let url: URL
  try { url = new URL(raw) }
  catch { throw new Error('provider.base_url must be an absolute HTTP(S) URL') }
  if (!['http:', 'https:'].includes(url.protocol) || !url.host) throw new Error('provider.base_url must be an absolute HTTP(S) URL')
  if (url.username || url.password) throw new Error('provider.base_url must not contain credentials')
  if (url.search || url.hash) throw new Error('provider.base_url must not contain a query or fragment')
  if (raw.length > 2048) throw new Error('provider.base_url is too long')
  const path = url.pathname.replace(/\/+$/u, '')
  if (path.toLowerCase().endsWith('/chat/completions')) {
    throw new Error('provider.base_url must be an API base URL, not a /chat/completions endpoint')
  }
  return `${url.protocol.toLowerCase()}//${url.host}${path}`
}

function providerResponse(provider: StandaloneProvider, apiKey: string): Record<string, unknown> {
  return {
    id: provider.id,
    name: provider.name,
    api_type: provider.api_type,
    base_url: provider.base_url,
    api_key: apiKey || provider.has_api_key ? '********' : '',
    has_api_key: provider.has_api_key || Boolean(apiKey),
    is_default: false,
    extra: isRecord(provider.extra) ? cloneState(provider.extra) : {},
  }
}

async function modelResponse(
  model: StandaloneModel,
  provider?: StandaloneProvider | null,
): Promise<Record<string, unknown>> {
  const projected = await modelWithReasoningDeclaration(model, provider)
  const extra = isRecord(projected.extra) ? cloneState(projected.extra) : {}
  return {
    id: projected.id,
    model_record_id: projected.id,
    provider_id: projected.provider_id,
    model_id: projected.model_id,
    display_name: projected.display_name,
    context_window: projected.context_window || 0,
    max_output_tokens: projected.max_output_tokens || 4096,
    thinking_supported: projected.thinking_supported || false,
    thinking_budget: projected.thinking_budget || 10000,
    temperature: projected.temperature ?? 0.2,
    reasoning_off_supported: projected.reasoning_off_supported === true,
    reasoning_levels: projected.reasoning_levels || [],
    capability: String(extra.capability || ''),
    notes: projected.notes || '',
    extra,
  }
}

/**
 * A model as the shared Composer consumes it: the record plus the reasoning
 * ladder that governs its requests, in the desktop's field names.
 *
 * A phone has no adapter-profile directory — `llm_adapters` is compiled into the
 * runtime — so the ladder is resolved by the host from the very profile the next
 * request will use. That is what gives a model added from a preset (which
 * carries only an `adapter_profile_id`) its own grades, and it keeps a model
 * that declares its own ladder (or whose provider does) ahead of the matched
 * profile, because the host applies the same precedence the request does.
 *
 * A host that cannot answer — no embedded runtime, or a build that does not
 * register the command — leaves the ladder empty, and the Composer shows the
 * product ladder exactly as it did before this existed. Nothing here may fail a
 * model catalog.
 */
async function modelWithReasoningDeclaration(
  model: StandaloneModel,
  provider?: StandaloneProvider | null,
): Promise<StandaloneModel> {
  const offSupported = booleanOrUndefined(model.reasoning_off_supported)
  if (Array.isArray(model.reasoning_levels)) {
    return { ...model, reasoning_off_supported: offSupported ?? true }
  }
  const declaration = provider
    ? await readEmbeddedModelReasoningDeclaration({ provider, model })
    : null
  return {
    ...model,
    reasoning_off_supported: offSupported ?? declaration?.off_supported ?? true,
    reasoning_levels: declaration?.levels ?? [],
  }
}

const LOAD_TOOLS_NAMESPACE = 'core.loadTools'

/**
 * The desktop's built-in modes, verbatim — same names, same descriptions, so a
 * mode means the same thing on both hosts. Names this host does not implement
 * are removed by `loadTools` against the catalog.
 */
function builtinLoadToolModes(): LoadToolModes {
  return {
    consider: {
      description: 'Consider mode: use read-only tools for analysis and research; do not modify files',
      tools: [
        'read_file', 'list_dir', 'search_files', 'search_content',
        'web_search', 'web_fetch', 'git_status', 'git_diff',
        'load_skill', 'message',
      ],
    },
    execute: {
      description: 'Execute mode: use all tools for complete code operations',
      tools: [],
    },
  }
}

/**
 * Accept only well-formed modes. A malformed entry is a hard error when the
 * caller is saving (`requireNonEmpty`) and is dropped when reading stored state,
 * so one bad record cannot take the whole panel down.
 */
function normalizeLoadToolModes(
  raw: Record<string, unknown>,
  options: { requireNonEmpty?: boolean } = {},
): LoadToolModes {
  const modes: LoadToolModes = {}
  for (const [rawName, entry] of Object.entries(raw)) {
    const name = rawName.trim()
    if (!name) continue
    if (!isRecord(entry)) {
      if (options.requireNonEmpty) throw new Error(`模式 ${name} 必须是对象`)
      continue
    }
    const tools = entry.tools
    if (!Array.isArray(tools)) {
      if (options.requireNonEmpty) throw new Error(`模式 ${name} 的 tools 必须是数组`)
      continue
    }
    modes[name] = {
      description: String(entry.description || '').trim(),
      tools: uniqueStrings(tools.filter((tool): tool is string => typeof tool === 'string' && tool.trim().length > 0)),
    }
  }
  return modes
}

/** Keep only tool names the host can run; a full-access mode stays empty. */
function restrictModesToCatalog(modes: LoadToolModes, known: Set<string>): LoadToolModes {
  const restricted: LoadToolModes = {}
  for (const [name, mode] of Object.entries(modes)) {
    restricted[name] = {
      description: mode.description,
      tools: mode.tools.filter(tool => known.has(tool)),
    }
  }
  return restricted
}

/**
 * Strip `//` and `/* *\/` comments so a JSONC document can be parsed.
 *
 * String-aware: a `//` inside a quoted value (a URL) must survive, which is the
 * rule the desktop's stripper follows too.
 */
function stripJsoncComments(content: string): string {
  let result = ''
  let inString = false
  let inLineComment = false
  let inBlockComment = false
  for (let index = 0; index < content.length; index += 1) {
    const character = content[index]
    const next = content[index + 1]
    if (inLineComment) {
      if (character === '\n') { inLineComment = false; result += character }
      continue
    }
    if (inBlockComment) {
      if (character === '*' && next === '/') { inBlockComment = false; index += 1 }
      continue
    }
    if (inString) {
      result += character
      if (character === '\\') { result += next ?? ''; index += 1; continue }
      if (character === '"') inString = false
      continue
    }
    if (character === '"') { inString = true; result += character; continue }
    if (character === '/' && next === '/') { inLineComment = true; index += 1; continue }
    if (character === '/' && next === '*') { inBlockComment = true; index += 1; continue }
    result += character
  }
  return result
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values)]
}

function randomHex(): string {
  return `${Date.now().toString(16)}${Math.random().toString(16).slice(2, 18)}`
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
