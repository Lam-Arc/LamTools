import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import EdgeConditionEditor from '../../src/lamtools_core/plugins/bundled/workflow/ui/EdgeConditionEditor.vue'

describe('workflow condition editor buttons', () => {
  it('uses shared buttons and preserves editing, saving and cancellation', async () => {
    const wrapper = mount(EdgeConditionEditor, { props: { value: 'old', anchor: { x: 10, y: 10 } } })
    await wrapper.get('textarea').setValue('quality >= 0.8')
    const buttons = wrapper.findAll('footer button')
    expect(buttons[0].classes()).toEqual(expect.arrayContaining(['btn', 'btn--secondary', 'btn--sm']))
    expect(buttons[1].classes()).toEqual(expect.arrayContaining(['btn', 'btn--primary', 'btn--sm']))
    await buttons[1].trigger('click')
    expect(wrapper.emitted('save')?.[0]).toEqual(['quality >= 0.8'])
    await buttons[0].trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })
})
