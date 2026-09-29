import { describe, expect, it } from 'vitest'
import {
  coreDeclaredThinkingLadder,
  coreModelSelectOptions,
  coreThinkingModeOptions,
  coreThinkingPayload,
  normalizeCoreThinkingMode,
  readStoredCoreShallowThinking,
  readStoredCoreThinkingMode,
  selectCoreExecutionModel,
  writeStoredCoreShallowThinking,
  writeStoredCoreThinkingMode,
} from '../src/composer/execution'

describe('core composer execution helpers', () => {
  it('builds grouped model options and resolves the active execution model', () => {
    const providers = [{ id: 'provider-1', name: 'Provider One' }]
    const models = [
      { id: 'model-default', provider_id: 'provider-1', model_id: 'k2', display_name: 'Kimi K2.6' },
      { id: 'model-other', provider_id: 'provider-1', model_id: 'glm', display_name: 'GLM' },
    ]

    const options = coreModelSelectOptions({
      models,
      providers,
      defaultModel: models[0],
      currentLabelPrefix: '当前：',
    })

    expect(selectCoreExecutionModel(models, 'model-other', models[0])).toBe(models[1])
    expect(selectCoreExecutionModel(models, '', models[0])).toBe(models[0])
    expect(options).toEqual([
      { value: '', label: '当前：Kimi K2.6', selectedLabel: 'Kimi K2.6', group: '', groupKey: 'default' },
      { value: 'model-default', label: 'Kimi K2.6', selectedLabel: 'Kimi K2.6', group: 'Provider One', groupKey: 'provider:provider-1' },
      { value: 'model-other', label: 'GLM', selectedLabel: 'GLM', group: 'Provider One', groupKey: 'provider:provider-1' },
    ])
  })

  it('projects models into multiple user groups and keeps ungrouped models visible', () => {
    const models = [
      { id: 'record-a', provider_id: 'provider-1', model_id: 'upstream/a', display_name: 'A' },
      { id: 'record-b', provider_id: 'provider-1', model_id: 'upstream/b', display_name: 'B' },
    ]
    const options = coreModelSelectOptions({
      models,
      view: 'group',
      groups: [
        { id: 'free', name: 'Free', model_ids: ['record-a'] },
        { id: 'coding', name: 'Coding', model_ids: ['record-a'] },
      ],
    })

    expect(options.filter(option => option.value === 'record-a').map(option => option.group)).toEqual(['Free', 'Coding'])
    expect(options.find(option => option.value === 'record-b')).toMatchObject({
      group: '未分组',
      groupKey: 'group:__ungrouped__',
    })
  })

  it('limits thinking options from model and provider capabilities', () => {
    expect(coreThinkingModeOptions({ model: { thinking_supported: false } })).toEqual([
      { value: 'off', label: '关闭' },
    ])
    expect(coreThinkingModeOptions({
      model: { thinking_supported: true },
      provider: { name: '讯飞 max', base_url: 'https://maas-coding.example.test' },
    }).map((option) => option.value)).toEqual(['max', 'xhigh', 'high', 'medium', 'light', 'off'])
    expect(coreThinkingModeOptions({ model: { thinking_supported: true } }).map((option) => option.value)).toEqual([
      'max',
      'xhigh',
      'high',
      'medium',
      'light',
      'off',
    ])
  })

  it('offers exactly the reasoning ladder the selected model declares', () => {
    const model = {
      thinking_supported: true,
      reasoning_off_supported: false,
      reasoning_levels: [
        { id: 'max', label: '高' },
        { id: 'medium', label: '中' },
        'low',
        'nonsense',
      ],
    }
    expect(coreDeclaredThinkingLadder({ model })).toEqual([
      { value: 'max', label: '高' },
      { value: 'medium', label: '中' },
      { value: 'light', label: '轻' },
    ])
    expect(coreThinkingModeOptions({ model })).toEqual([
      { value: 'max', label: '高' },
      { value: 'medium', label: '中' },
      { value: 'light', label: '轻' },
    ])
    // A level the model never declared is never sent: the strongest declared
    // level is used instead of a value the model does not accept.
    expect(coreThinkingPayload({ mode: 'xhigh', model })).toEqual({ reasoning_level: 'max' })
    // Turning thinking off on a model that cannot be turned off keeps the
    // published fallback: its weakest declared level, which it does accept.
    expect(coreThinkingPayload({ mode: 'off', model })).toEqual({ reasoning_level: 'light' })
    // Off appears only when the model itself declares it as honorable.
    expect(coreThinkingModeOptions({
      model: { thinking_supported: true, reasoning_levels: ['off', 'light'] },
    })).toEqual([
      { value: 'off', label: '关闭' },
      { value: 'light', label: '轻' },
    ])
    // Without a declaration the product ladder still applies (published behavior).
    expect(coreThinkingModeOptions({ model: { thinking_supported: true } }).map((option) => option.value)).toEqual([
      'max',
      'xhigh',
      'high',
      'medium',
      'light',
      'off',
    ])
    expect(coreDeclaredThinkingLadder({ model: { thinking_supported: true } })).toEqual([])
  })

  it('creates the Core turn thinking payload', () => {
    expect(coreThinkingPayload({
      mode: 'high',
      model: { thinking_supported: true, thinking_budget: 6_000 },
      shallow: true,
    })).toEqual({
      reasoning_level: 'high',
    })
    expect(coreThinkingPayload({
      mode: 'max',
      model: { thinking_supported: true, thinking_budget: 12_000 },
      provider: { base_url: 'https://xfyun.example.test' },
    })).toEqual({
      reasoning_level: 'max',
    })
    expect(coreThinkingPayload({
      mode: 'max',
      model: { thinking_supported: false },
      shallow: true,
    })).toEqual({
      reasoning_level: 'off',
    })
  })

  it('normalizes and persists composer thinking preferences defensively', () => {
    const data = new Map<string, string>()
    const storage = {
      getItem: (key: string) => data.get(key) ?? null,
      setItem: (key: string, value: string) => data.set(key, value),
    }

    expect(normalizeCoreThinkingMode('invalid', 'high')).toBe('high')
    expect(normalizeCoreThinkingMode('xh')).toBe('xhigh')
    expect(readStoredCoreThinkingMode(storage, 'thinking', 'max')).toBe('max')
    writeStoredCoreThinkingMode(storage, 'thinking', 'low')
    writeStoredCoreShallowThinking(storage, 'shallow', true)

    expect(readStoredCoreThinkingMode(storage, 'thinking', 'max')).toBe('light')
    expect(readStoredCoreShallowThinking(storage, 'shallow')).toBe(true)
  })
})
