import { invoke } from '@tauri-apps/api/core'
import { afterEach, expect, it, vi } from 'vitest'
import { startBrowserAgentBridge } from '@/browser/agentBridge'

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

// user:“这是工具返回值和实际状态不同步”+(界面绑定的目标页与传回工具的标签必须是同一个)。
it('adopts the tab from the click response before posting the result', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('__TAURI_INTERNALS__', {})
  const response = {
    tab: 't2',
    url: 'https://example.com/video',
    sourceTab: 't1',
    openedTabs: [{ tab: 't2', url: 'https://example.com/video' }],
  }
  vi.mocked(invoke).mockImplementation(async command => command === 'get_api_base'
    ? 'http://localhost'
    : response)
  const adopt = vi.fn()
  const fetchMock = vi.fn(async (_url: string, options?: RequestInit) => {
    if (options?.method === 'POST') {
      expect(adopt).toHaveBeenCalledOnce()
      expect(JSON.parse(String(options.body)).payload).toEqual(response)
    }
    return {
      ok: true,
      json: async () => ({
        requests: [{ id: 'click-1', command: 'browser_act', args: { tab: 't1', instruction: { op: 'click', ref: 'e26' } } }],
      }),
    }
  })
  vi.stubGlobal('fetch', fetchMock)
  const listener = (event: Event) => adopt((event as CustomEvent).detail)
  window.addEventListener('sunday:browser-agent-tab', listener)
  const stop = startBrowserAgentBridge()
  try {
    await vi.advanceTimersByTimeAsync(200)
    expect(adopt).toHaveBeenCalledExactlyOnceWith({ tab: 't2', url: 'https://example.com/video', opener: 't1' })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  } finally {
    stop()
    window.removeEventListener('sunday:browser-agent-tab', listener)
  }
})
