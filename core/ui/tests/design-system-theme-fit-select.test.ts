import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ThemeAreaEditor from '../src/components/ThemeAreaEditor.vue'

describe('shared theme image fit selector', () => {
  it('uses the shared menu and emits the chosen image fit', async () => {
    const wrapper = mount(ThemeAreaEditor, { props: { label: '主界面', stops: [{ color: '#1b1d22', position: 0 }], angle: 180, opacity: 1, textColor: '#fff', fillMode: 'image', glassLevel: 'off', image: 'data:image/png;base64,QQ==', imageFit: 'cover' }, global: { stubs: { Teleport: true } } })
    await wrapper.get('[data-theme-image-fit] .ui-select-trigger').trigger('click')
    const choice = wrapper.findAll('.ui-select-option').find(item => item.text() === '平铺')!
    await choice.trigger('click')
    expect(wrapper.emitted('update:image-fit')?.[0]).toEqual(['tile'])
    wrapper.unmount()
  })
})
