import { afterEach, describe, expect, it, vi } from 'vitest'

import { refreshPluginUIModes } from '../src/plugins/api'
import { getMode, pluginUIRegistry } from '../src/plugins/registry'

afterEach(() => pluginUIRegistry.clear())

// user:“测试，提交打包发布”+(测试通道使用与实际插件 RPC 一致的对象响应契约)。
function makeRpc(legacy: Record<string, unknown> | Error, system: Record<string, unknown> | Error) {
  return vi.fn(async (method: string) => {
    if (method === 'plugin.ui.list') {
      if (legacy instanceof Error) throw legacy
      return legacy
    }
    if (method === 'plugin.system.ui') {
      if (system instanceof Error) throw system
      return system
    }
    return {}
  })
}

describe('plugin mode sources', () => {
  it('registers a v2 mode declared through plugin.system.ui', async () => {
    const rpc = makeRpc(
      { modes: [] },
      {
        modes: [
          {
            pluginId: 'study',
            id: 'study',
            title: 'Study',
            entry: '',
            tools: ['notes', 'read_file'],
            capabilities: ['notes'],
          },
        ],
      },
    )

    await refreshPluginUIModes(rpc)

    const mode = getMode('study', 'study')
    expect(mode?.title).toBe('Study')
    expect(mode?.tools).toEqual(['notes', 'read_file'])
    expect(mode?.capabilities).toEqual(['notes'])
  })

  it('dedupes a mode declared by both systems', async () => {
    const entry = { pluginId: 'study', id: 'study', title: 'Study', entry: '' }
    const rpc = makeRpc({ modes: [entry] }, { modes: [entry] })

    await refreshPluginUIModes(rpc)

    expect(pluginUIRegistry.listModes()).toHaveLength(1)
  })

  it('keeps legacy modes when the v2 call fails', async () => {
    const rpc = makeRpc(
      { modes: [{ pluginId: 'study', id: 'study', title: 'Study', entry: '' }] },
      new Error('unsupported'),
    )

    await refreshPluginUIModes(rpc)

    expect(getMode('study', 'study')?.title).toBe('Study')
  })

  it('keeps v2 modes when the legacy call fails', async () => {
    const rpc = makeRpc(new Error('unsupported'), {
      modes: [{ pluginId: 'workflow', id: 'workflow', title: 'Workflow', entry: '' }],
    })

    await refreshPluginUIModes(rpc)

    expect(getMode('workflow', 'workflow')?.title).toBe('Workflow')
  })
})
