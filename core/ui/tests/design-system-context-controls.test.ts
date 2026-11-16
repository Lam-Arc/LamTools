import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import CoreSettings from '../src/components/CoreSettings.vue'
import { DEFAULT_THEME } from '../src/helpers/theme'

// user:“确保视觉、功能和交互不退化”+(上下文优先级零按输入保存，移除按钮说明目标)。
describe('context settings controls', () => {
  it('preserves zero priority and labels removal of excluded files', async () => {
    const rpc = vi.fn(async (method: string) => method === 'config.load_context.get' ? { addition: [{ name: 'RULES.md', priority: 0, kind: 'system' }], except: ['AGENTS.md'] } : {})
    const wrapper = mount(CoreSettings, { props: { models: [], providers: [], modelGroups: [], catalogView: 'provider', commandShellPlatform: 'windows', density: 'standard', theme: structuredClone(DEFAULT_THEME), requestRpc: rpc }, global: { stubs: { Teleport: true } } })
    await flushPromises(); await wrapper.get('[data-settings-section="agents"]').trigger('click'); await flushPromises()
    const card = wrapper.findAll('.setting-card').find(item => item.text().includes('全局上下文加载'))!
    expect(card.get('.lc-priority').element).toHaveProperty('value', '0')
    expect(card.get('.lc-chip-x').attributes('aria-label')).toContain('AGENTS.md')
    const save = card.findAll('button').find(button => button.text() === '保存')!
    await save.trigger('click'); await flushPromises()
    expect(rpc).toHaveBeenCalledWith('config.load_context.set', expect.objectContaining({ addition: [{ name: 'RULES.md', priority: 0, kind: 'system' }] }))
    wrapper.unmount()
  })
})
