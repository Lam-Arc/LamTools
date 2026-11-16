import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

describe('shared loading motion gallery', () => {
  it('shows speed variants and their source', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('SundaySpinner')
    expect(wrapper.findAll('.sunday-spin')).toHaveLength(4)
    await wrapper.get('[data-source="SundaySpinner"]').trigger('click')
    expect(wrapper.find('[data-source-content="SundaySpinner"]').exists()).toBe(true)
    wrapper.unmount()
  })
})
