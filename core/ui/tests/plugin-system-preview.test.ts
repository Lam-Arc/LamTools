import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import CorePluginSystemEditor from '../src/components/CorePluginSystemEditor.vue'
import CoreConfirmDialog from '../src/components/CoreConfirmDialog.vue'

const BASE_PLUGIN = {
  name: 'hello',
  version: '0.1.0',
  description: '',
  enabled: true,
  scope: 'global',
  root: '/plugins/hello',
}

function plugin(overrides: Record<string, unknown> = {}) {
  return { ...BASE_PLUGIN, ...overrides }
}

function makeRpc(list: unknown[] = [plugin()]) {
  return vi.fn(async (method: string) => {
    if (method === 'plugin.system.list') return { plugins: list, errors: [] }
    return {}
  })
}

const wrappers: Array<ReturnType<typeof mount>> = []

function mountEditor(rpc: ReturnType<typeof makeRpc>, attach = false) {
  const wrapper = mount(CorePluginSystemEditor, {
    props: { requestRpc: rpc },
    ...(attach ? { attachTo: document.body } : {}),
  })
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  while (wrappers.length) wrappers.pop()?.unmount()
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('plugin system preview', () => {
  it('lists the minimal plugin returned by the new host', async () => {
    const rpc = makeRpc()
    const wrapper = mountEditor(rpc)

    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('plugin.system.list', {})
    expect(wrapper.text()).toContain('hello')
    expect(wrapper.text()).toContain('0.1.0')
    expect(wrapper.find('.plugin-card[data-plugin="hello"]').exists()).toBe(true)
  })

  it('disables an enabled plugin and refreshes the list', async () => {
    const rpc = makeRpc()
    const wrapper = mountEditor(rpc)
    await flushPromises()

    await wrapper.find('button[data-toggle-for="hello"]').trigger('click')
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('plugin.system.disable', { name: 'hello' })
    // 四次：挂载拉列表 + 内嵌 settings 区贡献仓库拉一次 + 开关后刷新
    // + ensureContributions 重新读一次启用集合。
    expect(rpc.mock.calls.filter(([method]) => method === 'plugin.system.list')).toHaveLength(4)
  })

  it('opens the config panel from the plugin card', async () => {
    const rpc = makeRpc()
    const wrapper = mountEditor(rpc)
    await flushPromises()

    await wrapper.find('button[data-config-for="hello"]').trigger('click')
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('plugin.system.config.get', { name: 'hello' })
    expect(wrapper.text()).toContain('这个插件没有可配置项')
  })

  it('summarizes declared capabilities and declaration errors as chips', async () => {
    const rpc = vi.fn(async (method: string) => {
      if (method !== 'plugin.system.list') return {}
      return {
        plugins: [
          plugin({
            capabilities: {
              tools: ['demo_echo'],
              skills: ['demo-skill'],
              hooks: [],
              mcp: [],
              commands: [],
              context: [],
            },
          }),
          plugin({ name: 'broken', capability_error: 'tool is missing handler' }),
        ],
        errors: [],
      }
    })
    const wrapper = mountEditor(rpc as ReturnType<typeof makeRpc>)

    await flushPromises()

    const card = wrapper.get('.plugin-card[data-plugin="hello"]')
    expect(card.text()).toContain('工具 1')
    expect(card.text()).toContain('技能 1')
    expect(wrapper.get('.plugin-card[data-plugin="broken"]').text()).toContain('声明错误')
  })

  it('filters by plugin metadata, capability names and enabled state', async () => {
    const rpc = makeRpc([
      plugin({
        name: 'alpha',
        description: '视频处理',
        capabilities: {
          tools: ['video_probe'],
          skills: [],
          hooks: [],
          mcp: [],
          commands: [],
          context: [],
        },
      }),
      plugin({ name: 'beta', description: '笔记工具' }),
      plugin({ name: 'gamma', description: '旧版导入', enabled: false }),
    ])
    const wrapper = mountEditor(rpc)
    await flushPromises()

    await wrapper.get('[data-plugin-search]').setValue('video_probe')
    await flushPromises()
    expect(wrapper.find('.plugin-card[data-plugin="alpha"]').exists()).toBe(true)
    expect(wrapper.find('.plugin-card[data-plugin="beta"]').exists()).toBe(false)

    await wrapper.get('[data-plugin-search]').setValue('')
    await wrapper.get('[data-filter="disabled"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.plugin-card[data-plugin="gamma"]').exists()).toBe(true)
    expect(wrapper.find('.plugin-card[data-plugin="alpha"]').exists()).toBe(false)
    expect(wrapper.get('[data-filter="disabled"]').attributes('aria-pressed')).toBe('true')
  })

  it('shows a first-run empty state and a no-match state', async () => {
    const empty = mountEditor(makeRpc([]))
    await flushPromises()
    expect(empty.text()).toContain('还没有插件')
    expect(empty.find('[data-install-toggle]').exists()).toBe(true)

    const wrapper = mountEditor(makeRpc())
    await flushPromises()
    await wrapper.get('[data-plugin-search]').setValue('nothing-matches')
    await flushPromises()
    expect(wrapper.text()).toContain('没有匹配的插件')
    await wrapper.get('[data-clear-filters]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.plugin-card[data-plugin="hello"]').exists()).toBe(true)
  })

  it('queries the behavior table from the diagnostics drawer', async () => {
    const rpc = vi.fn(async (method: string) => {
      if (method === 'plugin.system.list') return { plugins: [plugin()], errors: [] }
      if (method === 'plugin.system.behavior') {
        return {
          entries: [{ module: 'plugin_system.host', ownership: 'kernel', layer: 'kernel' }],
          total_matches: 1,
        }
      }
      return {}
    })
    const wrapper = mountEditor(rpc as ReturnType<typeof makeRpc>)
    await flushPromises()

    await wrapper.get('[data-diagnostics-toggle]').trigger('click')
    expect(wrapper.get('[data-diagnostics-toggle]').attributes('aria-expanded')).toBe('true')
    await wrapper.get('.behavior-input').setValue('plugin_system.host')
    await wrapper.get('.behavior-form').trigger('submit')
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('plugin.system.behavior', { query: 'plugin_system.host' })
    expect(wrapper.text()).toContain('内核（不可替换）')
    expect(wrapper.text()).toContain('1 条匹配')
  })

  it('shows a retryable error state when the plugin list cannot load', async () => {
    const rpc = vi.fn(async (method: string) => {
      if (method === 'plugin.system.list') throw new Error('backend offline')
      return {}
    })
    const wrapper = mountEditor(rpc as ReturnType<typeof makeRpc>)
    await flushPromises()

    expect(wrapper.text()).toContain('无法加载插件')
    expect(wrapper.text()).toContain('backend offline')
    const callsBefore = rpc.mock.calls.filter(([method]) => method === 'plugin.system.list').length
    await wrapper.get('[data-retry-load]').trigger('click')
    await flushPromises()
    expect(
      rpc.mock.calls.filter(([method]) => method === 'plugin.system.list').length,
    ).toBeGreaterThan(callsBefore)
  })

  it('surfaces a failed backend with a retry action', async () => {
    const rpc = makeRpc([
      plugin({
        available: false,
        backend: { state: 'failed', error: { message: 'boom' } },
      }),
    ])
    const wrapper = mountEditor(rpc)
    await flushPromises()

    const card = wrapper.get('.plugin-card[data-plugin="hello"]')
    expect(card.text()).toContain('启动失败')
    expect(card.text()).toContain('boom')
    await card.get('[data-retry-for="hello"]').trigger('click')
    await flushPromises()
    expect(rpc).toHaveBeenCalledWith('plugin.system.enable', { name: 'hello' })
  })

  it('asks for confirmation before uninstalling and keeps the data directory', async () => {
    const rpc = makeRpc()
    const wrapper = mountEditor(rpc, true)
    await flushPromises()

    await wrapper.get('[data-uninstall-for="hello"]').trigger('click')
    await flushPromises()

    expect(rpc).not.toHaveBeenCalledWith('plugin.system.uninstall', expect.anything())
    const dialog = wrapper.findComponent(CoreConfirmDialog)
    expect(dialog.props('open')).toBe(true)
    expect(dialog.props('detail')).toContain('hello')
    expect(dialog.props('detail')).toContain('data 目录会保留')

    dialog.vm.$emit('confirm')
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('plugin.system.uninstall', { name: 'hello', keep_data: true })
  })
})
