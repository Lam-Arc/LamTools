import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import WorkflowTriggersPanel from '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowTriggersPanel.vue'

describe('workflow trigger gallery', () => {
  it('renders the real panel, saves a local draft and locates its source', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('WorkflowTriggersPanel')
    const panel = wrapper.getComponent(WorkflowTriggersPanel)
    await panel.get('input.sunday-checkbox').setValue(false)
    await panel.get('form[data-trigger-editor]').trigger('submit')
    expect(wrapper.get('[data-trigger-gallery-result]').text()).toContain('已保存')
    await wrapper.get('[data-source="WorkflowTriggersPanel"]').trigger('click')
    expect(wrapper.get('[data-source-content="WorkflowTriggersPanel"]').text()).toContain('wf-trigger-primary')
    wrapper.unmount()
  })
})
