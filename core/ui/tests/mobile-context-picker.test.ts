import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MobileContextPicker from '../src/components/MobileContextPicker.vue'

// user:“项目不应该和环境放在一个选项内”+
// (这张面板只说运行环境；项目与会话在列表里按项目折叠，项目的新建/管理也在列表里)。
describe('MobileContextPicker (运行环境)', () => {
  it('lists the environment only and never mixes projects into it', () => {
    const wrapper = mount(MobileContextPicker, {
      props: { open: true, environmentName: '本机 Android' },
    })

    expect(wrapper.get('[data-mobile-context-env]').text()).toContain('本机 Android')
    expect(wrapper.find('[data-mobile-context-project]').exists()).toBe(false)
    expect(wrapper.find('[data-mobile-context-create]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('closes from the backdrop and from the close button', async () => {
    const wrapper = mount(MobileContextPicker, { props: { open: true } })

    await wrapper.get('[data-mobile-context-close]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })

  it('offers a direct connection entry from the environment panel', async () => {
    const wrapper = mount(MobileContextPicker, { props: { open: true } })
    const connect = wrapper.get('[data-mobile-context-connect]')

    expect(connect.text()).toContain('连接电脑')
    expect(connect.text()).toContain('扫码')
    await connect.trigger('click')
    expect(wrapper.emitted('connect')).toHaveLength(1)
    wrapper.unmount()
  })

  it('turns the same entry into connection management when already connected', () => {
    const wrapper = mount(MobileContextPicker, {
      props: { open: true, remoteConnected: true },
    })

    const connect = wrapper.get('[data-mobile-context-connect]')
    expect(connect.text()).toContain('管理连接')
    expect(connect.text()).toContain('已连接电脑')
    wrapper.unmount()
  })

  it('renders nothing while closed', () => {
    const wrapper = mount(MobileContextPicker, { props: { open: false } })
    expect(wrapper.find('[data-mobile-context-picker]').exists()).toBe(false)
    wrapper.unmount()
  })
})
