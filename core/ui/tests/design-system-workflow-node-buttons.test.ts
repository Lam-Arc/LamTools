import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import NodeEditCard from '../../src/lamtools_core/plugins/bundled/workflow/ui/NodeEditCard.vue'

describe('workflow node editor button', () => {
  it('applies changed node data using the shared compact primary button', async () => {
    const wrapper = mount(NodeEditCard, { props: {
      node: { id: 'n', kind: 'agent', title: 'Agent', ports: [], config: { tools: [] } } as any,
      anchor: { x: 200, y: 100 }, availableTools: [{ name: 'read_file', description: '' }],
    } })
    await wrapper.get('.wf-tool-check input').setValue(true)
    const apply = wrapper.get('.wf-edit-foot button')
    expect(apply.classes()).toEqual(expect.arrayContaining(['btn', 'btn--primary', 'btn--sm']))
    await apply.trigger('click')
    expect(wrapper.emitted('update')?.[0]?.[0]).toMatchObject({ config: { tools: ['read_file'] } })
    wrapper.unmount()
  })
})
