import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import { renderComponentIndex } from '../../../scripts/ui-inventory.mjs'

describe('searchable component inventory', () => {
  it('indexes source clues and distinguishes production callers from previews', () => {
    const files = [
      { path: 'core/ui/src/components/Example.vue', signals: ['button', 'event'], imports: [] },
      { path: 'core/ui/src/components/Screen.vue', signals: [], imports: ['core/ui/src/components/Example.vue'] },
      { path: 'core/ui/src/design-system/Gallery.vue', signals: [], imports: ['core/ui/src/components/Example.vue'] },
    ]
    const item = renderComponentIndex(files).find(entry => entry.name === 'Example')!
    expect(item.signals).toEqual(['button', 'event'])
    expect(item.callers).toEqual(['core/ui/src/components/Screen.vue'])
    expect(item.previewCallers).toEqual(['core/ui/src/design-system/Gallery.vue'])
  })
  it('finds a component by its caller and exposes usage clues', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('ThemeAreaEditor')
    await wrapper.get('[data-show-inventory]').trigger('click')
    const row = wrapper.get('[data-inventory-path="core/ui/src/components/SundayRange.vue"]')
    expect(row.text()).toContain('ThemeAreaEditor.vue')
    expect(row.text()).toContain('range')
    wrapper.unmount()
  })
})
