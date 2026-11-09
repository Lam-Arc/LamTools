import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CoreGeneralEditor from '../src/components/CoreGeneralEditor.vue'
import { coreSendBehaviorMode, setCoreSendBehaviorMode } from '../src/composables'
import { useSplitPreviewPreference } from '../src/split/previewPreference'

function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>((done) => { resolve = done })
  return { promise, resolve }
}

type RequestRpc = (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>

function createRequestRpc(initial: Record<string, string> = {}) {
  const stored: Record<string, string> = { proxy: '', no_proxy: '', ca_cert: '', ...initial }
  const power = { enabled: false }
  const askAutoContinue = { enabled: false }
  // The backend default is「开着，4 GB」, so an unset namespace reports nothing.
  const memoryResume: { enabled?: boolean; threshold_gb?: number } = {}
  const sendBehavior: { mode?: string } = {}
  return {
    stored,
    power,
    askAutoContinue,
    memoryResume,
    sendBehavior,
    rpc: vi.fn<RequestRpc>(async (method, params) => {
      if (method === 'settings.get') {
        const namespace = params?.namespace
        if (namespace === 'core.keepAwake') return { namespace, value: { ...power } }
        if (namespace === 'core.askAutoContinue') return { namespace, value: { ...askAutoContinue } }
        if (namespace === 'core.memoryResume') return { namespace, value: { ...memoryResume } }
        if (namespace === 'core.sendBehavior') return { namespace, value: { ...sendBehavior } }
        return { namespace: 'core.network', value: { ...stored } }
      }
      if (method === 'settings.update') {
        const value = (params?.value || {}) as Record<string, unknown>
        if (params?.namespace === 'core.keepAwake') {
          power.enabled = !!value.enabled
          return { namespace: 'core.keepAwake', value: { ...power } }
        }
        if (params?.namespace === 'core.askAutoContinue') {
          askAutoContinue.enabled = !!value.enabled
          return { namespace: 'core.askAutoContinue', value: { ...askAutoContinue } }
        }
        if (params?.namespace === 'core.memoryResume') {
          if (value.enabled !== undefined) memoryResume.enabled = !!value.enabled
          if (typeof value.threshold_gb === 'number') memoryResume.threshold_gb = value.threshold_gb
          return { namespace: 'core.memoryResume', value: { ...memoryResume } }
        }
        if (params?.namespace === 'core.sendBehavior') {
          sendBehavior.mode = String(value.mode || '')
          return { namespace: 'core.sendBehavior', value: { ...sendBehavior } }
        }
        const text = value as Record<string, string>
        if (text.proxy && !/^https?:\/\/[^\s]+$/.test(text.proxy)) {
          throw new Error('代理地址必须是形如 http://127.0.0.1:7890 的完整地址')
        }
        Object.assign(stored, text)
        return { namespace: 'core.network', value: { ...stored } }
      }
      return {}
    }),
  }
}

async function mountEditor(
  initial: Record<string, string> = {},
  props: Record<string, unknown> = {},
) {
  const { rpc, stored, power, askAutoContinue, memoryResume, sendBehavior } = createRequestRpc(initial)
  const wrapperMounted = mount(CoreGeneralEditor, { props: { requestRpc: rpc, ...props } })
  await flushPromises()
  return { wrapper: wrapperMounted, rpc, stored, power, askAutoContinue, memoryResume, sendBehavior }
}

describe('CoreGeneralEditor', () => {
  it('renders the general entries under a 通用 title', async () => {
    const { wrapper } = await mountEditor()
    expect(wrapper.get('h1').text()).toBe('通用')
    const titles = wrapper.findAll('.subhead-title').map((node) => node.text())
    // user:“支持自定义 Assistant 显示名称和头像”+(通用设置新增一张 Assistant 显示卡片)
    // user:“设置中可调消息发送后直接引导或排队，默认直接引导”+(通用设置新增一张消息发送卡片)
    expect(titles).toEqual(['界面语言', 'HTTP 代理', '不使用代理的地址', '自定义证书', '提问自动继续', 'Enter 发送方式', 'Assistant 显示', '实验性功能'])
    expect(wrapper.findAll('.setting-card')).toHaveLength(8)
  })

  it('loads the stored routing settings into the fields', async () => {
    const { wrapper } = await mountEditor({ proxy: 'http://127.0.0.1:7890', no_proxy: 'localhost' })
    const inputs = wrapper.findAll('input')
    expect((inputs[0].element as HTMLInputElement).value).toBe('http://127.0.0.1:7890')
    expect((inputs[1].element as HTMLInputElement).value).toBe('localhost')
  })

  it('saves only the edited field and reports it saved', async () => {
    const { wrapper, rpc, stored } = await mountEditor()
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('  http://127.0.0.1:7890  ')
    await wrapper.findAll('.subhead-actions button')[1].trigger('click')
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('settings.update', {
      namespace: 'core.network',
      value: { proxy: 'http://127.0.0.1:7890' },
    })
    expect(stored.proxy).toBe('http://127.0.0.1:7890')
    expect((inputs[0].element as HTMLInputElement).value).toBe('http://127.0.0.1:7890')
    expect(wrapper.text()).toContain('已保存')
  })

  it('surfaces the backend rejection and does not claim a save', async () => {
    const { wrapper, stored } = await mountEditor()
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('127.0.0.1:7890')
    await wrapper.findAll('.subhead-actions button')[1].trigger('click')
    await flushPromises()

    expect(wrapper.get('.general-error').text()).toContain('代理地址必须是形如')
    expect(wrapper.text()).not.toContain('已保存')
    expect(stored.proxy).toBe('')
  })

  it('clears a field by saving an empty value', async () => {
    const { wrapper, rpc } = await mountEditor({ no_proxy: 'localhost,127.0.0.1' })
    const inputs = wrapper.findAll('input')
    await inputs[1].setValue('')
    // The second card's 保存 is its only action button.
    await wrapper.findAll('.subhead-actions button')[2].trigger('click')
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('settings.update', {
      namespace: 'core.network',
      value: { no_proxy: '' },
    })
  })

  it('hides the keep-awake switch off Windows and shows it on Windows', async () => {
    const { wrapper } = await mountEditor()
    expect(wrapper.text()).not.toContain('保持电脑运行')
    // The host-memory reading exists on Windows and Linux only.
    expect(wrapper.text()).not.toContain('内存中断自动续跑')

    const { wrapper: onWindows } = await mountEditor({}, { platform: 'windows' })
    expect(onWindows.text()).toContain('保持电脑运行')
    expect(onWindows.findAll('.setting-card')).toHaveLength(10)
  })

  it('persists the keep-awake toggle', async () => {
    const { wrapper, rpc, power } = await mountEditor({}, { platform: 'windows' })
    const toggle = wrapper.get('[aria-label="保持电脑运行"]')
    await toggle.setValue(true)
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('settings.update', {
      namespace: 'core.keepAwake',
      value: { enabled: true },
    })
    expect(power.enabled).toBe(true)
    expect((toggle.element as HTMLInputElement).checked).toBe(true)
  })

  it('persists the unattended ask auto-continue toggle', async () => {
    const { wrapper, rpc, askAutoContinue } = await mountEditor()
    const toggle = wrapper.get('[aria-label="提问自动继续"]')
    await toggle.setValue(true)
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('settings.update', {
      namespace: 'core.askAutoContinue',
      value: { enabled: true },
    })
    expect(askAutoContinue.enabled).toBe(true)
    expect((toggle.element as HTMLInputElement).checked).toBe(true)
  })

  // user:“直接enter是引导还是排队的切换在设置通用页面中加上”+
  // (开关即普通 Enter 的落点：开=直接引导、关=排队；切换立即写 settings 命名空间并同步
  //   共享单例，写失败退回最后一次确认保存的值，连点时以最后一次意图为准)。
  function findSendBehaviorSwitch(wrapper: ReturnType<typeof mount>) {
    const toggle = wrapper.get('[aria-label="Enter 直接引导"]')
    expect(toggle.attributes('role'), 'Enter 发送方式开关').toBe('switch')
    return toggle
  }

  it('renders the Enter switch in the default guide mode', async () => {
    setCoreSendBehaviorMode('guide')
    const { wrapper } = await mountEditor()
    const toggle = findSendBehaviorSwitch(wrapper)
    expect((toggle.element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.get('[data-send-behavior-summary]').text()).toContain('Enter 直接引导')
    setCoreSendBehaviorMode('guide')
  })

  it('persists the Enter switch and updates the shared mode', async () => {
    setCoreSendBehaviorMode('guide')
    const { wrapper, rpc, sendBehavior } = await mountEditor()
    const toggle = findSendBehaviorSwitch(wrapper)

    await toggle.setValue(false)
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('settings.update', {
      namespace: 'core.sendBehavior',
      value: { mode: 'queue' },
    })
    expect(sendBehavior.mode).toBe('queue')
    expect(wrapper.text()).toContain('已保存')
    expect(wrapper.get('[data-send-behavior-summary]').text()).toContain('Ctrl+Enter 直接引导')

    await toggle.setValue(true)
    await flushPromises()
    expect(sendBehavior.mode).toBe('guide')
    expect(wrapper.get('[data-send-behavior-summary]').text()).toContain('Ctrl+Enter 排队')
    setCoreSendBehaviorMode('guide')
  })

  it('adopts the stored mode on load', async () => {
    setCoreSendBehaviorMode('guide')
    const initial = createRequestRpc()
    initial.sendBehavior.mode = 'queue'
    const wrapper = mount(CoreGeneralEditor, { props: { requestRpc: initial.rpc } })
    await flushPromises()

    expect((findSendBehaviorSwitch(wrapper).element as HTMLInputElement).checked).toBe(false)
    setCoreSendBehaviorMode('guide')
  })

  it('reverts the Enter switch when the write fails', async () => {
    setCoreSendBehaviorMode('guide')
    const { rpc } = createRequestRpc()
    const base = rpc.getMockImplementation()!
    let failNext = false
    rpc.mockImplementation(async (method, params) => {
      if (failNext && params?.namespace === 'core.sendBehavior') throw new Error('保存失败')
      return base(method, params)
    })
    const wrapper = mount(CoreGeneralEditor, { props: { requestRpc: rpc } })
    await flushPromises()

    failNext = true
    await findSendBehaviorSwitch(wrapper).setValue(false)
    await flushPromises()

    expect(wrapper.get('.general-error').text()).toContain('保存失败')
    expect(coreSendBehaviorMode.mode).toBe('guide')
    expect((findSendBehaviorSwitch(wrapper).element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.text()).not.toContain('已保存')
    setCoreSendBehaviorMode('guide')
  })

  it('keeps the last pick when the switch is toggled while a write is in flight', async () => {
    setCoreSendBehaviorMode('guide')
    const { rpc, sendBehavior } = createRequestRpc()
    const base = rpc.getMockImplementation()!
    const firstWrite = deferred()
    const written: string[] = []
    rpc.mockImplementation(async (method, params) => {
      if (method === 'settings.update' && params?.namespace === 'core.sendBehavior') {
        const value = (params.value || {}) as { mode?: string }
        written.push(String(value.mode))
        if (value.mode === 'queue') await firstWrite.promise
      }
      return base(method, params)
    })
    const wrapper = mount(CoreGeneralEditor, { props: { requestRpc: rpc } })
    await flushPromises()

    const toggle = findSendBehaviorSwitch(wrapper)
    await toggle.setValue(false)
    await toggle.setValue(true)
    // 第一次写入还卡着时不再并发写第二次，只记住最新意图。
    expect(written).toEqual(['queue'])

    firstWrite.resolve()
    await flushPromises()

    expect(written).toEqual(['queue', 'guide'])
    expect(sendBehavior.mode).toBe('guide')
    expect((toggle.element as HTMLInputElement).checked).toBe(true)
    setCoreSendBehaviorMode('guide')
  })

  it('does not let a late settings read overwrite a fresh pick', async () => {
    setCoreSendBehaviorMode('guide')
    const { rpc } = createRequestRpc()
    const base = rpc.getMockImplementation()!
    const read = deferred()
    rpc.mockImplementation(async (method, params) => {
      if (method === 'settings.get' && params?.namespace === 'core.sendBehavior') await read.promise
      return base(method, params)
    })
    const wrapper = mount(CoreGeneralEditor, { props: { requestRpc: rpc } })
    // 只等网络卡片读完（sendBehavior 的读库仍挂起），开关此时已可用。
    await flushPromises()

    await findSendBehaviorSwitch(wrapper).setValue(false)
    read.resolve()
    await flushPromises()

    expect(coreSendBehaviorMode.mode).toBe('queue')
    setCoreSendBehaviorMode('guide')
  })

  it('marks split file preview as experimental and remembers the switch', async () => {    localStorage.clear()
    useSplitPreviewPreference().setEnabled(true)
    localStorage.clear()
    const { wrapper } = await mountEditor()
    const card = wrapper.get('[data-experimental-preview]')
    expect(card.text()).toContain('实验性功能')
    expect(card.text()).toContain('实验性')
    const toggle = card.get('input[role="switch"]')
    expect((toggle.element as HTMLInputElement).checked).toBe(true)

    await toggle.setValue(false)
    expect(localStorage.getItem('lamtools:split-preview-experimental')).toBe('off')
    expect((toggle.element as HTMLInputElement).checked).toBe(false)
  })

  it('reverts a toggle when the write fails', async () => {
    const { rpc, askAutoContinue } = createRequestRpc()
    const base = rpc.getMockImplementation()!
    let failNext = false
    rpc.mockImplementation(async (method, params) => {
      if (failNext && method === 'settings.update') throw new Error('保存失败')
      return base(method, params)
    })
    const wrapper = mount(CoreGeneralEditor, { props: { requestRpc: rpc, platform: 'windows' } })
    await flushPromises()

    failNext = true
    const toggle = wrapper.get('[aria-label="提问自动继续"]')
    await toggle.setValue(true)
    await flushPromises()

    expect((toggle.element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.get('.general-error').text()).toContain('保存失败')
    expect(askAutoContinue.enabled).toBe(false)
  })
})

/** 按标题找卡片：卡片顺序会随功能增加变化，不能用 at(-1)。 */
function findSettingCard(wrapper: ReturnType<typeof mount>, title: string) {
  const card = wrapper.findAll('.setting-card').find(node => node.text().includes(title))
  expect(card, `设置卡片：${title}`).toBeDefined()
  return card!
}

describe('CoreGeneralEditor memory resume', () => {
  it('shows the card on Windows and Linux only', async () => {
    const { wrapper } = await mountEditor({}, { platform: 'linux' })
    expect(wrapper.text()).toContain('内存中断自动续跑')

    const { wrapper: mobile } = await mountEditor({}, { platform: 'mobile' })
    expect(mobile.text()).not.toContain('内存中断自动续跑')
  })

  it('reads an unset namespace as the backend default (on, 4 GB)', async () => {
    const { wrapper, rpc } = await mountEditor({}, { platform: 'windows' })

    expect(rpc).toHaveBeenCalledWith('settings.get', { namespace: 'core.memoryResume' })
    const card = findSettingCard(wrapper, '内存中断自动续跑')
    const toggle = card.get('input[role="switch"]')
    expect((toggle.element as HTMLInputElement).checked).toBe(true)
    expect((card.get('input[type="number"]').element as HTMLInputElement).value).toBe('4')
  })

  it('persists the toggle and the threshold', async () => {
    const { wrapper, rpc, memoryResume } = await mountEditor({}, { platform: 'windows' })
    const card = findSettingCard(wrapper, '内存中断自动续跑')

    await card.get('input[role="switch"]').setValue(false)
    await flushPromises()
    expect(rpc).toHaveBeenCalledWith('settings.update', {
      namespace: 'core.memoryResume',
      value: { enabled: false },
    })
    expect(memoryResume.enabled).toBe(false)

    await card.get('input[type="number"]').setValue('8')
    await card.findAll('.subhead-actions button')[1].trigger('click')
    await flushPromises()
    expect(rpc).toHaveBeenCalledWith('settings.update', {
      namespace: 'core.memoryResume',
      value: { threshold_gb: 8 },
    })
    expect(memoryResume.threshold_gb).toBe(8)
  })

  it('refuses a threshold outside the accepted range', async () => {
    const { wrapper, rpc } = await mountEditor({}, { platform: 'windows' })
    const card = findSettingCard(wrapper, '内存中断自动续跑')

    await card.get('input[type="number"]').setValue('0.1')
    await card.findAll('.subhead-actions button')[1].trigger('click')
    await flushPromises()

    expect(rpc).not.toHaveBeenCalledWith('settings.update', {
      namespace: 'core.memoryResume',
      value: { threshold_gb: 0.1 },
    })
    // The draft is rejected with the accepted range rather than silently saved.
    expect(wrapper.get('.general-error').text()).toContain('0.5')
  })
})
