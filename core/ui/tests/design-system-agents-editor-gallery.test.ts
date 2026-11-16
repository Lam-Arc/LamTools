import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import CoreAgentsEditor from '../src/components/CoreAgentsEditor.vue'
describe('agent editor gallery', () => {
  it('edits and saves a local example without any project writes', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreAgentsEditor')
    const editor = wrapper.getComponent(CoreAgentsEditor)
    await editor.get('textarea').setValue('本地示例内容')
    await editor.get('form').trigger('submit')
    expect(wrapper.get('[data-agent-editor-result]').text()).toContain('本地示例内容')
    await wrapper.get('[data-source="CoreAgentsEditor"]').trigger('click')
    expect(wrapper.get('[data-source-content="CoreAgentsEditor"]').text()).toContain('btn--material')
    wrapper.unmount()
  })
})
