import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'

import RemoteConnectionPanel from '../src/components/RemoteConnectionPanel.vue'

const { listen } = vi.hoisted(() => ({ listen: vi.fn() }))
vi.mock('@tauri-apps/api/event', () => ({ listen }))

const now = () => Math.floor(Date.now() / 1000)
const qr = (ticket: string) => ({ svg: `<svg data-ticket="${ticket}"></svg>` })
let wrapper: VueWrapper | undefined

function openPanel(invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown>) {
  vi.stubGlobal('__TAURI_INTERNALS__', { invoke })
  wrapper = mount(RemoteConnectionPanel, { props: { platform: 'desktop' } })
  return wrapper
}

function pushStatus(payload: Record<string, unknown>) {
  for (const [event, callback] of listen.mock.calls) {
    if (event === 'p2p-state') callback({ payload })
  }
}

afterEach(() => {
  wrapper?.unmount()
  vi.unstubAllGlobals()
  listen.mockClear()
  vi.restoreAllMocks()
})

// user:“三项全做”+(电脑换发配对码时，图片、倒计时和复制始终对应同一张码)。
it('updates the desktop pairing code on push and ignores a superseded QR render', async () => {
  const first = 'sunday2:first'
  const middle = 'sunday2:middle'
  const current = 'sunday2:current'
  let renderMiddle!: (result: ReturnType<typeof qr>) => void
  let status = { running: true, ticket: first, expiresAt: now() + 60, pairingCodeRevision: 1 }
  const writeText = vi.fn(async () => {})
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  const panel = openPanel(vi.fn(async (command, args) => {
    if (command === 'p2p_status') return status
    if (command === 'p2p_qr') {
      const ticket = String(args?.ticket)
      if (ticket === middle) return new Promise<ReturnType<typeof qr>>((resolve) => { renderMiddle = resolve })
      return qr(ticket)
    }
    return {}
  }))
  await flushPromises()
  expect(panel.find(`svg[data-ticket="${first}"]`).exists()).toBe(true)

  status = { running: true, ticket: middle, expiresAt: now() + 120, pairingCodeRevision: 2 }
  pushStatus({ running: true, pairingCodeRevision: 2 })
  await flushPromises()
  expect(panel.find(`svg[data-ticket="${first}"]`).exists()).toBe(false)
  status = { running: true, ticket: current, expiresAt: now() + 185, pairingCodeRevision: 3 }
  pushStatus({ running: true, pairingCodeRevision: 3 })
  await flushPromises()
  renderMiddle(qr(middle))
  await flushPromises()

  expect(panel.find(`svg[data-ticket="${current}"]`).exists()).toBe(true)
  expect(panel.get('[data-remote-ticket]').text()).toBe(current)
  const service = panel.get('[data-p2p-service-status]')
  expect(Number(service.text().match(/二维码 (\d+) 秒后失效/)?.[1])).toBeGreaterThanOrEqual(184)
  await panel.get('[data-p2p-copy]').trigger('click')
  expect(writeText).toHaveBeenCalledWith(current)

  status = { ...status, expiresAt: now() - 1, pairingCodeRevision: 4 }
  pushStatus({ running: true, pairingCodeRevision: 4 })
  await flushPromises()
  expect(panel.find('.pair-card__qr').exists()).toBe(false)
  expect(panel.find('[data-p2p-copy]').exists()).toBe(false)
  expect(service.text()).toContain('二维码已过期')
})

it('shows QR rendering errors and can copy the code or retry rendering the same code', async () => {
  const ticket = 'sunday2:example'
  const writeText = vi.fn(async () => {})
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  let fail = true
  const invoke = vi.fn(async (command: string, args?: Record<string, unknown>) => {
    if (command === 'p2p_status') return { running: true, ticket, expiresAt: now() + 120 }
    if (command === 'p2p_qr') {
      if (fail) throw new Error('encoder unavailable')
      return qr(String(args?.ticket))
    }
    return {}
  })
  const panel = openPanel(invoke)
  await flushPromises()

  expect(panel.get('[data-p2p-qr-error]').text()).toContain('二维码生成失败')
  await panel.get('[data-p2p-copy]').trigger('click')
  expect(writeText).toHaveBeenCalledWith(ticket)

  fail = false
  await panel.get('[data-p2p-qr-retry]').trigger('click')
  await flushPromises()
  expect(panel.find('[data-p2p-qr-error]').exists()).toBe(false)
  expect(panel.find(`svg[data-ticket="${ticket}"]`).exists()).toBe(true)
  expect(invoke.mock.calls.filter(([command]) => command === 'p2p_qr')).toEqual([
    ['p2p_qr', { ticket }],
    ['p2p_qr', { ticket }],
  ])
})

it('keeps one-time service controls separate from the startup preference', async () => {
  let serving = false
  let autoConnect = false
  const ticket = 'sunday2:example'
  const invoke = vi.fn(async (command: string, args?: Record<string, unknown>) => {
    if (command === 'get_api_base') return 'http://127.0.0.1:8787'
    if (command === 'p2p_status') return { running: serving, autoConnect, ticket: serving ? ticket : '', expiresAt: serving ? now() + 120 : 0 }
    if (command === 'p2p_ticket') {
      serving = true
      return { ticket, expiresAt: now() + 120 }
    }
    if (command === 'p2p_qr') return qr(String(args?.ticket))
    if (command === 'p2p_config_set') {
      autoConnect = args?.autoConnect === true
      return { autoConnect }
    }
    if (command === 'p2p_serve_stop') serving = false
    return {}
  })
  const panel = openPanel(invoke)
  await flushPromises()
  const preference = panel.get<HTMLInputElement>('[data-p2p-autoconnect]')
  await panel.get('[data-p2p-generate]').trigger('click')
  await flushPromises()
  expect(preference.element.checked).toBe(false)

  await preference.setValue(true)
  await flushPromises()
  await panel.get('[data-p2p-stop]').trigger('click')
  await flushPromises()
  expect(preference.element.checked).toBe(true)
  expect(panel.find('[data-remote-ticket]').exists()).toBe(false)
  expect(invoke.mock.calls.filter(([command]) => command === 'p2p_config_set')).toEqual([
    ['p2p_config_set', { autoConnect: true }],
  ])
})

// user:“修完之后，去找远程连接/跨网通信/跨设备使用中最不稳定/问题最大的地方 修掉，并列出候选”+
// (中继卡住后，桌面设备页会收到明确的启动失败状态，并能再次尝试)。
it('shows startup timeout pushed by the desktop and leaves the pairing action available', async () => {
  const panel = openPanel(async () => ({}))
  await flushPromises()

  const error = '远程访问启动超时，请检查网络或中继设置后重试'
  pushStatus({ running: false, error, view: 'offline', reason: 'start_failed' })
  await flushPromises()

  expect(panel.get('[data-p2p-service-error]').text()).toContain(error)
  expect(panel.get<HTMLButtonElement>('[data-p2p-generate]').element.disabled).toBe(false)
})

// user:“全部处理并继续寻找”+(面板换过当前设备后，重试仍按原传输编号执行)。
it('retries the original transfer by ID even when another device is selected', async () => {
  const invoke = vi.fn(async (command: string) => {
    if (command === 'p2p_status') return {
      running: true,
      peer: 'other-device',
      transfers: [{
        id: 'original-transfer',
        direction: 'send',
        name: 'sample.zip',
        source: 'C:/samples/sample.zip',
        total: 1000,
        transferred: 500,
        state: 'failed',
      }],
    }
    return {}
  })
  const panel = openPanel(invoke)
  await flushPromises()
  await panel.get('[data-transfer-retry="original-transfer"]').trigger('click')
  await flushPromises()
  expect(invoke).toHaveBeenCalledWith('p2p_retry_transfer', { id: 'original-transfer' })
  expect(invoke.mock.calls.some(([name]) => name === 'p2p_send_file')).toBe(false)
})
