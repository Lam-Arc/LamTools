import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CoreSubAgentEditor from '../src/components/CoreSubAgentEditor.vue'
import UiSelect from '../src/components/UiSelect.vue'

const models = [
  { id: 'model-record-a', model_id: 'model-a', display_name: 'Model A', capability: 'text' },
  { id: 'model-record-b', model_id: 'model-b', display_name: 'Model B', capability: 'multimodal' },
]

type RequestRpc = (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>

function settingsResponse() {
  return {
    settings: {
      default_multimodal_model: '',
      role_assignments: [{
        task_type: '代码审查',
        type: 'consider',
        model: 'model-a',
        reasoning_min: 'light',
        reasoning_max: 'xh',
      }],
    },
    effective_role_assignments: [
      {
        task_type: '代码审查',
        type: 'consider',
        model: 'model-a',
        reasoning_min: 'light',
        reasoning_max: 'high',
      },
      {
        task_type: '资料检索',
        type: 'execute',
        model: 'model-b',
        reasoning_min: 'off',
        reasoning_max: 'max',
      },
    ],
    role_assignments_inherited: false,
    effective_delegation_strategy: 'medium',
    delegation_strategy_inherited: true,
  }
}

function mountEditor(requestRpc: RequestRpc, scope: 'global' | 'project' = 'project') {
  return mount(CoreSubAgentEditor, {
    props: {
      requestRpc,
      models,
      scope,
      workRoot: scope === 'project' ? 'E:\\workspace' : '',
    },
  })
}

describe('CoreSubAgentEditor role assignments', () => {
  it('edits only project-local rows while describing the merged global baseline', async () => {
    const requestRpc = vi.fn<RequestRpc>(async (method: string) => {
      if (method === 'config.subagent.settings.get') return settingsResponse()
      if (method === 'config.subagent.guide.get') return { content: '', is_builtin: true }
      return {}
    })
    const wrapper = mountEditor(requestRpc)
    await flushPromises()

    expect(wrapper.findAll('[data-role-assignment-row]')).toHaveLength(1)
    expect(wrapper.text()).toContain('全局规则作为基线')
    expect(wrapper.text()).toContain('当前合并后 2 条')
    expect(wrapper.get('input[aria-label="任务类型 1"]').element).toHaveProperty('value', '代码审查')

    const selects = wrapper.findAllComponents(UiSelect)
    const reasoningOptions = selects[4].props('options') as Array<{ value: string; label: string }>
    const reasoningValues = reasoningOptions.map(option => option.value)
    const modelValues = (selects[3].props('options') as Array<{ value: string }>).map(option => option.value)
    expect(reasoningValues).toEqual(['off', 'light', 'medium', 'high', 'xhigh', 'max'])
    expect(reasoningValues).not.toContain('shallow')
    expect(reasoningOptions.map(option => option.label)).toEqual([
      'off（关闭）', 'light（轻）', 'medium（中）', 'high（高）', 'xhigh（超高）', 'max（极高）',
    ])
    expect(selects[5].props('modelValue')).toBe('xhigh')
    expect(modelValues).toEqual(['model-a', 'model-b'])

    await wrapper.get('[data-role-assignment-save]').trigger('click')
    await flushPromises()

    const saveCall = requestRpc.mock.calls.find(call => call[0] === 'config.subagent.settings.set')
    expect(saveCall?.[1]).toEqual({
      scope: 'project',
      work_root: 'E:\\workspace',
      settings: {
        role_assignments: [{
          task_type: '代码审查',
          type: 'consider',
          model: 'model-a',
          reasoning_min: 'light',
          reasoning_max: 'xhigh',
        }],
      },
    })
  })

  it('blocks empty and reversed reasoning ranges before saving', async () => {
    const requestRpc = vi.fn<RequestRpc>(async (method: string) => {
      if (method === 'config.subagent.settings.get') {
        return { settings: { default_multimodal_model: '', role_assignments: [] }, effective_role_assignments: [] }
      }
      if (method === 'config.subagent.guide.get') return { content: '', is_builtin: true }
      return {}
    })
    const wrapper = mountEditor(requestRpc, 'global')
    await flushPromises()

    await wrapper.get('[data-role-assignment-add]').trigger('click')
    await wrapper.get('[data-role-assignment-save]').trigger('click')
    expect(wrapper.get('[role="alert"]').text()).toContain('任务类型不能为空')
    expect(requestRpc.mock.calls.filter(call => call[0] === 'config.subagent.settings.set')).toHaveLength(0)

    await wrapper.get('input[aria-label="任务类型 1"]').setValue('规划')
    const selects = wrapper.findAllComponents(UiSelect)
    selects[4].vm.$emit('update:modelValue', 'high')
    selects[5].vm.$emit('update:modelValue', 'medium')
    await flushPromises()
    await wrapper.get('[data-role-assignment-save]').trigger('click')
    expect(wrapper.get('[role="alert"]').text()).toContain('最低思考强度不能高于最高思考强度')

    selects[5].vm.$emit('update:modelValue', 'xhigh')
    await flushPromises()
    await wrapper.get('[data-role-assignment-save]').trigger('click')
    await flushPromises()

    const saveCall = requestRpc.mock.calls.find(call => call[0] === 'config.subagent.settings.set')
    expect(saveCall?.[1]).toEqual({
      scope: 'global',
      settings: {
        role_assignments: [{
          task_type: '规划',
          type: 'consider',
          model: 'model-a',
          reasoning_min: 'high',
          reasoning_max: 'xhigh',
        }],
      },
    })
  })

  it('blocks duplicate task types and missing canonical model IDs', async () => {
    const duplicateRpc = vi.fn<RequestRpc>(async (method: string) => {
      if (method === 'config.subagent.settings.get') {
        return {
          settings: {
            role_assignments: [
              { task_type: 'Straße', type: 'consider', model: 'model-a', reasoning_min: 'off', reasoning_max: 'max' },
              { task_type: ' STRASSE ', type: 'execute', model: 'model-b', reasoning_min: 'off', reasoning_max: 'max' },
            ],
          },
          effective_role_assignments: [],
        }
      }
      if (method === 'config.subagent.guide.get') return { content: '', is_builtin: true }
      return {}
    })
    const duplicateWrapper = mountEditor(duplicateRpc, 'global')
    await flushPromises()
    await duplicateWrapper.get('[data-role-assignment-save]').trigger('click')
    expect(duplicateWrapper.get('[role="alert"]').text()).toContain('任务类型“STRASSE”重复')
    expect(duplicateRpc.mock.calls.filter(call => call[0] === 'config.subagent.settings.set')).toHaveLength(0)
    duplicateWrapper.unmount()

    const missingModelRpc = vi.fn<RequestRpc>(async (method: string) => {
      if (method === 'config.subagent.settings.get') {
        return {
          settings: {
            role_assignments: [
              { task_type: 'Review', type: 'consider', model: '', reasoning_min: 'off', reasoning_max: 'max' },
            ],
          },
          effective_role_assignments: [],
        }
      }
      if (method === 'config.subagent.guide.get') return { content: '', is_builtin: true }
      return {}
    })
    const missingModelWrapper = mountEditor(missingModelRpc, 'global')
    await flushPromises()
    await missingModelWrapper.get('[data-role-assignment-save]').trigger('click')
    expect(missingModelWrapper.get('[role="alert"]').text()).toContain('必须选择建议模型')
    expect(missingModelRpc.mock.calls.filter(call => call[0] === 'config.subagent.settings.set')).toHaveLength(0)
  })
})

describe('CoreSubAgentEditor delegation strategy', () => {
  it('offers all four policies and falls back to medium', async () => {
    const requestRpc = vi.fn<RequestRpc>(async (method: string) => {
      if (method === 'config.subagent.settings.get') {
        return {
          settings: { role_assignments: [] },
          effective_role_assignments: [],
          delegation_strategy_inherited: true,
        }
      }
      if (method === 'config.subagent.guide.get') return { content: '', is_builtin: true }
      return {}
    })
    const wrapper = mountEditor(requestRpc, 'global')
    await flushPromises()

    const strategySelect = wrapper.findAllComponents(UiSelect)
      .find(select => select.props('ariaLabel') === '子代理委派策略')
    expect(strategySelect?.props('modelValue')).toBe('medium')
    expect(strategySelect?.props('options')).toEqual([
      { value: 'forbidden', label: '禁止' },
      { value: 'low', label: '低' },
      { value: 'medium', label: '中（默认）' },
      { value: 'high', label: '高' },
    ])
    expect(wrapper.text()).toContain('当前使用内置默认：中')
    expect(wrapper.text()).toContain('保持当前委派策略')
  })

  it('shows a project-inherited effective policy and saves only the local override', async () => {
    const requestRpc = vi.fn<RequestRpc>(async (method: string) => {
      if (method === 'config.subagent.settings.get') {
        return {
          settings: { role_assignments: [] },
          effective_role_assignments: [],
          effective_delegation_strategy: 'low',
          global_delegation_strategy: 'low',
          delegation_strategy_inherited: true,
        }
      }
      if (method === 'config.subagent.guide.get') return { content: '', is_builtin: true }
      return {}
    })
    const wrapper = mountEditor(requestRpc)
    await flushPromises()

    const strategySelect = wrapper.findAllComponents(UiSelect)
      .find(select => select.props('ariaLabel') === '子代理委派策略')
    expect(strategySelect?.props('modelValue')).toBe('inherit')
    expect(strategySelect?.props('options')).toEqual([
      { value: 'inherit', label: '继承全局（当前：低）' },
      { value: 'forbidden', label: '禁止' },
      { value: 'low', label: '低' },
      { value: 'medium', label: '中（默认）' },
      { value: 'high', label: '高' },
    ])
    expect(wrapper.text()).toContain('当前继承全局有效策略：低')

    strategySelect?.vm.$emit('update:modelValue', 'high')
    await flushPromises()
    expect(wrapper.text()).toContain('主 Agent 负责决策指挥、任务分配、依赖协调、冲突调解、结果整合与最终验收')
    await wrapper.get('[data-delegation-strategy-save]').trigger('click')
    await flushPromises()

    const saveCall = requestRpc.mock.calls.find(call =>
      call[0] === 'config.subagent.settings.set'
      && (call[1]?.settings as Record<string, unknown> | undefined)?.delegation_strategy === 'high')
    expect(saveCall?.[1]).toEqual({
      scope: 'project',
      work_root: 'E:\\workspace',
      settings: { delegation_strategy: 'high' },
    })
  })

  it('can remove an existing project override and restore global inheritance', async () => {
    const requestRpc = vi.fn<RequestRpc>(async (method: string) => {
      if (method === 'config.subagent.settings.get') {
        return {
          settings: { role_assignments: [], delegation_strategy: 'high' },
          effective_role_assignments: [],
          effective_delegation_strategy: 'high',
          global_delegation_strategy: 'low',
          delegation_strategy_inherited: false,
        }
      }
      if (method === 'config.subagent.guide.get') return { content: '', is_builtin: true }
      return {}
    })
    const wrapper = mountEditor(requestRpc)
    await flushPromises()

    const strategySelect = wrapper.findAllComponents(UiSelect)
      .find(select => select.props('ariaLabel') === '子代理委派策略')
    expect(strategySelect?.props('modelValue')).toBe('high')
    expect(strategySelect?.props('options')?.[0]).toEqual({
      value: 'inherit',
      label: '继承全局（当前：低）',
    })

    strategySelect?.vm.$emit('update:modelValue', 'inherit')
    await flushPromises()
    expect(wrapper.text()).toContain('保存后将移除当前项目覆盖')
    await wrapper.get('[data-delegation-strategy-save]').trigger('click')
    await flushPromises()

    const unsetCall = requestRpc.mock.calls.find(call =>
      call[0] === 'config.subagent.settings.set'
      && (call[1]?.settings as Record<string, unknown> | undefined)?.delegation_strategy === null)
    expect(unsetCall?.[1]).toEqual({
      scope: 'project',
      work_root: 'E:\\workspace',
      settings: { delegation_strategy: null },
    })
  })
})
