import { afterEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

import { MemorySecureStorage } from '../src/native/secureStorage'
import { StandaloneConfigStore } from '../src/standalone/StandaloneConfigStore'
import { MemoryStandaloneStateStorage } from '../src/standalone/StandaloneStateStorage'
import { StandaloneExtensionsStore } from '../src/standalone/StandaloneExtensionsStore'

const SCHEMAS = {
  imagegen: {
    path: 'bundled://imagegen/config/schema.jsonc',
    schema: {
      type: 'object',
      properties: {
        enabled: { type: 'boolean', description: '是否启用生图工具', default: false },
        api_url: { type: 'string' },
        api_key: { type: 'string' },
        model: { type: 'string' },
      },
    },
  },
  websearch: {
    path: 'bundled://websearch/config/schema.jsonc',
    schema: {
      type: 'object',
      properties: {
        provider: { type: 'string', enum: ['baidu', 'bing', 'ddg'], default: 'ddg' },
        limit: { type: 'integer', default: 5 },
        timeout: { type: 'number', default: 15 },
        fallback_providers: { type: 'array', items: { type: 'string' }, default: ['ddg', 'baidu', 'bing'] },
        proxy_port: { type: 'integer', minimum: 1, maximum: 65535 },
      },
    },
  },
}

/** The plugin catalogue the host reports: the universal plugins, and study. */
const CATALOG = [
  { name: 'imagegen', version: '0.1.0', description: '生图工具', platforms: 'universal', skills: [], skill_names: [], modes: [], dependencies: [], tools: [], declared_tool_count: 0, tools_note: '' },
  { name: 'websearch', version: '0.1.0', description: '网页搜索', platforms: 'universal', skills: [], skill_names: [], modes: [], dependencies: [], tools: [], declared_tool_count: 0, tools_note: '' },
  { name: 'study', version: '1.0.0', description: '全局学习空间与文本批注', platforms: 'universal', skills: [], skill_names: [], modes: [], dependencies: [], tools: [], declared_tool_count: 0, tools_note: '' },
]

function store(storage = new MemoryStandaloneStateStorage<any>()) {
  return new StandaloneConfigStore(new MemorySecureStorage(), storage)
}

afterEach(() => { invokeMock.mockReset(); vi.unstubAllGlobals() })

describe('standalone plugin configuration', () => {
  it('masks secrets on read, preserves them on a blank submit, and validates by schema', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'sunday_plugin_schemas') return SCHEMAS
      if (command === 'sunday_tool_catalog') return []
      throw new Error(`unexpected ${command}`)
    })
    const config = store()
    const saved = await config.handleRpc('plugin.config.update', {
      name: 'imagegen',
      config: { enabled: true, api_url: 'https://img.invalid/v1', api_key: 'sk-secret', model: 'gpt-image' },
    })
    expect(saved?.validated).toBe(true)

    // The key never comes back in clear text ...
    const read = await config.handleRpc('plugin.config.get', { name: 'imagegen' })
    expect(read?.has_secrets).toBe(true)
    expect(read?.config_schema_path).toBe('bundled://imagegen/config/schema.jsonc')
    expect((read?.config as Record<string, unknown>).api_key).toBe('********')
    expect((read?.config as Record<string, unknown>).api_url).toBe('https://img.invalid/v1')

    // ... and a panel that submits the mask must not wipe it.
    await config.handleRpc('plugin.config.update', {
      name: 'imagegen',
      config: { ...(read?.config as Record<string, unknown>), model: 'gpt-image-2' },
    })
    const reread = await config.handleRpc('plugin.config.get', { name: 'imagegen' })
    expect((reread?.config as Record<string, unknown>).model).toBe('gpt-image-2')
    // The stored document keeps the original secret, which is what the runtime reads.
    expect((await config.settings('core.imagegen')).api_key).toBe('sk-secret')

    // Schema violations are refused with the field named.
    await expect(config.handleRpc('plugin.config.update', {
      name: 'websearch',
      config: { provider: 'google' },
    })).rejects.toThrow('provider 只能是 baidu/bing/ddg')
    await expect(config.handleRpc('plugin.config.update', {
      name: 'websearch',
      config: { proxy_port: 70000 },
    })).rejects.toThrow('proxy_port 不能大于 65535')
    await expect(config.handleRpc('plugin.config.update', {
      name: 'websearch',
      config: { limit: 'many' },
    })).rejects.toThrow('limit 必须是整数')
    await expect(config.handleRpc('plugin.config.update', { name: 'websearch', config: 'nope' }))
      .rejects.toThrow('config 必须是对象')
  })

  it('writes search settings into the namespace the host reads, and a plugin without a schema has none', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'sunday_plugin_schemas') return SCHEMAS
      if (command === 'sunday_tool_catalog') return []
      throw new Error(`unexpected ${command}`)
    })
    const config = store()
    await config.handleRpc('plugin.config.update', {
      name: 'websearch',
      config: { provider: 'bing', fallback_providers: ['baidu'], limit: 8, timeout: 20 },
    })
    expect(await config.settings('core.websearch')).toEqual({
      provider: 'bing',
      fallback_providers: ['baidu'],
      limit: 8,
      timeout: 20,
    })
    await expect(config.handleRpc('plugin.config.get', { name: 'workflow' }))
      .rejects.toThrow("插件 'workflow' 没有可配置项")
  })

  it('answers the JSONC websearch editor with the document the runtime will read', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'sunday_plugin_schemas') return SCHEMAS
      if (command === 'sunday_tool_catalog') return []
      throw new Error(`unexpected ${command}`)
    })
    const config = store()
    // Nothing configured yet: an empty document, not an invented one.
    expect(await config.handleRpc('websearch.config.get', {})).toEqual({
      content: '', path: 'mobile://config/websearch.jsonc',
    })

    // JSONC with comments and a URL containing `//` must round-trip.
    const jsonc = [
      '{',
      '  // 搜索内核',
      '  "provider": "baidu",',
      '  "api_url": "https://example.invalid/v1",',
      '  "limit": 7',
      '}',
    ].join('\n')
    expect(await config.handleRpc('websearch.config.update', { content: jsonc }))
      .toEqual({ path: 'mobile://config/websearch.jsonc', saved: true })
    expect(await config.settings('core.websearch')).toEqual({
      provider: 'baidu',
      api_url: 'https://example.invalid/v1',
      limit: 7,
    })
    const readBack = await config.handleRpc('websearch.config.get', {})
    expect(JSON.parse(String(readBack?.content))).toEqual({
      provider: 'baidu',
      api_url: 'https://example.invalid/v1',
      limit: 7,
    })

    // Broken JSON is reported instead of silently stored.
    await expect(config.handleRpc('websearch.config.update', { content: '{ nope' }))
      .rejects.toThrow('Invalid JSON/JSONC')
    await expect(config.handleRpc('websearch.config.update', { content: '[]' }))
      .rejects.toThrow('必须是对象')
  })

  it('offers a configuration entry only for plugins that ship a schema', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'sunday_plugin_schemas') return SCHEMAS
      if (command === 'sunday_plugin_catalog') return CATALOG
      throw new Error(`unexpected ${command}`)
    })
    const extensions = new StandaloneExtensionsStore(
      new MemoryStandaloneStateStorage<any>(),
      async () => [],
    )
    const plugins = (await extensions.handleRpc('plugin.list', {}))!.plugins as Array<Record<string, unknown>>
    const byName = Object.fromEntries(plugins.map(plugin => [plugin.name, plugin]))
    expect(byName.imagegen.config_schema).toBe('bundled://imagegen/config/schema.jsonc')
    expect(byName.websearch.config_schema).toBe('bundled://websearch/config/schema.jsonc')
    // A schema-less plugin shows no configuration entry rather than an empty
    // form; a desktop-class plugin is not offered here at all.
    expect(byName.study.config_schema).toBe('')
    expect(byName.git).toBeUndefined()
    expect(byName.workflow).toBeUndefined()
  })
})
