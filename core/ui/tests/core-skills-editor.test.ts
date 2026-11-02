// user:“skill 界面也做成瀑布流，并分组管理”+技能页验收测试：
// 卡片瀑布流渲染、分组筛选、卡片上改分组、分组管理面板（新建/删除）。
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CoreSkillsEditor from '../src/components/CoreSkillsEditor.vue'
import CoreConfirmDialog from '../src/components/CoreConfirmDialog.vue'
import UiSelect from '../src/components/UiSelect.vue'

const skillsPayload = {
  skills: [
    { name: 'alpha', description: 'Alpha skill', location: 'C:/skills/alpha', source: 'user', enabled: true, deletable: true, group: '写作' },
    { name: 'beta', description: 'Beta skill', location: 'C:/skills/beta', source: 'user', enabled: false, deletable: true, group: '' },
    { name: 'gamma', description: 'Gamma skill', location: '', source: 'core', enabled: true, deletable: false, group: '' },
  ],
  groups: ['写作'],
  total_count: 3,
  enabled_count: 2,
}

function makeRpc() {
  return vi.fn(async (method: string, _params?: Record<string, unknown>) => {
    if (method === 'skill.list') return skillsPayload
    return {}
  })
}

describe('CoreSkillsEditor masonry wall', () => {
  it('renders every skill as a card in the wall', async () => {
    const wrapper = mount(CoreSkillsEditor, { props: { requestRpc: makeRpc() } })
    await flushPromises()

    const cards = wrapper.findAll('[data-skill-card]')
    expect(cards).toHaveLength(3)
    const alpha = wrapper.get('[data-skill-card="alpha"]')
    expect(alpha.text()).toContain('Alpha skill')
    expect(alpha.classes()).not.toContain('is-disabled')
    expect(wrapper.get('[data-skill-card="beta"]').classes()).toContain('is-disabled')
    // 分组与来源都直接落在卡片上，不再按来源分节。
    expect(alpha.text()).toContain('写作')
  })

  it('filters the wall through group chips', async () => {
    const wrapper = mount(CoreSkillsEditor, { props: { requestRpc: makeRpc() } })
    await flushPromises()

    await wrapper.get('[data-skill-filter="g:写作"]').trigger('click')
    expect(wrapper.findAll('[data-skill-card]')).toHaveLength(1)
    expect(wrapper.find('[data-skill-card="beta"]').exists()).toBe(false)

    await wrapper.get('[data-skill-filter="ungrouped"]').trigger('click')
    const ungrouped = wrapper.findAll('[data-skill-card]')
    expect(ungrouped).toHaveLength(2)

    await wrapper.get('[data-skill-filter="all"]').trigger('click')
    expect(wrapper.findAll('[data-skill-card]')).toHaveLength(3)
  })

  it('assigns a group from the card select', async () => {
    const requestRpc = makeRpc()
    const wrapper = mount(CoreSkillsEditor, { props: { requestRpc } })
    await flushPromises()

    const betaCard = wrapper.get('[data-skill-card="beta"]')
    await betaCard.findComponent(UiSelect).vm.$emit('update:modelValue', '写作')
    await flushPromises()

    const call = requestRpc.mock.calls.find(([method]) => method === 'skill.group.assign')
    expect(call).toBeTruthy()
    expect(call![1]).toEqual({ name: 'beta', group: '写作' })
  })

  it('creates a group from the manager panel', async () => {
    const requestRpc = makeRpc()
    const wrapper = mount(CoreSkillsEditor, { props: { requestRpc } })
    await flushPromises()

    await wrapper.get('[data-open-group-manager]').trigger('click')
    const input = wrapper.get('[data-group-name-input]')
    await input.setValue('编程')
    await wrapper.get('[data-group-create]').trigger('click')
    await flushPromises()

    const call = requestRpc.mock.calls.find(([method]) => method === 'skill.group.create')
    expect(call).toBeTruthy()
    expect(call![1]).toEqual({ name: '编程' })
  })

  it('deletes a group through the confirm dialog', async () => {
    const requestRpc = makeRpc()
    const wrapper = mount(CoreSkillsEditor, { props: { requestRpc } })
    await flushPromises()

    await wrapper.get('[data-open-group-manager]').trigger('click')
    await wrapper.get('[data-group-delete="写作"]').trigger('click')
    // 页面上有删技能/删分组两个确认胶囊，这里要找打开着的那个。
    const dialog = wrapper.findAllComponents(CoreConfirmDialog).find((candidate) => candidate.props('open'))
    expect(dialog).toBeTruthy()
    dialog!.vm.$emit('confirm')
    await flushPromises()

    const call = requestRpc.mock.calls.find(([method]) => method === 'skill.group.delete')
    expect(call).toBeTruthy()
    expect(call![1]).toEqual({ name: '写作' })
  })
})
