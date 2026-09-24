import {
  createStandaloneStateStorage,
  type StandaloneStateStorage,
} from './StandaloneStateStorage'
import {
  hasEmbeddedRustCore,
  createEmbeddedUserSkill,
  deleteEmbeddedUserSkill,
  listEmbeddedHooks,
  listEmbeddedPluginInventory,
  listEmbeddedStudySkills,
  listEmbeddedUserSkills,
  readEmbeddedPluginSchemas,
  type EmbeddedHookListPayload,
  type EmbeddedPluginInventory,
  type EmbeddedPluginSchema,
  type EmbeddedStudySkill,
} from '../native/rustAgent'
import { cloneState } from '../storage/cloneState'

const EXTENSION_STATE_KEY = 'lamtools.mobile.standalone.extensions.v1'

const plugins = [
  { name: 'git', version: '0.1.0', description: 'Git 工具（内置插件）' },
  { name: 'imagegen', version: '0.1.0', description: '生图工具（内置插件）' },
  { name: 'study', version: '1.0.0', description: '全局学习空间与文本批注', skills: ['answer', 'build-map', 'take-exam', 'teach', 'curate-notes'] },
  { name: 'websearch', version: '0.1.0', description: '网页搜索（内置插件）' },
  { name: 'workflow', version: '1.0.0', description: '确定性节点图工作流' },
] as const

const coreSkills = [
  ['create-plugin', '创建 LamTools 插件'],
  ['observe-events', '观察和分析运行事件'],
  ['office-charts', '创建 Office 图表'],
  ['office-documents', '创建和编辑文档'],
  ['office-email', '处理邮件内容'],
  ['office-files', '处理 Office 文件'],
  ['office-infographics', '创建信息图'],
  ['office-meetings', '整理会议内容'],
  ['office-pdf', '处理 PDF 文件'],
  ['office-renderer', '渲染 Office 文件'],
  ['office-research', '执行办公研究'],
  ['office-slides', '创建和编辑演示文稿'],
  ['office-spreadsheets', '创建和编辑电子表格'],
  ['plugin-manager', '管理 LamTools 插件'],
] as const

interface ExtensionState {
  disabledPlugins: string[]
  disabledSkills: string[]
  hookConfig: Record<string, unknown>
  trustedHookHashes: string[]
  mcpConfig: Record<string, unknown>
}

export class StandaloneExtensionsStore {
  private state: ExtensionState | null = null
  private inventory = new Map<string, EmbeddedPluginInventory>()
  private inventoryStatus: 'idle' | 'ready' | 'failed' = 'idle'
  private schemas = new Map<string, EmbeddedPluginSchema>()
  private schemasStatus: 'idle' | 'ready' | 'failed' = 'idle'

  constructor(
    private readonly storage: StandaloneStateStorage<ExtensionState> = createStandaloneStateStorage({
      database: 'lamtools-mobile-config',
      scope: 'extensions',
      legacyKey: EXTENSION_STATE_KEY,
    }),
    private readonly studySkillCatalog: () => Promise<EmbeddedStudySkill[]> = listEmbeddedStudySkills,
    private readonly pluginInventory: () => Promise<EmbeddedPluginInventory[]> = listEmbeddedPluginInventory,
    private readonly pluginSchemas: () => Promise<Record<string, EmbeddedPluginSchema>> = readEmbeddedPluginSchemas,
  ) {}

  /**
   * Read the runtime's tool inventory once per store instance.
   *
   * An unreadable inventory must not become a confident "0 tools": the panel
   * says the count is unknown instead.
   */
  private async loadInventory(): Promise<void> {
    if (this.inventoryStatus !== 'idle') return
    try {
      for (const entry of await this.pluginInventory()) this.inventory.set(entry.plugin, entry)
      this.inventoryStatus = 'ready'
    } catch (error) {
      this.inventoryStatus = 'failed'
      console.error('Failed to read the plugin tool inventory', error)
    }
  }

  private inventoryNote(name: string): string {
    if (this.inventoryStatus === 'failed') return '工具清单读取失败，无法确认'
    return this.inventory.get(name)?.note || ''
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
      await Promise.all([this.loadInventory(), this.loadSchemas()])
      return {
        plugins: plugins.map(plugin => {
          // Report only what the runtime actually assembles. A hand-written
          // list used to return an empty array for every plugin, which told the
          // user nothing about whether a tool was missing or merely unlisted.
          const inventory = this.inventory.get(plugin.name)
          return {
            ...plugin,
            id: plugin.name,
            builtin: true,
            root: `bundled://${plugin.name}`,
            enabled: !state.disabledPlugins.includes(plugin.name),
            skills: 'skills' in plugin ? [`bundled://${plugin.name}/skills`, `bundled://${plugin.name}/future`] : [],
            hooks: [], mcp: [],
            tools: inventory?.assembled?.length
              ? [{
                  path: `bundled://${plugin.name}/tools.jsonc`,
                  tools: inventory.assembled.map(tool => ({
                    name: tool.name,
                    permission: tool.permission,
                    visibility: 'model',
                    skill: '',
                    handler: `rust://${plugin.name}`,
                    timeout: 0,
                  })),
                }]
              : [],
            tools_note: this.inventoryNote(plugin.name),
            operations: [], commands: [],
            skill_names: 'skills' in plugin ? [...plugin.skills] : [],
            hook_summary: [], dependencies: [], deps_status: 'none',
            // A plugin with no schema shows no configuration entry rather than
            // an empty one; the path names the file the schema came from.
            config_schema: this.schemas.get(plugin.name)?.path || '',
          }
        }),
        errors: [],
      }
    }
    if (method === 'plugin.enable' || method === 'plugin.disable') {
      const name = String(params.name || '')
      if (!plugins.some(plugin => plugin.name === name)) throw new Error(`插件 '${name}' 不存在`)
      state.disabledPlugins = method === 'plugin.disable'
        ? [...new Set([...state.disabledPlugins, name])]
        : state.disabledPlugins.filter(item => item !== name)
      await this.persist()
      return { name, enabled: method === 'plugin.enable' }
    }
    if (method === 'skill.list') {
      const studyEnabled = !state.disabledPlugins.includes('study')
      const skills = [
        ...coreSkills.map(([name, description]) => ({ name, description, location: `bundled://skills/${name}/SKILL.md`, source: 'core', deletable: false })),
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
      const enabled = (name: string) => !state.disabledPlugins.includes(name)
      return {
        modes: [
          ...(enabled('study') ? [{ id: 'study', pluginId: 'study', plugin_id: 'study', title: 'Study', icon: 'book-open', capabilities: ['notes'] }] : []),
          // Workflow is not offered as a mode here, and the reason is not a
          // missing backend — this comment used to say that and it was wrong.
          // The RPC and the Rust store exist and work: list, list_grouped,
          // create, get, document.get, document.save, compile, semantic,
          // import.comfyui, export.comfyui, run, cancel, rename, expose,
          // unexpose, object_info/node_types, activation.list, queue.enqueue/
          // list/history/get/cancel/clear, human_task.list and delete. What is
          // missing is the rest of what the mode promises the model:
          // `workflow.tools.list` has no mobile answer, `activate`/`deactivate`
          // need the Arrange scheduler, `human_task.get|complete|timeout` and
          // `signal` need the full execution backend, and `pause`/`resume` need
          // a runner that can be paused. Opening the mode would advertise tools
          // this host refuses, so the entry stays closed on purpose — see
          // core/docs/audits/mobile-desktop-parity-2026-09-24.md.
        ],
        widgets: [],
      }
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
