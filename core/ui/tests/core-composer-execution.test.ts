import { describe, expect, it } from 'vitest'
import {
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
      { value: '', label: '当前：Kimi K2.6', selectedLabel: 'Kimi K2.6', group: '' },
      { value: 'model-default', label: 'Kimi K2.6', selectedLabel: 'Kimi K2.6', group: 'Provider One' },
      { value: 'model-other', label: 'GLM', selectedLabel: 'GLM', group: 'Provider One' },
    ])
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
