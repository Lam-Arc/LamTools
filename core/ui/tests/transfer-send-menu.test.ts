// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SendToDeviceMenu from '../src/components/SendToDeviceMenu.vue'
import { rememberSendSource, sendArgs, sendFileToDevice, sendTargetReason, ticketForDevice, trackSendSource, windowSendSources } from '../src/transfer/dispatch'
import { mergeTransferTargets } from '../src/transfer/send'

/**
 * user:“发送入口：文件树、资料库、预览器里对文件加「发送到设备」——列出已信任设备（含在线状态
 * 与直连/中继），选中后开始传输；对端离线/未配对给可读原因，不要静默失败”+
 * 入口这一层只做三件事：把三份事实合成清单、把不能发的理由写在行里、把选中变成一次宿主命令。
 */
const TICKET_OK = 'sunday1:eyJpZCI6ImQxIn0'
const TICKET_RETIRED = 'sunday1:eyJpZCI6ImQyIn0'

function seedDevices(): void {
  localStorage.setItem('sunday.p2p.devices', JSON.stringify([
    { id: 'd1', name: '手机', ticket: TICKET_OK },
    { id: 'd2', name: '平板', ticket: TICKET_RETIRED },
  ]))
}

function host(invoke: ReturnType<typeof vi.fn>) {
  return mount(SendToDeviceMenu, {
    props: { path: 'C:/work/报告.pdf', name: '报告.pdf', size: 2048, invoke },
  })
}

beforeEach(() => {
  localStorage.clear()
  seedDevices()
})

describe('send to device entry', () => {
  it('lists trusted devices with their online state and channel', async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === 'p2p_devices') return { devices: [{ id: 'd1', name: '手机' }, { id: 'd2', name: '平板' }] }
      if (command === 'p2p_status') return { devices: [{ id: 'd1', name: '手机', path: 'direct' }] }
      return {}
    })
    const wrapper = host(invoke)
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('手机')
    expect(text).toContain('在线 · 直连')
    // 名单里有、但此刻不在线：理由写在行里，不是灰了就算。
    expect(text).toContain('离线')
    expect(wrapper.find('[data-send-device="d2"]').attributes('disabled')).toBeDefined()
  })

  it('says why an unpaired device cannot receive', async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === 'p2p_devices') return { devices: [] }
      if (command === 'p2p_status') return { devices: [{ id: 'd9', name: '陌生设备', path: 'relay' }] }
      return {}
    })
    const wrapper = host(invoke)
    await flushPromises()
    expect(wrapper.text()).toContain('未配对')
    expect(wrapper.find('[data-send-device="d9"]').attributes('disabled')).toBeDefined()
  })

  it('starts the transfer with the ticket this machine holds', async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === 'p2p_devices') return { devices: [{ id: 'd1', name: '手机' }] }
      if (command === 'p2p_status') return { devices: [{ id: 'd1', name: '手机', path: 'direct' }] }
      if (command === 'p2p_send_file') return { started: true, source: 'C:/work/报告.pdf' }
      return {}
    })
    const wrapper = host(invoke)
    await flushPromises()
    await wrapper.find('[data-send-device="d1"]').trigger('click')
    await flushPromises()
    expect(invoke).toHaveBeenCalledWith('p2p_send_file', {
      path: 'C:/work/报告.pdf',
      ticket: TICKET_OK,
      name: '报告.pdf',
    })
    expect(wrapper.emitted('sent')?.[0]?.[0]).toMatchObject({ deviceId: 'd1', path: 'C:/work/报告.pdf' })
  })

  it('does not pretend it can send outside the desktop app', async () => {
    const wrapper = mount(SendToDeviceMenu, { props: { path: 'C:/work/a.txt' } })
    await flushPromises()
    expect(wrapper.text()).toContain('需要在桌面应用里使用')
  })

  it('shows the empty state when nothing is paired', async () => {
    localStorage.clear()
    const invoke = vi.fn(async (command: string) => {
      if (command === 'p2p_devices') return { devices: [] }
      if (command === 'p2p_status') return { devices: [] }
      return {}
    })
    const wrapper = host(invoke)
    await flushPromises()
    expect(wrapper.text()).toContain('还没有配对的设备')
  })
})

describe('dispatch helpers', () => {
  it('picks the ticket that belongs to the device, never another one', () => {
    const devices = [
      { id: 'd1', name: '手机', ticket: TICKET_OK },
      { id: 'd2', name: '平板', ticket: TICKET_RETIRED },
    ]
    expect(ticketForDevice(devices, 'd2')).toBe(TICKET_RETIRED)
    expect(ticketForDevice(devices, 'missing')).toBe('')
  })

  it('refuses to dial a device we have no ticket for', () => {
    const target = { id: 'd1', name: '手机', trusted: true, online: true, path: 'direct' as const }
    expect(sendTargetReason(target, { path: 'C:/a.txt' }, '')).toContain('地址票')
    expect(sendTargetReason(target, { path: 'C:/a.txt' }, TICKET_OK)).toBe('')
  })

  it('only carries the file name when the caller gave one', () => {
    expect(sendArgs({ path: 'C:/a.txt', ticket: TICKET_OK })).toEqual({ path: 'C:/a.txt', ticket: TICKET_OK })
    expect(sendArgs({ path: 'C:/a.txt', ticket: TICKET_OK, name: ' 对端名.txt ' })).toEqual({
      path: 'C:/a.txt',
      ticket: TICKET_OK,
      name: '对端名.txt',
    })
  })

  it('surfaces a refused start instead of reporting success', async () => {
    const invoke = vi.fn(async () => ({ started: false, reason: '找不到这个文件' }))
    await expect(sendFileToDevice(invoke, { path: 'C:/a.txt', ticket: TICKET_OK })).rejects.toThrow('找不到这个文件')
  })

  it('keeps the source for the panel retry', () => {
    const sources = rememberSendSource({}, 't-1', 'C:/work/a.bin')
    expect(sources).toEqual({ 't-1': 'C:/work/a.bin' })
    // 没有 id 或没有路径时不要造出空映射。
    expect(rememberSendSource(sources, '', 'C:/b.bin')).toBe(sources)
  })

  it('records the source in the window registry so any entry point can retry', () => {
    // user:“失败可重试”+(发起入口可能是资料库/预览器/设备页，面板必须能从一张共享表里
    // 找到源文件；写进临时对象等于没记)。
    expect(trackSendSource('t-88', 'C:/work/b.bin')['t-88']).toBe('C:/work/b.bin')
    expect(windowSendSources()['t-88']).toBe('C:/work/b.bin')
    // 缺 id 或缺路径时不要往表里塞空记录。
    const before = Object.keys(windowSendSources()).length
    trackSendSource('', 'C:/c.bin')
    trackSendSource('t-89', '')
    expect(Object.keys(windowSendSources()).length).toBe(before)
  })

  it('marks ticket availability when merging the picker list', () => {
    const targets = mergeTransferTargets(
      [{ id: 'd1', name: '手机' }, { id: 'd2', name: '平板' }],
      [{ id: 'd1', path: 'direct' }],
      (id) => id === 'd1',
    )
    expect(targets[0]).toMatchObject({ id: 'd1', hasTicket: true })
    expect(targets[1]).toMatchObject({ id: 'd2', hasTicket: false })
  })
})
