import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CoreBubbleAppearance from '../src/components/CoreBubbleAppearance.vue'
import {
  ASSISTANT_DISPLAY_DEFAULTS,
  assistantDisplayPreferences,
  setAssistantDisplayPreferences,
} from '../src/composables/useAssistantDisplayPreferences'

type RpcCall = [string, Record<string, unknown> | undefined]

function createRpc(stored: Record<string, unknown> = {}) {
  const calls: RpcCall[] = []
  const rpc = vi.fn(async (method: string, params?: Record<string, unknown>) => {
    calls.push([method, params])
    if (method === 'settings.get') {
      return { namespace: 'core.assistantDisplay', value: { ...stored } }
    }
    return { namespace: 'core.assistantDisplay', value: { ...stored } }
  })
  return { rpc, calls }
}

beforeEach(() => {
  setAssistantDisplayPreferences(ASSISTANT_DISPLAY_DEFAULTS)
})

/**
 * user:“放进 界面/主题”+(气泡外观卡片挂在界面分区，读写仍走 core.assistantDisplay)
 */
describe('CoreBubbleAppearance', () => {
  it('renders shape, glass and both fill colors', async () => {
    const { rpc } = createRpc()
    const wrapper = mount(CoreBubbleAppearance, { props: { requestRpc: rpc } })
    await flushPromises()
    expect(wrapper.text()).toContain('气泡外观')
    expect(wrapper.find('[aria-label="玻璃气泡"]').exists()).toBe(true)
    expect(wrapper.find('input[aria-label="用户气泡颜色"]').exists()).toBe(true)
    expect(wrapper.find('input[aria-label="助手气泡颜色"]').exists()).toBe(true)
  })

  it('loads stored appearance and persists color edits', async () => {
    const { rpc, calls } = createRpc({
      bubbleShape: 'capsule',
      bubbleGlass: false,
      bubbleUserColor: '#112233',
    })
    const wrapper = mount(CoreBubbleAppearance, { props: { requestRpc: rpc } })
    await flushPromises()
    expect(assistantDisplayPreferences.bubbleShape).toBe('capsule')
    expect(assistantDisplayPreferences.bubbleGlass).toBe(false)
    expect(assistantDisplayPreferences.bubbleUserColor).toBe('#112233')

    await wrapper.get('input[aria-label="用户气泡颜色"]').setValue('#ff00aa')
    await flushPromises()
    const update = calls.filter(([method]) => method === 'settings.update').at(-1)
    expect(update?.[1]?.namespace).toBe('core.assistantDisplay')
    expect((update?.[1]?.value as Record<string, unknown>).bubbleUserColor).toBe('#ff00aa')
    expect(assistantDisplayPreferences.bubbleUserColor).toBe('#ff00aa')
  })
})
