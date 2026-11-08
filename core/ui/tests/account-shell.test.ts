// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AccountShell from '../src/components/AccountShell.vue'

/**
 * user:“页面里头的账号，什么该删的删，适配新体系”+
 * 账号页现在是远程连接页：只有一块「设备连接」面板，出票据或扫码。
 * 旧的登录、账号、设备列表、配对码、方案传输都不该再出现。
 */
function mountAccount(platform: 'desktop' | 'mobile' = 'mobile') {
  return mount(AccountShell, {
    props: { appRuntime: { platform } },
    global: { stubs: { Teleport: true } },
  })
}

describe('remote connection page', () => {
  it('only renders the device connection panel', () => {
    const wrapper = mountAccount()
    const text = wrapper.text()
    expect(text).toContain('设备连接')
    for (const gone of ['登录', '账号', '注册', '配对码', '方案传输']) {
      expect(text, `账号页不该再出现「${gone}」`).not.toContain(gone)
    }
    expect(wrapper.find('input').exists()).toBe(false)
  })

  it('has no header of its own: the full-area band owns the back button and title', () => {
    const wrapper = mountAccount()
    expect(wrapper.find('header').exists()).toBe(false)
    expect(wrapper.find('.account-back').exists()).toBe(false)
  })

  it('keeps one primary action per side: scan on the phone, a ticket on the desktop', async () => {
    const phone = mountAccount('mobile')
    expect(phone.find('[data-remote-scan]').exists()).toBe(true)
    // 手动粘贴是退路，默认不占位置。
    expect(phone.find('[data-remote-ticket-input]').exists()).toBe(false)
    await phone.get('[data-remote-paste-toggle]').trigger('click')
    expect(phone.find('[data-remote-ticket-input]').exists()).toBe(true)

    const desktop = mountAccount('desktop')
    expect(desktop.text()).toContain('生成票据')
    expect(desktop.find('[data-remote-scan]').exists()).toBe(false)
    // 没有可信设备时整块不出现。
    expect(desktop.find('.remote-panel__devices').exists()).toBe(false)
  })

  it('only offers stop once a ticket exists', () => {
    const desktop = mountAccount('desktop')
    expect(desktop.text()).not.toContain('换一张')
    expect(desktop.text()).not.toContain('停止')
  })
})
