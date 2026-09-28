import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CorePluginsEditor from '../src/components/CorePluginsEditor.vue'
import { createFakeTransport } from './fake-transport'

const transport = createFakeTransport()

function plugin(overrides: Record<string, unknown>) {
  return {
    name: 'plugin',
    version: '0.1.0',
    description: 'plugin',
    root: 'bundled://plugin',
    enabled: true,
    skills: [],
    hooks: [],
    mcp: [],
    tools: [],
    skill_names: [],
    hook_summary: [],
    dependencies: [],
    deps_status: 'none',
    config_schema: '',
    ...overrides,
  }
}

function mountEditor(plugins: Record<string, unknown>[]) {
  const rpc = vi.fn(async (method: string) => {
    if (method === 'plugin.list') return { plugins, errors: [] }
    if (method === 'config.models.list') return { models: [] }
    return {}
  })
  return mount(CorePluginsEditor, {
    props: { requestRpc: rpc, transport },
    global: { stubs: { Teleport: true } },
  })
}

describe('plugin tool inventory display', () => {
  it('counts only the tools the host reported and shows why the rest are absent', async () => {
    const wrapper = mountEditor([
      plugin({
        name: 'study',
        tools: [{
          path: 'bundled://study/tools.jsonc',
          tools: [
            { name: 'get_knowledge_net', permission: 'auto_allow' },
            { name: 'build_knowledge_net', permission: 'auto_allow' },
          ],
        }],
        tools_note: '',
      }),
      plugin({
        name: 'git',
        tools: [],
        tools_note: '移动端未装配：Android 没有 git 可执行文件，且项目目录不是仓库',
      }),
    ])
    await flushPromises()

    // The count comes from the host, and a zero is explained rather than bare.
    expect(wrapper.text()).toContain('2 工具')
    expect(wrapper.text()).toContain('0 工具')
    expect(wrapper.text()).toContain('移动端未装配：Android 没有 git 可执行文件，且项目目录不是仓库')
    expect(wrapper.findAll('.is-plugins-note')).toHaveLength(1)
  })

  it('renders no note when the host assembled every declared tool', async () => {
    const wrapper = mountEditor([
      plugin({
        name: 'study',
        tools: [{ path: 'bundled://study/tools.jsonc', tools: [{ name: 'notes', permission: 'auto_allow' }] }],
      }),
    ])
    await flushPromises()

    expect(wrapper.text()).toContain('1 工具')
    expect(wrapper.findAll('.is-plugins-note')).toHaveLength(0)
  })
})

describe('plugin platform classification', () => {
  it('groups by the class the host reported and reads 内置 from the payload', async () => {
    const wrapper = mountEditor([
      plugin({ name: 'websearch', platforms: 'universal', builtin: true }),
      plugin({ name: 'git', platforms: 'desktop', builtin: true }),
      plugin({ name: 'phone-thing', platforms: 'mobile', builtin: false }),
      // 未声明即通用，与宿主侧的默认一致（第三方插件不会因为没写而消失）。
      plugin({ name: 'community', builtin: false }),
    ])
    await flushPromises()

    const groups = wrapper.findAll('.provider-group')
    expect(groups.map(group => group.find('.provider-head strong').text()))
      .toEqual(['通用', '桌面端专用', '移动端专用'])
    const namesIn = (index: number) => groups[index]
      .findAll('.plugin-name-btn strong')
      .map(node => node.text())
    expect(namesIn(0)).toEqual(['websearch', 'community'])
    expect(namesIn(1)).toEqual(['git'])
    expect(namesIn(2)).toEqual(['phone-thing'])

    // 内置徽标与卸载按钮都读载荷里的 builtin，界面上不再存第二份内置名单。
    expect(groups[1].text()).toContain('内置')
    expect(groups[1].find('[aria-label="卸载"]').exists()).toBe(false)
    expect(groups[2].find('[aria-label="卸载"]').exists()).toBe(true)
  })

  it('shows no group for a class the host did not send', async () => {
    const wrapper = mountEditor([plugin({ name: 'study', platforms: 'universal' })])
    await flushPromises()

    expect(wrapper.findAll('.provider-group')).toHaveLength(1)
    expect(wrapper.find('.provider-head strong').text()).toBe('通用')
  })
})
