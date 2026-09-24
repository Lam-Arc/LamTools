import { describe, expect, it, vi } from 'vitest'
import { StandaloneExtensionsStore } from '../src/standalone/StandaloneExtensionsStore'
import { MemoryStandaloneStateStorage } from '../src/standalone/StandaloneStateStorage'

describe('standalone bundled extensions', () => {
  it('uses the native bundled Study catalog with canonical descriptions and resource paths', async () => {
    const catalog = vi.fn(async () => [
      { name: 'teach', description: 'Teach a learning topic', location: 'bundled://study/skills/teach/SKILL.md' },
      { name: 'curate-notes', description: 'Organize study notes', location: 'bundled://study/future/curate-notes/SKILL.md' },
    ])
    const store = new StandaloneExtensionsStore(undefined, catalog)
    const pluginResult = (await store.handleRpc('plugin.list', {}))!
    expect((pluginResult.plugins as Array<{ name: string; builtin: boolean }>).map(item => item.name))
      .toEqual(['git', 'imagegen', 'study', 'websearch', 'workflow'])
    expect((pluginResult.plugins as Array<{ name: string; builtin: boolean }>).every(item => item.builtin)).toBe(true)

    const skillResult = (await store.handleRpc('skill.list', {}))!
    expect((skillResult.skills as Array<{ name: string }>).map(item => item.name)).toContain('teach')
    expect(skillResult.total_count).toBeGreaterThan(5)
    expect(catalog).toHaveBeenCalledOnce()
    expect(skillResult.skills).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: 'curate-notes', description: 'Organize study notes', location: 'bundled://study/future/curate-notes/SKILL.md' }),
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

  it('reports only the tools the runtime assembles and explains the rest', async () => {
    const inventory = vi.fn(async () => [
      { plugin: 'study', assembled: [{ name: 'get_knowledge_net', permission: 'auto_allow' }], declared_count: 5, note: '' },
      { plugin: 'git', assembled: [], declared_count: 2, note: '移动端未装配：Android 没有 git 可执行文件，且项目目录不是仓库' },
    ])
    const store = new StandaloneExtensionsStore(undefined, vi.fn(async () => []), inventory)
    const plugins = (await store.handleRpc('plugin.list', {}))!.plugins as Array<Record<string, unknown>>

    const study = plugins.find(plugin => plugin.name === 'study')!
    expect(study.tools).toEqual([
      expect.objectContaining({
        path: 'bundled://study/tools.jsonc',
        tools: [expect.objectContaining({ name: 'get_knowledge_net', permission: 'auto_allow' })],
      }),
    ])
    expect(study.tools_note).toBe('')

    const git = plugins.find(plugin => plugin.name === 'git')!
    // A plugin whose tools are missing must not imply it has none by accident.
    expect(git.tools).toEqual([])
    expect(String(git.tools_note)).toContain('Android 没有 git')
    expect(inventory).toHaveBeenCalledOnce()
  })

  it('does not claim zero tools when the tool inventory cannot be read', async () => {
    const store = new StandaloneExtensionsStore(
      undefined,
      vi.fn(async () => []),
      vi.fn(async () => { throw new Error('no native host') }),
    )
    const plugins = (await store.handleRpc('plugin.list', {}))!.plugins as Array<Record<string, unknown>>
    expect(plugins.every(plugin => plugin.tools_note === '工具清单读取失败，无法确认')).toBe(true)
  })

  it('registers Study and persists extension switches', async () => {
    const storage = new MemoryStandaloneStateStorage({ disabledPlugins: [], disabledSkills: [] })
    const store = new StandaloneExtensionsStore(storage)
    const modes = (await store.handleRpc('plugin.ui.list', {}))!.modes as Array<Record<string, unknown>>
    expect(modes).toEqual(expect.arrayContaining([
      expect.objectContaining({ pluginId: 'study', id: 'study' }),
    ]))
    const studyMode = modes.find(mode => mode.pluginId === 'study')!
    expect(studyMode.capabilities).toEqual(['notes'])
    expect(modes.some(mode => mode.pluginId === 'workflow')).toBe(false)
    await store.handleRpc('plugin.disable', { name: 'study' })
    const restored = new StandaloneExtensionsStore(storage)
    expect((await restored.handleRpc('plugin.ui.list', {}))!.modes).not.toEqual(expect.arrayContaining([
      expect.objectContaining({ pluginId: 'study' }),
    ]))
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
