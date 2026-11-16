import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
describe('composer theme tokens in the gallery', () => {
  it('exposes the real input background and text tokens', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('DesignTokens')
    expect(wrapper.find('[data-token-value="--theme-composer-background"]').exists()).toBe(true)
    expect(wrapper.find('[data-token-value="--theme-composer-text"]').exists()).toBe(true)
    wrapper.unmount()
  })
})
