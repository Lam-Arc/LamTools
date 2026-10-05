import { describe, expect, it } from 'vitest'
import { reactive } from 'vue'
import { cloneState } from '../src/storage'
import { MemorySecureStorage } from '../src/native/secureStorage'
import { StandaloneConfigStore } from '../src/standalone/StandaloneConfigStore'
import { MemoryStandaloneStateStorage } from '../src/standalone/StandaloneStateStorage'
import { StandaloneExtensionsStore } from '../src/standalone/StandaloneExtensionsStore'

describe('cloneState', () => {
  it('clones JSON state and detaches nested references', () => {
    const source = { nested: { value: 1 }, list: [1, 2] }
    const copy = cloneState(source)
    expect(copy).toEqual(source)
    expect(copy).not.toBe(source)
    expect(copy.nested).not.toBe(source.nested)
  })

  it('accepts a reactive proxy that structuredClone rejects', () => {
    // Settings panels hand reactive objects back to the stores, so this is the
    // shape that used to surface as
    // "Failed to execute 'structuredClone' on 'Window': #<Object> could not be cloned."
    const proxy = reactive({ nested: { value: 1 }, list: [1, 2] })
    expect(() => structuredClone(proxy)).toThrow()
    expect(cloneState(proxy)).toEqual({ nested: { value: 1 }, list: [1, 2] })
  })
})

describe('standalone stores keep reactive writes out of persisted state', () => {
  it('reads settings back after a reactive value was written', async () => {
    const store = new StandaloneConfigStore(new MemorySecureStorage())
    await store.handleRpc('settings.update', {
      namespace: 'core.imagegen',
      value: reactive({ enabled: true, min_turns: 5 }),
    })

    // Reading used to clone stored state, so a leaked proxy broke the read.
    await expect(store.settings('core.imagegen')).resolves.toEqual({ enabled: true, min_turns: 5 })
    // A reactive value must not become the stored object either.
    await expect(store.handleRpc('settings.get', { namespace: 'core.imagegen' }))
      .resolves.toEqual({ namespace: 'core.imagegen', value: { enabled: true, min_turns: 5 } })
  })

  it('reads Sub Agent settings back after a reactive role assignment was written', async () => {
    const store = new StandaloneConfigStore(new MemorySecureStorage())
    await store.handleRpc('config.subagent.settings.set', {
      scope: 'global',
      settings: reactive({
        delegation_strategy: 'high',
        role_assignments: [{ role: 'researcher', model_id: 'model-a' }],
      }),
    })

    const runtime = await store.subAgentRuntime('project-1')
    expect(runtime).toEqual(expect.objectContaining({ enabled: true }))
    await expect(store.settings('core.subagent.settings.global')).resolves.toEqual(
      expect.objectContaining({
        delegation_strategy: 'high',
        role_assignments: [{ role: 'researcher', model_id: 'model-a' }],
      }),
    )
  })

  it('reads hook and MCP config back without a clone failure', async () => {
    const store = new StandaloneExtensionsStore(new MemoryStandaloneStateStorage())
    const runtime = await store.runtimeHooks()
    expect(runtime.hookConfig).toEqual(expect.any(Object))
    expect(runtime.mcpConfig).toEqual(expect.any(Object))
  })
})
