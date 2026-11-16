import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import CorePetEditor from '../src/components/CorePetEditor.vue'
describe('pet settings gallery', () => {
  it('shows the real editor in isolated preview mode and exposes its source', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CorePetEditor'); await flushPromises()
    const editor = wrapper.getComponent(CorePetEditor)
    expect(editor.props('preview')).toBe(true)
    const sector = editor.get('.pet-settings-sector-label')
    await sector.setValue('预览名称'); await sector.trigger('change')
    expect((sector.element as HTMLInputElement).value).toBe('预览名称')
    await wrapper.get('[data-source="CorePetEditor"]').trigger('click')
    expect(wrapper.get('[data-source-content="CorePetEditor"]').text()).toContain('theme-composer-background')
    wrapper.unmount()
  })
})
