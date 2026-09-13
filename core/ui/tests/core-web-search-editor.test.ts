import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CoreWebSearchEditor from '../src/components/CoreWebSearchEditor.vue'

describe('CoreWebSearchEditor proxy config', () => {
  it('loads and saves a port-only DuckDuckGo proxy setting', async () => {
    const requestRpc = vi.fn(async (method: string, _params?: Record<string, unknown>) => {
      if (method === 'websearch.config.get') {
        return {
          content: JSON.stringify({ provider: 'ddg', limit: 5, timeout: 15, proxy_port: 7890 }),
        }
      }
      return {}
    })
    const wrapper = mount(CoreWebSearchEditor, { props: { requestRpc } })
    await flushPromises()

    const proxyInput = wrapper.get('input[aria-label="DuckDuckGo 本地代理端口"]')
    expect((proxyInput.element as HTMLInputElement).value).toBe('7890')
    await proxyInput.setValue('8888')

    const saveButton = wrapper.findAll('button').find((button) => button.text() === '保存')
    expect(saveButton).toBeTruthy()
    await saveButton!.trigger('click')
    await flushPromises()

    const updateCall = requestRpc.mock.calls.find(([method]) => method === 'websearch.config.update')
    expect(updateCall).toBeTruthy()
    const saved = JSON.parse(String(updateCall![1]?.content || '{}'))
    expect(saved.proxy_port).toBe(8888)
  })
})
