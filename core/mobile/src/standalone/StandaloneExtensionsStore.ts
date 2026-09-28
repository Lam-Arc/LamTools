import {
  createStandaloneStateStorage,
  type StandaloneStateStorage,
} from './StandaloneStateStorage'
import {
  hasEmbeddedRustCore,
  createEmbeddedUserSkill,
  deleteEmbeddedUserSkill,
  listEmbeddedCoreSkills,
  listEmbeddedHooks,
  listEmbeddedPluginCatalog,
  listEmbeddedStudySkills,
  listEmbeddedUserSkills,
  readEmbeddedPluginSchemas,
  type EmbeddedHookListPayload,
  type EmbeddedPluginCatalogEntry,
  type EmbeddedPluginSchema,
  type EmbeddedSkillRecord,
  type EmbeddedStudySkill,
} from '../native/rustAgent'
import { cloneState } from '../storage/cloneState'

const EXTENSION_STATE_KEY = 'lamtools.mobile.standalone.extensions.v1'

interface ExtensionState {
  disabledPlugins: string[]
  disabledSkills: string[]
  hookConfig: Record<string, unknown>
  trustedHookHashes: string[]
  mcpConfig: Record<string, unknown>
}

export class StandaloneExtensionsStore {
  private state: ExtensionState | null = null
  private catalog = new Map<string, EmbeddedPluginCatalogEntry>()
  private catalogStatus: 'idle' | 'ready' | 'failed' = 'idle'
  private schemas = new Map<string, EmbeddedPluginSchema>()
  private schemasStatus: 'idle' | 'ready' | 'failed' = 'idle'

  constructor(
    private readonly storage: StandaloneStateStorage<ExtensionState> = createStandaloneStateStorage({
      database: 'lamtools-mobile-config',
      scope: 'extensions',
      legacyKey: EXTENSION_STATE_KEY,
    }),
    private readonly studySkillCatalog: () => Promise<EmbeddedStudySkill[]> = listEmbeddedStudySkills,
    private readonly pluginCatalog: () => Promise<EmbeddedPluginCatalogEntry[]> = listEmbeddedPluginCatalog,
    private readonly pluginSchemas: () => Promise<Record<string, EmbeddedPluginSchema>> = readEmbeddedPluginSchemas,
    private readonly coreSkillCatalog: () => Promise<EmbeddedSkillRecord[]> = listEmbeddedCoreSkills,
  ) {}

  /**
   * Read the host's plugin catalogue once per store instance.
   *
   * An unreadable catalogue is reported instead of shown: an empty panel would
   * claim this host has no plugins, which is a different statement from "the
   * host did not answer".
   */
  private async loadCatalog(): Promise<void> {
    if (this.catalogStatus !== 'idle') return
    const entries = await this.pluginCatalog()
    for (const entry of entries) this.catalog.set(entry.name, entry)
    this.catalogStatus = 'ready'
  }

  /**
   * Read the schemas the host ships once per store instance.
   *
   * The panel offers a configuration entry only where a schema exists, so an
   * unreadable schema map must not look like "this plugin has no settings".
   */
  private async loadSchemas(): Promise<void> {
    if (this.schemasStatus !== 'idle') return
    try {
      for (const [name, entry] of Object.entries(await this.pluginSchemas())) {
        this.schemas.set(name, entry)
      }
      this.schemasStatus = 'ready'
    } catch (error) {
      this.schemasStatus = 'failed'
      console.error('Failed to read the bundled plugin schemas', error)
    }
  }

  async handleRpc(method: string, params: Record<string, unknown>): Promise<Record<string, unknown> | null> {
    const state = await this.load()
    if (method === 'plugin.list') {
      await Promise.all([this.loadCatalog(), this.loadSchemas()])
      return {
        plugins: [...this.catalog.values()].map(entry => ({
          name: entry.name,
          version: entry.version,
          description: entry.description,
          // The class this plugin declares; the panel groups by it.
          platforms: entry.platforms,
          id: entry.name,
          builtin: true,
          root: `bundled://${entry.name}`,
          enabled: !state.disabledPlugins.includes(entry.name),
          // Skill roots the manifest declares, and the skills the host has
          // embedded under them — both read from the plugin's own declaration.
          skills: [...entry.skills],
          hooks: [], mcp: [],
          // Only the tools this host actually assembles; a declared-but-missing
          // tool is a note, never a silent zero.
          tools: entry.tools.length
            ? [{
                path: `bundled://${entry.name}/tools.jsonc`,
                tools: entry.tools.map(tool => ({
                  name: tool.name,
                  permission: tool.permission,
                  visibility: 'model',
                  skill: '',
                  handler: `rust://${entry.name}`,
                  timeout: 0,
                })),
              }]
            : [],
          tools_note: entry.tools_note,
          operations: [], commands: [],
          skill_names: [...entry.skill_names],
          hook_summary: [],
          dependencies: [...entry.dependencies],
          // This host installs no Python dependencies, so a plugin that declares
          // some is reported as unknown rather than as "no dependencies".
          deps_status: entry.dependencies.length ? 'unknown' : 'none',
          // A plugin with no schema shows no configuration entry rather than
          // an empty one; the path names the file the schema came from.
          config_schema: this.schemas.get(entry.name)?.path || '',
        })),
        errors: [],
      }
    }
    if (method === 'plugin.enable' || method === 'plugin.disable') {
      const name = String(params.name || '')
      await this.loadCatalog()
      if (!this.catalog.has(name)) throw new Error(`插件 '${name}' 不存在`)
      state.disabledPlugins = method === 'plugin.disable'
        ? [...new Set([...state.disabledPlugins, name])]
        : state.disabledPlugins.filter(item => item !== name)
      await this.persist()
      return { name, enabled: method === 'plugin.enable' }
    }
    if (method === 'skill.list') {
      const studyEnabled = !state.disabledPlugins.includes('study')
      const skills = [
        // Bundled skills come from the runtime, so what the panel lists is what
        // the model can load: a skill whose instructions need the desktop is not
        // in this list because `load_skill` would refuse it.
        ...(await this.coreSkillCatalog()).map(skill => ({
          ...skill,
          source: 'core',
          deletable: false,
        })),
        ...(await this.studySkillCatalog()).map(skill => ({
          ...skill,
          source: 'plugin',
          deletable: false,
        })),
        // User skills live in the app-private skill root the runtime scans, and
        // they are the only skills this host can delete.
        ...(await listEmbeddedUserSkills()).map(skill => ({
          ...skill,
          source: 'user',
          deletable: true,
        })),
      ].map(skill => ({
        ...skill,
        enabled: !state.disabledSkills.includes(skill.name) && (skill.source !== 'plugin' || studyEnabled),
      }))
      return { skills, total_count: skills.length, enabled_count: skills.filter(skill => skill.enabled).length }
    }
    if (method === 'skill.create') {
      // A new skill starts enabled: the runtime loads everything present unless
      // it was switched off, and nothing has switched this one off.
      const created = await createEmbeddedUserSkill({
        name: String(params.name || ''),
        description: String(params.description || ''),
        content: String(params.content || ''),
      })
      return { name: created.name, location: created.location, created: true }
    }
    if (method === 'skill.delete') {
      const name = String(params.name || '')
      if (!(await listEmbeddedUserSkills()).some(skill => skill.name === name)) {
        // Bundled and plugin skills live inside the binary; the panel must not
        // be able to report them deleted.
        throw new Error(`技能 '${name}' 不可删除（只允许删除自建技能）`)
      }
      const deleted = await deleteEmbeddedUserSkill(name)
      state.disabledSkills = state.disabledSkills.filter(item => item !== name)
      await this.persist()
      return { name: deleted.name, location: deleted.location, deleted: true }
    }
    if (method === 'skill.enable' || method === 'skill.disable') {
      const name = String(params.name || '')
      state.disabledSkills = method === 'skill.disable'
        ? [...new Set([...state.disabledSkills, name])]
        : state.disabledSkills.filter(item => item !== name)
      await this.persist()
      return { name, enabled: method === 'skill.enable' }
    }
    if (method === 'hook.list') return { ...(await this.listHooks(state)) }
    if (method === 'hook.config.get') {
      return { content: JSON.stringify(state.hookConfig, null, 2), path: 'mobile://config/hooks.json' }
    }
    if (method === 'hook.config.update') {
      const content = String(params.content ?? '')
      let parsed: unknown
      try {
        parsed = JSON.parse(content)
      } catch (error) {
        throw new Error(`hooks.json 不是合法 JSON：${error instanceof Error ? error.message : String(error)}`)
      }
      if (!isRecord(parsed)) throw new Error('hooks.json 顶层必须是 JSON 对象')
      if ('hooks' in parsed && !isRecord(parsed.hooks)) throw new Error('hooks 字段必须是对象')
      state.hookConfig = parsed
      await this.persist()
      return { updated: true, path: 'mobile://config/hooks.json' }
    }
    if (method === 'hook.trust' || method === 'hook.untrust') {
      const id = String(params.hook_id || params.hookId || '')
      const listing = await this.listHooks(state)
      const hook = listing.hooks.find(item => item.id === id)
      if (!hook) throw new Error('hook_id not found')
      state.trustedHookHashes = method === 'hook.trust'
        ? [...new Set([...state.trustedHookHashes, hook.definition_hash])]
        : state.trustedHookHashes.filter(hash => hash !== hook.definition_hash)
      await this.persist()
      return { hook_id: id, trusted: method === 'hook.trust' }
    }
    if (method === 'hook.delete') {
      const id = String(params.hook_id || params.hookId || '')
      const listing = await this.listHooks(state)
      const hook = listing.hooks.find(item => item.id === id)
      if (!hook) throw new Error('hook_id not found')
      if (hook.source !== 'user' || hook.source_name !== 'config') {
        throw new Error('cannot delete plugin-managed hook')
      }
      deleteConfiguredHook(state.hookConfig, id)
      state.trustedHookHashes = state.trustedHookHashes.filter(hash => hash !== hook.definition_hash)
      await this.persist()
      return { hook_id: id, deleted: true }
    }
    if (method === 'mcp.config.get') {
      return { content: JSON.stringify(state.mcpConfig, null, 2), path: 'mobile://config/mcp.json' }
    }
    if (method === 'mcp.config.update') {
      const content = String(params.content ?? '')
      let parsed: unknown
      try {
        parsed = JSON.parse(content)
      } catch (error) {
        throw new Error(`mcp.json 不是合法 JSON：${error instanceof Error ? error.message : String(error)}`)
      }
      if (!isRecord(parsed)) throw new Error('mcp.json 顶层必须是 JSON 对象')
      state.mcpConfig = parsed
      await this.persist()
      return { updated: true, path: 'mobile://config/mcp.json' }
    }
    if (method === 'plugin.ui.list') {
      await this.loadCatalog()
      // Modes come from the same manifests the panel reads; a plugin the host
      // does not offer has no modes here either. Workflow used to be withheld by
      // hand in this method — it is absent now because its manifest declares
      // `desktop`, and the entry stays closed for the reason recorded in
      // core/docs/audits/mobile-desktop-parity-2026-09-24.md.
      const modes = [...this.catalog.values()]
        .filter(entry => !state.disabledPlugins.includes(entry.name))
        .flatMap(entry => entry.modes.map(mode => ({
          id: mode.id,
          pluginId: entry.name,
          plugin_id: entry.name,
          title: mode.title,
          icon: mode.icon,
          ...(typeof mode.capabilities === 'object' && mode.capabilities !== null
            ? { capabilities: [...mode.capabilities] }
            : {}),
        })))
      return { modes, widgets: [] }
    }
    if (method === 'plugin.widget.list') return { widgets: [] }
    return null
  }

  async runtimeHooks(): Promise<{
    hookConfig: Record<string, unknown>
    trustedHookHashes: string[]
    mcpConfig: Record<string, unknown>
  }> {
    const state = await this.load()
    return {
      hookConfig: cloneState(state.hookConfig),
      trustedHookHashes: [...state.trustedHookHashes],
      mcpConfig: cloneState(state.mcpConfig),
    }
  }

  async runtimeSkills(): Promise<{
    studyEnabled: boolean
    disabledSkillNames: string[]
    disabledPluginNames: string[]
  }> {
    const state = await this.load()
    return {
      studyEnabled: !state.disabledPlugins.includes('study'),
      disabledSkillNames: [...state.disabledSkills],
      // Plugin switches must reach the runtime, otherwise the panel offers a
      // control that changes nothing.
      disabledPluginNames: [...state.disabledPlugins],
    }
  }

  private async load(): Promise<ExtensionState> {
    if (this.state) return this.state
    const parsed = await this.storage.read()
    this.state = {
      disabledPlugins: Array.isArray(parsed?.disabledPlugins) ? parsed.disabledPlugins : [],
      disabledSkills: Array.isArray(parsed?.disabledSkills) ? parsed.disabledSkills : [],
      hookConfig: isRecord(parsed?.hookConfig) ? parsed.hookConfig : {},
      trustedHookHashes: Array.isArray(parsed?.trustedHookHashes)
        ? parsed.trustedHookHashes.filter((value): value is string => typeof value === 'string')
        : [],
      mcpConfig: isRecord(parsed?.mcpConfig) ? parsed.mcpConfig : {},
    }
    return this.state
  }

  private async persist(): Promise<void> {
    if (this.state) await this.storage.write(this.state)
  }

  private async listHooks(state: ExtensionState): Promise<EmbeddedHookListPayload> {
    if (hasEmbeddedRustCore()) {
      return await listEmbeddedHooks(state.hookConfig, state.trustedHookHashes)
    }
    return await fallbackHookList(state.hookConfig, state.trustedHookHashes)
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function deleteConfiguredHook(config: Record<string, unknown>, id: string): void {
  const parts = id.split(':')
  if (parts.length < 6) throw new Error('invalid hook id format')
  const event = parts[2]
  const groupIndex = Number(parts[3])
  const handlerIndex = Number(parts[4])
  const hooks = isRecord(config.hooks) ? config.hooks : null
  const groups = hooks && Array.isArray(hooks[event]) ? hooks[event] as unknown[] : null
  const group = groups?.[groupIndex]
  if (!groups || !isRecord(group) || !Array.isArray(group.hooks)) throw new Error('hook group not found')
  if (!Number.isInteger(handlerIndex) || handlerIndex < 0 || handlerIndex >= group.hooks.length) {
    throw new Error('hook handler not found')
  }
  group.hooks.splice(handlerIndex, 1)
  if (!group.hooks.length) groups.splice(groupIndex, 1)
  if (!groups.length && hooks) delete hooks[event]
  if (hooks && !Object.keys(hooks).length) delete config.hooks
}

async function fallbackHookList(
  config: Record<string, unknown>,
  trustedHashes: string[],
): Promise<EmbeddedHookListPayload> {
  const items: EmbeddedHookListPayload['hooks'] = []
  const hooks = isRecord(config.hooks) ? config.hooks : {}
  for (const [event, rawGroups] of Object.entries(hooks)) {
    if (!Array.isArray(rawGroups)) continue
    for (let groupIndex = 0; groupIndex < rawGroups.length; groupIndex++) {
      const group = rawGroups[groupIndex]
      if (!isRecord(group) || !Array.isArray(group.hooks)) continue
      const matcher = typeof group.matcher === 'string' && group.matcher ? group.matcher : '*'
      for (let handlerIndex = 0; handlerIndex < group.hooks.length; handlerIndex++) {
        const handler = group.hooks[handlerIndex]
        if (!isRecord(handler)) continue
        const handlerType = typeof handler.type === 'string' ? handler.type : 'command'
        if (!['command', 'http', 'mcp', 'prompt'].includes(handlerType)) continue
        const hash = await stableHash({
          config_path: 'mobile://config/hooks.json',
          event,
          handler,
          matcher,
          plugin_name: '',
          source: 'user',
          source_name: 'config',
        })
        const trusted = trustedHashes.includes(hash)
        items.push({
          id: `user:config:${event}:${groupIndex}:${handlerIndex}:${hash.slice(0, 12)}`,
          event,
          matcher,
          source: 'user',
          source_name: 'config',
          plugin_name: '',
          config_path: 'mobile://config/hooks.json',
          handler_type: handlerType,
          command: typeof handler.command === 'string' ? handler.command : '',
          definition_hash: hash,
          trusted,
          status: trusted ? 'trusted' : 'pending_review',
        })
      }
    }
  }
  return {
    hooks: items,
    total_count: items.length,
    trusted_count: items.filter(item => item.trusted).length,
    trustable_count: items.filter(item => !item.trusted).length,
  }
}

async function stableHash(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(pythonStyleJson(value))
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes)
  return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('')
}

function pythonStyleJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(pythonStyleJson).join(', ')}]`
  if (isRecord(value)) {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}: ${pythonStyleJson(value[key])}`).join(', ')}}`
  }
  return JSON.stringify(value) ?? 'null'
}
