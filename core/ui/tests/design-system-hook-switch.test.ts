import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import CoreHooksEditor from '../src/components/CoreHooksEditor.vue'
import SundaySwitch from '../src/components/SundaySwitch.vue'
describe('hook required switch', () => {
  it('uses the shared switch and saves the selected hook failure policy', async () => {
    const rpc = vi.fn(async (method: string) => method === 'hook.config.get' ? { content: '{}' } : { hooks: [] })
    const wrapper = mount(CoreHooksEditor, { props: { requestRpc: rpc } }); await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '新增 Hook')!.trigger('click')
    const control = wrapper.findAllComponents(SundaySwitch).find(switcher => switcher.props('label') === 'hook 失败时阻断执行')
    expect(control).toBeDefined()
    await control!.get('input').setValue(true)
    await wrapper.get('textarea').setValue('node test.mjs')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    const call = rpc.mock.calls.find(([method]) => method === 'hook.config.update')
    expect(call).toBeDefined()
    const config = JSON.parse((call![1] as { content: string }).content)
    expect(Object.values(config.hooks).flatMap((groups: any) => groups.flatMap((group: any) => group.hooks))).toEqual(expect.arrayContaining([expect.objectContaining({ required: true, command: 'node test.mjs' })]))
    wrapper.unmount()
  })
})
