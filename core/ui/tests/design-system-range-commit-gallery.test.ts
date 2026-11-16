import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

describe('range gallery commit', () => {
  it('reports the committed value after the drag finishes', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('SundayRange')
    const input = wrapper.get('input[aria-label="数值"]')
    ;(input.element as HTMLInputElement).value = '65'
    await input.trigger('input')
    expect(wrapper.text()).not.toContain('已提交：65')
    await input.trigger('change')
    expect(wrapper.text()).toContain('已提交：65')
    wrapper.unmount()
  })
})
