import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CoreGeneralEditor from '../src/components/CoreGeneralEditor.vue'

type RequestRpc = (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>

function createRequestRpc(initial: Record<string, string> = {}) {
  const stored: Record<string, string> = { proxy: '', no_proxy: '', ca_cert: '', ...initial }
  const power = { enabled: false }
  const askAutoContinue = { enabled: false }
  // The backend default is「开着，4 GB」, so an unset namespace reports nothing.
  const memoryResume: { enabled?: boolean; threshold_gb?: number } = {}
  return {
    stored,
    power,
    askAutoContinue,
    memoryResume,
    rpc: vi.fn<RequestRpc>(async (method, params) => {
      if (method === 'settings.get') {
        const namespace = params?.namespace
        if (namespace === 'core.keepAwake') return { namespace, value: { ...power } }
        if (namespace === 'core.askAutoContinue') return { namespace, value: { ...askAutoContinue } }
        if (namespace === 'core.memoryResume') return { namespace, value: { ...memoryResume } }
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
  const { rpc, stored, power, askAutoContinue, memoryResume } = createRequestRpc(initial)
  const wrapper = mount(CoreGeneralEditor, { props: { requestRpc: rpc, ...props } })
  await flushPromises()
  return { wrapper, rpc, stored, power, askAutoContinue, memoryResume }
}

describe('CoreGeneralEditor', () => {
  it('renders the general entries under a 通用 title', async () => {
    const { wrapper } = await mountEditor()
    expect(wrapper.get('h1').text()).toBe('通用')
    const titles = wrapper.findAll('.subhead-title').map((node) => node.text())
    expect(titles).toEqual(['HTTP 代理', '不使用代理的地址', '自定义证书', '提问自动继续'])
    expect(wrapper.findAll('.setting-card')).toHaveLength(4)
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
    expect(onWindows.findAll('.setting-card')).toHaveLength(6)
  })

  it('persists the keep-awake toggle', async () => {
    const { wrapper, rpc, power } = await mountEditor({}, { platform: 'windows' })
    const toggle = wrapper.get('[aria-label="保持电脑运行"]')
    await toggle.trigger('click')
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('settings.update', {
      namespace: 'core.keepAwake',
      value: { enabled: true },
    })
    expect(power.enabled).toBe(true)
    expect(toggle.classes()).toContain('is-on')
  })

  it('persists the unattended ask auto-continue toggle', async () => {
    const { wrapper, rpc, askAutoContinue } = await mountEditor()
    const toggle = wrapper.get('[aria-label="提问自动继续"]')
    await toggle.trigger('click')
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('settings.update', {
      namespace: 'core.askAutoContinue',
      value: { enabled: true },
    })
    expect(askAutoContinue.enabled).toBe(true)
    expect(toggle.classes()).toContain('is-on')
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
    await toggle.trigger('click')
    await flushPromises()

    expect(toggle.classes()).not.toContain('is-on')
    expect(wrapper.get('.general-error').text()).toContain('保存失败')
    expect(askAutoContinue.enabled).toBe(false)
  })
})

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
    const card = wrapper.findAll('.setting-card').at(-1)!
    const toggle = card.get('.toggle-btn')
    expect(toggle.attributes('aria-pressed')).toBe('true')
    expect((card.get('input').element as HTMLInputElement).value).toBe('4')
  })

  it('persists the toggle and the threshold', async () => {
    const { wrapper, rpc, memoryResume } = await mountEditor({}, { platform: 'windows' })
    const card = wrapper.findAll('.setting-card').at(-1)!

    await card.get('.toggle-btn').trigger('click')
    await flushPromises()
    expect(rpc).toHaveBeenCalledWith('settings.update', {
      namespace: 'core.memoryResume',
      value: { enabled: false },
    })
    expect(memoryResume.enabled).toBe(false)

    await card.get('input').setValue('8')
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
    const card = wrapper.findAll('.setting-card').at(-1)!

    await card.get('input').setValue('0.1')
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
