// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MobileControlPanel from '../src/components/MobileControlPanel.vue'

const status = {
  baseUrl: 'https://relay.example.com',
  serverId: 'relay',
  username: 'lam',
  nodeId: 'mobile-1',
  accessExpiresAtMs: Date.now() + 60_000,
  refreshExpiresAtMs: Date.now() + 120_000,
}

const devices = [{
  nodeId: 'mobile-1',
  label: 'LamTools Mobile',
  detail: '当前移动设备',
  platform: 'android',
  online: true,
  current: true,
}]

describe('MobileControlPanel shared account state', () => {
  it('renders host account state instead of a second credentials form', () => {
    const wrapper = mount(MobileControlPanel, { props: { accountStatus: status, accountDevices: devices } })

    expect(wrapper.text()).toContain('lam')
    expect(wrapper.text()).toContain('LamTools Mobile')
    expect(wrapper.find('input[autocomplete="username"]').exists()).toBe(false)
  })

  it('emits logout so the host remains the only account state owner', async () => {
    const wrapper = mount(MobileControlPanel, { props: { accountStatus: status, accountDevices: devices } })

    await wrapper.get('.mobile-control-account-connected button').trigger('click')
    expect(wrapper.emitted('account-logout')).toHaveLength(1)
  })

  it('does not treat a missing Tauri bridge as logged out', () => {
    const wrapper = mount(MobileControlPanel, {
      props: { accountStatus: status, accountDevices: devices, available: false },
    })

    expect(wrapper.text()).toContain('已登录')
    expect(wrapper.find('input[autocomplete="username"]').exists()).toBe(false)
  })
})
