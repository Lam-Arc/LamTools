import { describe, expect, it, vi } from 'vitest'
import { StandaloneExtensionsStore } from '../src/standalone/StandaloneExtensionsStore'
import { MemoryStandaloneStateStorage } from '../src/standalone/StandaloneStateStorage'
import type { EmbeddedPluginCatalogEntry } from '../src/native/rustAgent'

/** One catalogue entry as the host reports it, straight from a manifest. */
function catalogEntry(overrides: Partial<EmbeddedPluginCatalogEntry> & { name: string }): EmbeddedPluginCatalogEntry {
  return {
    version: '1.0.0',
    description: `${overrides.name} 说明`,
    platforms: 'universal',
    skills: [],
    skill_names: [],
    modes: [],
    dependencies: [],
    tools: [],
    declared_tool_count: 0,
    tools_note: '',
    ...overrides,
  }
}

/** The three universal plugins, as the class filter leaves them on a phone. */
const phoneCatalog = [
  catalogEntry({
    name: 'imagegen',
    description: '生图工具（内置插件）',
    tools: [{ name: 'generate_image', permission: 'ask_user' }],
    declared_tool_count: 1,
  }),
  catalogEntry({
    name: 'study',
    skills: ['bundled://study/skills', 'bundled://study/future'],
    skill_names: ['teach', 'curate-notes'],
    modes: [{ id: 'study', title: 'Study', icon: 'book-open', tools: ['notes'], capabilities: ['notes'] }],
    tools: [{ name: 'get_knowledge_net', permission: 'auto_allow' }],
    declared_tool_count: 1,
  }),
  catalogEntry({
    name: 'websearch',
    tools: [{ name: 'web_search', permission: 'auto_allow' }],
    declared_tool_count: 1,
  }),
]

describe('standalone bundled extensions', () => {
  it('lists the skills the runtime offers and the plugins this host ships', async () => {
    const catalog = vi.fn(async () => [
      { name: 'teach', description: 'Teach a learning topic', location: 'bundled://study/skills/teach/SKILL.md' },
      { name: 'curate-notes', description: 'Organize study notes', location: 'bundled://study/future/curate-notes/SKILL.md' },
    ])
    // Core skills come from the runtime, which drops the desktop-only ones; the
    // panel must show that answer rather than a list of its own.
    const core = vi.fn(async () => [
      { name: 'example-core', description: 'Offered by this host', location: 'bundled://core/example-core/SKILL.md' },
    ])
    const plugins = vi.fn(async () => phoneCatalog)
    const store = new StandaloneExtensionsStore(undefined, catalog, plugins, undefined, core)
    const pluginResult = (await store.handleRpc('plugin.list', {}))!
    expect((pluginResult.plugins as Array<{ name: string; builtin: boolean }>).map(item => item.name))
      .toEqual(['imagegen', 'study', 'websearch'])
    expect((pluginResult.plugins as Array<{ name: string; builtin: boolean }>).every(item => item.builtin)).toBe(true)
    expect(plugins).toHaveBeenCalledOnce()

    const skillResult = (await store.handleRpc('skill.list', {}))!
    expect((skillResult.skills as Array<{ name: string }>).map(item => item.name)).toContain('teach')
    expect(skillResult.total_count).toBe(3)
    expect(catalog).toHaveBeenCalledOnce()
    expect(core).toHaveBeenCalledOnce()
    expect(skillResult.skills).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: 'curate-notes', description: 'Organize study notes', location: 'bundled://study/future/curate-notes/SKILL.md' }),
      expect.objectContaining({ name: 'example-core', source: 'core', deletable: false, enabled: true }),
    ]))
    await store.handleRpc('skill.disable', { name: 'teach' })
    await store.handleRpc('plugin.disable', { name: 'study' })
    // The plugin switch has to reach the runtime, not just the panel.
    expect(await store.runtimeSkills()).toEqual({
      studyEnabled: false,
      disabledSkillNames: ['teach'],
      disabledPluginNames: ['study'],
    })
    expect((await store.handleRpc('skill.list', {}))!.skills).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: 'teach', enabled: false }),
      expect.objectContaining({ name: 'curate-notes', enabled: false }),
    ]))
  })

  it('reports what the host declares and what it can actually run', async () => {
    const plugins = vi.fn(async () => [
      catalogEntry({
        name: 'study',
        version: '1.0.0',
        description: '全局学习空间与文本批注',
        skills: ['bundled://study/skills', 'bundled://study/future'],
        skill_names: ['answer', 'build-map', 'take-exam', 'teach', 'curate-notes'],
        tools: [{ name: 'get_knowledge_net', permission: 'auto_allow' }],
        declared_tool_count: 5,
      }),
      catalogEntry({
        name: 'imagegen',
        version: '0.1.0',
        tools: [{ name: 'generate_image', permission: 'ask_user' }],
        declared_tool_count: 1,
        tools_note: '需在设置 → 生图中启用并填写 API 地址，模型才会看到该工具',
      }),
    ])
    const store = new StandaloneExtensionsStore(undefined, vi.fn(async () => []), plugins)
    const listed = (await store.handleRpc('plugin.list', {}))!.plugins as Array<Record<string, unknown>>

    const study = listed.find(plugin => plugin.name === 'study')!
    // The class, version and declared assets come from the manifest, so the panel
    // and the plugin the desktop loads cannot describe different things.
    expect(study.platforms).toBe('universal')
    expect(study.version).toBe('1.0.0')
    expect(study.description).toBe('全局学习空间与文本批注')
    expect(study.skills).toEqual(['bundled://study/skills', 'bundled://study/future'])
    expect(study.skill_names).toEqual(['answer', 'build-map', 'take-exam', 'teach', 'curate-notes'])
    expect(study.tools).toEqual([
      expect.objectContaining({
        path: 'bundled://study/tools.jsonc',
        tools: [expect.objectContaining({ name: 'get_knowledge_net', permission: 'auto_allow', handler: 'rust://study' })],
      }),
    ])
    expect(study.tools_note).toBe('')

    // A plugin the host cannot run says why instead of reporting zero tools.
    const imagegen = listed.find(plugin => plugin.name === 'imagegen')!
    expect(String(imagegen.tools_note)).toContain('生图')
    // This host installs no Python dependencies and has no dependency manager, so
    // a plugin that declares none is the only one that can claim "none".
    expect(study.deps_status).toBe('none')
    expect(plugins).toHaveBeenCalledOnce()
  })

  it('reports an unreadable plugin catalogue instead of an empty panel', async () => {
    const store = new StandaloneExtensionsStore(
      undefined,
      vi.fn(async () => []),
      vi.fn(async () => { throw new Error('no native host') }),
    )
    // "No plugins" and "the host did not answer" are different statements.
    await expect(store.handleRpc('plugin.list', {})).rejects.toThrow('no native host')
  })

  it('offers the modes the manifests declare, and only those', async () => {
    const storage = new MemoryStandaloneStateStorage({ disabledPlugins: [], disabledSkills: [] })
    const plugins = vi.fn(async () => phoneCatalog)
    const store = new StandaloneExtensionsStore(storage, vi.fn(async () => []), plugins)
    const modes = (await store.handleRpc('plugin.ui.list', {}))!.modes as Array<Record<string, unknown>>
    expect(modes).toEqual([
      expect.objectContaining({ pluginId: 'study', plugin_id: 'study', id: 'study', title: 'Study', capabilities: ['notes'] }),
    ])
    // A desktop-class plugin is not in the catalogue at all, so its mode cannot
    // be offered here even though this host keeps a workflow RPC surface.
    expect(modes.some(mode => mode.pluginId === 'workflow')).toBe(false)
    await store.handleRpc('plugin.disable', { name: 'study' })
    expect((await store.handleRpc('plugin.ui.list', {}))!.modes).toEqual([])
  })

  it('refuses a switch for a plugin this host does not offer', async () => {
    const store = new StandaloneExtensionsStore(
      undefined,
      vi.fn(async () => []),
      vi.fn(async () => phoneCatalog),
    )
    await expect(store.handleRpc('plugin.disable', { name: 'git' })).rejects.toThrow("插件 'git' 不存在")
    await expect(store.handleRpc('plugin.enable', { name: 'workflow' })).rejects.toThrow("插件 'workflow' 不存在")
  })

  it('returns the same empty default hook configuration as desktop', async () => {
    expect(await new StandaloneExtensionsStore().handleRpc('hook.list', {})).toEqual({
      hooks: [], trustable_count: 0, total_count: 0, trusted_count: 0,
    })
  })

  it('persists, reviews, trusts, and deletes hook definitions', async () => {
    const storage = new MemoryStandaloneStateStorage({ disabledPlugins: [], disabledSkills: [] })
    const store = new StandaloneExtensionsStore(storage)
    await store.handleRpc('hook.config.update', { content: JSON.stringify({
      hooks: {
        PreToolUse: [{
          matcher: 'write_text_file',
          hooks: [{ type: 'prompt', prompt: 'Review ${TOOL_NAME}' }],
        }],
      },
    }) })
    const pending = (await store.handleRpc('hook.list', {}))!
    const hook = (pending.hooks as Array<{ id: string; trusted: boolean }>)[0]
    expect(hook).toEqual(expect.objectContaining({ trusted: false }))
    expect(pending.trustable_count).toBe(1)

    await store.handleRpc('hook.trust', { hook_id: hook.id })
    expect((await store.handleRpc('hook.list', {}))!.trusted_count).toBe(1)

    await store.handleRpc('hook.delete', { hook_id: hook.id })
    expect((await store.handleRpc('hook.list', {}))!.total_count).toBe(0)
    const restored = new StandaloneExtensionsStore(storage)
    expect((await restored.handleRpc('hook.list', {}))!.total_count).toBe(0)
  })
})
