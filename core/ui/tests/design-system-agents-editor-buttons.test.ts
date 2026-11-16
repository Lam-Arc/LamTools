import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CoreAgentsEditor from '../src/components/CoreAgentsEditor.vue'
describe('agent editor shared buttons', () => {
  it('preserves save and cancel while using shared button variants', async () => {
    const wrapper = mount(CoreAgentsEditor, { props: { content: 'old' } })
    await wrapper.get('textarea').setValue('new')
    const save = wrapper.get('[data-agents-save]')
    expect(save.classes()).toEqual(expect.arrayContaining(['btn', 'btn--primary']))
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('save')?.[0]).toEqual(['new'])
    const cancel = wrapper.findAll('button').find(button => button.text() === '取消')!
    expect(cancel.classes()).toEqual(expect.arrayContaining(['btn', 'btn--ghost']))
    await cancel.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    await wrapper.setProps({ loading: true })
    expect((save.element as HTMLButtonElement).disabled).toBe(true)
    wrapper.unmount()
  })
})
