import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import CoreSubAgentActivityIndicator from '../src/components/CoreSubAgentActivityIndicator.vue'

describe('sub-agent activity gallery', () => {
  it('shows active and inactive real indicators and exposes their source', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreSubAgentActivityIndicator')
    const variants = wrapper.findAllComponents(CoreSubAgentActivityIndicator)
    expect(variants).toHaveLength(2)
    expect(variants[0].props('active')).toBe(true)
    expect(variants[0].get('[role=img]').attributes('aria-label')).toContain('示例')
    expect(variants[1].props('active')).toBe(false)
    await wrapper.get('[data-source="CoreSubAgentActivityIndicator"]').trigger('click')
    expect(wrapper.get('[data-source-content="CoreSubAgentActivityIndicator"]').text()).toContain('prefers-reduced-motion')
    wrapper.unmount()
  })
})

