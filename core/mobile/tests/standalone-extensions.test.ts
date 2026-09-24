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
    expect(await store.runtimeSkills()).toEqual({ studyEnabled: false, disabledSkillNames: ['teach'] })
    expect((await store.handleRpc('skill.list', {}))!.skills).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: 'teach', enabled: false }),
      expect.objectContaining({ name: 'curate-notes', enabled: false }),
    ]))
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
