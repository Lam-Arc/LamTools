import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import AccountShell from '../src/components/AccountShell.vue'

/**
 * 用户共识：账号单独一个界面，内容先保持很少，以后再添。
 * 这份契约锁住"少"的边界：只回答现在是谁、有哪些设备、方案传输会不会用到账号；
 * 登录/注册/配对表单留在完整设置里，方案传输没接入就明说"待接入"，不放假按钮。
 */
function mountAccount(props: Record<string, unknown> = {}) {
  const onLogout = vi.fn()
  const onOpenSettings = vi.fn()
  const onRefresh = vi.fn()
  const wrapper = mount(AccountShell, {
    props: { onLogout, onOpenSettings, onRefresh, ...props },
    global: { stubs: { Teleport: true } },
  })
  return { wrapper, onLogout, onOpenSettings, onRefresh }
}

const ACCOUNT = {
  serverId: 'server-1',
  username: 'lam',
  nodeId: 'node-desktop-1',
  baseUrl: 'https://47.114.43.99.nip.io',
  accessExpiresAtMs: 0,
  refreshExpiresAtMs: 0,
}

describe('account screen', () => {
  it('shows who is signed in, without the settings forms', () => {
    const { wrapper } = mountAccount({
      accountStatus: ACCOUNT,
      devices: [],
    })

    expect(wrapper.find('.account-head-title').text()).toBe('账号')
    expect(wrapper.text()).toContain('已登录')
    expect(wrapper.text()).toContain('lam')
    expect(wrapper.text()).toContain('node-desktop-1')
    // 表单属于完整设置，这个界面里不该出现
    expect(wrapper.text()).not.toContain('注册')
    expect(wrapper.find('input').exists()).toBe(false)
  })

  it('offers logout when signed in, and a way to sign in when not', async () => {
    const signedIn = mountAccount({ accountStatus: ACCOUNT })
    await signedIn.wrapper.find('.account-btn').trigger('click')
    expect(signedIn.onLogout).toHaveBeenCalledTimes(1)

    const signedOut = mountAccount({ accountStatus: null })
    expect(signedOut.wrapper.text()).toContain('未登录')
    await signedOut.wrapper.find('.account-btn').trigger('click')
    expect(signedOut.onOpenSettings).toHaveBeenCalledTimes(1)
    expect(signedOut.onLogout).not.toHaveBeenCalled()
  })

  it('lists devices with their online state and marks this machine', () => {
    const { wrapper } = mountAccount({
      accountStatus: ACCOUNT,
      devices: [
        { nodeId: 'node-desktop-1', label: 'LamTools Desktop', detail: '当前桌面工作环境', platform: 'desktop', online: true, current: true },
        { nodeId: 'node-mobile-1', label: 'Pixel', detail: '已配对移动设备', platform: 'android', online: false },
      ],
    })

    expect(wrapper.text()).toContain('1/2 在线')
    expect(wrapper.findAll('.account-device-dot.online')).toHaveLength(1)
    expect(wrapper.text()).toContain('本机')
    expect(wrapper.text()).toContain('Pixel')
  })

  it('says plainly that plan transfer is not wired yet', () => {
    const { wrapper } = mountAccount({ accountStatus: ACCOUNT })

    expect(wrapper.text()).toContain('方案传输')
    expect(wrapper.text()).toContain('待接入')
    // 明说用导出／导入顶一段，而不是摆一个按不动的发送按钮
    expect(wrapper.text()).toContain('导出')
  })

  it('points at the full settings screen for the detailed forms', async () => {
    const { wrapper, onOpenSettings } = mountAccount({ accountStatus: ACCOUNT })

    await wrapper.find('.account-link').trigger('click')
    expect(onOpenSettings).toHaveBeenCalledTimes(1)
  })
})
