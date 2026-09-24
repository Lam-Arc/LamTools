import { afterEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

import { MemorySecureStorage } from '../src/native/secureStorage'
import { StandaloneConfigStore } from '../src/standalone/StandaloneConfigStore'
import { MemoryStandaloneStateStorage } from '../src/standalone/StandaloneStateStorage'

const CATALOG = [
  { name: 'read_file', category: 'file_read' },
  { name: 'list_dir', category: 'file_read' },
  { name: 'search_files', category: 'file_read' },
  { name: 'search_content', category: 'file_read' },
  { name: 'write_file', category: 'file_write' },
  { name: 'edit_file', category: 'file_write' },
  { name: 'web_search', category: 'web' },
  { name: 'web_fetch', category: 'web' },
  { name: 'load_skill', category: 'skill' },
  { name: 'generate_image', category: 'image' },
  { name: 'sub_agent', category: 'agent' },
  { name: 'sub_agent_message', category: 'agent' },
  { name: 'notes', category: 'other' },
]

/** One storage instance per test, so a second store sees the first one's writes. */
function store(storage: MemoryStandaloneStateStorage<any>) {
  return new StandaloneConfigStore(new MemorySecureStorage(), storage)
}

afterEach(() => { invokeMock.mockReset(); vi.unstubAllGlobals() })

describe('standalone mode tool-sets', () => {
  it('serves the desktop built-in modes with the host catalog, and never names a missing tool', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'sunday_tool_catalog') return CATALOG
      if (command === 'sunday_plugin_mode_tools') return []
      throw new Error(`unexpected ${command}`)
    })
    const storage = new MemoryStandaloneStateStorage<any>()
    const config = store(storage)
    const result = await config.handleRpc('config.loadtools.get', {})
    expect(result?.source).toBe('builtin')
    expect(result?.catalog).toEqual(CATALOG)
    const modes = result?.modes as Record<string, { description: string; tools: string[] }>
    expect(Object.keys(modes)).toEqual(['consider', 'execute'])
    expect(modes.consider.description).toContain('read-only tools')
    // The desktop default names git tools and `message`; this host has neither,
    // so they must not be promised by a mode the panel shows.
    expect(modes.consider.tools).not.toContain('git_status')
    expect(modes.consider.tools).not.toContain('git_diff')
    expect(modes.consider.tools).not.toContain('message')
    expect(modes.consider.tools).toEqual([
      'read_file', 'list_dir', 'search_files', 'search_content',
      'web_search', 'web_fetch', 'load_skill',
    ])
    // A full-access mode stays empty rather than becoming an empty whitelist.
    expect(modes.execute.tools).toEqual([])
  })

  it('round-trips saved modes, validates the payload, and enforces them for a turn', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    invokeMock.mockImplementation(async (command: string) => {
      if (command === 'sunday_tool_catalog') return CATALOG
      if (command === 'sunday_plugin_mode_tools') return []
      throw new Error(`unexpected ${command}`)
    })
    const storage = new MemoryStandaloneStateStorage<any>()
    const config = store(storage)

    await expect(config.handleRpc('config.loadtools.set', { modes: 'nope' })).rejects.toThrow('modes 不能为空')
    await expect(config.handleRpc('config.loadtools.set', { modes: { broken: 3 } })).rejects.toThrow('必须是对象')
    await expect(config.handleRpc('config.loadtools.set', { modes: { broken: { tools: 'x' } } }))
      .rejects.toThrow('必须是数组')

    const saved = await config.handleRpc('config.loadtools.set', {
      modes: {
        consider: { description: '只读', tools: ['read_file', 'search_content', 'git_status', 'read_file'] },
        execute: { description: '', tools: [] },
      },
    })
    expect(saved?.source).toBe('config')
    // Duplicates collapse, and the answer reports only what is in force.
    expect((saved?.modes as Record<string, { tools: string[] }>).consider.tools)
      .toEqual(['read_file', 'search_content'])
    // The document keeps the name this host cannot run, so a later version that
    // implements it does not silently lose the user's configuration.
    const stored = await config.settings('core.loadTools') as { modes: Record<string, { tools: string[] }> }
    expect(stored.modes.consider.tools).toEqual(['read_file', 'search_content', 'git_status'])

    // A restart reads the saved document back, not the built-in one.
    const restored = store(storage)
    const reloaded = await restored.handleRpc('config.loadtools.get', {})
    expect(reloaded?.source).toBe('config')
    expect((reloaded?.modes as Record<string, { description: string }>).consider.description).toBe('只读')

    // The turn path gets the same whitelist and the desktop's prompt line.
    expect(await restored.modePlan('consider')).toEqual({
      tools: ['read_file', 'search_content'],
      promptLine: 'Current mode: consider — 只读',
    })
    // Full access and unknown modes restrict nothing.
    expect(await restored.modePlan('execute')).toEqual({ tools: null, promptLine: 'Current mode: execute — execute' })
    expect(await restored.modePlan('nope')).toEqual({ tools: null, promptLine: '' })
    expect(await restored.modePlan('')).toEqual({ tools: null, promptLine: '' })
  })

  it('takes a plugin mode from the plugin declaration and an empty answer as no restriction', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    invokeMock.mockImplementation(async (command: string, args?: { mode?: string }) => {
      if (command === 'sunday_plugin_mode_tools') {
        return args?.mode === 'study:study' ? ['notes', 'read_file', 'web_search'] : []
      }
      if (command === 'sunday_tool_catalog') return CATALOG
      throw new Error(`unexpected ${command}`)
    })
    const storage = new MemoryStandaloneStateStorage<any>()
    const config = store(storage)
    expect(await config.modePlan('study:study')).toEqual({
      tools: ['notes', 'read_file', 'web_search'],
      promptLine: '',
    })
    expect(await config.modePlan('other:mode')).toEqual({ tools: null, promptLine: '' })
  })
})
