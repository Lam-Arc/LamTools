import { beforeEach, describe, expect, it } from 'vitest'

import {
  activateDevice,
  readDevices,
  readKeepAlivePref,
  readResumeTicket,
  readTicket,
  rememberDevice,
  saveConnectedDevice,
  saveKeepAlivePref,
  ticketDeviceId,
} from '../src/app/remoteSession.ts'

/** 一张 `sunday1:` 地址票：只带节点 id 与地址，代表“已配对设备重连用”。 */
function resumeTicket(id: string): string {
  const json = JSON.stringify({ id, addrs: [] })
  const base64 = btoa(json).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
  return `sunday1:${base64}`
}

beforeEach(() => {
  localStorage.clear()
})

describe('sunday1 resume tickets', () => {
  it('reads the device id out of an address ticket', () => {
    expect(ticketDeviceId(resumeTicket('device-1'))).toBe('device-1')
  })

  it('keeps the address ticket as the durable credential after pairing', () => {
    // user:“配对成功后建立持久设备信任，下次自动连接”+(5 分钟配对票不能当长期凭据；
    // 连接成功后当前票、重连票和设备清单都换成 sunday1)。
    const pairing = 'sunday2:not-a-resume-ticket'
    const resume = resumeTicket('device-1')
    expect(saveConnectedDevice(pairing, resume, '我的电脑')).toBe(resume)
    expect(readTicket()).toBe(resume)
    expect(readResumeTicket()).toBe(resume)
    expect(readDevices()).toEqual([{ id: 'device-1', name: '我的电脑', ticket: resume }])
  })

  it('does not lose the durable ticket when switching devices', () => {
    const first = resumeTicket('device-1')
    const second = resumeTicket('device-2')
    saveConnectedDevice(first, first, '电脑一')
    rememberDevice(second, '电脑二')
    activateDevice('device-2')
    expect(readTicket()).toBe(second)
    expect(readResumeTicket()).toBe(second)
    activateDevice(null)
    expect(readTicket()).toBe('')
    expect(readResumeTicket()).toBe('')
  })

  it('falls back to the scanned ticket when an older host returns no resume', () => {
    const pairing = 'sunday2:older-host'
    expect(saveConnectedDevice(pairing, '', '旧电脑')).toBe(pairing)
    expect(readTicket()).toBe(pairing)
    expect(readResumeTicket()).toBe('')
    // 配对票没有可解析的节点 id，设备清单不会凭空多出一条。
    expect(readDevices()).toEqual([])
  })

  // user:“简单可靠易用”+(后台保持连接默认开，只有用户明确关掉才持久化为关)。
  it('keeps background connection on unless the user turned it off', () => {
    expect(readKeepAlivePref()).toBe(true)
    saveKeepAlivePref(false)
    expect(readKeepAlivePref()).toBe(false)
    saveKeepAlivePref(true)
    expect(readKeepAlivePref()).toBe(true)
  })
})
