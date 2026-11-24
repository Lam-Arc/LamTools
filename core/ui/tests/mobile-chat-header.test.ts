import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MobileChatHeader from '../src/components/MobileChatHeader.vue'
import MobileSessionSettings from '../src/components/MobileSessionSettings.vue'

describe('MobileChatHeader (L2)', () => {
  it('shows the session title, owning project and device state', () => {
    const wrapper = mount(MobileChatHeader, {
      props: {
        title: 'Relay 优化',
        projectName: 'Sunday 开发',
        deviceLabel: '电脑 · 已连接',
        deviceState: 'remote',
      },
    })

    expect(wrapper.get('[data-mobile-chat-header-title]').text()).toBe('Relay 优化')
    const device = wrapper.get('[data-mobile-chat-header-device]')
    expect(device.text()).toContain('Sunday 开发')
    expect(device.text()).toContain('电脑 · 已连接')
    expect(device.attributes('data-device-state')).toBe('remote')
  })

  it('returns to the list and opens the menu from its two ends', async () => {
    const wrapper = mount(MobileChatHeader, {
      props: { title: '会话', deviceLabel: '本机 Android', deviceState: 'local' },
    })

    await wrapper.get('[data-mobile-chat-back]').trigger('click')
    expect(wrapper.emitted('back')).toHaveLength(1)

    await wrapper.get('[data-mobile-chat-more]').trigger('click')
    expect(wrapper.emitted('more')).toHaveLength(1)
  })
})

describe('MobileSessionSettings (L3)', () => {
  const baseProps = {
    open: true,
    title: '日常聊天',
    projectName: '默认项目',
    deviceLabel: '本机 Android',
    deviceState: 'local' as const,
    createdAt: '2026-11-20T09:05:00',
    pinned: false,
  }

  it('lists the session facts needed to identify the conversation', () => {
    const wrapper = mount(MobileSessionSettings, { props: baseProps })

    const text = wrapper.text()
    expect(text).toContain('日常聊天')
    expect(text).toContain('默认项目')
    expect(text).toContain('本机 Android')
    expect(text).toContain('2026/11/20 09:05')
  })

  it('exposes pin state and forwards rename/pin/export/delete', async () => {
    const wrapper = mount(MobileSessionSettings, { props: baseProps })

    const pin = wrapper.get('[data-mobile-session-pin]')
    expect(pin.attributes('aria-checked')).toBe('false')
    await pin.trigger('click')
    expect(wrapper.emitted('toggle-pin')).toHaveLength(1)

    await wrapper.get('[data-mobile-session-rename]').trigger('click')
    expect(wrapper.emitted('rename')).toHaveLength(1)

    await wrapper.get('[data-mobile-session-export]').trigger('click')
    expect(wrapper.emitted('export')).toHaveLength(1)

    await wrapper.get('[data-mobile-session-delete]').trigger('click')
    expect(wrapper.emitted('delete')).toHaveLength(1)
  })

  it('shows the switch as on when the session is pinned', () => {
    const wrapper = mount(MobileSessionSettings, { props: { ...baseProps, pinned: true } })
    expect(wrapper.get('[data-mobile-session-pin]').attributes('aria-checked')).toBe('true')
    expect(wrapper.get('.mobile-session__switch').classes()).toContain('is-on')
  })
})
