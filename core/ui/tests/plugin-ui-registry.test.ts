import { describe, expect, it } from 'vitest'
import { PluginUIRegistry } from '../src/plugins/registry'

describe('PluginUIRegistry', () => {
  it('registers and resolves plugin modes', () => {
    const registry = new PluginUIRegistry()
    const component = { name: 'WorkflowView' }
    registry.registerMode(
      { pluginId: 'workflow', id: 'workflow', title: 'Workflow', entry: './ui/index.ts' },
      async () => component,
    )

    expect(registry.getMode('workflow', 'workflow')?.title).toBe('Workflow')
    expect(registry.getMode('workflow')?.pluginId).toBe('workflow')
    expect(registry.listModes()).toHaveLength(1)
  })

  it('requires an unambiguous id without a plugin id', () => {
    const registry = new PluginUIRegistry()
    const loader = async () => ({ name: 'Mode' })
    registry.registerMode({ pluginId: 'alpha', id: 'main', title: 'A', entry: 'a' }, loader)
    registry.registerMode({ pluginId: 'beta', id: 'main', title: 'B', entry: 'b' }, loader)

    expect(registry.getMode('main')).toBeUndefined()
    expect(registry.getMode('main', 'beta')?.title).toBe('B')
  })

  it('removes every contribution from a disabled plugin', () => {
    const registry = new PluginUIRegistry()
    const loader = async () => ({ name: 'Mode' })
    registry.registerMode({ pluginId: 'workflow', id: 'main', title: 'Main', entry: 'main' }, loader)
    registry.registerMode({ pluginId: 'workflow', id: 'inspector', title: 'Inspector', entry: 'inspector' }, loader)
    registry.registerMode({ pluginId: 'other', id: 'main', title: 'Other', entry: 'other' }, loader)

    registry.unregisterPlugin('workflow')

    expect(registry.listModes().map((mode) => mode.pluginId)).toEqual(['other'])
  })
})
