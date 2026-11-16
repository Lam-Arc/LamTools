import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import CoreSystemEventRow from '../src/components/CoreSystemEventRow.vue'
describe('system event gallery', () => {
  it('compares real member and memory events and locates their source', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreSystemEventRow')
    const rows = wrapper.findAllComponents(CoreSystemEventRow)
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('已完成')
    expect(rows[1].text()).toContain('记忆续跑')
    await wrapper.get('[data-source="CoreSystemEventRow"]').trigger('click')
    expect(wrapper.get('[data-source-content="CoreSystemEventRow"]').text()).toContain('CoreSystemEvent')
    wrapper.unmount()
  })
})
